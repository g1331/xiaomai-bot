import asyncio
from utils.bf1.account_manager import BF1AccountManager


async def main() -> None:
    manager = BF1AccountManager()
    try:
        # 示例：使用 pid、remid 和 sid 添加账户，并确保登录
        account_client = await manager.add_account(remid="your_remid", sid="your_sid")
        session = await account_client.ensure_session()
        print(f"账户 {account_client.auth.pid} 获取 session: {session}")

        # 示例：调用 Game.reserveSlot 接口
        reserve_result = await account_client.api.game.leave_game(
            game="tunguska",
            gameId=123456,
        )
        print("reserveSlot 返回结果:", reserve_result)
    except Exception as e:
        print("测试异常:", e)


if __name__ == "__main__":
    asyncio.run(main())
