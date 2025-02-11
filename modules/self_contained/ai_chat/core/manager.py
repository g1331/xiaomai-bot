"""
对话管理逻辑
"""
import asyncio
import json
from enum import Enum
from typing import AsyncGenerator
from datetime import datetime

from loguru import logger

from .preset import preset_dict
from ..config import CONFIG_PATH
from ..core.plugin import BasePlugin
from ..core.provider import BaseAIProvider


class Conversation:
    class Mode(Enum):
        DEFAULT = "default"
        CUSTOM = "custom"

    def __init__(self, provider: BaseAIProvider, plugins: list[BasePlugin]):
        self.provider = provider
        self.plugins = plugins
        self.history = []
        self.mode = Conversation.Mode.DEFAULT
        self.preset = None  # 新增: preset 设定
        self.interrupted = False  # 新增: 中断标记

    def switch_provider(self, new_provider: BaseAIProvider):
        if self.mode == Conversation.Mode.DEFAULT:
            self.provider = new_provider

    def set_custom_mode(self, custom_provider: BaseAIProvider):
        self.mode = Conversation.Mode.CUSTOM
        self.provider = custom_provider

    def set_preset(self, preset: str):
        """设置对话的预设提示词，独立管理，不直接修改历史"""
        if not preset:
            return
        self.preset = preset

    def clear_preset(self):
        """清除预设提示词"""
        self.preset = None

    def clear_memory(self):
        """清除所有对话历史，preset单独管理"""
        self.history = []

    def interrupt(self):
        """中断当前对话"""
        self.interrupted = True

    def _get_time_message(self) -> dict:
        """获取当前时间信息的消息"""
        current_time = datetime.now()
        weekday_map = {
            0: "星期一",
            1: "星期二",
            2: "星期三",
            3: "星期四",
            4: "星期五",
            5: "星期六",
            6: "星期日"
        }
        weekday = weekday_map[current_time.weekday()]
        time_str = current_time.strftime(f"%Y年%m月%d日 {weekday} %H:%M:%S")
        return {
            "role": "system",
            "content": f"现在的时间是北京时间: {time_str}"
        }

    def _get_base_messages(self) -> list:
        """获取基础消息列表，仅包含当前时间信息
           （preset 消息已通过 set_preset 插入到 history 中，不再重复添加）
        """
        return [self._get_time_message()]

    def get_round(self) -> int:
        # 要排除 system 和 tool 的消息，然后计算 user 和 assistant 的消息数量，然后除以 2
        return len([msg for msg in self.history if msg["role"] in ["user", "assistant"]]) // 2

    async def process_message(self, user_input: str, use_tool: bool = False) -> AsyncGenerator[str, None]:
        """处理用户消息,包括历史记录管理和工具调用"""
        try:
            # 重置中断标记
            self.interrupted = False

            # 1. 准备工具配置
            tools = []
            plugin_map = {}

            # 检查并清理过多的历史记录
            max_token = self.provider.config.max_total_tokens
            if self.provider.get_usage().get("total_tokens", 0) > max_token:
                for i, msg in enumerate(self.history):
                    self.history.pop(i)
                    break

            # 构造传入 AI 模型的消息列表，按照 [系统固定消息] + [preset] + [user/model 交互历史] + [当前用户消息]
            base_messages = self._get_base_messages()
            preset_messages = [{"role": "system", "content": self.preset}] if self.preset else []
            user_input_messages = [{"role": "user", "content": user_input}]
            ask_messages = base_messages + preset_messages + self.history + user_input_messages
            tool_response_messages = []

            if use_tool:  # 只有在启用工具时才准备工具配置
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

            response_contents = []
            response_messages = []

            async for response in self.provider.ask(messages=ask_messages, tools=tools if use_tool else None):
                # 检查是否被中断
                if self.interrupted:
                    logger.info("对话被中断")
                    return

                if use_tool and tools and response.tool_calls:
                    # 工具调用模式
                    tool_response_messages.append({
                        "role": "assistant",
                        "content": response.content,
                        "tool_calls": response.tool_calls
                    })

                    async def execute_tool_call(tool_call):
                        _plugin = plugin_map.get(tool_call.function.name)
                        if not _plugin:
                            return None
                        try:
                            arguments = json.loads(tool_call.function.arguments)
                        except json.JSONDecodeError:
                            arguments = {"raw": tool_call.function.arguments}
                        try:
                            logger.debug(f"Plugin {_plugin.description.name} execute with arguments: {arguments}")
                            result = await _plugin.execute(arguments)
                            return {
                                "role": "tool",
                                "content": str(result),
                                "tool_call_id": tool_call.id
                            }
                        except Exception as e:
                            logger.error(f"Plugin {_plugin.description.name} execute error: {e}")
                            return {
                                "role": "tool",
                                "content": f"插件 {_plugin.description.name} 执行异常",
                                "tool_call_id": tool_call.id
                            }

                    tasks = [execute_tool_call(tc) for tc in response.tool_calls if plugin_map.get(tc.function.name)]
                    results = await asyncio.gather(*tasks, return_exceptions=False)
                    tool_response_messages.extend([r for r in results if r is not None])

                    # 获取最终响应
                    ask_messages.extend(tool_response_messages)
                    async for final_chunk in self.provider.ask(messages=ask_messages):
                        content = final_chunk.content if hasattr(final_chunk, 'content') else ''
                        if content:
                            yield content
                            response_contents.append(content)
                else:  # 普通对话模式
                    content = response.content if hasattr(response, 'content') else ''
                    if content:
                        yield content
                        response_contents.append(content)

            # 组装结果
            if response_contents:
                response_messages = [{"role": "assistant", "content": "".join(response_contents)}]

            # 更新历史记录
            if response_contents:
                self.history.extend(user_input_messages)
                if tool_response_messages:
                    self.history.extend(tool_response_messages)
                self.history.extend(response_messages)

        except Exception as e:
            logger.error(f"Error in process_message: {e}")
            yield f"Error: {str(e)}"


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

        def __init__(self, manager: 'ConversationManager', group_id: str, member_id: str):
            self.key = self._generate_key(manager, group_id, member_id)
            self.is_shared = manager.get_group_mode(group_id) == ConversationManager.GroupMode.SHARED
            self.lock_key = f"group:{self.key}" if self.is_shared else f"user:{self.key}"

        @staticmethod
        def _generate_key(manager: 'ConversationManager', group_id: str, member_id: str) -> str:
            """生成会话密钥"""
            if manager.get_group_mode(group_id) == ConversationManager.GroupMode.SHARED:
                return group_id
            else:
                if manager.get_user_mode(group_id, member_id) == ConversationManager.UserMode.GLOBAL:
                    return f"global-{member_id}"
                else:
                    return f"{group_id}-{member_id}"

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

    def update_group_mode(self, group_id: str, new_mode: "ConversationManager.GroupMode"):
        group_config = self._configs.setdefault(group_id, {})
        group_config["group_mode"] = new_mode.value
        self._config_dirty = True
        asyncio.create_task(self._delayed_save_configs())

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

    def _get_conversation_key(self, group_id: str, member_id: str) -> ConversationKey:
        """获取会话密钥对象"""
        return self.ConversationKey(self, group_id, member_id)

    def get_conversation(self, group_id: str, member_id: str) -> Conversation:
        """获取会话实例"""
        conv_key = self._get_conversation_key(group_id, member_id)
        if conv_key.key not in self.conversations:
            provider = self.provider_factory(conv_key.key)
            plugins = self.plugins_factory(conv_key.key)
            self.conversations[conv_key.key] = Conversation(provider, plugins)
        return self.conversations[conv_key.key]

    def remove_conversation(self, group_id: str, member_id: str):
        """移除会话实例"""
        conv_key = self._get_conversation_key(group_id, member_id)
        if conv_key.key in self.conversations:
            del self.conversations[conv_key.key]

    def new(self, group_id: str, member_id: str, preset: str = "") -> Conversation:
        conv_key = self._get_conversation_key(group_id, member_id)

        # 如果发现用户锁处于占用状态，则打断旧对话
        if conv_key.lock_key in self.locks and self.locks[conv_key.lock_key].locked():
            logger.info("检测到当前会话未结束，打断并覆盖旧会话。")
            # 中断旧的对话
            if conv_key.key in self.conversations:
                old_conversation = self.conversations[conv_key.key]
                old_conversation.interrupt()  # 新增：中断旧对话
                self.remove_conversation(group_id, member_id)
            del self.locks[conv_key.lock_key]

        # 如果是共享模式，检查群锁是否处于占用状态，若占用则打断当前群对话
        if conv_key.is_shared and f"group:{group_id}" in self.locks and self.locks[f"group:{group_id}"].locked():
            logger.info("检测到群聊对话未结束，打断并覆盖旧群对话。")
            # 中断旧的群对话
            if conv_key.key in self.conversations:
                old_conversation = self.conversations[conv_key.key]
                old_conversation.interrupt()  # 新增：中断旧群对话
                self.remove_conversation(group_id, member_id)
            del self.locks[f"group:{group_id}"]

        # 释放已存在的锁（此时若仍有旧锁则删除）
        if conv_key.lock_key in self.locks:
            del self.locks[conv_key.lock_key]
        if conv_key.is_shared and f"group:{group_id}" in self.locks:
            del self.locks[f"group:{group_id}"]

        # 创建新的会话
        provider = self.provider_factory(conv_key.key)
        plugins = self.plugins_factory(conv_key.key)
        conversation = Conversation(provider, plugins)
        preset = preset_dict[preset]["content"] if preset in preset_dict \
            else (preset if preset else preset_dict["umaru"]["content"])
        conversation.set_preset(preset)
        self.conversations[conv_key.key] = conversation
        self.clear_memory(group_id, member_id)
        return conversation

    def set_user_custom_mode(self, group_id: str, member_id: str, custom_provider: BaseAIProvider):
        conversation = self.get_conversation(group_id, member_id)
        conversation.set_custom_mode(custom_provider)

    def switch_user_provider(self, group_id: str, member_id: str, new_provider: BaseAIProvider):
        conversation = self.get_conversation(group_id, member_id)
        conversation.switch_provider(new_provider)

    def set_preset(self, group_id: str, member_id: str, preset: str):
        conversation = self.get_conversation(group_id, member_id)
        conversation.set_preset(preset)

    def clear_preset(self, group_id: str, member_id: str):
        conversation = self.get_conversation(group_id, member_id)
        conversation.clear_preset()

    def get_preset(self, group_id: str, member_id: str) -> str:
        conversation = self.get_conversation(group_id, member_id)
        return conversation.preset or ""

    def clear_memory(self, group_id: str, member_id: str):
        conversation = self.get_conversation(group_id, member_id)
        conversation.clear_memory()

    # 获取当前对话消耗的总usage
    def get_total_usage(self, group_id: str, member_id: str) -> int:
        conv_key = self._get_conversation_key(group_id, member_id)
        if conv_key.key in self.conversations:
            return self.conversations[conv_key.key].provider.get_usage().get("total_tokens", 0)
        return 0

    async def __process_conversation(
            self, conversation: Conversation,
            member_name: str, member_id: str, message: str,
            shared: bool, use_tool: bool = False
    ) -> str:
        response_chunks = []
        if shared:
            async for chunk in conversation.process_message(f"{member_name}(QQ:{member_id})说:{message}",
                                                            use_tool=use_tool):
                response_chunks.append(chunk)
        else:
            async for chunk in conversation.process_message(message, use_tool=use_tool):
                response_chunks.append(chunk)
        return "".join(response_chunks)

    # 获取对话回合数
    def get_round(self, group_id: str, member_id: str) -> int:
        conversation = self.get_conversation(group_id, member_id)
        return conversation.get_round()

    async def send_message(
            self, group_id: str, member_id: str, member_name: str,
            message: str, use_tool: bool
    ) -> str | None:
        conv_key = self._get_conversation_key(group_id, member_id)
        conv_lock = self.locks.setdefault(conv_key.lock_key, asyncio.Lock())

        if conv_lock.locked():
            return "错误：正在处理上一条消息，请稍后再试。"

        try:
            if not await conv_lock.acquire():
                return "错误：正在处理上一条消息，请稍后再试。"

            conversation = self.get_conversation(group_id, member_id)
            if conv_key.is_shared:
                group_lock = self.locks.setdefault(f"group:{group_id}", asyncio.Lock())
                if group_lock.locked():
                    return "错误：正在处理群内其他消息，请稍后再试。"
                async with group_lock:
                    return await self.__process_conversation(
                        conversation, member_name, member_id, message,
                        shared=True, use_tool=use_tool
                    )
            else:
                return await self.__process_conversation(
                    conversation, member_name, member_id, message,
                    shared=False, use_tool=use_tool
                )
        finally:
            if conv_lock.locked():
                conv_lock.release()
