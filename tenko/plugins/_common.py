from __future__ import annotations

from arclet.entari import MessageChain, Session
from satori import Text

from tenko.context import MessageContext


def context_from_session(session: Session) -> MessageContext:
    """Convert Entari's message session to the Tenko permission context."""

    origin = getattr(session.event, "_origin", None)
    if origin is None:
        raise ValueError("Entari session event does not expose a Satori origin")
    return MessageContext.from_event(origin)


def text_message(content: str) -> MessageChain:
    """Build a native Entari message from a Satori text element."""

    return MessageChain(Text(content))


def normalize_targets(value: object) -> tuple[str, ...]:
    """Normalize values already parsed by Alconna into database IDs."""

    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)  # type: ignore[union-attr]
