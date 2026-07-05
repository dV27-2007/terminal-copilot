# Zsh integration

The zsh integration defines a `zsh-autosuggestions` custom strategy:

```zsh
_zsh_autosuggest_strategy_term_copilot
```

The strategy sends the current prefix to the local daemon, receives `ghost_text`,
and returns the full suggestion to zsh-autosuggestions. Prediction uses Unix
socket IPC first when `$TERM_COPILOT_SOCKET` or the default
`~/.cache/term-copilot/daemon.sock` exists. If the socket path is unavailable,
the plugin falls back to the existing localhost HTTP `/predict` endpoint.

The socket path uses zsh builtins from `zsh/net/socket` and `zsh/system`, so the
prediction hot path does not spawn Python when Unix socket IPC is available.
Failures are silent and bounded by `$TERM_COPILOT_TIMEOUT`, defaulting to
`0.20` seconds.

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

The plugin records executed commands through `preexec` and `precmd` hooks. It does not record commands where daemon-side redaction detects secrets.
Command execution and suggestion-accepted events still use the existing
background HTTP event helper.

Current limitation: the zsh adapter does not yet reliably emit
`suggestion_ignored`. The daemon and store support the event for future adapter
wiring.
