# Native Terminal

Stage 17 starts a new Rust product layer for terminal-copilot: a custom native
Linux terminal application in the Kitty/Alacritty/WezTerm family.

This is not a shell plugin, not a PTY wrapper only, not GTK/VTE, not
QTermWidget, not xterm.js, not Electron, and not Tauri. The existing Python
daemon remains the local intelligence engine for future AI/autosuggestion
features. The Rust terminal is a separate application layer that will later
consume that engine through local IPC.

## Current Scope

The new crate lives in:

```text
native-terminal/
```

Stage 17 implements a small, testable terminal core model:

- `Cell`
- `Cursor`
- `TerminalGrid`
- `Scrollback`
- `TerminalState`
- parser boundary for basic bytes/chars
- session/PTY module boundary with a placeholder for real PTY work
- binary entrypoint with `--version` and `--headless-demo`

Supported core behavior:

- fixed rows/cols grid;
- printable character insertion;
- cursor advance;
- deterministic long-line wrapping;
- newline;
- carriage return;
- backspace;
- scrolling when the cursor moves past the bottom row;
- visible lines exposed as strings for tests and demos.

## What Works Now

Run from the crate directory:

```bash
cargo test
cargo run -- --version
cargo run -- --headless-demo
```

`--headless-demo` feeds sample text through the parser into `TerminalState` and
prints the visible grid. A normal run prints:

```text
native terminal renderer is not implemented yet; use --headless-demo for core demo
```

That message is intentional. Stage 17 does not claim a usable GUI terminal.

## Boundaries

The Python engine keeps ownership of:

- prediction IPC over Unix sockets, Windows Named Pipes and HTTP fallback;
- SQLite history/cache;
- project context;
- scoring and safety;
- redaction;
- optional AI fallback, disabled by default;
- shell adapter compatibility.

The Rust terminal will own:

- terminal grid/state;
- parser and terminal emulation;
- PTY session management;
- native window lifecycle;
- text rendering;
- selection/search/scrollback UI;
- tabs/panes/profiles;
- eventual AI suggestion overlay using the existing local engine.

## Deferred

Stage 17 intentionally does not implement:

- real PTY shell sessions;
- full ANSI/VT parsing;
- colors/styles;
- cursor movement escape sequences;
- alternate screen;
- mouse mode;
- GUI windowing;
- GPU text rendering;
- tabs or panes;
- AI suggestion UI.

## Roadmap

- Stage 18: real PTY shell session.
- Stage 19: native window with `winit`.
- Stage 20: GPU text renderer.
- Stage 21: ANSI/VT parser and colors.
- Stage 22: scrollback, search and selection.
- Stage 23: tabs, panes and profiles.
- Stage 24: AI suggestion overlay using the existing Python engine.
- Stage 25: command palette and smart actions.
- Stage 26: themes, keybindings and config.
- Stage 27: packaging and performance benchmarking.
