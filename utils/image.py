import aiohttp

from graia.ariadne.event.message import Friend, Member


async def get_user_avatar_bytes(user: Friend or Member or int or str, size: int = 640) -> bytes:
    if isinstance(user, Friend or Member):
        user = user.id
    if isinstance(user, str) and not user.isnumeric():
        raise ValueError
    url = f"https://q1.qlogo.cn/g?b=qq&nk={user}&s={size}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            return await resp.read()


async def get_user_avatar_url(user: Friend or Member or int or str, size: int = 640) -> str:
    if isinstance(user, Friend or Member):
        user = user.id
    if isinstance(user, str) and not user.isnumeric():
        raise ValueError
    return f"https://q1.qlogo.cn/g?b=qq&nk={user}&s={size}"
