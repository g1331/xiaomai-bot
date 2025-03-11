from typing import TypeVar

from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.parser.twilight import MatchResult

T = TypeVar("T")


def is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def parse_bool(message: str, default_value: bool | None = None) -> bool | None:
    if message.lower() in ("true", "false"):
        return message.lower() == "true"
    return default_value


def parse_type(
    message: MessageChain | str, res_type: type[T], default_value: T | None = None
) -> T:
    if isinstance(message, MessageChain):
        message = message.display.strip()
    message = message.strip()
    if res_type is bool:
        return parse_bool(message, default_value)
    try:
        return res_type(message)
    except ValueError:
        return default_value


def parse_match_type(
    match: MatchResult, res_type: type[T], default_value: T | None = None
) -> T:
    return (
        parse_type(match.result, res_type, default_value)
        if match.matched
        else default_value
    )
