#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUT_DIR="${1:-$ROOT_DIR/../crab-trading-public}"
ALLOWLIST_FILE="${ROOT_DIR}/.public-export-allowlist"
IGNORE_FILE="${ROOT_DIR}/.public-export-ignore"

if [[ -e "$OUT_DIR" ]]; then
  echo "ERROR: output directory already exists: $OUT_DIR" >&2
  echo "Choose a new path, e.g.:" >&2
  echo "  bash export_public.sh ../crab-trading-public-$(date +%Y%m%d-%H%M%S)" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"

if [[ ! -f "$ALLOWLIST_FILE" && ! -f "$IGNORE_FILE" ]]; then
  echo "ERROR: missing export filters. Expected $ALLOWLIST_FILE or $IGNORE_FILE" >&2
  exit 1
fi

RSYNC_FILTER_ARGS=()
if [[ -f "$ALLOWLIST_FILE" ]]; then
  RSYNC_FILTER_ARGS+=(--filter="merge $ALLOWLIST_FILE")
fi
if [[ -f "$IGNORE_FILE" ]]; then
  RSYNC_FILTER_ARGS+=(--filter="merge $IGNORE_FILE")
fi

rsync -a --prune-empty-dirs --exclude='.git/' \
  "${RSYNC_FILTER_ARGS[@]}" \
  "$ROOT_DIR"/ "$OUT_DIR"/

echo "Public export created at: $OUT_DIR"
echo "Next steps:"
echo "  cd \"$OUT_DIR\""
echo "  git init"
echo "  git add ."
echo "  git commit -m \"Initial public release\""
