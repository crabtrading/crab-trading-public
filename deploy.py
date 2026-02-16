#!/usr/bin/env python3
"""Deploy helper for Crab Trading.

Modes:
- local: restart local services only (no rsync/ssh)
- remote: rsync to remote host and restart remote services
- auto: remote when CRAB_REMOTE_HOST + CRAB_REMOTE_DIR are set, otherwise local
"""

from __future__ import annotations

import argparse
import os
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


def local_deploy(skip_nginx: bool) -> None:
    sysctl = ensure_local_systemctl()
    run([sysctl, "restart", "crab-trading"])
    run([sysctl, "is-active", "crab-trading"])

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
    skip_nginx: bool,
) -> None:
    rsync_cmd = ["rsync", "-az", "--delete", "-e", "ssh"]
    for pattern in EXCLUDES:
        rsync_cmd.extend(["--exclude", pattern])
    rsync_cmd.extend([local_dir, f"{remote_host}:{remote_dir}"])
    run(rsync_cmd)

    remote_cmd = (
        "sudo /usr/bin/systemctl restart crab-trading && "
        "sudo /usr/bin/systemctl is-active crab-trading"
    )
    if not skip_nginx:
        remote_cmd += (
            " && if sudo /usr/bin/systemctl is-active nginx >/dev/null 2>&1; then "
            "sudo /usr/bin/systemctl reload nginx && "
            "sudo /usr/bin/systemctl is-active nginx; "
            "else echo 'nginx is not active remotely; skipping reload.'; fi"
        )
    run(["ssh", remote_host, remote_cmd])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crab Trading deploy helper")
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
        default=os.getenv("CRAB_REMOTE_HOST", ""),
        help="Remote SSH host, e.g. user@server.example.com",
    )
    parser.add_argument(
        "--remote-dir",
        default=os.getenv("CRAB_REMOTE_DIR", ""),
        help="Remote project directory, e.g. /opt/crab-trading/",
    )
    parser.add_argument(
        "--skip-nginx",
        action="store_true",
        help="Skip nginx reload step",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    mode = args.mode
    if mode == "auto":
        mode = "remote" if args.remote_host and args.remote_dir else "local"

    try:
        if mode == "local":
            local_deploy(skip_nginx=args.skip_nginx)
        elif mode == "remote":
            if not args.remote_host or not args.remote_dir:
                raise RuntimeError(
                    "Remote mode requires --remote-host and --remote-dir "
                    "(or CRAB_REMOTE_HOST / CRAB_REMOTE_DIR)."
                )
            remote_deploy(
                local_dir=args.local_dir,
                remote_host=args.remote_host,
                remote_dir=args.remote_dir,
                skip_nginx=args.skip_nginx,
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
