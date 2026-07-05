# Fish Integration

The fish adapter is a lightweight fallback:

```fish
source /path/to/terminal-copilot/fish/terminal-copilot.fish
```

It does not provide zsh-style ghost text. Instead, it binds `Ctrl+F` to request
one prediction for the current commandline, then inserts the returned full
command. It never executes the suggestion automatically.

## Transport

`Ctrl+F` uses a small Python helper because fish does not provide a portable
built-in Unix socket client. The helper prefers `$TERM_COPILOT_SOCKET` and falls
back to HTTP only for non-root shells. This is not a per-keystroke hot path.

The adapter sends only:

- current commandline;
- cursor position;
- cwd;
- shell name;
- root/session metadata.

It does not send terminal scrollback, read `.env`, call AI directly, or print
debug output.

## Root Mode

Root mode is detected from `TERM_COPILOT_ROOT_MODE=1` or effective uid `0`.
Root fish shells require an explicit `TERM_COPILOT_SOCKET`. If it is missing or
unreachable, prediction and event posting fail silently and HTTP fallback is not
used.

## Events

The adapter records:

- `suggestion_accepted` when `Ctrl+F` inserts a suggestion;
- `command_executed` through fish's `fish_postexec` event when available.

It does not emit `suggestion_ignored`; fish does not give this adapter a
reliable low-noise signal for ignored suggestions.

## Install

```bash
./venv/bin/python -m daemon.main install --shell fish
```

The managed block is written to `~/.config/fish/config.fish`, is idempotent, and
can be removed with:

```bash
./venv/bin/python -m daemon.main uninstall --shell fish
```

If fish is installed, syntax-check the adapter with:

```bash
fish -n fish/terminal-copilot.fish
```
