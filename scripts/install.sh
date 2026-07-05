#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-python}"
"$PYTHON" -m pip install -e .
"$PYTHON" -m daemon.main install --user "$@"
cat <<'MSG'
Installed user integration.
Start daemon with:
  scripts/start_daemon.sh
or:
  python -m daemon.main daemon
Check local setup with:
  python -m daemon.main status
  python -m daemon.main doctor
MSG
