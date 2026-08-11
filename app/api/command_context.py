"""Map an HTTP request to a command execution context."""

from app.application.commands import CommandContext


def command_context(request) -> CommandContext:
    return CommandContext(
        actor_type="user",
        actor_id="local",
        request_id=getattr(request.state, "request_id", ""),
        idempotency_key=request.headers.get("idempotency-key") or None,
    )
