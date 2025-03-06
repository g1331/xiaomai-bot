"""
对话管理逻辑
"""

from ..config import CONFIG_PATH
from .conversation import Conversation
from .conversation_manager import ConversationManager

# 导出所有需要的类，使外部引用方式不变
__all__ = ["Conversation", "ConversationManager", "CONFIG_PATH"]
