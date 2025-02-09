"""
对话管理逻辑
"""
import asyncio
import json
from enum import Enum
from typing import AsyncGenerator

from loguru import logger

from ..core.plugin import BasePlugin
from ..core.provider import BaseAIProvider


class Conversation:
    # 新增枚举，避免硬编码
    class Mode(Enum):
        DEFAULT = "default"
        CUSTOM = "custom"

    def __init__(self, provider: BaseAIProvider, plugins: list[BasePlugin]):
        self.provider = provider
        self.plugins = plugins
        self.history = []
        # 修改：使用枚举而非硬编码字符串
        self.mode = Conversation.Mode.DEFAULT

    def switch_provider(self, new_provider: BaseAIProvider):
        # 修改：使用枚举判断
        if self.mode == Conversation.Mode.DEFAULT:
            self.provider = new_provider

    def set_custom_mode(self, custom_provider: BaseAIProvider):
        # 修改：使用枚举赋值
        self.mode = Conversation.Mode.CUSTOM
        self.provider = custom_provider

    async def process_message(self, user_input: str) -> AsyncGenerator[str, None]:
        """处理用户消息,包括历史记录管理和工具调用"""
        # 1. 准备工具配置
        tools = []
        plugin_map = {}  # 用于快速查找插件
        for plugin in self.plugins:
            desc = plugin.description
            tool = {
                "type": "function",
                "function": {
                    "name": desc.name,
                    "description": desc.description,
                    "parameters": {
                        "type": "object",
                        "properties": {
                            key: {"type": "string", "description": value}
                            for key, value in desc.parameters.items()
                        },
                        "required": list(desc.parameters.keys())
                    }
                }
            }
            tools.append(tool)
            plugin_map[desc.name] = plugin

        # 2. 构建完整消息
        messages = self.history + [{"role": "user", "content": user_input}]
        response_content = []  # 用于收集非工具调用的响应内容

        # 3. 调用 Provider 并处理响应
        try:
            async for response in self.provider.ask(messages=messages, tools=tools):
                if tools:  # 工具调用模式
                    # 添加 assistant 消息
                    self.history.append({
                        "role": "assistant",
                        "content": response.content,
                        "tool_calls": response.tool_calls
                    })

                    # 处理工具调用
                    for tool_call in response.tool_calls:
                        if plugin := plugin_map.get(tool_call.function.name):
                            try:
                                arguments = json.loads(tool_call.function.arguments)
                            except json.JSONDecodeError:
                                arguments = {"raw": tool_call.function.arguments}

                            # 调用插件
                            try:
                                logger.debug(f"Plugin {plugin.description.name} arguments: {arguments}")
                                result = await plugin.execute(arguments)
                                # 添加插件响应
                                self.history.append({
                                    "role": "tool",
                                    "content": str(result),
                                    "tool_call_id": tool_call.id
                                })
                            except Exception as e:
                                # 记录插件执行异常
                                logger.error(f"Plugin {plugin.description.name} execute error: {e}")
                                # self.history.append({
                                #     "role": "tool",
                                #     "content": f"插件 {plugin.description.name} 执行异常",
                                #     "tool_call_id": tool_call.id
                                # })

                    # 获取最终响应
                    async for final_chunk in self.provider.ask(messages=self.history):
                        content = final_chunk.content if hasattr(final_chunk, 'content') else ''
                        if content:
                            yield content
                    return
                else:  # 普通对话模式
                    content = response.content if hasattr(response, 'content') else ''
                    if content:
                        yield content
                        response_content.append(content)

            # 更新历史记录
            if response_content:
                self.history.append({
                    "role": "assistant",
                    "content": "".join(response_content)
                })

        except Exception as e:
            logger.error(f"Error in process_message: {e}")
            yield f"Error: {str(e)}"


