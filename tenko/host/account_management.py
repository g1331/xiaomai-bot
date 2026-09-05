"""账户管理偏好与连接准入；协议连接仍由 Satori 创建。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from .accounts import AccountRegistry, account_key, account_reference
from .actions import ActionCapability, ActionService

if TYPE_CHECKING:
    from ..db.repositories import ManagementRepository


class AccountManagement:
    def __init__(self, accounts: AccountRegistry, actions: ActionService) -> None:
        self.accounts = accounts
        self.actions = actions
        self.repository: ManagementRepository | None = None
        self.preferences: dict[tuple[str, str], dict[str, Any]] = {}
        self.ready = False
        self.lock = asyncio.Lock()

    async def initialize(self, legacy_capabilities: Any) -> None:
        if self.repository is None:
            raise RuntimeError("账户管理数据库未配置")
        self.ready = False
        rows = await self.repository.accounts()
        preferences = {(row["platform"], row["id"]): row for row in rows}
        # 导入标记与账户行分开保存，忘记账户后不会被旧 TOML 再次创建。
        if not await self.repository.setting("account-capabilities-imported"):
            from .actions import _capability

            for account_id, capabilities in legacy_capabilities.items():
                key = ("onebot", str(account_id))
                if key not in preferences:
                    value = self.default(key)
                    value["capabilities"] = {
                        _capability(name).value: enabled
                        for name, enabled in capabilities.items()
                    }
                    await self.repository.save_account(value)
                    preferences[key] = value
            await self.repository.save_setting("account-capabilities-imported", True)
        self.preferences = preferences
        for key, value in preferences.items():
            self.accounts.set_enabled(key, value["enabled"])
        self._apply_capabilities()
        self.ready = True

    async def restore_settings(self, features, plugins) -> None:
        """即使 WebUI 关闭，也恢复已经保存的运行期选择。"""

        if self.repository is None:
            raise RuntimeError("管理数据库未配置")
        default_enabled = await self.repository.setting("feature-default")
        if default_enabled is not None:
            if type(default_enabled) is not bool:
                raise ValueError("持久化功能默认值非法")
            features.default_enabled = default_enabled
        disabled = await self.repository.setting("disabled-plugins") or []
        if not isinstance(disabled, list) or not all(
            isinstance(name, str) for name in disabled
        ):
            raise ValueError("持久化插件状态非法")
        if plugins is not None:
            for info in plugins.discover():
                if info.name in disabled and not plugins.is_protected(info):
                    if not await plugins.set_enabled(info, False):
                        raise RuntimeError(f"无法恢复插件状态: {info.name}")

    @staticmethod
    def default(key: tuple[str, str]) -> dict[str, Any]:
        return {
            "platform": key[0],
            "id": key[1],
            "alias": "",
            "enabled": True,
            "capabilities": {},
        }

    def can_connect(self, platform: str, account_id: str) -> bool:
        return self.ready and self.accounts.is_enabled((platform, account_id))

    def _apply_capabilities(self) -> None:
        self.actions.configure_capability_overrides(
            {
                account_reference(key): value["capabilities"]
                for key, value in self.preferences.items()
            }
        )

    async def update(self, key: tuple[str, str], changes: dict[str, Any]) -> None:
        if not self.ready or self.repository is None:
            raise RuntimeError("账户管理数据库尚未就绪")
        value = {**self.preferences.get(key, self.default(key)), **changes}
        if set(changes) - {"alias", "enabled", "capabilities"}:
            raise ValueError("未知账户设置")
        if not isinstance(value["alias"], str) or len(value["alias"]) > 128:
            raise ValueError("别名必须是不超过 128 字的字符串")
        if type(value["enabled"]) is not bool:
            raise ValueError("enabled 必须是布尔值")
        caps = value["capabilities"]
        if not isinstance(caps, dict) or any(
            name not in {item.value for item in ActionCapability}
            or type(enabled) is not bool
            for name, enabled in caps.items()
        ):
            raise ValueError("能力覆盖必须使用已知能力名和布尔值")
        await self.repository.save_account(value)
        self.preferences[key] = value
        self.accounts.set_enabled(key, value["enabled"])
        self._apply_capabilities()

    async def forget(self, key: tuple[str, str]) -> None:
        if not self.ready or self.repository is None:
            raise RuntimeError("账户管理数据库尚未就绪")
        # 先保存路由清理，失败时不能假报记录已删除。
        self.accounts.unregister(key)
        await self.accounts.flush_persistence()
        await self.accounts.persist_state()
        await self.repository.forget_account(*key)
        self.preferences.pop(key, None)
        self.actions.reset_capabilities(account_reference(key))
        self.accounts.set_enabled(key, True)
        self._apply_capabilities()

    def contains(self, key: tuple[str, str]) -> bool:
        return key in self.preferences or self.accounts.get(key) is not None

    def list_accounts(self) -> list[dict[str, Any]]:
        keys = list(self.preferences)
        keys.extend(
            key
            for account in self.accounts.accounts.values()
            if (key := account_key(account)) not in keys
        )
        return [dict(self.preferences.get(key, self.default(key))) for key in keys]
