import httpx

from bilireq.utils import post

hc = httpx.AsyncClient()


async def get_b23_url(burl: str) -> str:
    """
    b23 链接转换

    Args:
        burl: 需要转换的 BiliBili 链接
    """
    url = "https://api.bilibili.com/x/share/click"
    data = {
        "build": 6700300,
        "buvid": 0,
        "oid": burl,
        "platform": "android",
        "share_channel": "COPY",
        "share_id": "public.webview.0.0.pv",
        "share_mode": 3,
    }
    return (await post(url, data=data))["content"]
