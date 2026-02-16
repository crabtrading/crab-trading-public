#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUT_DIR="${1:-$ROOT_DIR/../crab-trading-public}"

if [[ -e "$OUT_DIR" ]]; then
  echo "ERROR: output directory already exists: $OUT_DIR" >&2
  echo "Choose a new path, e.g.:" >&2
  echo "  bash export_public.sh ../crab-trading-public-$(date +%Y%m%d-%H%M%S)" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"

rsync -a \
  --filter='merge .public-export-ignore' \
  "$ROOT_DIR"/ "$OUT_DIR"/

echo "Public export created at: $OUT_DIR"
echo "Next steps:"
echo "  cd \"$OUT_DIR\""
echo "  git init"
echo "  git add ."
echo "  git commit -m \"Initial public release\""
