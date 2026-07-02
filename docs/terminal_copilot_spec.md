# Terminal Copilot MVP Spec

The MVP must:

1. Run a local daemon.
2. Connect from zsh.
3. Read current `BUFFER`.
4. Save executed commands.
5. Suggest command continuations from history.
6. Use cwd/project/git context.
7. Display ghost suggestion through zsh-autosuggestions.
8. Accept suggestion with Right Arrow or Ctrl+F.
9. Ignore natural language input.
10. Avoid AI calls by default.

This repository implements those points as a working first source tree.
