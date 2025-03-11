import datetime


class DateTimeUtils:
    @staticmethod
    def add_days(start_date: datetime.datetime, days: int) -> datetime.datetime:
        """
        返回开始日期加上指定天数后的日期。

        Args:
        start_date (datetime.datetime): 开始日期。
        days (int): 要添加的天数。

        Returns:
        datetime.datetime: 开始日期加上指定天数后的日期。

        Raises:
        ValueError: 如果 start_date 不是 datetime.datetime 对象，或者 days 不是整数。
        """
        if not isinstance(start_date, datetime.datetime):
            raise ValueError("start_date must be a datetime.datetime object")
        if not isinstance(days, int):
            raise ValueError("days must be an integer")
        return start_date + datetime.timedelta(days=days)

    @staticmethod
    def diff_days(date1: datetime.datetime, date2: datetime.datetime) -> int:
        """
        返回两个日期之间的天数差。

        Args:
        date1 (datetime.datetime): 第一个日期。
        date2 (datetime.datetime): 第二个日期。

        Returns:
        int: 两个日期之间的天数差，使用date1 - date2。如果 date1 日期较晚（更大），返回值为正数；如果 date1 日期较早（更小），返回值为负数。

        Raises:
        ValueError: 如果 date1 或 date2 不是 datetime.datetime 对象。
        """
        if not isinstance(date1, datetime.datetime) or not isinstance(
            date2, datetime.datetime
        ):
            raise ValueError("Both date1 and date2 must be datetime.datetime objects")

        # 将datetime对象转换为date对象
        date1 = date1.date()
        date2 = date2.date()

        return (date1 - date2).days
