# Zsh integration

The zsh integration defines a `zsh-autosuggestions` custom strategy:

```zsh
_zsh_autosuggest_strategy_term_copilot
```

The strategy sends the current prefix to `/predict`, receives `ghost_text`, and returns the full suggestion to zsh-autosuggestions.

Suggested config:

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
