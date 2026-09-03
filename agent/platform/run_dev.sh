#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
cd "$SCRIPT_DIR"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required. Install uv first, then run 'uv sync' in agent/platform." >&2
  exit 1
fi

set -a
if [ -f ./.env.local ]; then
  # shellcheck disable=SC1091
  . ./.env.local
elif [ -f ./.env ]; then
  # shellcheck disable=SC1091
  . ./.env
fi
set +a

exec uv run --no-sync python -m uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 9010

# exec uv run --no-sync python -m uvicorn app.main:app \
#   --reload \
#   --reload-exclude 'data/*' \
#   --reload-exclude 'tests/*' \
#   --host 0.0.0.0 \
#   --port 9010
