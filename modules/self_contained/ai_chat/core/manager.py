"""
修改后的对话管理逻辑
"""
import json
from typing import AsyncGenerator
from enum import Enum
from ..core.provider import BaseAIProvider
from ..core.plugin import BasePlugin, PluginDescription
import asyncio


class Conversation:
    def __init__(self, provider: BaseAIProvider, plugins: list[BasePlugin]):
        self.provider = provider
        self.plugins = plugins
        self.history = []
        self.mode = "default"  # "default" or "custom"

    def switch_provider(self, new_provider: BaseAIProvider):
        """
        默认模式下，允许切换到新的provider，保留history。
        """
        if self.mode == "default":
            self.provider = new_provider

    def set_custom_mode(self, custom_provider: BaseAIProvider):
        """
        切换到自定义模式，使用用户自己的provider
        """
        self.mode = "custom"
        self.provider = custom_provider

    async def _build_system_prompt(self) -> str:
        """构建包含插件信息的系统提示"""
        base_prompt = "你是一个智能助手，可以使用以下工具：\n"
        plugin_descs = []

        for plugin in self.plugins:
            desc = plugin.description
            plugin_descs.append(
                f"工具名称：{desc.name}\n"
                f"功能描述：{desc.description}\n"
                f"参数说明：{json.dumps(desc.parameters, ensure_ascii=False)}\n"
                f"使用示例：{desc.example}\n"
            )

        tool_prompt = "\n".join(plugin_descs)
        decision_prompt = (
            "\n请根据对话内容决定是否需要使用工具，如果需要，请严格按以下JSON格式响应：\n"
            '{"reason": "使用原因", "tool": "工具名称", "parameters": {参数键值对}}\n'
            "如果不需要使用工具，直接回复普通内容"
        )
        return base_prompt + tool_prompt + decision_prompt

    async def process_message(self, user_input: str) -> AsyncGenerator[str, None]:
        # 先记录用户消息
        self.history.append({"role": "user", "content": user_input})

        # 构建系统提示并重置对话
        system_prompt = await self._build_system_prompt()
        self.provider.reset(system_prompt)

        # 步骤1：获取初始决策响应
        decision_response = ""
        async for chunk in self.provider.ask(user_input, json_mode=True):
            decision_response += chunk
            yield chunk  # 流式输出
        # 记录初始响应
        self.history.append({"role": "assistant", "content": decision_response})

        # 步骤2：尝试解析工具调用
        try:
            tool_call = json.loads(decision_response.strip().split('\n')[-1])
            if isinstance(tool_call, dict) and "tool" in tool_call:
                # 执行插件
                selected_plugin = next(
                    p for p in self.plugins if p.description.name == tool_call["tool"]
                )
                result = await selected_plugin.execute(tool_call["parameters"])
                # 记录工具调用结果
                self.history.append({"role": "tool", "content": result})

                # 步骤3：生成最终响应
                final_prompt = (
                    f"用户问题：{user_input}\n"
                    f"工具执行结果：{result}\n"
                    "请根据以上信息生成最终回复"
                )
                final_response = ""
                async for chunk in self.provider.ask(final_prompt, self.history):
                    final_response += chunk
                    yield chunk
                # 记录最终回复
                self.history.append({"role": "assistant", "content": final_response})
                return
        except (json.JSONDecodeError, StopIteration):
            pass  # 无有效工具调用

        # 直接返回原始响应
        yield decision_response


# 用于管理多个用户对话的会话管理器，配置由配置文件加载与更新存储
class RunMode(Enum):
    GLOBAL = "global"  # 跨群共享，仅按用户标识生成 key
    GROUP = "group"  # 每个群内用户独立会话
    GROUP_SHARED = "group_shared"  # 同一群所有用户共享对话


class ConversationManager:
    CONFIG_FILE = "chat_run_mode_config.json"  # 配置文件路径

    def __init__(self, provider_factory, plugins_factory):
        """
        provider_factory: 根据 key 返回独立的 BaseAIProvider 实例
        plugins_factory: 根据 key 返回相应的插件列表
        """
        self.conversations = {}
        self.provider_factory = provider_factory
        self.plugins_factory = plugins_factory
        # 内存中保存各群的配置（key: group_id, value: RunMode.value）
        self._configs = self._load_configs()
        # 针对 GROUP_SHARED 模式下增加锁
        self.locks = {}
        self._config_dirty = False

    def _load_configs(self) -> dict:
        try:
            with open(self.CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data
        except Exception:
            return {}  # 默认空配置

    async def _delayed_save_configs(self, delay: float = 5.0):
        await asyncio.sleep(delay)
        try:
            with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self._configs, f, ensure_ascii=False, indent=2)
            self._config_dirty = False
        except Exception:
            pass

    def update_run_mode(self, group_id: str, new_mode: RunMode):
        """
        更新指定群的运行模式配置，会延迟写入到配置文件。
        """
        self._configs[group_id] = new_mode.value
        self._config_dirty = True
        asyncio.create_task(self._delayed_save_configs())

    def get_run_mode(self, group_id: str) -> RunMode:
        """
        根据 group_id 获取运行模式，未配置时默认返回 GLOBAL 模式。
        """
        mode_val = self._configs.get(group_id, RunMode.GLOBAL.value)
        return RunMode(mode_val)

    def _get_conv_key(self, group_id: str, member_id: str) -> str:
        # 根据当前群的 run_mode 决定 key 生成逻辑
        mode = self.get_run_mode(group_id)
        if mode == RunMode.GLOBAL:
            return member_id  # 跨群共享
        elif mode == RunMode.GROUP_SHARED:
            return group_id  # 同一群共享
        else:  # RunMode.GROUP：每个群中每个用户独立会话
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

    # 重置会话，创建新对话实例
    def new(self, group_id: str, member_id: str, preset: str = "") -> Conversation:
        key = self._get_conv_key(group_id, member_id)
        if key in self.conversations:
            self.remove_conversation(key)
        provider = self.provider_factory(key)
        plugins = self.plugins_factory(key)
        conversation = Conversation(provider, plugins)
        # 如有 preset，可在此处设定初始上下文
        self.conversations[key] = conversation
        return conversation

    # 发送消息，聚合返回完整响应
    async def send_message(self, group_id: str, member_id: str, member_name: str, message: str) -> str:
        """
        发送消息，并聚合返回完整响应：
        在 GROUP_SHARED 模式下，构造输入格式为 "member_name (member_id) say: message"
        并确保同一群共享 client 不会并发响应
        """
        key = self._get_conv_key(group_id, member_id)
        conversation = self.get_conversation(key)
        formatted_message = f"{member_name} ({member_id}) say: {message}"
        if self.get_run_mode(group_id) == RunMode.GROUP_SHARED:
            lock = self.locks.setdefault(group_id, asyncio.Lock())
            async with lock:
                response_chunks = []
                async for chunk in conversation.process_message(formatted_message):
                    response_chunks.append(chunk)
                return "".join(response_chunks)
        else:
            response_chunks = []
            async for chunk in conversation.process_message(formatted_message):
                response_chunks.append(chunk)
            return "".join(response_chunks)
