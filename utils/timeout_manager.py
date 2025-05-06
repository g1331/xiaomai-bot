from loguru import logger


class TimeoutManager:
    """
    动态超时计算管理器
    算法：
    - 基础超时：10秒
    - 每账号增量：3秒
    - 最大超时：30秒
    - 公式：timeout = min(10 + 3*account_count, 30)
    """

    @staticmethod
    def calculate_timeout(account_count: int) -> int:
        """
        计算动态超时时间

        :param account_count: 账号数量
        :return: 计算后的超时时间(秒)
        """
        base_timeout = 10
        increment_per_account = 3
        max_timeout = 30

        timeout = min(base_timeout + increment_per_account * account_count, max_timeout)
        logger.debug(
            f"超时计算完成 | 账号数={account_count} | 基础={base_timeout}s | 增量={increment_per_account}s/账号 | 最大={max_timeout}s | 最终超时={timeout}s"
        )
        return timeout

    @staticmethod
    def get_progress(current: int, total: int) -> float:
        """
        获取初始化进度百分比

        :param current: 当前已初始化数量
        :param total: 总数
        :return: 进度百分比(0-100)
        """
        if total <= 0:
            return 100.0
        progress = (current / total) * 100
        return round(progress, 2)
