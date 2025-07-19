"""
pytest测试文件：Minecraft WebSocket 请求头管理修复验证

测试覆盖范围：
1. 验证文档更新是否正确包含 header 命令
2. 验证 x-self-name 请求头设置逻辑修复
3. 确保用户可以正确覆盖 x-self-name 值

修复问题：
1. metadata.json 中缺少 header 命令文档
2. add_server_header 函数中 x-self-name 设置逻辑问题

运行方式：
- 运行所有测试：uv run pytest tests/test_minecraft_header_fix.py
- 运行详细输出：uv run pytest tests/test_minecraft_header_fix.py -v
"""

import json
import os
import sys
from pathlib import Path

import pytest

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestMinecraftHeaderFix:
    """Minecraft WebSocket 请求头管理修复的pytest测试类"""

    def test_metadata_includes_header_commands(self):
        """测试 metadata.json 是否包含 header 命令文档"""
        metadata_file = Path("modules/self_contained/minicraft_info/metadata.json")
        assert metadata_file.exists(), "metadata.json 文件不存在"

        # 读取 metadata.json
        with open(metadata_file, encoding="utf-8") as f:
            metadata = json.load(f)

        # 检查 usage 部分是否包含 header 命令
        usage = metadata.get("usage", [])
        usage_text = "\n".join(usage)

        assert "WebSocket 请求头管理:" in usage_text, (
            "usage 中缺少 WebSocket 请求头管理说明"
        )
        assert "添加请求头: /mcadmin header add" in usage_text, (
            "usage 中缺少 header add 命令"
        )
        assert "移除请求头: /mcadmin header remove" in usage_text, (
            "usage 中缺少 header remove 命令"
        )
        assert "列出请求头: /mcadmin header list" in usage_text, (
            "usage 中缺少 header list 命令"
        )

        # 检查 example 部分是否包含 header 命令示例
        examples = metadata.get("example", [])
        examples_text = "\n".join(examples)

        assert "/mcadmin header add" in examples_text, "example 中缺少 header add 示例"
        assert "/mcadmin header list" in examples_text, (
            "example 中缺少 header list 示例"
        )
        assert "/mcadmin header remove" in examples_text, (
            "example 中缺少 header remove 示例"
        )

    def test_header_command_examples_format(self):
        """测试 header 命令示例格式是否正确"""
        metadata_file = Path("modules/self_contained/minicraft_info/metadata.json")

        with open(metadata_file, encoding="utf-8") as f:
            metadata = json.load(f)

        examples = metadata.get("example", [])

        # 查找 header 相关的示例
        header_examples = [ex for ex in examples if "/mcadmin header" in ex]

        # 验证示例格式
        assert len(header_examples) >= 3, (
            f"header 示例数量不足，当前有 {len(header_examples)} 个"
        )

        # 检查具体的示例格式
        add_examples = [ex for ex in header_examples if "header add" in ex]
        list_examples = [ex for ex in header_examples if "header list" in ex]
        remove_examples = [ex for ex in header_examples if "header remove" in ex]

        assert len(add_examples) >= 1, "缺少 header add 示例"
        assert len(list_examples) >= 1, "缺少 header list 示例"
        assert len(remove_examples) >= 1, "缺少 header remove 示例"

        # 验证 add 示例包含三个参数：服务器ID、key、value
        for example in add_examples:
            parts = example.split()
            assert len(parts) >= 5, f"header add 示例格式不正确: {example}"
            assert parts[0] == "/mcadmin", f"示例应以 /mcadmin 开头: {example}"
            assert parts[1] == "header", f"示例应包含 header: {example}"
            assert parts[2] == "add", f"示例应包含 add: {example}"

    def test_database_header_logic_structure(self):
        """测试数据库 header 逻辑结构是否正确修复"""
        database_file = Path("modules/self_contained/minicraft_info/database.py")
        assert database_file.exists(), "database.py 文件不存在"

        # 读取文件内容
        content = database_file.read_text(encoding="utf-8")

        # 检查修复后的逻辑：允许用户设置自定义的 x-self-name
        assert 'key != "x-self-name"' in content, "缺少修复后的 x-self-name 设置逻辑"

        # 检查是否移除了强制设置 x-self-name 的逻辑
        lines = content.split("\n")

        # 查找 add_server_header 函数
        in_add_header_function = False
        add_header_lines = []

        for line in lines:
            if "async def add_server_header" in line:
                in_add_header_function = True
            elif (
                in_add_header_function
                and line.strip()
                and not line.startswith(" ")
                and not line.startswith("\t")
            ):
                # 函数结束
                break

            if in_add_header_function:
                add_header_lines.append(line)

        add_header_code = "\n".join(add_header_lines)

        # 验证修复：只有在不是设置 x-self-name 时才自动添加
        assert 'key != "x-self-name"' in add_header_code, "修复逻辑不正确"

        # 验证不会强制覆盖用户设置的 x-self-name
        problematic_patterns = [
            'current_headers["x-self-name"] = server_name',
            'headers["x-self-name"] = server.server_name',
        ]

        # 这些模式应该只在条件语句中出现，不应该无条件执行
        for pattern in problematic_patterns:
            if pattern in add_header_code:
                # 确保它在条件语句中
                pattern_lines = [line for line in add_header_lines if pattern in line]
                for line in pattern_lines:
                    # 检查这行是否在 if 语句中（通过缩进判断）
                    stripped = line.strip()
                    if stripped == pattern:
                        # 这行应该有适当的缩进，表示在条件语句中
                        indent = len(line) - len(line.lstrip())
                        assert indent > 12, (
                            f"发现无条件设置 x-self-name 的代码: {line.strip()}"
                        )

    def test_websocket_header_usage_consistency(self):
        """测试 WebSocket 使用 header 的逻辑一致性"""
        websocket_file = Path("modules/self_contained/minicraft_info/websocket.py")
        assert websocket_file.exists(), "websocket.py 文件不存在"

        content = websocket_file.read_text(encoding="utf-8")

        # 检查 WebSocket 连接时正确使用 headers
        assert "headers = server.websocket_headers or {}" in content, (
            "WebSocket 未正确读取服务器 headers"
        )
        assert "additional_headers=headers" in content, (
            "WebSocket 未正确使用 additional_headers"
        )

        # 检查只有在 x-self-name 不存在时才设置默认值
        assert 'if "x-self-name" not in headers:' in content, (
            "WebSocket 未正确检查 x-self-name 存在性"
        )
        assert 'headers["x-self-name"] = server.server_name' in content, (
            "WebSocket 未正确设置默认 x-self-name"
        )

    def test_header_command_implementation_exists(self):
        """测试 header 命令实现是否存在"""
        init_file = Path("modules/self_contained/minicraft_info/__init__.py")
        assert init_file.exists(), "__init__.py 文件不存在"

        content = init_file.read_text(encoding="utf-8")

        # 检查三个 header 命令的实现
        assert "mcadmin header add" in content, "缺少 header add 命令实现"
        assert "mcadmin header remove" in content, "缺少 header remove 命令实现"
        assert "mcadmin header list" in content, "缺少 header list 命令实现"

        # 检查命令处理函数
        assert "async def handle_header_add" in content or "header_add" in content, (
            "缺少 header add 处理函数"
        )
        assert (
            "async def handle_header_remove" in content or "header_remove" in content
        ), "缺少 header remove 处理函数"
        assert "async def handle_header_list" in content or "header_list" in content, (
            "缺少 header list 处理函数"
        )

    def test_x_self_name_override_scenario(self):
        """测试 x-self-name 覆盖场景的代码逻辑"""
        database_file = Path("modules/self_contained/minicraft_info/database.py")
        content = database_file.read_text(encoding="utf-8")

        # 模拟用户设置 x-self-name 的场景
        # 确保代码允许用户覆盖 x-self-name 值

        # 检查修复后的逻辑：
        # 1. 如果用户设置的是 x-self-name，不应该被自动覆盖
        # 2. 只有在设置其他 key 时才自动添加 x-self-name

        lines = content.split("\n")

        # 查找关键的条件判断
        key_check_lines = [line for line in lines if 'key != "x-self-name"' in line]
        assert len(key_check_lines) >= 2, "缺少足够的 x-self-name 检查逻辑"

        # 确保在设置 x-self-name 时不会被自动覆盖
        for line in key_check_lines:
            # 这些行应该在条件语句中，确保只有在不是设置 x-self-name 时才执行
            assert "if" in line or "elif" in line, (
                f"x-self-name 检查应该在条件语句中: {line.strip()}"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
