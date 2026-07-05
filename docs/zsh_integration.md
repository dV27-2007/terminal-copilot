# Zsh integration

The zsh integration defines a `zsh-autosuggestions` custom strategy:

```zsh
_zsh_autosuggest_strategy_term_copilot
```

The strategy sends the current prefix to the local daemon, receives `ghost_text`,
and returns the full suggestion to zsh-autosuggestions. Prediction uses Unix
socket IPC first when `$TERM_COPILOT_SOCKET` or the default
`~/.cache/term-copilot/daemon.sock` exists. If the socket path is unavailable,
the plugin falls back to the existing localhost HTTP `/predict` endpoint for
normal user shells.

In root mode, detected from effective uid `0` or `TERM_COPILOT_ROOT_MODE=1`, the
adapter requires an explicit `TERM_COPILOT_SOCKET` and does not fall back to
HTTP prediction. This lets a sudo/root shell connect to the regular user's
daemon only when the socket path has been intentionally configured. If root mode
has no explicit socket, prediction and event posting both fail silently.

The socket path uses zsh builtins from `zsh/net/socket` and `zsh/system`, so the
prediction hot path does not spawn Python when Unix socket IPC is available.
Failures are silent and bounded by `$TERM_COPILOT_TIMEOUT`, defaulting to
`0.20` seconds.

The strategy clears its last suggestion state before each prediction request.
This prevents an older ghost suggestion from being accepted after the buffer has
changed or the daemon becomes unavailable.

Managed install:

```bash
./venv/bin/python -m daemon.main install --shell zsh
```

Manual config:

```zsh
source /path/to/zsh-autosuggestions.zsh
source /path/to/terminal-copilot/zsh/terminal-copilot.zsh
ZSH_AUTOSUGGEST_STRATEGY=(term_copilot history)
```

Accepted keys:

```text
Right Arrow
Ctrl+F
```

The plugin records executed commands through `preexec` and `precmd` hooks. It
does not record commands where daemon-side redaction detects secrets. Command
execution and suggestion-accepted events use the existing background HTTP event
helper and do not print terminal output. Event payloads include shell, cwd,
effective uid, root mode, original user metadata when present, exit code for
executed commands, and duration when available. Accepted suggestions are
recorded only after the shell buffer has been updated to the predicted full
command.

Current limitation: the zsh adapter does not yet reliably emit
`suggestion_ignored`. The daemon and store support the event for future adapter
wiring, but zsh-autosuggestions does not expose a stable enough public hook in
this adapter to distinguish a truly ignored visible suggestion from redraws,
normal buffer changes, Ctrl+C, daemon misses, or accept transitions without
fragile shell state.

Manual smoke test:

```bash
export TERM_COPILOT_DB=/tmp/term-copilot-stage13.sqlite3
export TERM_COPILOT_SOCKET=/tmp/term-copilot-stage13.sock
./venv/bin/python -m daemon.main record "docker compose ps" --cwd "$PWD" --exit-code 0
./venv/bin/python -m daemon.main daemon --port 9876
```

In another zsh:

```zsh
export TERM_COPILOT_DB=/tmp/term-copilot-stage13.sqlite3
export TERM_COPILOT_SOCKET=/tmp/term-copilot-stage13.sock
source zsh/terminal-copilot.zsh
```

Then type `docker co`, accept with Right Arrow or Ctrl+F, execute the command,
and verify the shell stays quiet if the daemon is stopped.
