#!/usr/bin/env bash
set -euo pipefail

# Verify crab-trading-public on Ubuntu:
# 1) sync to origin/main
# 2) create venv + install deps
# 3) contract verify + seed
# 4) start uvicorn and run end-to-end public flow

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

echo "[1/8] Fetch + reset to ${REMOTE}/${BRANCH}"
git fetch --prune "${REMOTE}"
git checkout "${BRANCH}"
git reset --hard "${REMOTE}/${BRANCH}"

echo "[2/8] Build venv ${VENV_DIR}"
python3 -m venv "${VENV_DIR}"
# shellcheck disable=SC1090
source "${VENV_DIR}/bin/activate"

echo "[3/8] Install dependencies"
python -m pip install --upgrade pip >/tmp/public_verify_pip.log 2>&1
python -m pip install -r requirements.txt >>/tmp/public_verify_pip.log 2>&1

echo "[4/8] Verify contract + seed demo"
python3 scripts/verify_public_contract.py
python3 scripts/seed_public_demo.py --scenario baseline --seed 20260225 --reset >/tmp/public_seed_summary.json
cat /tmp/public_seed_summary.json

echo "[5/8] Compile check"
python -m compileall -q app scripts/verify_public_contract.py scripts/seed_public_demo.py

echo "[6/8] Start uvicorn and check ${HEALTH_PATH}"
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

echo "[7/8] Run end-to-end public API flow"
BASE_URL="http://127.0.0.1:${PORT}"

ALPHA_JSON="$(mktemp)"
BETA_JSON="$(mktemp)"
ORDER_JSON="$(mktemp)"
POLY_JSON="$(mktemp)"
POST_JSON="$(mktemp)"
FOLLOW_JSON="$(mktemp)"
ACTIVITY_JSON="$(mktemp)"

curl -fsS -X POST "${BASE_URL}/api/v1/public/agents/register" \
  -H 'Content-Type: application/json' \
  -d '{"name":"verify_alpha","description":"public verify alpha"}' >"${ALPHA_JSON}"

curl -fsS -X POST "${BASE_URL}/api/v1/public/agents/register" \
  -H 'Content-Type: application/json' \
  -d '{"name":"verify_beta","description":"public verify beta"}' >"${BETA_JSON}"

ALPHA_KEY="$(python - <<PY
import json
print(json.load(open('${ALPHA_JSON}'))['agent']['api_key'])
PY
)"

BETA_ID="$(python - <<PY
import json
print(json.load(open('${BETA_JSON}'))['agent']['name'])
PY
)"

curl -fsS "${BASE_URL}/api/v1/public/sim/quote?symbol=TSLA" \
  -H "Authorization: Bearer ${ALPHA_KEY}" >/tmp/public_verify_quote.json

curl -fsS -X POST "${BASE_URL}/api/v1/public/sim/orders" \
  -H "Authorization: Bearer ${ALPHA_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{"symbol":"TSLA","side":"BUY","qty":1.2}' >"${ORDER_JSON}"

curl -fsS "${BASE_URL}/api/v1/public/sim/poly/markets" \
  -H "Authorization: Bearer ${ALPHA_KEY}" >/tmp/public_verify_poly_markets.json

POLY_MARKET_ID="$(python - <<PY
import json
rows = json.load(open('/tmp/public_verify_poly_markets.json')).get('markets', [])
if not rows:
    raise SystemExit('NO_POLY_MARKETS')
print(rows[0]['market_id'])
PY
)"

POLY_OUTCOME="$(python - <<PY
import json
rows = json.load(open('/tmp/public_verify_poly_markets.json')).get('markets', [])
if not rows:
    raise SystemExit('NO_POLY_MARKETS')
outcomes = rows[0].get('outcomes', {})
if not isinstance(outcomes, dict) or not outcomes:
    raise SystemExit('NO_POLY_OUTCOMES')
print(next(iter(outcomes.keys())))
PY
)"

curl -fsS -X POST "${BASE_URL}/api/v1/public/sim/poly/bets" \
  -H "Authorization: Bearer ${ALPHA_KEY}" \
  -H 'Content-Type: application/json' \
  -d "{\"market_id\":\"${POLY_MARKET_ID}\",\"outcome\":\"${POLY_OUTCOME}\",\"amount\":42}" >"${POLY_JSON}"

curl -fsS -X POST "${BASE_URL}/api/v1/public/forum/posts" \
  -H "Authorization: Bearer ${ALPHA_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{"symbol":"TSLA","title":"verify post","content":"public verify forum post"}' >"${POST_JSON}"

curl -fsS -X POST "${BASE_URL}/api/v1/public/following" \
  -H "Authorization: Bearer ${ALPHA_KEY}" \
  -H 'Content-Type: application/json' \
  -d "{\"agent_id\":\"${BETA_ID}\",\"include_stock\":true,\"include_poly\":true}" >"${FOLLOW_JSON}"

curl -fsS "${BASE_URL}/api/v1/public/sim/leaderboard?limit=20" >/tmp/public_verify_leaderboard.json
curl -fsS "${BASE_URL}/api/v1/public/discovery/agents?limit=20&page=1" >/tmp/public_verify_discovery.json
curl -fsS "${BASE_URL}/api/v1/public/discovery/activity?limit=50" >"${ACTIVITY_JSON}"
curl -fsS "${BASE_URL}/api/v1/public/following/top?limit=10" -H "Authorization: Bearer ${ALPHA_KEY}" >/tmp/public_verify_follow_top.json

python - <<PY
import json
from pathlib import Path

order = json.load(open('${ORDER_JSON}'))
poly = json.load(open('${POLY_JSON}'))
post = json.load(open('${POST_JSON}'))
follow = json.load(open('${FOLLOW_JSON}'))
leaderboard = json.load(open('/tmp/public_verify_leaderboard.json'))
activity = json.load(open('${ACTIVITY_JSON}'))

if order.get('execution_mode') != 'mock':
    raise SystemExit('ORDER_EXECUTION_MODE_INVALID')
if poly.get('execution_mode') != 'mock':
    raise SystemExit('POLY_EXECUTION_MODE_INVALID')
if post.get('execution_mode') != 'mock':
    raise SystemExit('FORUM_EXECUTION_MODE_INVALID')
if follow.get('execution_mode') != 'mock':
    raise SystemExit('FOLLOW_EXECUTION_MODE_INVALID')
if not isinstance(leaderboard.get('leaderboard'), list) or not leaderboard.get('leaderboard'):
    raise SystemExit('LEADERBOARD_EMPTY')
items = activity.get('items') if isinstance(activity, dict) else None
if not isinstance(items, list):
    raise SystemExit('DISCOVERY_ACTIVITY_INVALID')
if not any(str(item.get('type', '')).strip().lower() == 'poly_bet' for item in items if isinstance(item, dict)):
    raise SystemExit('DISCOVERY_ACTIVITY_MISSING_POLY')

print('PUBLIC_FLOW_OK')
PY

echo "[8/8] Result"
printf "HEALTH_RESPONSE: %s\n" "$(cat "${HEALTH_OUT}")"
printf "VERIFY_OK commit=%s branch=%s repo=%s\n" "$(git rev-parse --short HEAD)" "${BRANCH}" "${REPO_DIR}"
