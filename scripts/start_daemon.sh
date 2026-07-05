#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-python}"

: "${TERM_COPILOT_SOCKET:=${HOME}/.cache/term-copilot/daemon.sock}"
export TERM_COPILOT_SOCKET

exec "$PYTHON" -m daemon.main daemon "$@"
