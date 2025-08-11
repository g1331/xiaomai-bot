"""
简单的集成测试：验证自动重连的日志输出

这个脚本模拟了自动重连过程中的日志输出，展示用户会看到的消息。
"""

import asyncio
from unittest.mock import patch, AsyncMock
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# 创建一个简单的日志模拟
class MockLogger:
    def info(self, msg):
        print(f"[INFO] {msg}")
    
    def warning(self, msg):
        print(f"[WARNING] {msg}")
    
    def success(self, msg):
        print(f"[SUCCESS] {msg}")
    
    def error(self, msg):
        print(f"[ERROR] {msg}")
    
    def debug(self, msg):
        print(f"[DEBUG] {msg}")

# 模拟关键组件
class MockBlazeSocket:
    def __init__(self, should_fail=False):
        self.authenticated = True
        self.should_fail = should_fail
    
    async def send(self, packet):
        if self.should_fail:
            raise ConnectionError("模拟连接断开")
        return {"test": "response"}
    
    async def close(self):
        pass

class MockBlazeData:
    @staticmethod
    def player_list_handle(response):
        return {12345: {"players": [], "time": 1234567890}}

class MockBF1DA:
    pid = 123456
    remid = "test_remid"
    sid = "test_sid"

class MockBlazeClientManagerInstance:
    clients_by_pid = {}
    
    @staticmethod
    async def remove_client(pid):
        if pid in MockBlazeClientManagerInstance.clients_by_pid:
            del MockBlazeClientManagerInstance.clients_by_pid[pid]

# 模拟的BF1BlazeManager类
class MockBF1BlazeManager:
    call_count = 0
    
    @staticmethod
    async def init_socket(pid, remid, sid):
        MockBF1BlazeManager.call_count += 1
        print(f"[调用] init_socket 第 {MockBF1BlazeManager.call_count} 次")
        
        if MockBF1BlazeManager.call_count == 1:
            # 第一次返回会失败的socket
            return MockBlazeSocket(should_fail=True)
        else:
            # 第二次返回正常的socket
            return MockBlazeSocket(should_fail=False)
    
    @staticmethod
    async def get_player_list(game_ids, origin=False, platoon=False):
        """带自动重连的玩家列表获取方法（简化版）"""
        logger = MockLogger()
        
        # 检查game_ids类型
        if not isinstance(game_ids, list):
            game_ids = [game_ids]
        game_ids = [int(game_id) for game_id in game_ids]
        
        # 定义内部函数来执行实际的查询
        async def _perform_query(retry_attempt=False):
            blaze_socket = await MockBF1BlazeManager.init_socket(
                MockBF1DA.pid, MockBF1DA.remid, MockBF1DA.sid
            )
            if not blaze_socket:
                return "BlazeClient初始化出错!"
            
            packet = {
                "method": "GameManager.getGameDataFromId",
                "type": "Command",
                "data": {
                    "DNAM 1": "csFullGameList",
                    "GLST 40": game_ids,
                },
            }
            
            try:
                response = await blaze_socket.send(packet)
            except Exception as e:
                # 连接异常，可能需要重连
                logger.warning(f"Blaze连接异常: {e}")
                try:
                    await blaze_socket.close()
                except Exception:
                    pass
                if not retry_attempt:
                    logger.info("检测到连接异常，尝试自动重连...")
                    return "需要重连"
                else:
                    return f"连接失败: {e}"
            
            if origin:
                return response
            
            response = MockBlazeData.player_list_handle(response)
            if not isinstance(response, dict):
                if not retry_attempt:
                    logger.info("数据处理失败，可能连接已断开，尝试自动重连...")
                    return "需要重连"
                return response
            
            return response
        
        # 首次尝试查询
        result = await _perform_query(retry_attempt=False)
        
        # 如果需要重连，则清理连接并重试一次
        if result == "需要重连":
            logger.info("正在执行自动重连...")
            # 强制清理现有连接
            pid = int(MockBF1DA.pid)
            if pid in MockBlazeClientManagerInstance.clients_by_pid:
                try:
                    old_socket = MockBlazeClientManagerInstance.clients_by_pid[pid]
                    await old_socket.close()
                except Exception as e:
                    logger.debug(f"清理旧连接时出错: {e}")
                finally:
                    await MockBlazeClientManagerInstance.remove_client(pid)
            
            # 重试查询
            result = await _perform_query(retry_attempt=True)
            if isinstance(result, dict):
                logger.success("自动重连成功!")
            elif isinstance(result, str) and "出错" not in result and "失败" not in result and "超时" not in result:
                logger.warning(f"自动重连后仍有问题: {result}")
        
        # 如果仍然失败，返回错误信息
        if not isinstance(result, dict):
            return result
        
        return result

async def demonstrate_auto_reconnect():
    """演示自动重连过程"""
    print("模拟 Blaze 自动重连演示")
    print("=" * 50)
    print()
    
    # 重置计数器
    MockBF1BlazeManager.call_count = 0
    
    print("🔄 模拟用户调用玩家列表查询...")
    print("场景：第一次连接失败，自动重连成功")
    print()
    
    try:
        result = await MockBF1BlazeManager.get_player_list([12345])
        print()
        print("📊 查询结果:", "成功!" if isinstance(result, dict) else f"失败: {result}")
        print()
        print("✅ 用户体验：无需手动输入 '/blaze relogin'，系统自动处理了连接问题！")
        
    except Exception as e:
        print(f"❌ 演示出错: {e}")

if __name__ == "__main__":
    asyncio.run(demonstrate_auto_reconnect())