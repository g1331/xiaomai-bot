"""
对话实现类
"""

import asyncio
import json
from collections.abc import AsyncGenerator
from datetime import datetime
from enum import Enum

from loguru import logger

from ..core.plugin import BasePlugin
from ..core.provider import BaseAIProvider, FileContent


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
        """切换提供商，同时保留历史和预设"""
        if self.mode == Conversation.Mode.DEFAULT:
            # 记录旧提供商的token消耗信息，以便在新提供商中保持连续性
            old_usage = self.provider.get_usage()
            self.provider = new_provider
            # 将旧使用情况传递给新提供商，确保历史token统计的连续性
            for key, value in old_usage.items():
                if hasattr(self.provider.usage, key):
                    self.provider.usage[key] = value
            logger.info(
                f"已切换到新提供商: {new_provider.__class__.__name__}, 模型: {new_provider.model_name}"
            )

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
            6: "星期日",
        }
        weekday = weekday_map[current_time.weekday()]
        time_str = current_time.strftime(f"%Y年%m月%d日 {weekday} %H时")
        return {"role": "system", "content": f"现在是北京时间: {time_str}"}

    def get_round(self) -> int:
        # 要排除 system 和 tool 的消息，然后计算 user 和 assistant 的消息数量，然后除以 2
        return (
            len([msg for msg in self.history if msg["role"] in ["user", "assistant"]])
            // 2
        )

    def can_retry(self) -> tuple[bool, str]:
        """检查是否可以重试上一次对话

        Returns:
            Tuple[bool, str]: (是否可以重试, 成功/失败的原因)
        """
        # 检查历史记录中是否有用户消息
        user_messages = [msg for msg in self.history if msg.get("role") == "user"]
        if not user_messages:
            return False, "没有检测到历史对话"

        # 检查最后一次用户消息后是否有AI回复
        last_user_index = -1
        for i in range(len(self.history) - 1, -1, -1):
            if self.history[i].get("role") == "user":
                last_user_index = i
                break

        if last_user_index == -1 or last_user_index == len(self.history) - 1:
            return False, "没有找到需要重试的AI回复"

        # 检查用户消息后是否有AI回复
        has_assistant_reply = False
        for i in range(last_user_index + 1, len(self.history)):
            if self.history[i].get("role") == "assistant":
                has_assistant_reply = True
                break

        if not has_assistant_reply:
            return False, "没有找到需要重试的AI回复"

        return True, "可以重试"

    async def retry_last_message(
        self, files: list[FileContent] = None, use_tool: bool = False
    ) -> str:
        """重试上一次对话，即删除AI的最后一个回复，重新生成

        Args:
            files: 附加文件
            use_tool: 是否启用工具

        Returns:
            str: 重新生成的回复
        """
        try:
            # 查找最后一个用户消息的索引
            last_user_index = -1
            for i in range(len(self.history) - 1, -1, -1):
                if self.history[i].get("role") == "user":
                    last_user_index = i
                    break

            if last_user_index == -1:
                return "错误：没有找到用户的历史消息。"

            # 删除最后一个用户消息之后的所有消息（包括AI回复和工具结果）
            self.history = self.history[: last_user_index + 1]

            # 重置中断标记
            self.interrupted = False

            # 获取最后一次用户输入，便于调试
            last_user_message = self.history[last_user_index].get("content", "")
            logger.info(f"重试用户消息: {last_user_message[:50]}...")

            # 调用处理消息流程重新生成回复
            response_chunks = []
            async for chunk in self.process_message("", files, use_tool=use_tool):
                response_chunks.append(chunk)

            return "".join(response_chunks)
        except Exception as e:
            logger.error(f"重试消息时发生错误: {str(e)}")
            return f"重试消息时发生错误: {str(e)}"

    def _maybe_add_time_message(self):
        """根据小时变化或日期变化决定是否添加时间信息

        在以下情况下会添加时间信息:
        1. 首次对话(_last_time 为 None)
        2. 小时数发生变化(包括日期变化)
        """
        current_hour = datetime.now().strftime("%Y-%m-%d %H")
        if self._last_time is None or current_hour != self._last_time:
            self.history.append(self._get_time_message())
            self._last_time = current_hour

    # 让模型总结历史记录
    async def summarize_history(self) -> str | None:
        max_token = self.provider.model_config.max_total_tokens
        current_tokens = self.provider.get_usage().get("prompt_tokens", 0)
        # 预留0.5k token给总结历史记录
        if current_tokens + 512 <= max_token:
            return None
        logger.info(
            f"历史记录token数超过限制，当前token数: {current_tokens}, 最大token数: {max_token}，开始总结历史记录"
        )
        try:
            response_contents = []
            response_messages = []
            origin_tokens_num = self.provider.calculate_tokens(self.history)
            # 这里仍然添加preset是为了命中缓存
            preset_messages = (
                [{"role": "system", "content": self.preset}] if self.preset else []
            )
            summary_instruction = {
                "role": "system",
                "content": (
                    "请按照以下规则总结历史对话：\n"
                    "1.背景信息：概述对话的起点和核心话题。\n"
                    "2.用户主要问题：列出用户的关键提问。\n"
                    "3.模型主要回答：总结你给出的重要回复。\n"
                    "4.未解决问题（如有）：如果对话中仍有未解答的问题，列出它们。\n"
                    "请按照规则生成结构化总结。"
                ),
            }
            ask_messages = preset_messages + self.history + [summary_instruction]
            async for response in self.provider.ask(messages=ask_messages):
                content = response.content if hasattr(response, "content") else ""
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
            call_key = (tool_call.function.name, tool_call.function.arguments)

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
        self, user_input: str, files: list[FileContent] = None, use_tool: bool = False
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
                logger.warning(
                    f"用户输入过长({len(user_input)}字符)，已截断至{max_input_length}字符"
                )
                user_input = user_input[:max_input_length] + "...(内容已截断)"

            # 构造传入 AI 模型的消息列表
            preset_messages = (
                [{"role": "system", "content": self.preset}] if self.preset else []
            )

            # 仅当有用户输入时才添加到历史记录
            user_input_messages = []
            if user_input:
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
                    if (
                        isinstance(msg["content"], str)
                        and len(msg["content"]) > max_input_length
                    ):
                        msg_copy = msg.copy()
                        msg_copy["content"] = (
                            msg["content"][:max_input_length] + "...(内容已截断)"
                        )
                        sanitized_history.append(msg_copy)
                    else:
                        sanitized_history.append(msg)

            # 使用净化后的历史记录
            ask_messages = preset_messages + sanitized_history + user_input_messages
            tool_response_messages = []

            # 检查API调用的消息是否超过数量限制
            max_messages = 100  # OpenAI API通常有消息数量限制
            if len(ask_messages) > max_messages:
                logger.warning(
                    f"消息数量({len(ask_messages)})超过限制，已截断至最新的{max_messages}条"
                )
                # 保留系统消息和最新的消息
                system_messages = [
                    msg for msg in ask_messages if msg.get("role") == "system"
                ]
                non_system_messages = [
                    msg for msg in ask_messages if msg.get("role") != "system"
                ]
                ask_messages = (
                    system_messages
                    + non_system_messages[-max_messages + len(system_messages) :]
                )

            if use_tool and not self.provider.supports_tools:
                logger.warning("当前模型不支持工具调用，将忽略工具请求")
                use_tool = False

            if use_tool:  # 只有在启用工具且模型支持时才准备工具配置
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
                                "required": list(desc.parameters.keys()),
                            },
                        },
                    }
                    tools.append(tool)
                    plugin_map[desc.name] = plugin

            response_contents = []
            response_messages = []

            try:
                async for response in self.provider.ask(
                    messages=ask_messages,
                    files=files,
                    tools=tools if use_tool else None,
                ):
                    # 检查是否被中断
                    if self.interrupted:
                        logger.info("对话被中断")
                        return

                    if (
                        use_tool
                        and tools
                        and hasattr(response, "tool_calls")
                        and response.tool_calls
                    ):
                        # 对tool_calls进行去重处理
                        tool_calls, skipped_by_id, skipped_by_key = (
                            self._deduplicate_tool_calls(response.tool_calls)
                        )
                        response.tool_calls = tool_calls

                        # 只在有重复时输出日志
                        if skipped_by_id or skipped_by_key:
                            logger.info(
                                f"工具调用去重: 跳过 {skipped_by_id} 个重复ID，{skipped_by_key} 个重复（name, arguments）的调用"
                            )

                        # 工具调用模式
                        tool_response_content = getattr(response, "content", "") or ""
                        tool_response_messages.append(
                            {
                                "role": "assistant",
                                "content": tool_response_content,
                                "tool_calls": response.tool_calls,
                            }
                        )

                        # 日志输出本次要执行的工具调用，以及本身拥有的插件
                        logger.info(
                            f"Tool calls: {';'.join([tc.function.name for tc in response.tool_calls])}"
                        )

                        async def execute_tool_call(tool_call):
                            _plugin = plugin_map.get(tool_call.function.name)
                            if not _plugin:
                                return None
                            try:
                                arguments = json.loads(tool_call.function.arguments)
                            except json.JSONDecodeError:
                                arguments = {"raw": tool_call.function.arguments}
                            try:
                                logger.debug(
                                    f"Plugin {_plugin.description.name} execute with arguments: {arguments}"
                                )
                                result = await _plugin.execute(arguments)
                                logger.debug(
                                    f"Plugin {_plugin.description.name} execute result: {result}"
                                )
                                return {
                                    "role": "tool",
                                    "content": str(result),
                                    "tool_call_id": tool_call.id,
                                }
                            except Exception as e:
                                logger.error(
                                    f"Plugin {_plugin.description.name} execute error: {e}"
                                )
                                return {
                                    "role": "tool",
                                    "content": f"插件 {_plugin.description.name} 执行异常",
                                    "tool_call_id": tool_call.id,
                                }

                        tasks = [
                            execute_tool_call(tc)
                            for tc in response.tool_calls
                            if plugin_map.get(tc.function.name)
                        ]
                        results = await asyncio.gather(*tasks, return_exceptions=False)
                        tool_response_messages.extend(
                            [r for r in results if r is not None]
                        )

                        # 获取最终响应
                        final_ask_messages = ask_messages + tool_response_messages
                        try:
                            async for final_chunk in self.provider.ask(
                                messages=final_ask_messages
                            ):
                                content = (
                                    final_chunk.content
                                    if hasattr(final_chunk, "content")
                                    else ""
                                )
                                if content:
                                    yield content
                                    response_contents.append(content)
                        except Exception as e:
                            error_msg = f"工具调用后获取最终响应失败: {str(e)}"
                            logger.error(error_msg)
                            yield f"抱歉，工具使用过程中出现了问题：{error_msg}"
                    else:  # 普通对话模式
                        content = (
                            response.content if hasattr(response, "content") else ""
                        )
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
                response_messages = [
                    {"role": "assistant", "content": "".join(response_contents)}
                ]

            # 更新历史记录
            if response_contents:
                self.history.extend(user_input_messages)
                if tool_response_messages:
                    self.history.extend(tool_response_messages)
                self.history.extend(response_messages)

        except Exception as e:
            logger.error(f"Error in process_message: {e}")
            yield f"处理消息时发生错误: {str(e)}"

    def check_model_compatibility(self, model_config) -> tuple[bool, str]:
        """
        检查给定的模型配置是否与当前会话历史兼容

        Args:
            model_config: 要检查的模型配置

        Returns:
            tuple: (是否兼容, 不兼容的原因)
        """
        # 检查历史中是否有工具调用
        has_tool_calls = any(
            msg.get("role") == "assistant" and msg.get("tool_calls")
            for msg in self.history
        )
        if has_tool_calls and not model_config.supports_tool_calls:
            return False, "当前会话包含工具调用记录，但目标模型不支持工具调用"

        # 检查历史中是否有多模态内容
        has_vision_content = False
        for msg in self.history:
            content = msg.get("content", "")
            if isinstance(content, list):
                # 检查多模态内容
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "image_url":
                        has_vision_content = True
                        break
            if has_vision_content:
                break

        if has_vision_content and not model_config.supports_vision:
            return False, "当前会话包含图像内容，但目标模型不支持视觉功能"

        return True, ""
