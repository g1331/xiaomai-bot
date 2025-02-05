"""
修改后的对话管理逻辑
"""
import json
from typing import AsyncGenerator
from ..core.provider import BaseAIProvider
from ..core.plugin import BasePlugin, PluginDescription


class Conversation:
    def __init__(self, provider: BaseAIProvider, plugins: list[BasePlugin]):
        self.provider = provider
        self.plugins = plugins
        self.history = []

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
        # 步骤1：生成初始决策
        system_prompt = await self._build_system_prompt()
        self.provider.reset(system_prompt)

        # 步骤2：获取AI的初始决策
        decision_response = ""
        async for chunk in self.provider.ask(user_input):
            decision_response += chunk
            yield chunk  # 流式输出

        # 步骤3：解析工具调用
        try:
            tool_call = json.loads(decision_response.strip().split('\n')[-1])
            if isinstance(tool_call, dict) and "tool" in tool_call:
                # 步骤4：执行插件
                selected_plugin = next(
                    p for p in self.plugins
                    if p.description.name == tool_call["tool"]
                )
                result = await selected_plugin.execute(tool_call["parameters"])

                # 步骤5：生成最终响应
                final_prompt = (
                    f"用户问题：{user_input}\n"
                    f"工具执行结果：{result}\n"
                    "请根据以上信息生成最终回复"
                )
                async for chunk in self.provider.ask(final_prompt):
                    yield chunk
                return
        except (json.JSONDecodeError, StopIteration):
            pass  # 无有效工具调用

        # 直接返回原始响应
        yield decision_response
