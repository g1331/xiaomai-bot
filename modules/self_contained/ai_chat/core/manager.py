"""
对话管理逻辑
"""
import asyncio
import json
import warnings
from enum import Enum
from typing import AsyncGenerator, List, Optional
from datetime import datetime

from loguru import logger

from .preset import preset_dict
from ..config import CONFIG_PATH
from ..core.plugin import BasePlugin
from ..core.provider import BaseAIProvider, FileContent, FileType


class Conversation:
    class Mode(Enum):
        DEFAULT = "default"
        CUSTOM = "custom"

    def __init__(self, provider: BaseAIProvider, plugins: list[BasePlugin]):
        self.provider = provider
        self.plugins = plugins
        self._last_time = None  # 记录上次添加时间信息的时间
        self.history = []
        self.mode = Conversation.Mode.DEFAULT
        self.preset = None  # preset 设定
        self.interrupted = False  # 中断标记
        self._maybe_add_time_message()

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
        time_str = current_time.strftime(f"%Y年%m月%d日 {weekday} %H时")
        return {
            "role": "system",
            "content": f"现在是北京时间: {time_str}"
        }

    def get_round(self) -> int:
        # 要排除 system 和 tool 的消息，然后计算 user 和 assistant 的消息数量，然后除以 2
        return len([msg for msg in self.history if msg["role"] in ["user", "assistant"]]) // 2

    def _maybe_add_time_message(self):
        """根据小时变化或日期变化决定是否添加时间信息
        
        在以下情况下会添加时间信息:
        1. 首次对话(_last_time 为 None)
        2. 小时数发生变化(包括日期变化)
        """
        current_hour = datetime.now().strftime('%Y-%m-%d %H')
        if self._last_time is None or current_hour != self._last_time:
            self.history.append(self._get_time_message())
            self._last_time = current_hour

    def _clean_history_if_needed(self) -> int:
        """
        检查并清理过多的历史记录
        :return: 清理掉的消息数量
        """
        warnings.warn(
            "Conversation._clean_history_if_needed() is deprecated and will be removed in the future.",
            DeprecationWarning,
            stacklevel=2
        )

        cleaned_count = 0
        max_token = self.provider.config.max_total_tokens
        current_tokens = self.provider.get_usage().get("total_tokens", 0)

        if current_tokens <= max_token:
            return cleaned_count

        # 按顺序找出可以删除的消息索引
        to_remove_indices = []
        i = 0
        max_iterations = 5  # 设置最大循环次数
        iteration_count = 0

        while i < len(self.history) and iteration_count < max_iterations:
            # 如果是工具调用，则遍历一直到下一个非工具调用消息
            if (
                    self.history[i]["role"] == "assistant"
                    and self.history[i]["tool_calls"] is not None
                    and i + 1 < len(self.history)
            ):
                # 如果是assistant消息，检查后面是否有相关的tool消息
                next_index = i + 1
                tool_indices = []
                while (
                        next_index < len(self.history) and
                        self.history[next_index]["role"] == "tool"
                ):
                    tool_indices.append(next_index)
                    next_index += 1
                # 添加assistant消息和相关的所有tool消息的索引
                to_remove_indices.extend([i] + tool_indices)
                i = next_index
            elif self.history[i]["role"] in ["user", "assistant"]:
                to_remove_indices.append(i)
                i += 1
            else:
                i += 1

            # 检查清理后是否足够
            if to_remove_indices:
                cleaned_count = len(to_remove_indices)
                # 从后向前删除，避免索引变化
                for idx in sorted(to_remove_indices, reverse=True):
                    self.history.pop(idx)

                current_tokens = self.provider.calculate_tokens(self.history)
                if current_tokens <= max_token:
                    break

            iteration_count += 1  # 增加循环计数器

        if cleaned_count > 0:
            logger.info(f"已清理 {cleaned_count} 条历史消息以控制token使用量")

        if iteration_count >= max_iterations:
            logger.warning("达到最大清理迭代次数，可能存在无法完全清理历史记录的问题。")

        return cleaned_count

    # 让模型总结历史记录
    async def summarize_history(self) -> str | None:
        max_token = self.provider.config.max_total_tokens
        current_tokens = self.provider.get_usage().get("prompt_tokens", 0)
        # 预留0.5k token给总结历史记录
        if current_tokens + 512 <= max_token:
            return None
        logger.info(f"历史记录token数超过限制，当前token数: {current_tokens}, 最大token数: {max_token}，开始总结历史记录")
        try:
            response_contents = []
            response_messages = []
            origin_tokens_num = self.provider.calculate_tokens(self.history)
            # 这里仍然添加preset是为了命中缓存
            preset_messages = [{"role": "system", "content": self.preset}] if self.preset else []
            summary_instruction = {
                "role": "system",
                "content": (
                    "请按照以下规则总结历史对话：\n"
                    "1.背景信息：概述对话的起点和核心话题。\n"
                    "2.用户主要问题：列出用户的关键提问。\n"
                    "3.模型主要回答：总结你给出的重要回复。\n"
                    "4.未解决问题（如有）：如果对话中仍有未解答的问题，列出它们。\n"
                    "请按照规则生成结构化总结。"
                )
            }
            ask_messages = preset_messages + self.history + [summary_instruction]
            async for response in self.provider.ask(messages=ask_messages):
                content = response.content if hasattr(response, 'content') else ''
                if content:
                    response_contents.append(content)
            if response_contents:
                response_messages = [
                    {"role": "assistant", "content": "".join(response_contents)}
                ]
            if response_messages:
                self.history = response_messages
                current_tokens_num = self.provider.calculate_tokens(self.history)
                logger.success(
                    f"历史记录已被总结，原始token数: {origin_tokens_num}, 当前token数: {current_tokens_num}, "
                    f"总结内容: {''.join(response_contents)}"
                )
                self.provider.reset_usage()
                self.provider.set_total_tokens(current_tokens_num)
                return None
            return None
        except Exception as e:
            logger.error(f"Error in summarize_history: {e}")
            return f"Error: {str(e)}"

    @staticmethod
    def _deduplicate_tool_calls(tool_calls) -> tuple[list, int, int]:
        """
        对tool_calls进行去重，防止有些模型重复调用相同的工具和参数
        
        Args:
            tool_calls: 原始工具调用列表
            
        Returns:
            tuple[list, int, int]: (去重后的工具调用列表, 重复ID数量, 重复调用数量)
        """
        tool_call_ids = set()
        unique_tool_calls = []
        seen_calls = set()  # 用于检查name和arguments组合的集合
        
        # 统计重复的数量
        skipped_by_id = 0
        skipped_by_key = 0
        
        for tool_call in tool_calls:
            # 先检查id是否重复
            if tool_call.id in tool_call_ids:
                skipped_by_id += 1
                continue
                
            # 创建用于检查重复的键
            call_key = (
                tool_call.function.name,
                tool_call.function.arguments
            )
            
            # 检查name和arguments组合是否重复
            if call_key in seen_calls:
                skipped_by_key += 1
                continue
                
            # 如果都不重复，则添加到结果中
            tool_call_ids.add(tool_call.id)
            seen_calls.add(call_key)
            unique_tool_calls.append(tool_call)
        
        return unique_tool_calls, skipped_by_id, skipped_by_key

    async def process_message(
            self, 
            user_input: str, 
            files: List[FileContent] = None, 
            use_tool: bool = False
    ) -> AsyncGenerator[str, None]:
        """处理用户消息,包括历史记录管理和工具调用
        
        Args:
            user_input: 用户输入文本
            files: 多模态文件列表
            use_tool: 是否启用工具
        """
        try:
            # 重置中断标记
            self.interrupted = False

            # 1. 准备工具配置
            tools = []
            plugin_map = {}

            # 清理历史记录
            if await self.summarize_history():
                yield "服务器忙不过来了哦，稍后再试吧~"
                return

            # 添加时间信息(如果需要)
            self._maybe_add_time_message()

            # 限制用户输入长度，防止超出API限制
            max_input_length = 32000  # 设置一个合理的最大长度
            if len(user_input) > max_input_length:
                logger.warning(f"用户输入过长({len(user_input)}字符)，已截断至{max_input_length}字符")
                user_input = user_input[:max_input_length] + "...(内容已截断)"
                
            # 构造传入 AI 模型的消息列表
            preset_messages = [{"role": "system", "content": self.preset}] if self.preset else []
            user_input_messages = [{"role": "user", "content": user_input}]
            
            # 检查历史记录中是否有格式不正确的消息
            sanitized_history = []
            for msg in self.history:
                # 确保每条消息都有role和content字段
                if "role" not in msg:
                    logger.warning(f"跳过缺少role字段的历史消息: {msg}")
                    continue
                
                # 处理content字段
                if "content" not in msg:
                    # 如果没有content但有tool_calls，这是合法的
                    if msg.get("role") == "assistant" and "tool_calls" in msg:
                        sanitized_history.append(msg)
                        continue
                    # 否则添加空content字段
                    msg = msg.copy()
                    msg["content"] = ""
                elif isinstance(msg["content"], list):
                    # 检查多模态content列表格式
                    valid_content = []
                    for item in msg["content"]:
                        if isinstance(item, dict) and "type" in item:
                            if item["type"] == "text" and "text" in item:
                                valid_content.append(item)
                            elif item["type"] == "image_url" and "image_url" in item:
                                valid_content.append(item)
                            # 跳过无效格式
                        else:
                            logger.warning(f"跳过格式不正确的content项: {item}")
                    if valid_content:
                        msg_copy = msg.copy()
                        msg_copy["content"] = valid_content
                        sanitized_history.append(msg_copy)
                else:
                    # 确保字符串内容不超过API限制
                    if isinstance(msg["content"], str) and len(msg["content"]) > max_input_length:
                        msg_copy = msg.copy()
                        msg_copy["content"] = msg["content"][:max_input_length] + "...(内容已截断)"
                        sanitized_history.append(msg_copy)
                    else:
                        sanitized_history.append(msg)
                    
            # 使用净化后的历史记录
            ask_messages = preset_messages + sanitized_history + user_input_messages
            tool_response_messages = []

            # 检查API调用的消息是否超过数量限制
            max_messages = 100  # OpenAI API通常有消息数量限制
            if len(ask_messages) > max_messages:
                logger.warning(f"消息数量({len(ask_messages)})超过限制，已截断至最新的{max_messages}条")
                # 保留系统消息和最新的消息
                system_messages = [msg for msg in ask_messages if msg.get("role") == "system"]
                non_system_messages = [msg for msg in ask_messages if msg.get("role") != "system"]
                ask_messages = system_messages + non_system_messages[-max_messages + len(system_messages):]

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

            try:
                async for response in self.provider.ask(
                    messages=ask_messages, 
                    files=files, 
                    tools=tools if use_tool else None
                ):
                    # 检查是否被中断
                    if self.interrupted:
                        logger.info("对话被中断")
                        return

                    if use_tool and tools and hasattr(response, "tool_calls") and response.tool_calls:
                        # 对tool_calls进行去重处理
                        tool_calls, skipped_by_id, skipped_by_key = self._deduplicate_tool_calls(response.tool_calls)
                        response.tool_calls = tool_calls
                        
                        # 只在有重复时输出日志
                        if skipped_by_id or skipped_by_key:
                            logger.info(
                                f"工具调用去重: 跳过 {skipped_by_id} 个重复ID，{skipped_by_key} 个重复（name, arguments）的调用"
                            )
                        
                        # 工具调用模式
                        tool_response_content = getattr(response, "content", "") or ""
                        tool_response_messages.append({
                            "role": "assistant",
                            "content": tool_response_content,
                            "tool_calls": response.tool_calls
                        })

                        # 日志输出本次要执行的工具调用，以及本身拥有的插件
                        logger.info(f"Tool calls: {';'.join([tc.function.name for tc in response.tool_calls])}")

                        # ...existing code for tool execution...
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
                                logger.debug(f"Plugin {_plugin.description.name} execute result: {result}")
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
                        final_ask_messages = ask_messages + tool_response_messages
                        try:
                            async for final_chunk in self.provider.ask(messages=final_ask_messages):
                                content = final_chunk.content if hasattr(final_chunk, 'content') else ''
                                if content:
                                    yield content
                                    response_contents.append(content)
                        except Exception as e:
                            error_msg = f"工具调用后获取最终响应失败: {str(e)}"
                            logger.error(error_msg)
                            yield f"抱歉，工具使用过程中出现了问题：{error_msg}"
                    else:  # 普通对话模式
                        content = response.content if hasattr(response, 'content') else ''
                        if content:
                            yield content
                            response_contents.append(content)
            except Exception as api_error:
                error_msg = f"API调用发生错误: {str(api_error)}"
                logger.error(error_msg)
                yield f"抱歉，与AI通信时发生了错误：{error_msg}"
                return

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
            yield f"处理消息时发生错误: {str(e)}"


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

    def _create_conversation(self, conv_key: ConversationKey, preset: str = "") -> Conversation:
        """创建新的对话实例"""
        provider = self.provider_factory(conv_key.key)
        plugins = self.plugins_factory(conv_key.key)
        conversation = Conversation(provider, plugins)
        preset_content = preset_dict[preset]["content"] if preset in preset_dict \
            else (preset or preset_dict["umaru"]["content"])
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

    def new(self, group_id: str, member_id: str, preset: str = "") -> Conversation:
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

        if conv_key.is_shared and f"group:{group_id}" in self.locks and self.locks[f"group:{group_id}"].locked():
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
            message: str, files: List[FileContent] = None, use_tool: bool = False
    ) -> str:
        response_chunks = []
        async for chunk in conversation.process_message(message, files, use_tool=use_tool):
            response_chunks.append(chunk)
        return "".join(response_chunks)

    # 获取对话回合数
    def get_round(self, group_id: str, member_id: str) -> int:
        conversation = self.get_conversation(group_id, member_id)
        return conversation.get_round()

    async def send_message(
            self, 
            group_id: str, 
            member_id: str, 
            member_name: str,
            message: str, 
            files: List[FileContent] = None,
            use_tool: bool = False
    ) -> str | None:
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
                        conversation, message, files,
                        use_tool=use_tool
                    )
            else:
                return await self.__process_conversation(
                    conversation, message, files,
                    use_tool=use_tool
                )
        finally:
            if conv_lock.locked():
                conv_lock.release()