class ConversationManager:
    CONFIG_FILE = "chat_run_mode_config.json"  # 配置文件路径

    # 新增嵌套枚举
    class GroupMode(Enum):
        DEFAULT = "default"  # 默认：进入用户模式判断
        SHARED = "shared"  # 共享：群内所有用户共用同一对话

    class UserMode(Enum):
        GLOBAL = "global"  # 全局：用户唯一对话
        INDEPENDENT = "independent"  # 群内独立：每个群中彼此独立

    def __init__(self, provider_factory, plugins_factory):
        self.conversations = {}
        self.provider_factory = provider_factory
        self.plugins_factory = plugins_factory
        self._configs = self._load_configs()
        self.locks = {}  # 合并了用户级和群级锁的字典
        self._config_dirty = False

    def _load_configs(self) -> dict:
        try:
            with open(self.CONFIG_FILE, "r", encoding="utf-8") as f:
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

    # 删除旧的 update_run_mode 方法
    # 新增更新群模式
    def update_group_mode(self, group_id: str, new_mode: "ConversationManager.GroupMode"):
        group_config = self._configs.setdefault(group_id, {})
        group_config["group_mode"] = new_mode.value
        self._config_dirty = True
        asyncio.create_task(self._delayed_save_configs())

    # 新增更新用户模式
    def update_user_mode(self, group_id: str, member_id: str, new_mode: "ConversationManager.UserMode"):
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
    def get_user_mode(self, group_id: str, member_id: str) -> "ConversationManager.UserMode":
        group_config = self._configs.get(group_id, {})
        user_modes = group_config.get("user_modes", {})
        mode = user_modes.get(member_id, "global")
        return ConversationManager.UserMode(mode)

    # 修改 _get_conv_key，按层级模式构造 key
    def _get_conv_key(self, group_id: str, member_id: str) -> str:
        if self.get_group_mode(group_id) == ConversationManager.GroupMode.SHARED:
            return group_id
        else:
            if self.get_user_mode(group_id, member_id) == ConversationManager.UserMode.GLOBAL:
                return member_id
            else:
                return f"{group_id}-{member_id}"

    def get_conversation(self, key: str) -> Conversation:
        if key not in self.conversations:
            provider = self.provider_factory(key)
            plugins = self.plugins_factory(key)
            self.conversations[key] = Conversation(provider, plugins)
        return self.conversations[key]

    def remove_conversation(self, key: str):
        if key in self.conversations:
            del self.conversations[key]

    def set_user_custom_mode(self, group_id: str, member_id: str, custom_provider: BaseAIProvider):
        key = self._get_conv_key(group_id, member_id)
        conv = self.get_conversation(key)
        conv.set_custom_mode(custom_provider)

    def switch_user_provider(self, group_id: str, member_id: str, new_provider: BaseAIProvider):
        key = self._get_conv_key(group_id, member_id)
        conv = self.get_conversation(key)
        conv.switch_provider(new_provider)

    def new(self, group_id: str, member_id: str, preset: str = "") -> Conversation:
        key = self._get_conv_key(group_id, member_id)
        if key in self.conversations:
            self.remove_conversation(key)
        provider = self.provider_factory(key)
        plugins = self.plugins_factory(key)
        conversation = Conversation(provider, plugins)
        self.conversations[key] = conversation
        return conversation

    async def __process_conversation(
            self, conversation: Conversation,
            member_name: str, member_id: str, message: str,
            shared: bool
    ) -> str:
        response_chunks = []
        if shared:
            async for chunk in conversation.process_message(f"{member_name} ({member_id}) say: {message}"):
                response_chunks.append(chunk)
        else:
            async for chunk in conversation.process_message(message):
                response_chunks.append(chunk)
        return "".join(response_chunks)

    async def send_message(self, group_id: str, member_id: str, member_name: str, message: str) -> str | None:
        # 用户级锁：使用统一的 self.locks 字典，键加前缀 "user:"
        user_lock_key = f"user:global-{member_id}"
        conv_lock = self.locks.setdefault(user_lock_key, asyncio.Lock())
        try:
            await asyncio.wait_for(conv_lock.acquire(), timeout=300)
        except asyncio.TimeoutError:
            return "错误：上一次对话尚未结束，请稍后再试。"
        try:
            # 根据群模式决定会话 key和共享方式
            if self.get_group_mode(group_id) == ConversationManager.GroupMode.SHARED:
                conversation_key = group_id
                shared = True
            else:
                conversation_key = f"global-{member_id}"
                shared = False
            if conversation_key not in self.conversations:
                provider = self.provider_factory(conversation_key)
                plugins = self.plugins_factory(conversation_key)
                self.conversations[conversation_key] = Conversation(provider, plugins)
            conversation = self.conversations[conversation_key]
            if shared:
                # 群共享模式：使用统一的 self.locks 字典，键前缀 "group:"
                group_lock = self.locks.setdefault(f"group:{group_id}", asyncio.Lock())
                async with group_lock:
                    return await self.__process_conversation(conversation, member_name, member_id, message, shared=True)
            else:
                return await self.__process_conversation(conversation, member_name, member_id, message, shared=False)
        finally:
            conv_lock.release()
