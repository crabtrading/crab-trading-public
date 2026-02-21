#!/usr/bin/env bash
set -euo pipefail

# Verify crab-trading-public on Ubuntu:
# 1) sync to origin/main
# 2) create venv + install deps
# 3) compile + import checks
# 4) start uvicorn and hit /health

REPO_DIR="${1:-$HOME/crab-trading-public}"
REMOTE="${REMOTE:-origin}"
BRANCH="${BRANCH:-main}"
VENV_DIR="${VENV_DIR:-.venv-public-verify}"
PORT="${PORT:-18080}"
HEALTH_PATH="${HEALTH_PATH:-/health}"
PUBLIC_REPO_URL="${PUBLIC_REPO_URL:-https://github.com/crabtrading/crab-trading-public.git}"

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

need_cmd git
need_cmd python3
need_cmd curl

if [[ ! -d "${REPO_DIR}/.git" ]]; then
  echo "Repo not found at ${REPO_DIR}, cloning..."
  mkdir -p "$(dirname "${REPO_DIR}")"
  git clone "${PUBLIC_REPO_URL}" "${REPO_DIR}"
fi

cd "${REPO_DIR}"

if ! git remote get-url "${REMOTE}" >/dev/null 2>&1; then
  echo "Remote ${REMOTE} missing in ${REPO_DIR}" >&2
  exit 1
fi

echo "[1/6] Fetch + reset to ${REMOTE}/${BRANCH}"
git fetch --prune "${REMOTE}"
git checkout "${BRANCH}"
git reset --hard "${REMOTE}/${BRANCH}"

echo "[2/6] Build venv ${VENV_DIR}"
python3 -m venv "${VENV_DIR}"
# shellcheck disable=SC1090
source "${VENV_DIR}/bin/activate"

echo "[3/6] Install dependencies"
python -m pip install --upgrade pip >/tmp/public_verify_pip.log 2>&1
python -m pip install -r requirements.txt >>/tmp/public_verify_pip.log 2>&1

echo "[4/6] Compile + import smoke checks"
python -m compileall -q app deploy.py
python - <<'PY'
import importlib
from fastapi.routing import APIRoute

mod = importlib.import_module("app.public_main")
app = getattr(mod, "app", None)
if app is None:
    raise SystemExit("PUBLIC_MAIN_APP_MISSING")

paths = []
for route in app.routes:
    if isinstance(route, APIRoute):
        paths.append(str(route.path))

required = ["/health", "/api/v1/agents/register", "/web/sim/account"]
missing = [path for path in required if path not in paths]
if missing:
    raise SystemExit(f"PUBLIC_ROUTE_MISSING:{','.join(missing)}")

blocked_prefixes = ("/web/live/", "/web/owner/", "/internal/")
for path in paths:
    if any(path.startswith(prefix) for prefix in blocked_prefixes):
        raise SystemExit(f"PUBLIC_PRIVATE_ROUTE_EXPOSED:{path}")

print("IMPORT_OK")
PY

echo "[5/6] Start uvicorn and check ${HEALTH_PATH}"
HEALTH_OUT="$(mktemp)"
UVICORN_LOG="$(mktemp)"
export CRAB_LIVE_ENABLED_GLOBAL=0
python -m uvicorn app.public_main:app --host 127.0.0.1 --port "${PORT}" >"${UVICORN_LOG}" 2>&1 &
UVICORN_PID=$!

cleanup() {
  if [[ -n "${UVICORN_PID:-}" ]] && kill -0 "${UVICORN_PID}" >/dev/null 2>&1; then
    kill "${UVICORN_PID}" >/dev/null 2>&1 || true
    wait "${UVICORN_PID}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

READY=0
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${PORT}${HEALTH_PATH}" >"${HEALTH_OUT}" 2>/dev/null; then
    READY=1
    break
  fi
  sleep 1
done

if [[ "${READY}" != "1" ]]; then
  echo "Health check failed. Last uvicorn log lines:" >&2
  tail -n 80 "${UVICORN_LOG}" >&2 || true
  exit 1
fi

echo "[6/6] Result"
printf "HEALTH_RESPONSE: %s\n" "$(cat "${HEALTH_OUT}")"
printf "VERIFY_OK commit=%s branch=%s repo=%s\n" "$(git rev-parse --short HEAD)" "${BRANCH}" "${REPO_DIR}"
