# Windows Validation

Use this checklist on a real Windows machine. Linux CI can verify the docs and
guarded benchmark script, but native Windows Named Pipe behavior, PSReadLine
behavior, Windows Terminal behavior, and Windows PowerShell 5.1 behavior must be
validated on Windows.

## Scope

Validate:

- Windows PowerShell 5.1;
- PowerShell 7+;
- Windows Terminal launching both shells;
- normal non-admin shells;
- Administrator shells;
- Named Pipe prediction;
- HTTP fallback prediction;
- pipe-only `suggestion_accepted`;
- HTTP-only `suggestion_accepted`;
- stopped-daemon silent failure;
- missing profile adapter silent behavior;
- install and uninstall profile behavior;
- natural-language rejection;
- secret-looking input rejection;
- no automatic execution;
- no ghost text claim.

Still deferred:

- PowerShell ghost text;
- PowerShell `command_executed` remains deferred;
- PowerShell `suggestion_ignored`.

## Preparation

From the repository root in PowerShell:

```powershell
$env:TERM_COPILOT_DB = "$env:TEMP\term-copilot-windows-validation.sqlite3"
$env:TERM_COPILOT_PIPE = "\\.\pipe\term-copilot-$env:USERNAME"
$env:TERM_COPILOT_HTTP_URL = "http://127.0.0.1:9876"
```

Start the daemon:

```powershell
$env:TERM_COPILOT_PIPE = "\\.\pipe\term-copilot-$env:USERNAME"
$env:TERM_COPILOT_HTTP_URL = "http://127.0.0.1:9876"
.\venv\Scripts\python.exe -m daemon.main daemon --port 9876 --pipe $env:TERM_COPILOT_PIPE
```

In another PowerShell window, seed a known command:

```powershell
.\venv\Scripts\python.exe -m daemon.main record "docker compose ps" --cwd "$PWD" --exit-code 0
```

Source the adapter:

```powershell
. .\powershell\terminal-copilot.ps1
```

Manual UX check:

1. Type `docker co`.
2. Press `Ctrl+F`.
3. Confirm the line becomes `docker compose ps`.
4. Confirm Enter is not pressed automatically.
5. Press Enter yourself only if you intentionally want to run the command.

## PowerShell 7+

1. Open `pwsh`.
2. Run the preparation commands.
3. Source `.\powershell\terminal-copilot.ps1`.
4. Type `docker co` and press `Ctrl+F`.
5. Confirm suffix insertion, no automatic execution, and no debug output.
6. Type a natural-language phrase such as `how do I list docker services`.
7. Press `Ctrl+F` and confirm no suggestion is inserted.
8. Type a secret-looking buffer such as `export API_KEY=sk-test`.
9. Press `Ctrl+F` and confirm no suggestion is inserted.

## Windows PowerShell 5.1

1. Open `powershell.exe`.
2. Run the preparation commands.
3. Source `.\powershell\terminal-copilot.ps1`.
4. Type `docker co` and press `Ctrl+F`.
5. Confirm suffix insertion, no automatic execution, and no debug output.
6. Confirm no ghost text UI is shown; this MVP uses explicit `Ctrl+F`
   insertion only.

## Windows Terminal

1. Open Windows Terminal with a PowerShell 7+ tab.
2. Repeat the PowerShell 7+ checks.
3. Open a Windows PowerShell 5.1 tab if available.
4. Repeat the Windows PowerShell 5.1 checks.
5. Confirm Windows Terminal itself requires no separate adapter.

## Non-Admin Named Pipe Prediction

1. Use a normal non-admin PowerShell shell.
2. Set `TERM_COPILOT_PIPE` and `TERM_COPILOT_HTTP_URL`.
3. Start the daemon with `--pipe`.
4. Source the adapter.
5. Type `docker co` and press `Ctrl+F`.
6. Confirm `docker compose ps` is inserted.

## Administrator Shell

