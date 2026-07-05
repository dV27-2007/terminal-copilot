# PowerShell Integration

PowerShell support is a lightweight MVP. It provides explicit `Ctrl+F`
suggestion insertion through PSReadLine when available. It does not provide
ghost text, Named Pipe IPC, tab completion, or automatic command execution.

## Install

```bash
./venv/bin/python -m daemon.main install --shell powershell
```

The installer creates the profile parent directory when needed, creates the
profile file when missing, backs up an existing profile before editing, and
keeps exactly one managed block:

```powershell
# >>> term-copilot init >>>
...
# <<< term-copilot init <<<
```

The managed block dot-sources the runtime adapter only when it exists:

```powershell
$TermCopilotAdapter = "<repo>\powershell\terminal-copilot.ps1"
if (Test-Path -LiteralPath $TermCopilotAdapter) { . $TermCopilotAdapter }
```

If the adapter file is missing, PowerShell startup remains quiet.

## Runtime UX

When PSReadLine is available, the adapter binds `Ctrl+F`:

```powershell
Set-PSReadLineKeyHandler -Chord "Ctrl+f"
```

Pressing `Ctrl+F` requests one prediction for the current command line. If the
daemon returns a valid continuation, the adapter inserts only the suffix needed
to complete the current line. It does not press Enter and does not execute the
suggestion.

If PSReadLine is unavailable, the adapter still defines
`Invoke-TermCopilotSuggestion`, but profile load stays silent and no keybinding
is installed.

The MVP intentionally does not implement PowerShell ghost text. Ghost text
requires a more careful PSReadLine version matrix and should remain deferred
until explicit insertion is stable on Windows PowerShell 5.1 and PowerShell 7+.

## Transport

The MVP uses local HTTP only:

```text
TERM_COPILOT_HTTP_URL, or http://127.0.0.1:8765 by default
```

`TERM_COPILOT_URL` is also accepted for compatibility with the other adapters.
Requests use a short timeout and fail silently when the daemon is unavailable.

Named Pipe IPC is deferred. The adapter does not use external dependencies,
PowerShell modules, `socat`, `nc`, or provider APIs.

## Profile Path

By default, terminal-copilot checks the current-user current-host PowerShell 7
style profile path:

```text
~/Documents/PowerShell/Microsoft.PowerShell_profile.ps1
```

Set `TERM_COPILOT_POWERSHELL_PROFILE` to use an exact profile path, which is
also useful for tests and manual verification.

`TERM_COPILOT_POWERSHELL_PROFILE_TARGET` can select a planned logical target:

- `current-user-current-host`
- `current-user-all-hosts`
- `powershell-7-current-user-current-host`
- `powershell-7-current-user-all-hosts`
- `windows-powershell-5.1-current-user-current-host`
- `windows-powershell-5.1-current-user-all-hosts`

The runtime adapter stage should verify native Windows paths against actual
`$PROFILE` values before adding broader defaults.

## Uninstall

```bash
./venv/bin/python -m daemon.main uninstall --shell powershell
```

Uninstall removes only the managed block and preserves unrelated profile
content. It is idempotent and does not fail when the profile file is missing.

## Status And Doctor

```bash
./venv/bin/python -m daemon.main status
./venv/bin/python -m daemon.main doctor
```

Status reports the PowerShell profile path, whether it exists, and the managed
block count. Doctor reports profile facts, duplicate blocks, whether `pwsh` or
`powershell.exe` is available, and whether the adapter file exists. Missing
PowerShell is a warning, not a failure.

## Events

The adapter emits `suggestion_accepted` only after it inserts a suggestion.
Event posting is best-effort and silent on failure.

`command_executed` and `suggestion_ignored` are not implemented in the
PowerShell MVP. They should be added only when the adapter can capture them
without false positives.

## Windows Terminal And WSL

Windows Terminal does not need separate integration; it launches PowerShell,
which loads the selected profile according to normal PowerShell behavior.

WSL should keep using the Linux shell adapters and Unix socket path. Native
PowerShell should use the PowerShell profile path and local HTTP in this MVP.
Crossing the WSL/native Windows boundary is not part of this stage.

## Execution Policy

The installer does not change execution policy. If a local profile is blocked by
PowerShell policy, fix that explicitly in the user environment; terminal-copilot
will not alter it automatically.

## Security

The PowerShell adapter:

- does not execute suggestions;
- inserts only through explicit `Ctrl+F`;
- does not send terminal scrollback;
- does not read `.env`;
- does not enable AI;
- does not upload data;
- rejects dangerous-risk responses;
- stays silent when the daemon is unavailable.

Administrator mode is detected best-effort through Windows identity APIs or
`TERM_COPILOT_ROOT_MODE=1`. Admin mode is sent as `root_mode=true`/`admin=true`.
Admin shells do not auto-discover another user's daemon; use
`TERM_COPILOT_HTTP_URL` explicitly for Administrator shell testing.

## Manual Verification

```powershell
$env:TERM_COPILOT_HTTP_URL = "http://127.0.0.1:8765"
. .\powershell\terminal-copilot.ps1
```

Then type `docker co`, press `Ctrl+F`, and verify that a matching suggestion is
inserted without executing. Stop the daemon and verify that `Ctrl+F` is silent.
