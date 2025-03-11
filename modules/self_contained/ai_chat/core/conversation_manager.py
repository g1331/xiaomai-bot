"""
会话管理器
"""

import asyncio
import json
from enum import Enum

from loguru import logger

from ..config import CONFIG_PATH
from ..core.provider import BaseAIProvider, FileContent
from .conversation import Conversation
from .preset import preset_dict


class ConversationManager:
    CONFIG_FILE = CONFIG_PATH / "chat_run_mode_config.json"  # 配置文件路径

    class GroupMode(Enum):
        DEFAULT = "default"  # 默认：进入用户模式判断
        SHARED = "shared"  # 共享：群内所有用户共用同一对话

    class UserMode(Enum):
        GLOBAL = "global"  # 全局：用户唯一对话
        INDEPENDENT = "independent"  # 群内独立：每个群中彼此独立

    class ConversationKey:
        """会话密钥管理"""

        def __init__(
            self, manager: "ConversationManager", group_id: str, member_id: str
        ):
            self.key = self._generate_key(manager, group_id, member_id)
            self.is_shared = (
                manager.get_group_mode(group_id) == ConversationManager.GroupMode.SHARED
            )
            self.lock_key = (
                f"group:{self.key}" if self.is_shared else f"user:{self.key}"
            )

        @staticmethod
        def _generate_key(
            manager: "ConversationManager", group_id: str, member_id: str
        ) -> str:
            """生成会话密钥"""
            if manager.get_group_mode(group_id) == ConversationManager.GroupMode.SHARED:
                return group_id
            else:
                if (
                    manager.get_user_mode(group_id, member_id)
                    == ConversationManager.UserMode.GLOBAL
                ):
                    return f"global-{member_id}"
                else:
                    return f"{group_id}-{member_id}"

    def __init__(self, provider_factory, plugins_factory):
        self.conversations: dict[str, Conversation] = {}
        self.provider_factory = provider_factory
        self.plugins_factory = plugins_factory
        self._configs = self._load_configs()
        self.locks = {}  # 合并了用户级和群级锁的字典
        self._config_dirty = False

    def _load_configs(self) -> dict:
        try:
            with open(self.CONFIG_FILE, encoding="utf-8") as f:
                data = json.load(f)
            return data
        except Exception:
            return {}

    async def _delayed_save_configs(self, delay: float = 5.0):
        await asyncio.sleep(delay)
        try:
            with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self._configs, f, ensure_ascii=False, indent=2)
            self._config_dirty = False
        except Exception:
            pass

    def update_group_mode(
        self, group_id: str, new_mode: "ConversationManager.GroupMode"
    ):
        group_config = self._configs.setdefault(group_id, {})
        group_config["group_mode"] = new_mode.value
        self._config_dirty = True
        asyncio.create_task(self._delayed_save_configs())

    def update_user_mode(
        self, group_id: str, member_id: str, new_mode: "ConversationManager.UserMode"
    ):
        group_config = self._configs.setdefault(group_id, {})
        user_modes = group_config.setdefault("user_modes", {})
        user_modes[member_id] = new_mode.value
        self._config_dirty = True
        asyncio.create_task(self._delayed_save_configs())

    # 获取群模式，默认返回 DEFAULT
    def get_group_mode(self, group_id: str) -> "ConversationManager.GroupMode":
        group_config = self._configs.get(group_id, {})
        mode = group_config.get("group_mode", "default")
        return ConversationManager.GroupMode(mode)

    # 获取用户模式，默认返回 GLOBAL
    def get_user_mode(
        self, group_id: str, member_id: str
    ) -> "ConversationManager.UserMode":
        group_config = self._configs.get(group_id, {})
        user_modes = group_config.get("user_modes", {})
        mode = user_modes.get(member_id, "global")
        return ConversationManager.UserMode(mode)

    def _get_conversation_key(self, group_id: str, member_id: str) -> ConversationKey:
        """获取会话密钥对象"""
        return self.ConversationKey(self, group_id, member_id)

    def _create_conversation(
        self, conv_key: ConversationKey, preset: str = ""
    ) -> Conversation:
        """创建新的对话实例"""
        provider = self.provider_factory(conv_key.key)
        plugins = self.plugins_factory(conv_key.key)
        conversation = Conversation(provider, plugins)
        preset_content = (
            preset_dict[preset]["content"]
            if preset in preset_dict
            else (preset or preset_dict["umaru"]["content"])
        )
        conversation.set_preset(preset_content)
        return conversation

    def get_conversation(self, group_id: str, member_id: str) -> Conversation:
        """获取会话实例"""
        conv_key = self._get_conversation_key(group_id, member_id)
        if conv_key.key not in self.conversations:
            self.conversations[conv_key.key] = self._create_conversation(conv_key)
        return self.conversations[conv_key.key]

    def remove_conversation(self, group_id: str, member_id: str):
        """移除会话实例"""
        conv_key = self._get_conversation_key(group_id, member_id)
        if conv_key.key in self.conversations:
            del self.conversations[conv_key.key]
            # 同时清理相关锁
            if conv_key.lock_key in self.locks:
                del self.locks[conv_key.lock_key]
            if conv_key.is_shared and f"group:{group_id}" in self.locks:
                del self.locks[f"group:{group_id}"]
            logger.info(f"已移除会话: {conv_key.key}")

    def new(self, group_id: str, member_id: str, preset: str = "") -> Conversation:
        """创建新的会话，如果已存在则中断旧会话并创建新会话"""
        conv_key = self._get_conversation_key(group_id, member_id)
        # 若对话不存在，则直接创建新对话
        if conv_key.key not in self.conversations:
            conversation = self._create_conversation(conv_key, preset)
            self.conversations[conv_key.key] = conversation
            return conversation

        # 仅在对话存在时进行锁检查和中断逻辑
        if conv_key.lock_key in self.locks and self.locks[conv_key.lock_key].locked():
            logger.info("检测到当前会话未结束，打断并覆盖旧会话。")
            if conv_key.key in self.conversations:
                old_conversation = self.conversations[conv_key.key]
                old_conversation.interrupt()  # 中断旧对话
                self.remove_conversation(group_id, member_id)
            del self.locks[conv_key.lock_key]

        if (
            conv_key.is_shared
            and f"group:{group_id}" in self.locks
            and self.locks[f"group:{group_id}"].locked()
        ):
            logger.info("检测到群聊对话未结束，打断并覆盖旧群对话。")
            if conv_key.key in self.conversations:
                old_conversation = self.conversations[conv_key.key]
                old_conversation.interrupt()  # 中断旧群对话
                self.remove_conversation(group_id, member_id)
            del self.locks[f"group:{group_id}"]

        if conv_key.lock_key in self.locks:
            del self.locks[conv_key.lock_key]
        if conv_key.is_shared and f"group:{group_id}" in self.locks:
            del self.locks[f"group:{group_id}"]

        conversation = self._create_conversation(conv_key, preset)
        self.conversations[conv_key.key] = conversation
        self.clear_memory(group_id, member_id)
        return conversation

    def set_user_custom_mode(
        self, group_id: str, member_id: str, custom_provider: BaseAIProvider
    ):
        """设置用户自定义模式"""
        conversation = self.get_conversation(group_id, member_id)
        conversation.set_custom_mode(custom_provider)

    def switch_user_provider(
        self, group_id: str, member_id: str, new_provider: BaseAIProvider
    ):
        """切换用户提供商"""
        conversation = self.get_conversation(group_id, member_id)
        conversation.switch_provider(new_provider)

    def set_preset(self, group_id: str, member_id: str, preset: str):
        """设置会话预设"""
        conversation = self.get_conversation(group_id, member_id)
        conversation.set_preset(preset)

    def clear_preset(self, group_id: str, member_id: str):
        """清除会话预设"""
        conversation = self.get_conversation(group_id, member_id)
        conversation.clear_preset()

    def get_preset(self, group_id: str, member_id: str) -> str:
        """获取当前会话预设内容"""
        conversation = self.get_conversation(group_id, member_id)
        return conversation.preset or ""

    def clear_memory(self, group_id: str, member_id: str):
        """清除会话历史记录"""
        conversation = self.get_conversation(group_id, member_id)
        conversation.clear_memory()

    def get_total_usage(self, group_id: str, member_id: str) -> int:
        """获取当前对话消耗的总token数"""
        conv_key = self._get_conversation_key(group_id, member_id)
        if conv_key.key in self.conversations:
            return (
                self.conversations[conv_key.key]
                .provider.get_usage()
                .get("total_tokens", 0)
            )
        return 0

    async def __process_conversation(
        self,
        conversation: Conversation,
        message: str,
        files: list[FileContent] = None,
        use_tool: bool = False,
    ) -> str:
        """处理会话消息并获取完整响应

        Args:
            conversation: 会话对象
            message: 用户消息
            files: 附加文件
            use_tool: 是否使用工具

        Returns:
            str: 完整响应内容
        """
        response_chunks = []
        async for chunk in conversation.process_message(
            message, files, use_tool=use_tool
        ):
            response_chunks.append(chunk)
        return "".join(response_chunks)

    def get_round(self, group_id: str, member_id: str) -> int:
        """获取当前会话轮数"""
        conversation = self.get_conversation(group_id, member_id)
        return conversation.get_round()

    def can_retry(self, group_id: str, member_id: str) -> tuple[bool, str]:
        """检查是否可以重试上一次对话

        Args:
            group_id: 群组ID
            member_id: 成员ID

        Returns:
            Tuple[bool, str]: (是否可以重试, 成功/失败的原因)
        """
        try:
            conversation = self.get_conversation(group_id, member_id)
            return conversation.can_retry()
        except Exception as e:
            logger.error(f"检查重试状态时出错: {str(e)}")
            return False, f"检查重试状态时出错: {str(e)}"

    async def retry(
        self,
        group_id: str,
        member_id: str,
        files: list[FileContent] = None,
        use_tool: bool = False,
    ) -> str | None:
        """重试上一次对话，即删除AI的最后一个回复，重新生成

        Args:
            group_id: 群组ID
            member_id: 成员ID
            files: 附加文件
            use_tool: 是否使用工具

        Returns:
            str或None: 响应内容，如果出错则返回错误消息
        """
        conv_key = self._get_conversation_key(group_id, member_id)
        conv_lock = self.locks.setdefault(conv_key.lock_key, asyncio.Lock())

        if conv_lock.locked():
            return "错误：正在处理上一条消息，请稍后再试。"

        try:
            if not await conv_lock.acquire():
                return "错误：正在处理上一条消息，请稍后再试。"

            conversation = self.conversations.get(conv_key.key)
            if not conversation:
                return "错误：未找到有效的对话记录。"

            # 检查是否可以重试
            can_retry, message = conversation.can_retry()
            if not can_retry:
                return f"无法重试: {message}"

            if conv_key.is_shared:
                group_lock = self.locks.setdefault(f"group:{group_id}", asyncio.Lock())
                if group_lock.locked():
                    return "错误：正在处理群内其他消息，请稍后再试。"
                async with group_lock:
                    return await conversation.retry_last_message(
                        files, use_tool=use_tool
                    )
            else:
                return await conversation.retry_last_message(files, use_tool=use_tool)
        finally:
            if conv_lock.locked():
                conv_lock.release()

    async def send_message(
        self,
        group_id: str,
        member_id: str,
        member_name: str,
        message: str,
        files: list[FileContent] = None,
        use_tool: bool = False,
    ) -> str | None:
        """发送消息到会话并获取响应

        Args:
            group_id: 群组ID
            member_id: 成员ID
            member_name: 成员名称
            message: 消息内容
            files: 附加文件
            use_tool: 是否使用工具

        Returns:
            str或None: 响应内容，如果出错则返回错误消息
        """
        conv_key = self._get_conversation_key(group_id, member_id)
        conv_lock = self.locks.setdefault(conv_key.lock_key, asyncio.Lock())

        if conv_lock.locked():
            return "错误：正在处理上一条消息，请稍后再试。"

        try:
            if not await conv_lock.acquire():
                return "错误：正在处理上一条消息，请稍后再试。"
            # 新增: 若首次对话（会话不存在），则通过 new() 创建新会话
            if conv_key.key not in self.conversations:
                conversation = self.new(group_id, member_id)
            else:
                conversation = self.conversations[conv_key.key]
            if conv_key.is_shared:
                group_lock = self.locks.setdefault(f"group:{group_id}", asyncio.Lock())
                if group_lock.locked():
                    return "错误：正在处理群内其他消息，请稍后再试。"
                async with group_lock:
                    return await self.__process_conversation(
                        conversation, message, files, use_tool=use_tool
                    )
            else:
                return await self.__process_conversation(
                    conversation, message, files, use_tool=use_tool
                )
        finally:
            if conv_lock.locked():
                conv_lock.release()

    def switch_conversation_model(
        self, group_id: str, member_id: str, model_name: str
    ) -> tuple[bool, str]:
        """
        为现有会话切换模型，保留对话历史和预设

        Args:
            group_id: 群组ID
            member_id: 成员ID
            model_name: 目标模型名称

        Returns:
            tuple: (是否成功切换, 成功/失败的详细信息)
        """
        conv_key = self._get_conversation_key(group_id, member_id)

        # 检查会话是否存在
        if conv_key.key not in self.conversations:
            return False, "会话不存在，请先开始对话"

        conversation = self.conversations[conv_key.key]
        current_provider = conversation.provider

        try:
            # 创建新的提供商实例以获取目标模型配置
            new_provider = self.provider_factory(conv_key.key)

            # 先检查模型是否有效
            try:
                new_provider.switch_model(model_name)
            except ValueError as e:
                return False, f"模型切换失败: {str(e)}"

            # 检查模型与当前会话的兼容性
            compatible, reason = conversation.check_model_compatibility(
                new_provider.model_config
            )
            if not compatible:
                return False, reason

            # 直接在当前提供商上切换模型
            current_provider.switch_model(model_name)
            logger.info(f"会话 {conv_key.key} 直接切换到模型 {model_name}")
            return True, f"已成功切换到模型 {model_name}"

        except Exception as e:
            error_msg = f"切换会话模型失败: {str(e)}"
            logger.error(error_msg)
            return False, error_msg
