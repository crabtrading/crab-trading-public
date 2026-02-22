#!/usr/bin/env python3
"""Deploy helper for Crab Trading.

Modes:
- local: restart local services only (no rsync/ssh)
- remote: rsync to remote host and restart remote services
- auto: remote when CRAB_REMOTE_HOST + CRAB_REMOTE_DIR are set, otherwise local

Targets:
- prod: defaults to production service/path/host
- custom: no target defaults
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


EXCLUDES = [
    ".git",
    ".venv",
    ".env",
    ".env.*",
    "runtime_state.json",
    "runtime_state.json-*",
    "runtime_state.db",
    "runtime_state.db-*",
    ".codex",
    "__pycache__",
    "*.pyc",
    "balance.py",
    "nl_mcp.py",
    "tsll_options_mcp.py",
    "tsll_price_mcp.py",
]

TARGET_DEFAULTS = {
    "prod": {
        "service_name": "crab-trading",
        "remote_dir": "/opt/crab-trading/",
        "health_host": "crabtrading.ai",
    },
    "custom": {},
}


def run(cmd: list[str], *, shell: bool = False) -> None:
    if shell:
        pretty = cmd[0]
    else:
        pretty = " ".join(shlex.quote(part) for part in cmd)
    print(f"$ {pretty}")
    subprocess.run(cmd if shell else cmd, check=True, shell=shell)


def systemctl_bin() -> str:
    return shutil.which("systemctl") or "/usr/bin/systemctl"


def ensure_local_systemctl() -> str:
    bin_path = systemctl_bin()
    if not shutil.which(bin_path) and not Path(bin_path).exists():
        raise RuntimeError(
            "systemctl is not available on this machine. "
            "Use remote mode or deploy manually."
        )
    return bin_path


def local_deploy(service_name: str, skip_nginx: bool) -> None:
    sysctl = ensure_local_systemctl()
    run([sysctl, "restart", service_name])
    run([sysctl, "is-active", service_name])

    if skip_nginx:
        print("Skipping nginx reload (--skip-nginx).")
        return

    nginx_active = subprocess.run(
        [sysctl, "is-active", "nginx"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0
    if not nginx_active:
        print("nginx is not active locally; skipping reload.")
        return

    run([sysctl, "reload", "nginx"])
    run([sysctl, "is-active", "nginx"])


def remote_deploy(
    local_dir: str,
    remote_host: str,
    remote_dir: str,
    service_name: str,
    skip_nginx: bool,
    health_host: str,
    health_path: str,
    skip_health_check: bool,
) -> None:
    rsync_cmd = ["rsync", "-az", "--delete", "-e", "ssh"]
    for pattern in EXCLUDES:
        rsync_cmd.extend(["--exclude", pattern])
    rsync_cmd.extend([local_dir, f"{remote_host}:{remote_dir}"])
    run(rsync_cmd)

    remote_cmd = (
        f"sudo /usr/bin/systemctl restart {shlex.quote(service_name)} && "
        f"sudo /usr/bin/systemctl is-active {shlex.quote(service_name)}"
    )
    if not skip_nginx:
        remote_cmd += (
            " && if sudo /usr/bin/systemctl is-active nginx >/dev/null 2>&1; then "
            "sudo /usr/bin/systemctl reload nginx && "
            "sudo /usr/bin/systemctl is-active nginx; "
            "else echo 'nginx is not active remotely; skipping reload.'; fi"
        )
    if not skip_health_check and health_host:
        remote_cmd += (
            " && curl -fsS "
            "--retry 8 --retry-delay 1 --retry-all-errors "
            f"-H {shlex.quote(f'Host: {health_host}')} "
            f"http://127.0.0.1{shlex.quote(health_path)}"
        )
    run(["ssh", remote_host, remote_cmd])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crab Trading deploy helper")
    parser.add_argument(
        "--target",
        choices=["prod", "custom"],
        default=os.getenv("CRAB_DEPLOY_TARGET", "prod"),
        help="Deployment target preset (default: prod)",
    )
    parser.add_argument(
        "--mode",
        choices=["auto", "local", "remote"],
        default="auto",
        help="Deployment mode (default: auto)",
    )
    parser.add_argument(
        "--local-dir",
        default=os.getenv("CRAB_LOCAL_DIR", str(Path(__file__).resolve().parent) + "/"),
        help="Local project directory for rsync in remote mode",
    )
    parser.add_argument(
        "--remote-host",
        default="",
        help="Remote SSH host, e.g. user@server.example.com",
    )
    parser.add_argument(
        "--remote-dir",
        default="",
        help="Remote project directory, e.g. /opt/crab-trading/",
    )
    parser.add_argument(
        "--service-name",
        default="",
        help="systemd service name to restart (defaults from target)",
    )
    parser.add_argument(
        "--health-host",
        default="",
        help="Host header used for remote health check curl",
    )
    parser.add_argument(
        "--health-path",
        default=os.getenv("CRAB_HEALTH_PATH", "/health"),
        help="Path for remote health check (default: /health)",
    )
    parser.add_argument(
        "--skip-nginx",
        action="store_true",
        help="Skip nginx reload step",
    )
    parser.add_argument(
        "--skip-health-check",
        action="store_true",
        help="Skip remote health curl check",
    )
    parser.add_argument(
        "--require-branch",
        default="",
        help="Require exact git branch name before deploy",
    )
    parser.add_argument(
        "--require-branch-regex",
        default="",
        help="Require git branch regex before deploy",
    )
    return parser.parse_args()


def _resolve_value(cli_value: str, env_key: str, default_value: str) -> str:
    value = (cli_value or "").strip()
    if value:
        return value
    env_value = (os.getenv(env_key) or "").strip()
    if env_value:
        return env_value
    return default_value


def _current_branch() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("Unable to determine git branch for deploy guard.")
    return result.stdout.strip()


def main() -> int:
    args = parse_args()
    target_defaults = TARGET_DEFAULTS.get(args.target, {})

    service_name = _resolve_value(
        args.service_name, "CRAB_SERVICE_NAME", target_defaults.get("service_name", "crab-trading")
    )
    remote_host = _resolve_value(args.remote_host, "CRAB_REMOTE_HOST", "")
    remote_dir = _resolve_value(args.remote_dir, "CRAB_REMOTE_DIR", target_defaults.get("remote_dir", ""))
    health_host = _resolve_value(args.health_host, "CRAB_HEALTH_HOST", target_defaults.get("health_host", ""))
    health_path = args.health_path if args.health_path.startswith("/") else f"/{args.health_path}"

    mode = args.mode
    if mode == "auto":
        mode = "remote" if remote_host and remote_dir else "local"

    try:
        if args.require_branch:
            branch = _current_branch()
            if branch != args.require_branch:
                raise RuntimeError(
                    f"Blocked by --require-branch: current={branch} expected={args.require_branch}"
                )
        if args.require_branch_regex:
            branch = _current_branch()
            if not re.fullmatch(args.require_branch_regex, branch):
                raise RuntimeError(
                    "Blocked by --require-branch-regex: "
                    f"current={branch} expected={args.require_branch_regex}"
                )

        if mode == "local":
            local_deploy(service_name=service_name, skip_nginx=args.skip_nginx)
        elif mode == "remote":
            if not remote_host or not remote_dir:
                raise RuntimeError(
                    "Remote mode requires --remote-host and --remote-dir "
                    "(or CRAB_REMOTE_HOST / CRAB_REMOTE_DIR)."
                )
            remote_deploy(
                local_dir=args.local_dir,
                remote_host=remote_host,
                remote_dir=remote_dir,
                service_name=service_name,
                skip_nginx=args.skip_nginx,
                health_host=health_host,
                health_path=health_path,
                skip_health_check=args.skip_health_check,
            )
        else:
            raise RuntimeError(f"Unsupported mode: {mode}")
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print("Deploy complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