1. Open PowerShell as Administrator.
2. Do not set `TERM_COPILOT_PIPE` or `TERM_COPILOT_HTTP_URL`.
3. Source the adapter.
4. Type `docker co` and press `Ctrl+F`.
5. Confirm it fails silently and does not attach to a guessed endpoint.
6. Set an explicit endpoint:

```powershell
$env:TERM_COPILOT_PIPE = "\\.\pipe\term-copilot-$env:USERNAME"
```

7. Press `Ctrl+F` again with the daemon running.
8. Confirm prediction uses the explicit pipe.

## HTTP Fallback Prediction

1. Keep the daemon running on port `9876`.
2. Unset the pipe and keep HTTP explicit:

```powershell
Remove-Item Env:\TERM_COPILOT_PIPE -ErrorAction SilentlyContinue
$env:TERM_COPILOT_HTTP_URL = "http://127.0.0.1:9876"
```

3. Source the adapter in a fresh non-admin shell.
4. Type `docker co` and press `Ctrl+F`.
5. Confirm insertion still works through HTTP fallback.

## Pipe-Only Accepted Event

1. Set a validation DB path before starting the daemon:

```powershell
$env:TERM_COPILOT_DB = "$env:TEMP\term-copilot-windows-validation.sqlite3"
$env:TERM_COPILOT_PIPE = "\\.\pipe\term-copilot-$env:USERNAME"
Remove-Item Env:\TERM_COPILOT_HTTP_URL -ErrorAction SilentlyContinue
```

2. Start the daemon with `--pipe`.
3. Record `docker compose ps`.
4. Source the adapter.
5. Type `docker co` and press `Ctrl+F`.
6. Confirm insertion works with no HTTP URL configured.
7. If `sqlite3` is available, confirm accepted count changed:

```powershell
sqlite3 $env:TERM_COPILOT_DB "select command, accepted_count from commands where command='docker compose ps';"
```

## HTTP-Only Accepted Event

1. Start the daemon with HTTP enabled.
2. Remove the pipe and set HTTP:

```powershell
Remove-Item Env:\TERM_COPILOT_PIPE -ErrorAction SilentlyContinue
$env:TERM_COPILOT_HTTP_URL = "http://127.0.0.1:9876"
```

3. Source the adapter in a fresh non-admin shell.
4. Type `docker co` and press `Ctrl+F`.
5. Confirm insertion works.
6. If `sqlite3` is available, confirm accepted count changed:

```powershell
sqlite3 $env:TERM_COPILOT_DB "select command, accepted_count from commands where command='docker compose ps';"
```

## Stopped-Daemon Silent Failure

1. Stop the daemon.
2. Keep the adapter sourced.
3. Type `docker co` and press `Ctrl+F`.
4. Confirm no output, no error text, no prompt corruption, and no command
   execution.

## Missing Adapter Silent Behavior

1. Temporarily point the profile block at a missing adapter path or move the
   adapter file out of the way.
2. Start a new PowerShell session.
3. Confirm profile load is quiet.
4. Restore the adapter path before continuing.

## Install And Uninstall Profile Behavior

Use a temporary profile path to avoid changing your normal profile during
validation:

```powershell
$env:TERM_COPILOT_POWERSHELL_PROFILE = "$env:TEMP\terminal-copilot-profile-test.ps1"
.\venv\Scripts\python.exe -m daemon.main install --shell powershell
Get-Content $env:TERM_COPILOT_POWERSHELL_PROFILE
.\venv\Scripts\python.exe -m daemon.main uninstall --shell powershell
Get-Content $env:TERM_COPILOT_POWERSHELL_PROFILE -ErrorAction SilentlyContinue
```

Confirm install creates one managed block and uninstall removes only that block.

## Benchmark Check

With the daemon running:

```powershell
.\venv\Scripts\python.exe benchmarks\bench_windows_pipe.py --pipe $env:TERM_COPILOT_PIPE --iterations 200
```

Confirm output includes `count`, `min_ms`, `p50_ms`, `p95_ms`, `max_ms`, and
`avg_ms`.
