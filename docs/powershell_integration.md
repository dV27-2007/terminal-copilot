# PowerShell Integration

PowerShell support is currently profile-management only. The runtime adapter is
deferred, so this stage does not add keybindings, PSReadLine integration, Named
Pipe IPC, ghost text, or command/event recording from PowerShell.

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

The managed block is safe before the runtime adapter exists:

```powershell
$TermCopilotAdapter = "<repo>\powershell\terminal-copilot.ps1"
if (Test-Path -LiteralPath $TermCopilotAdapter) { . $TermCopilotAdapter }
```

If the adapter file is missing, PowerShell startup remains quiet.

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
`powershell.exe` is available, and whether the future adapter file exists.
Missing PowerShell or a missing adapter is a warning, not a failure.

## Windows Terminal And WSL

Windows Terminal does not need separate integration; it launches PowerShell,
which loads the selected profile according to normal PowerShell behavior.

WSL should keep using the Linux shell adapters and Unix socket path. Native
PowerShell should use the PowerShell profile path and, in a later stage, native
Windows IPC or HTTP fallback. Crossing the WSL/native Windows boundary is not
part of this stage.

## Execution Policy

The installer does not change execution policy. If a local profile is blocked by
PowerShell policy, fix that explicitly in the user environment; terminal-copilot
will not alter it automatically.

## Security

This profile-management stage:

- does not execute suggestions;
- does not bind keys;
- does not send terminal scrollback;
- does not read `.env`;
- does not enable AI;
- does not upload data;
- stays silent when the adapter is missing because the dot-source is guarded.

The next planned stage is a PowerShell Ctrl+F insert adapter that requests one
local prediction and inserts it without executing it.
