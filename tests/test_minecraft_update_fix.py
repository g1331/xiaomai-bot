"""
pytest测试文件：Minecraft 服务器管理模块参数解析修复验证

测试覆盖范围：
1. parse_match_type 函数处理 MessageChain 对象的各种场景
2. 数据库参数绑定类型安全性验证
3. 用户实际使用的命令格式兼容性测试

修复问题：解决 /mcadmin update 命令中 MessageChain 对象被错误传递给数据库导致的
"type 'MessageChain' is not supported" 和 "'MessageChain' object has no attribute 'decode'" 错误

运行方式：
- 运行所有测试：uv run pytest tests/test_minecraft_update_fix.py
- 运行详细输出：uv run pytest tests/test_minecraft_update_fix.py -v
"""

import os
import sys
from unittest.mock import Mock

import pytest

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Plain
from graia.ariadne.message.parser.twilight import ArgResult

from utils.type import parse_match_type


class TestMinecraftParameterParsing:
    """Minecraft 服务器管理模块参数解析修复的pytest测试类"""

    def test_parse_match_type_with_message_chain(self):
        """测试 parse_match_type 能正确处理 MessageChain 对象"""
        # 模拟 ArgResult 对象，其中 result 是 MessageChain
        mock_arg_result = Mock(spec=ArgResult)
        mock_arg_result.matched = True
        mock_arg_result.result = MessageChain([Plain(text="13的香草纪元")])

        # 使用 parse_match_type 解析
        result = parse_match_type(mock_arg_result, str, None)

        # 验证结果是纯字符串
        assert result == "13的香草纪元"
        assert isinstance(result, str)

    def test_parse_match_type_with_string(self):
        """测试 parse_match_type 能正确处理字符串对象"""
        # 模拟 ArgResult 对象，其中 result 是字符串
        mock_arg_result = Mock(spec=ArgResult)
        mock_arg_result.matched = True
        mock_arg_result.result = "测试服务器"

        # 使用 parse_match_type 解析
        result = parse_match_type(mock_arg_result, str, None)

        # 验证结果是纯字符串
        assert result == "测试服务器"
        assert isinstance(result, str)

    def test_parse_match_type_not_matched(self):
        """测试 parse_match_type 在参数未匹配时返回默认值"""
        # 模拟 ArgResult 对象，未匹配
        mock_arg_result = Mock(spec=ArgResult)
        mock_arg_result.matched = False

        # 使用 parse_match_type 解析
        result = parse_match_type(mock_arg_result, str, None)

        # 验证返回默认值
        assert result is None

    def test_parse_match_type_with_complex_message_chain(self):
        """测试 parse_match_type 能正确处理复杂的 MessageChain 对象"""
        # 模拟包含多个元素的 MessageChain
        mock_arg_result = Mock(spec=ArgResult)
        mock_arg_result.matched = True
        mock_arg_result.result = MessageChain(
            [Plain(text="服务器名称: "), Plain(text="我的世界服务器")]
        )

        # 使用 parse_match_type 解析
        result = parse_match_type(mock_arg_result, str, None)

        # 验证结果是合并后的纯字符串
        assert result == "服务器名称: 我的世界服务器"
        assert isinstance(result, str)

    def test_database_parameter_binding_simulation(self):
        """模拟数据库参数绑定场景，确保不会出现 MessageChain 类型错误"""
        # 模拟从命令解析得到的参数
        name_arg = Mock(spec=ArgResult)
        name_arg.matched = True
        name_arg.result = MessageChain([Plain(text="13的香草纪元")])

        address_arg = Mock(spec=ArgResult)
        address_arg.matched = True
        address_arg.result = MessageChain([Plain(text="mc.example.com:25565")])

        websocket_arg = Mock(spec=ArgResult)
        websocket_arg.matched = False

        # 使用修复后的解析方式
        new_name = parse_match_type(name_arg, str, None)
        new_address = parse_match_type(address_arg, str, None)
        new_websocket_url = parse_match_type(websocket_arg, str, None)

        # 验证所有参数都是正确的类型
        assert isinstance(new_name, str)
        assert new_name == "13的香草纪元"

        assert isinstance(new_address, str)
        assert new_address == "mc.example.com:25565"

        assert new_websocket_url is None

        # 模拟数据库操作 - 这些参数现在可以安全地传递给数据库
        # 不会出现 "type 'MessageChain' is not supported" 错误
        db_params = [new_name, new_address, new_websocket_url]
        for param in db_params:
            if param is not None:
                assert isinstance(param, str), f"参数 {param} 不是字符串类型"

    def test_websocket_url_with_equals_sign(self):
        """测试带等号的 WebSocket URL 参数解析（模拟用户实际使用的命令）"""
        # 模拟用户使用 --websocket=ws://example.com:8080 的情况
        websocket_arg = Mock(spec=ArgResult)
        websocket_arg.matched = True
        websocket_arg.result = MessageChain([Plain(text="ws://example.com:8080")])

        # 使用修复后的解析方式
        new_websocket_url = parse_match_type(websocket_arg, str, None)

        # 验证结果是正确的字符串
        assert isinstance(new_websocket_url, str)
        assert new_websocket_url == "ws://example.com:8080"

        # 验证 URL 格式正确（可以被 urlparse 解析）
        from urllib.parse import urlparse

        parsed = urlparse(new_websocket_url)
        assert parsed.scheme == "ws"
        assert parsed.hostname == "example.com"
        assert parsed.port == 8080


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
