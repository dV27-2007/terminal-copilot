#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python -m pip install -e .
python -m daemon.main install
cat <<'MSG'
Installed user integration.
Start daemon with:
  term-predictord
or:
  python -m daemon.main daemon
Then restart zsh or run:
  source ~/.zshrc
MSG
