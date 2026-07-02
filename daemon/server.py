from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .config import load_settings
from .models import PredictRequest
from .predictor import Predictor

settings = load_settings()
predictor = Predictor(settings=settings)
app = FastAPI(title="Terminal Copilot Daemon", version="0.1.0")


class PredictBody(BaseModel):
    buffer: str = Field(default="")
    cursor: int | None = None
    cwd: str | None = None
    shell: str = "zsh"
    user: str | None = None
    effective_uid: int | None = None
    original_user: str | None = None
    root_mode: bool = False


class EventBody(BaseModel):
    event: str
    command: str | None = None
    buffer: str | None = None
    suggestion: str | None = None
    source: str | None = None
    cwd: str | None = None
    shell: str = "zsh"
    exit_code: int | None = None
    duration_ms: int | None = None


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "pid": os.getpid(), "db_path": settings.daemon.db_path}


@app.post("/predict")
def predict(body: PredictBody) -> dict[str, Any]:
    request = PredictRequest(**body.model_dump())
    return predictor.predict(request).to_dict()


@app.post("/events")
def events(body: EventBody) -> dict[str, Any]:
    if body.event == "command_executed" and body.command:
        predictor.record_command(body.command, cwd=body.cwd, exit_code=body.exit_code, duration_ms=body.duration_ms, shell=body.shell)
        return {"ok": True}
    if body.event == "suggestion_accepted" and body.suggestion:
        predictor.mark_suggestion(body.suggestion, accepted=True)
        return {"ok": True}
    if body.event == "suggestion_ignored" and body.suggestion:
        predictor.mark_suggestion(body.suggestion, accepted=False)
        return {"ok": True}
    return {"ok": False, "reason": "unknown or incomplete event"}
