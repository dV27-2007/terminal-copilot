# Install

Terminal Copilot is local-first. The install commands only edit shell rc files
with managed source blocks. They do not enable AI, upload data, or configure
autostart.

## Start The Daemon

Set local paths when you want an explicit test setup:

```bash
export TERM_COPILOT_DB=/tmp/term-copilot.sqlite3
export TERM_COPILOT_SOCKET=/tmp/term-copilot.sock
```

Start the daemon:

```bash
./venv/bin/python -m daemon.main daemon
```

or:

```bash
scripts/start_daemon.sh
```

The daemon listens on the Unix socket when supported and keeps the HTTP fallback
on `127.0.0.1`.

## Install Zsh

```bash
./venv/bin/python -m daemon.main install --shell zsh
```

The installer writes one managed block to `~/.zshrc`:

```text
# >>> term-copilot init >>>
...
# <<< term-copilot init <<<
```

The block uses absolute source paths, preserves existing rc content, creates a
backup before modifying an existing file, and is idempotent. Re-running install
updates or collapses managed blocks instead of duplicating them.

The zsh plugin expects `zsh-autosuggestions` for ghost text rendering. If it is
not installed, `doctor` reports a warning.

## Install Bash Fallback

```bash
./venv/bin/python -m daemon.main install --shell bash
```

Bash does not render zsh-style ghost text. The bash adapter records executed
commands and provides a `Ctrl+F` prediction accept helper through Readline.

## Status

```bash
./venv/bin/python -m daemon.main status
```

Status prints local state quickly and does not fail when the daemon is stopped:

- daemon reachable: yes/no;
- IPC mode: Unix socket, HTTP fallback, or unavailable;
- socket path and HTTP URL;
- DB path and whether the DB exists;
- command/cache counts when cheap to query;
- AI enabled/disabled;
- protocol version;
- managed shell block counts.

## Doctor

```bash
./venv/bin/python -m daemon.main doctor
```

Doctor prints `PASS`, `WARN`, and `FAIL` checks for local setup:

- package import;
- DB path creation and writability;
- socket directory creation and socket reachability;
- HTTP fallback reachability;
- plugin file presence;
- zsh syntax check when `zsh` is available;
- common `zsh-autosuggestions` install locations;
- managed rc blocks and duplicate managed blocks;
- config files.

Warnings include expected states such as a stopped daemon. The command exits
non-zero only for serious local failures such as unwritable DB/socket paths or a
missing plugin file.

## Uninstall

```bash
./venv/bin/python -m daemon.main uninstall --shell zsh
./venv/bin/python -m daemon.main uninstall --shell bash
```

Uninstall removes only blocks between the managed markers. It preserves all other
shell rc content and creates a backup before modifying an existing rc file. It
does not delete the SQLite DB or cache.

## Root Install

Root shell integration is explicit only:

```bash
sudo TERM_COPILOT_SOCKET=/tmp/term-copilot-root.sock \
  ./venv/bin/python -m daemon.main install --root --shell zsh --socket /tmp/term-copilot-root.sock
```

Automatic systemd/launchd autostart is intentionally not part of this stage.

## Known Limitations

- zsh emits `suggestion_accepted` and `command_executed` events.
- zsh does not yet reliably emit `suggestion_ignored`.
- Bash remains a fallback adapter and does not provide native ghost text.
