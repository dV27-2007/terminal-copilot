#!/usr/bin/env bash
set -euo pipefail
python - <<'PY'
from pathlib import Path
for file in (Path.home()/'.zshrc', Path.home()/'.bashrc'):
    if not file.exists():
        continue
    lines = file.read_text(errors='ignore').splitlines()
    kept = []
    skip = False
    for line in lines:
        if '# terminal-copilot user integration' in line:
            skip = True
            continue
        if skip and line.startswith('#') and 'terminal-copilot' not in line:
            skip = False
        if skip and ('TERM_COPILOT' in line or 'terminal-copilot' in line or line.startswith('[ -f ')):
            continue
        kept.append(line)
    file.write_text('\n'.join(kept) + '\n')
    print(f'cleaned {file}')
PY
