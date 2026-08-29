from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from satori import ChannelType, EventType, Image, Text
from satori.element import Element
from satori.model import Event

ChatType = Literal["private", "group", "other"]


def _value(value: object) -> str:
    return str(getattr(value, "value", value))


def _extract_content(elements: Iterable[Element]) -> tuple[str, tuple[str, ...]]:
    text_parts: list[str] = []
    image_urls: list[str] = []

    def visit(element: Element) -> None:
        if isinstance(element, Text):
            text_parts.append(element.text)
        elif isinstance(element, Image):
            image_urls.append(element.src)

        for child in element.children:
            visit(child)

    for element in elements:
        visit(element)
    return "".join(text_parts), tuple(image_urls)


@dataclass(frozen=True, slots=True)
class MessageContext:
    """与协议无关的消息上下文，供后续插件迁移使用。"""

    account_id: str
    event_type: str
    protocol_event_type: str | None
    chat_type: ChatType
    channel_id: str
    user_id: str
    message_id: str
    text: str
    image_urls: tuple[str, ...]
    member_role: str | None = None

    @classmethod
    def from_event(cls, event: Event) -> MessageContext:
        if event.login.user is None:
            raise ValueError("消息事件缺少登录账号信息")
        if event.channel is None:
            raise ValueError("消息事件缺少 channel")
        if event.user is None:
            raise ValueError("消息事件缺少 user")
        if event.message is None:
            raise ValueError("消息事件缺少 message")

        event_type = _value(event.type)
        protocol_event_type = _value(event._type) if event._type is not None else None
        text, image_urls = _extract_content(event.message.message)

        if event.channel.type == ChannelType.DIRECT or event_type.startswith(
            "message.private"
        ):
            chat_type: ChatType = "private"
        elif (
            event.guild is not None
            or event_type.startswith("message.group")
            or event_type.startswith("message_sent.group")
        ):
            chat_type = "group"
        else:
            chat_type = "other"

        return cls(
            account_id=event.login.user.id,
            event_type=event_type,
            protocol_event_type=protocol_event_type,
            chat_type=chat_type,
            channel_id=event.channel.id,
            user_id=event.user.id,
            message_id=event.message.id,
            text=text,
            image_urls=image_urls,
            member_role=(
                _member_role(event.member) if event.member is not None else None
            ),
        )


def _member_role(member: object) -> str | None:
    """把 Satori Member 的标准角色 ID 映射为 Tenko 权限角色。"""

    for role in getattr(member, "roles", ()):
        role_id = _value(getattr(role, "id", "")).lower()
        if role_id in {"owner", "admin", "member"}:
            return role_id
        if role_id in {"administrator", "管理员"}:
            return "admin"
        if role_id in {"群主"}:
            return "owner"
    return None


def is_message_created(event: Event) -> bool:
    """判断事件是否是可交给最小消息闭环处理的消息事件。"""

    return _value(event.type) == EventType.MESSAGE_CREATED.value
