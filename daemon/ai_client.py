from __future__ import annotations

from .models import CommandContext, Suggestion, empty_suggestion
from .redactor import contains_secret, redact_payload


class AIClient:
    """Interface for optional cloud completion.

    MVP deliberately keeps AI disabled by default. This class is a safe stub with the
    validation contract already in place, so provider implementations can be added
    without changing predictor flow.
    """

    def __init__(self, enabled: bool = False):
        self.enabled = enabled

    def complete(self, context: CommandContext) -> Suggestion:
        if not self.enabled:
            return empty_suggestion("ai disabled")
        payload = redact_payload(
            {
                "mode": "inline_shell_completion",
                "shell": context.shell,
                "cwd_type": context.project.project_type,
                "project_type": context.project.project_type,
                "current_buffer": context.buffer,
                "cursor_position": context.cursor,
                "git_branch": context.git_branch,
                "known_docker_services": context.project.docker_services,
                "package_scripts": context.project.package_scripts,
                "recent_successful_commands": context.recent_commands,
            }
        )
        if contains_secret(str(payload)):
            return empty_suggestion("redaction failed")
        # Provider implementations should return JSON only and must be validated by predictor.
        return empty_suggestion("provider not configured")
