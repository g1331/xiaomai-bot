from __future__ import annotations

from arclet.alconna import Alconna, Args, CommandMeta
from arclet.entari import Session, command, plugin
from arclet.entari.command import Query
from arclet.entari.plugin import PluginRole

from tenko.host.accounts import AccountRegistry, account_registry
from tenko.host.perm import Permission, PermissionChecker
from tenko.plugins._common import context_from_session, text_message


plugin.metadata(
    "响应管理查询",
    PluginRole.NORMAL,
    author=["13"],
    version="0.1.0",
    description="查询 Tenko 多账号在线、群绑定和禁言状态；不提供运行时切换。",
    classifier=["required"],
)
# Entari 0.18.6 has no constructor field for default_switch.  Keep the
# compatibility marker on native metadata for host/plugins.py and inspectors.
plugin.get_plugin().metadata.default_switch = True


permission_checker = PermissionChecker()


def _mute_label(registry: AccountRegistry, account_id: str, group_id: str) -> str:
    if not registry.is_muted(account_id, group_id):
        return "可用"
    until = registry.mute_until(account_id, group_id)
    return "禁言（永久）" if until is None else f"禁言至 {until.isoformat()}"


def _account_label(
    registry: AccountRegistry, account_id: str, group_id: str | None = None
) -> str:
    status = "在线" if registry.is_available(account_id) else "离线"
    if group_id is not None:
        return f"{status}，{_mute_label(registry, account_id, group_id)}"
    return status


def format_group_bots(registry: AccountRegistry, group_id: str | int) -> str:
    """Format one group's bound accounts, retaining unavailable account details."""

    normalized_group = str(group_id)
    accounts = registry.bound_accounts_for_group(normalized_group)
    if not accounts:
        return f"没有找到目标群:{normalized_group}"

    response_type = registry.response_type_for_group(normalized_group)
    if response_type == "deterministic":
        selected = registry.deterministic_account_for_group(normalized_group)
        response_label = f"指定({selected})"
    else:
        response_label = "随机"

    lines = [
        f"群{normalized_group}响应账号:",
        f"响应类型: {response_label}",
        f"当前群绑定BOT: {len(accounts)}",
    ]
    lines.extend(
        f"{account.self_id}: {_account_label(registry, account.self_id, normalized_group)}"
        for account in accounts
    )
    return "\n".join(lines)


def format_account_groups(registry: AccountRegistry, account_id: str | int) -> str:
    """Format one account and every known group route without changing state."""

    normalized_account = str(account_id)
    if registry.get(normalized_account) is None:
        return f"没有找到指定BOT：{normalized_account}"

    groups = registry.groups_for_account(normalized_account)
    lines = [
        f"BOT{normalized_account}: {_account_label(registry, normalized_account)}",
        f"已绑定{len(groups)}个群",
    ]
    if not groups:
        lines.append("暂无群绑定")
        return "\n".join(lines)

    for group_id in groups:
        response_type = registry.response_type_for_group(group_id) or "random"
        lines.append(
            f"群{group_id}: {response_type}; "
            f"{_account_label(registry, normalized_account, group_id)}"
        )
    return "\n".join(lines)


def format_online_bots(registry: AccountRegistry) -> str:
    """Format all registered accounts and their current host availability."""

    accounts = tuple(registry.accounts.items())
    online_count = sum(registry.is_available(account_id) for account_id, _ in accounts)
    lines = [f"在线BOT列表:{online_count}/{len(accounts)}"]
    if not accounts:
        lines.append("当前没有注册BOT")
        return "\n".join(lines)

    for account_id, _ in accounts:
        groups = registry.groups_for_account(account_id)
        group_label = f"已绑定{len(groups)}个群"
        lines.append(
            f"{account_id}: {_account_label(registry, account_id)}，{group_label}"
        )
    return "\n".join(lines)


async def _authorized(session: Session, required: int) -> bool:
    context = context_from_session(session)
    return (
        context.chat_type == "group"
        and await permission_checker.require_group_perm(context, Permission.ActiveGroup)
        and await permission_checker.require_perm(context, required)
    )


bot_list_command = Alconna(
    "BOT列表",
    Args["group_id?", int],
    meta=CommandMeta(
        "查询指定群的多账号绑定和禁言状态",
        usage="BOT列表 [群号]",
        example="$BOT列表\n$BOT列表 40001",
        compact=True,
    ),
)


@command.on(bot_list_command)
async def bot_list(
    session: Session,
    group_id: Query[int] = Query("group_id", None),
):
    if not await _authorized(session, Permission.BotAdmin):
        return text_message("权限不足")
    context = context_from_session(session)
    target_group = str(group_id.result) if group_id.available else context.channel_id
    return text_message(format_group_bots(account_registry, target_group))


bot_group_list_command = Alconna(
    "BOT群列表",
    Args["account_id?", str],
    meta=CommandMeta(
        "查询 BOT 的群绑定和群内禁言状态",
        usage="BOT群列表 [BOT账号]",
        example="$BOT群列表\n$BOT群列表 10001",
        compact=False,
    ),
)


@command.on(bot_group_list_command)
async def bot_group_list(
    session: Session,
    account_id: Query[str] = Query("account_id", None),
):
    if not await _authorized(session, Permission.BotAdmin):
        return text_message("权限不足")
    if account_id.available:
        return text_message(format_account_groups(account_registry, account_id.result))

    if not account_registry.accounts:
        return text_message("当前没有注册BOT")
    return text_message(
        "\n\n".join(
            format_account_groups(account_registry, current_id)
            for current_id in account_registry.accounts
        )
    )


online_bot_command = Alconna(
    "在线BOT",
    Args["group_id?", int],
    meta=CommandMeta(
        "查询在线 BOT 及其群绑定状态",
        usage="在线BOT [群号]",
        example="$在线BOT\n$在线BOT 40001",
        compact=True,
    ),
)


@command.on(online_bot_command)
async def online_bot(
    session: Session,
    group_id: Query[int] = Query("group_id", None),
):
    if not await _authorized(session, Permission.User):
        return text_message("权限不足")
    context = context_from_session(session)
    target_group = str(group_id.result) if group_id.available else context.channel_id
    normalized_target = str(target_group)
    bound = account_registry.bound_accounts_for_group(normalized_target)
    available = account_registry.accounts_for_group(normalized_target)
    if not bound:
        return text_message(f"没有找到目标群:{normalized_target}")
    result = format_group_bots(account_registry, normalized_target)
    return text_message(
        f"群{normalized_target}在线BOT: {len(available)}/{len(bound)}\n{result}"
    )
