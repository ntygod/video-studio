"""Map an HTTP request to a command execution context."""

from fastapi import HTTPException

from app.application.commands import CommandContext

MAX_IDEMPOTENCY_KEY_LENGTH = 200


def command_context(request) -> CommandContext:
    key = (request.headers.get("idempotency-key") or "").strip()
    if len(key) > MAX_IDEMPOTENCY_KEY_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Idempotency-Key 最长 {MAX_IDEMPOTENCY_KEY_LENGTH} 个字符",
        )
    return CommandContext(
        actor_type="user",
        actor_id="local",
        request_id=getattr(request.state, "request_id", ""),
        idempotency_key=key or None,
    )
