# Architecture

Runtime path:

```text
zsh/bash input
  -> shell integration
  -> local daemon
  -> context detector
  -> history/project candidates
  -> scoring + safety
  -> cache / optional AI fallback
  -> ghost suggestion
```

The shell integration is not the brain. It only captures the current buffer, cwd, shell/user/root metadata and sends it to the daemon. The daemon owns history, scoring, safety, cache and AI validation.

## Runtime modules

- `daemon/server.py`: FastAPI daemon API.
- `daemon/predictor.py`: pipeline coordinator.
- `daemon/history_store.py`: SQLite command memory.
- `daemon/cache_store.py`: SQLite suggestion cache.
- `daemon/context_detector.py`: command-like detection and context builder.
- `daemon/project_detector.py`: project root/type parser.
- `daemon/scoring.py`: local ranking.
- `daemon/safety.py`: risk classification.
- `daemon/redactor.py`: client-side redaction utility.
- `zsh/terminal-copilot.zsh`: zsh autosuggestion strategy.
- `bash/terminal-copilot.bash`: bash fallback.

## Stages

Stage 1: local predictor without AI.

Stage 2: project context.

Stage 3: AI inline completion behind redaction and safety gates.

Stage 4: adaptive learning from accepted/ignored/success/fail events.

Stage 5: daemon auto-start, logs, config reload and hardening.
