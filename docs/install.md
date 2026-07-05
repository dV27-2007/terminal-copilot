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
commands and provides a `Ctrl+F` prediction accept helper through Readline. For
normal user shells it uses the same default socket path as zsh,
`~/.cache/term-copilot/daemon.sock`, unless `TERM_COPILOT_SOCKET` is already
set. In root mode it does not guess `/root/.cache/...`; set
`TERM_COPILOT_SOCKET` explicitly.

## Install Fish Fallback

```bash
./venv/bin/python -m daemon.main install --shell fish
```

The fish adapter is a lightweight fallback. It does not provide zsh-style ghost
text. It binds `Ctrl+F` to request one prediction from the daemon and insert the
returned full command into the commandline without executing it. It records
`command_executed` through fish's `fish_postexec` event when available and
records `suggestion_accepted` only when the adapter inserts a suggestion.

The managed block is written to:

```text
~/.config/fish/config.fish
```

For normal user shells, fish uses the same default socket path as zsh,
`~/.cache/term-copilot/daemon.sock`, unless `TERM_COPILOT_SOCKET` is already
set. In root mode it requires an explicit `TERM_COPILOT_SOCKET` and does not use
HTTP fallback.

## Install PowerShell Profile Block

```bash
./venv/bin/python -m daemon.main install --shell powershell
```

PowerShell support is staged. This command manages the profile block only; it
does not install a runtime adapter, bind keys, add Named Pipe IPC, or enable
ghost text. The block safely checks for the future adapter path before
dot-sourcing it, so a missing adapter is silent.

By default the checked profile target is the current-user current-host
PowerShell 7 style path:

```text
~/Documents/PowerShell/Microsoft.PowerShell_profile.ps1
```

Use `TERM_COPILOT_POWERSHELL_PROFILE` to point install, uninstall, status and
doctor at a specific profile file. `--shell all` does not include PowerShell;
use `--shell powershell` explicitly.

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
- PowerShell profile path, existence, and managed block count.

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
- zsh, bash and fish syntax checks when those shells are available;
- PowerShell profile and future adapter visibility without requiring PowerShell
  to be installed;
- common `zsh-autosuggestions` install locations;
- managed rc blocks and duplicate managed blocks;
- config files.

For end-to-end zsh verification, start the daemon with a temp DB/socket, source
the zsh plugin in a second shell, type `docker co`, accept the ghost suggestion
with Right Arrow or Ctrl+F, execute it, then run `status` to confirm command and
cache counts changed. Natural-language input such as `как запустить backend`
should not produce a suggestion, and a stopped daemon should not print shell
errors.

Warnings include expected states such as a stopped daemon. The command exits
non-zero only for serious local failures such as unwritable DB/socket paths or a
missing plugin file.

## Uninstall

```bash
./venv/bin/python -m daemon.main uninstall --shell zsh
./venv/bin/python -m daemon.main uninstall --shell bash
./venv/bin/python -m daemon.main uninstall --shell fish
./venv/bin/python -m daemon.main uninstall --shell powershell
```

Uninstall removes only blocks between the managed markers. It preserves all other
shell rc content and creates a backup before modifying an existing rc file. It
does not delete the SQLite DB or cache.

## Root Install

The main daemon should normally run as the regular user. Root shells should
connect to that daemon through an explicit socket path owned by the user daemon,
for example `/home/david/.cache/term-copilot/daemon.sock`.

Root shell integration is explicit only:

```bash
sudo TERM_COPILOT_SOCKET=/tmp/term-copilot-root.sock \
  ./venv/bin/python -m daemon.main install --root --shell zsh --socket /tmp/term-copilot-root.sock
```

The root managed block sets:

```text
TERM_COPILOT_SOCKET=<provided path>
TERM_COPILOT_ROOT_MODE=1
TERM_COPILOT_USER=<original user when provided or safely inferred>
TERM_COPILOT_HOME=<original home when provided or safely inferred>
```

Root install refuses to run unless `--socket` or `TERM_COPILOT_SOCKET` is
provided. Shell adapters also suppress prediction and event posting in root mode
when no explicit socket is configured. They do not guess a regular user's socket
path on their own. Uninstall uses the same managed markers and removes only the
managed block:

```bash
sudo ./venv/bin/python -m daemon.main uninstall --root --shell zsh
```

For ad hoc root testing without editing root rc files:

```bash
sudo env \
  TERM_COPILOT_SOCKET=/home/david/.cache/term-copilot/daemon.sock \
  TERM_COPILOT_ROOT_MODE=1 \
  TERM_COPILOT_USER="$USER" \
  TERM_COPILOT_HOME="$HOME" \
  ./venv/bin/python -m daemon.main doctor
```

Automatic systemd/launchd autostart is intentionally not part of this stage.

## Known Limitations

- zsh emits `suggestion_accepted` and `command_executed` events.
- zsh does not yet reliably emit `suggestion_ignored`; the daemon/store support
  the event, but the adapter avoids fragile false-positive shell logic.
- Bash remains a fallback adapter and does not provide native ghost text.
- Fish remains a fallback adapter and does not provide native ghost text.
