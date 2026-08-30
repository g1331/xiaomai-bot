from __future__ import annotations

from collections.abc import Iterable

import pytest
from arclet.alconna import Alconna, command_manager

from tenko.commands import configure_command_prefix


_POSITIVE_CASES: dict[str, dict[str, tuple[str, ...]]] = {
    "帮助": {
        "positive": ("/帮助", "/帮助 1"),
        "boundary": ("/帮助-1", "/ 帮助"),
    },
    "群设置": {
        "positive": ("/群设置", "/群设置 --group 40001"),
        "boundary": ("/群设置-1", "/ 群设置"),
    },
    "禁言": {
        "positive": ("/禁言 20002 5", "/禁言 -t 5 20002"),
        "boundary": ("/禁言-1", "/ 禁言"),
    },
    "解禁": {
        "positive": ("/解禁 20002", "/解禁"),
        "boundary": ("/解禁-1", "/ 解禁"),
    },
    "解禁自己": {
        "positive": ("/解禁自己",),
        "boundary": ("/解禁自己-1", "/ 解禁自己"),
    },
    "开启": {
        "positive": ("/开启 demo",),
        "boundary": ("/开启-1", "/ 开启"),
    },
    "关闭": {
        "positive": ("/关闭 demo",),
        "boundary": ("/关闭-1", "/ 关闭"),
    },
    "全体禁言": {
        "positive": ("/全体禁言",),
        "boundary": ("/全体禁言-1", "/ 全体禁言"),
    },
    "全体解禁": {
        "positive": ("/全体解禁",),
        "boundary": ("/全体解禁-1", "/ 全体解禁"),
    },
    "撤回": {
        "positive": ("/撤回",),
        "boundary": ("/撤回-1", "/ 撤回"),
    },
    "踢出": {
        "positive": ("/踢出 20002", "/踢出"),
        "boundary": ("/踢出-1", "/ 踢出"),
    },
    "同意邀请": {
        "positive": ("/同意邀请 request-1",),
        "boundary": ("/同意邀请", "/ 同意邀请"),
    },
    "拒绝邀请": {
        "positive": ("/拒绝邀请 request-1", "/拒绝邀请 request-1 理由"),
        "boundary": ("/拒绝邀请", "/ 拒绝邀请"),
    },
    "待审邀请": {
        "positive": ("/待审邀请",),
        "boundary": ("/待审邀请-1", "/ 待审邀请"),
    },
    "重置能力": {
        "positive": ("/重置能力", "/重置能力 10001"),
        "boundary": ("/重置能力-1", "/ 重置能力"),
    },
    "公告": {
        "positive": ("/公告 帮助系统 维护通知", "/公告 帮助系统 维护 通知 -t 2"),
        "boundary": ("/公告-1", "/ 公告"),
    },
    "修改权限": {
        "positive": ("/修改权限 16 30001", "/修改权限 32 30001 30002"),
        "boundary": ("/修改权限-1", "/ 修改权限"),
    },
    "修改群权限": {
        "positive": ("/修改群权限 1", "/修改群权限 3 --group 40001"),
        "boundary": ("/修改群权限x", "/ 修改群权限"),
    },
    "修改群权限类型": {
        "positive": (
            "/修改群权限类型 admin",
            "/修改群权限类型 default --group 40001",
        ),
        "boundary": ("/修改群权限类型-1", "/ 修改群权限类型"),
    },
    "VIP群列表": {
        "positive": ("/VIP群列表", "/VIP群列表 "),
        "boundary": ("/VIP群列表-1", "/ VIP群列表"),
    },
    "权限列表": {
        "positive": ("/权限列表", "/权限列表 --group 40001"),
        "boundary": ("/权限列表-1", "/ 权限列表"),
    },
    "全局黑": {
        "positive": ("/全局黑 添加 30001", "/全局黑 删除 30001"),
        "boundary": ("/全局黑-1", "/ 全局黑"),
    },
    "全局黑名单列表": {
        "positive": ("/全局黑名单列表", "/全局黑名单列表 "),
        "boundary": ("/全局黑名单列表-1", "/ 全局黑名单列表"),
    },
    "BOT管理": {
        "positive": ("/BOT管理 添加 30001", "/BOT管理 删除 30001"),
        "boundary": ("/BOT管理-1", "/ BOT管理"),
    },
    "BOT管理列表": {
        "positive": ("/BOT管理列表", "/BOT管理列表 "),
        "boundary": ("/BOT管理列表-1", "/ BOT管理列表"),
    },
    "-bot": {
        "positive": ("/-bot", "/状态 -t"),
        "boundary": ("/-bot-1", "/ -bot"),
    },
}


def _parse(command: Alconna, text: str):
    try:
        return command.parse(text)
    except (
        Exception
    ) as exc:  # pragma: no cover - turns parser regressions into assertion output
        pytest.fail(f"解析 {text!r} 时不应抛出 {exc!r}")


def _commands_for_loaded_plugin() -> Iterable[Alconna]:
    return command_manager.get_commands()


@pytest.mark.parametrize(
    "loaded_plugin",
    [
        "helper",
        "group_manager",
        "perm_manager",
        "status",
        "announcement",
        "feature_manager",
    ],
    indirect=True,
)
def test_every_required_command_has_positive_negative_and_boundary_matrix(
    loaded_plugin,
) -> None:
    commands = list(_commands_for_loaded_plugin())
    assert commands

    for command in commands:
        case = _POSITIVE_CASES[command.command]
        assert command.prefixes == ["/"]

        for text in case["positive"]:
            assert _parse(command, text).matched, (command.command, text)

        negative = (
            case["positive"][0].removeprefix("/"),
            "HELP",
            f"/{command.command}x",
            f"请{command.command}我",
        )
        if command.command in {"同意邀请", "拒绝邀请"}:
            # request_id is an opaque platform flag and can legally be
            # adjacent to the command header; do not treat that token as a
            # command-boundary assertion.
            negative = tuple(
                text for text in negative if text != f"/{command.command}x"
            )
        for text in negative:
            assert not _parse(command, text).matched, (command.command, text)

        for text in case["boundary"]:
            result = _parse(command, text)
            if command.command == "帮助" and text == "/帮助-1":
                assert result.matched
                assert loaded_plugin.build_help(result.main_args["index"]) == (
                    "编号不在范围内~"
                )
            else:
                assert not result.matched, (command.command, text)


@pytest.mark.parametrize("loaded_plugin", ["helper"], indirect=True)
def test_help_list_and_out_of_range_detail_use_native_prefix(loaded_plugin) -> None:
    # The fixture loads helper only, so its native registry is deterministic.
    assert "/帮助" in loaded_plugin.build_help()
    assert loaded_plugin.build_help(0) == "编号不在范围内~"
    assert loaded_plugin.build_help(99999999999999999999) == "编号不在范围内~"
    assert not _parse(loaded_plugin.help_command, "/帮助 abc").matched
    assert _parse(loaded_plugin.help_command, "/帮助 0").matched
    assert _parse(loaded_plugin.help_command, "/帮助 99999999999999999999").matched


def test_command_prefix_configuration_is_applied_before_alconna_construction() -> None:
    configure_command_prefix("!")
    command = Alconna("临时前缀命令")
    try:
        assert command.prefixes == ["!"]
        assert command.parse("!临时前缀命令").matched
        assert not command.parse("临时前缀命令").matched
    finally:
        command_manager.delete(command)
        configure_command_prefix("/")
