# Native Terminal

This crate is the Stage 17 foundation for a future native Linux terminal
application in the terminal-copilot project.

It is deliberately small:

- no GTK/VTE;
- no xterm.js;
- no Electron/Tauri;
- no AI UI yet;
- no real PTY shell session yet;
- no GUI renderer yet.

The current crate owns only a testable terminal core model: cells, cursor,
fixed-size grid, scrollback, basic parser boundary, and a headless demo.

## Commands

```bash
cargo test
cargo run -- --version
cargo run -- --headless-demo
```

Normal `cargo run` prints a clear message because the native renderer is not
implemented yet.
