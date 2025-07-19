"""
pytest测试文件：Minecraft 服务器管理模块异步数据库操作修复验证

测试覆盖范围：
1. 验证修复后的代码结构和模式
2. 确保异步上下文管理的正确性
3. 检查函数签名和返回值类型

修复问题：解决 SQLAlchemy 异步错误 "greenlet_spawn has not been called; can't call await_only() here"

运行方式：
- 运行所有测试：uv run pytest tests/test_minecraft_async_fix.py
- 运行详细输出：uv run pytest tests/test_minecraft_async_fix.py -v
"""

import os
import sys
from pathlib import Path

import pytest

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestMinecraftAsyncDatabaseFix:
    """Minecraft 服务器管理模块异步数据库操作修复的pytest测试类"""

    def test_database_file_structure(self):
        """测试数据库文件的结构和修复"""
        database_file = Path("modules/self_contained/minicraft_info/database.py")
        assert database_file.exists(), "数据库文件不存在"

        # 读取文件内容
        content = database_file.read_text(encoding="utf-8")

        # 检查修复后的模式：在 async with 上下文内获取属性
        assert "server_name = server.server_name" in content, (
            "缺少修复后的服务器名称获取模式"
        )

        # 检查是否有正确的异步上下文管理
        assert "async with orm.async_session() as session:" in content, (
            "缺少异步上下文管理器"
        )

    def test_bind_function_code_pattern(self):
        """测试 bind_server_to_group 函数的代码模式"""
        database_file = Path("modules/self_contained/minicraft_info/database.py")
        content = database_file.read_text(encoding="utf-8")

        # 查找 bind_server_to_group 函数
        lines = content.split("\n")
        in_bind_function = False
        bind_function_lines = []

        for line in lines:
            if "async def bind_server_to_group" in line:
                in_bind_function = True
            elif (
                in_bind_function
                and line.strip()
                and not line.startswith(" ")
                and not line.startswith("\t")
            ):
                # 函数结束
                break

            if in_bind_function:
                bind_function_lines.append(line)

        bind_function_code = "\n".join(bind_function_lines)

        # 检查修复：server_name 在 async with 上下文内获取
        assert "server_name = server.server_name" in bind_function_code

        # 检查 return 语句使用的是局部变量而不是对象属性
        assert (
            'return True, f"成功将服务器 {server_name} 绑定到群' in bind_function_code
        )

    def test_unbind_function_code_pattern(self):
        """测试 unbind_server_from_group 函数的代码模式"""
        database_file = Path("modules/self_contained/minicraft_info/database.py")
        content = database_file.read_text(encoding="utf-8")

        # 查找 unbind_server_from_group 函数
        lines = content.split("\n")
        in_unbind_function = False
        unbind_function_lines = []

        for line in lines:
            if "async def unbind_server_from_group" in line:
                in_unbind_function = True
            elif (
                in_unbind_function
                and line.strip()
                and not line.startswith(" ")
                and not line.startswith("\t")
            ):
                # 函数结束
                break

            if in_unbind_function:
                unbind_function_lines.append(line)

        unbind_function_code = "\n".join(unbind_function_lines)

        # 检查修复：return 语句在 async with 上下文内
        assert (
            'return True, f"成功从群 {group_id} 解绑服务器 {server_name}"'
            in unbind_function_code
        )

        # 检查 server_name 在上下文内获取
        assert "server_name = server.server_name if server else" in unbind_function_code

    def test_get_headers_function_code_pattern(self):
        """测试 get_server_headers 函数的代码模式"""
        database_file = Path("modules/self_contained/minicraft_info/database.py")
        content = database_file.read_text(encoding="utf-8")

        # 查找 get_server_headers 函数
        lines = content.split("\n")
        in_headers_function = False
        headers_function_lines = []

        for line in lines:
            if "async def get_server_headers" in line:
                in_headers_function = True
            elif (
                in_headers_function
                and line.strip()
                and not line.startswith(" ")
                and not line.startswith("\t")
            ):
                # 函数结束
                break

            if in_headers_function:
                headers_function_lines.append(line)

        headers_function_code = "\n".join(headers_function_lines)

        # 检查修复：server_name 在 async with 上下文内获取
        assert "server_name = server.server_name" in headers_function_code

        # 检查 return 语句使用局部变量
        assert (
            'return True, f"服务器 {server_name} 的请求头", headers'
            in headers_function_code
        )

    def test_no_attribute_access_outside_context(self):
        """测试确保没有在 async with 上下文外访问 ORM 对象属性"""
        database_file = Path("modules/self_contained/minicraft_info/database.py")
        content = database_file.read_text(encoding="utf-8")

        # 检查是否还有在 return 语句中直接访问 server.server_name 的情况
        # 这种模式会导致 SQLAlchemy 异步错误
        problematic_patterns = [
            'return True, f"成功将服务器 {server.server_name}',
            'return True, f"成功从群 {group_id} 解绑服务器 {server.server_name}',
            'return True, f"服务器 {server.server_name} 的请求头',
        ]

        for pattern in problematic_patterns:
            assert pattern not in content, f"发现有问题的模式: {pattern}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
