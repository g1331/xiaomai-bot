"""
测试 Blaze 自动重连功能

这个测试验证当 Blaze 连接断开时，get_player_list 方法能够自动重连。

运行方法：
- 运行测试：python -m pytest tests/test_blaze_auto_reconnect.py -v
- 或者：python tests/test_blaze_auto_reconnect.py
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
import sys
import os

# 添加项目根目录到 sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

try:
    from utils.bf1.bf_utils import BF1BlazeManager
    from utils.bf1.blaze.BlazeClient import BlazeClientManagerInstance
    from utils.bf1.default_account import BF1DA
except ImportError as e:
    print(f"导入模块失败，可能是因为依赖缺失: {e}")
    print("这个测试需要在完整的项目环境中运行")
    sys.exit(1)


class TestBlazeAutoReconnect(unittest.TestCase):
    """测试 Blaze 自动重连功能"""

    def setUp(self):
        """测试前的设置"""
        self.game_ids = [12345]  # 测试用的游戏ID

    @patch('utils.bf1.bf_utils.BF1DA')
    @patch('utils.bf1.bf_utils.BlazeClientManagerInstance')
    @patch('utils.bf1.bf_utils.BlazeData')
    async def test_auto_reconnect_on_connection_error(self, mock_blaze_data, mock_client_manager, mock_bf1da):
        """测试连接错误时的自动重连"""
        
        # 模拟 BF1DA
        mock_bf1da.pid = 123456
        mock_bf1da.remid = "test_remid"
        mock_bf1da.sid = "test_sid"
        
        # 创建模拟的 socket
        mock_socket = AsyncMock()
        mock_socket.authenticated = True
        mock_socket.close = AsyncMock()
        
        # 模拟第一次连接失败，第二次成功
        mock_client_manager.clients_by_pid = {}
        mock_client_manager.remove_client = AsyncMock()
        
        # 模拟 init_socket 方法
        call_count = 0
        async def mock_init_socket(pid, remid, sid):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # 第一次返回None，模拟连接失败
                return None
            else:
                # 第二次返回正常的socket
                return mock_socket
        
        # 模拟 BlazeData.player_list_handle
        mock_response = {12345: {"players": [], "time": 1234567890}}
        mock_blaze_data.player_list_handle.return_value = mock_response
        
        with patch.object(BF1BlazeManager, 'init_socket', side_effect=mock_init_socket):
            # 调用 get_player_list
            result = await BF1BlazeManager.get_player_list(self.game_ids)
            
            # 验证结果
            # 第一次失败应该会触发重试，第二次成功
            self.assertEqual(call_count, 2, "应该调用了两次 init_socket")
            self.assertIsInstance(result, dict, "最终应该返回成功的结果")

    @patch('utils.bf1.bf_utils.BF1DA')
    @patch('utils.bf1.bf_utils.BlazeClientManagerInstance')
    @patch('utils.bf1.bf_utils.BlazeData')
    async def test_auto_reconnect_on_send_exception(self, mock_blaze_data, mock_client_manager, mock_bf1da):
        """测试发送异常时的自动重连"""
        
        # 模拟 BF1DA
        mock_bf1da.pid = 123456
        mock_bf1da.remid = "test_remid"
        mock_bf1da.sid = "test_sid"
        
        # 创建模拟的 socket
        mock_socket_fail = AsyncMock()
        mock_socket_fail.authenticated = True
        mock_socket_fail.close = AsyncMock()
        mock_socket_fail.send = AsyncMock(side_effect=ConnectionError("Connection lost"))
        
        mock_socket_success = AsyncMock()
        mock_socket_success.authenticated = True
        mock_socket_success.send = AsyncMock(return_value={"test": "response"})
        
        # 模拟客户端管理器
        mock_client_manager.clients_by_pid = {123456: mock_socket_fail}
        mock_client_manager.remove_client = AsyncMock()
        
        # 模拟 init_socket 方法
        call_count = 0
        async def mock_init_socket(pid, remid, sid):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_socket_fail
            else:
                return mock_socket_success
        
        # 模拟 BlazeData.player_list_handle
        mock_response = {12345: {"players": [], "time": 1234567890}}
        mock_blaze_data.player_list_handle.return_value = mock_response
        
        with patch.object(BF1BlazeManager, 'init_socket', side_effect=mock_init_socket):
            # 调用 get_player_list
            result = await BF1BlazeManager.get_player_list(self.game_ids)
            
            # 验证结果
            self.assertEqual(call_count, 2, "应该调用了两次 init_socket")
            self.assertIsInstance(result, dict, "最终应该返回成功的结果")
            # 验证旧连接被清理
            mock_client_manager.remove_client.assert_called_once_with(123456)

    @patch('utils.bf1.bf_utils.BF1DA')
    @patch('utils.bf1.bf_utils.BlazeClientManagerInstance')
    async def test_no_retry_on_timeout(self, mock_client_manager, mock_bf1da):
        """测试超时错误不会触发重试"""
        
        # 模拟 BF1DA
        mock_bf1da.pid = 123456
        mock_bf1da.remid = "test_remid"
        mock_bf1da.sid = "test_sid"
        
        # 创建模拟的 socket
        mock_socket = AsyncMock()
        mock_socket.authenticated = True
        mock_socket.close = AsyncMock()
        mock_socket.send = AsyncMock(side_effect=TimeoutError("Timeout"))
        
        # 模拟客户端管理器
        mock_client_manager.clients_by_pid = {}
        
        call_count = 0
        async def mock_init_socket(pid, remid, sid):
            nonlocal call_count
            call_count += 1
            return mock_socket
        
        with patch.object(BF1BlazeManager, 'init_socket', side_effect=mock_init_socket):
            # 调用 get_player_list
            result = await BF1BlazeManager.get_player_list(self.game_ids)
            
            # 验证结果
            self.assertEqual(call_count, 1, "超时错误不应该触发重试")
            self.assertEqual(result, "Blaze后端超时!", "应该返回超时错误信息")


async def run_async_tests():
    """运行异步测试"""
    test_instance = TestBlazeAutoReconnect()
    test_instance.setUp()
    
    try:
        print("测试: 连接错误时的自动重连...")
        await test_instance.test_auto_reconnect_on_connection_error()
        print("✓ 连接错误自动重连测试通过")
        
        print("测试: 发送异常时的自动重连...")
        await test_instance.test_auto_reconnect_on_send_exception()
        print("✓ 发送异常自动重连测试通过")
        
        print("测试: 超时不触发重试...")
        await test_instance.test_no_retry_on_timeout()
        print("✓ 超时不重试测试通过")
        
        print("\n所有测试通过! ✓")
        
    except Exception as e:
        print(f"\n测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True


if __name__ == "__main__":
    print("Blaze 自动重连功能测试")
    print("=" * 40)
    
    success = asyncio.run(run_async_tests())
    if not success:
        sys.exit(1)