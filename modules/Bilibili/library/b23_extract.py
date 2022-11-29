import re
import httpx


async def b23_extract(text: str):
    if "b23.tv" not in text:
        return None
    if not (b23 := re.compile(r"b23.tv[\\/]+(\w+)").search(text)):
        return None
    try:
        url = f"https://b23.tv/{b23[1]}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, follow_redirects=True)
        return str(resp.url)
    except TypeError:
        return None
