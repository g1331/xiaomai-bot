import httpx

from loguru import logger


head = {
    "user-agent": (
        "Mozilla/5.0 (Windows NT 6.1) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/41.0.2228.0 "
        "Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
}


async def get_status_info_by_uids(uids):
    for _ in range(3):
        for retry in range(3):
            try:
                async with httpx.AsyncClient(headers=head) as client:
                    r = await client.post(
                        "https://api.live.bilibili.com/room/v1/Room/get_status_info_by_uids",
                        json=uids,
                    )
            except httpx.HTTPError as e:
                logger.error(f"[BiliBili推送] API 访问失败，正在第 {retry + 1} 重试 {str(type(e))}")
            else:
                if r.status_code != 412:
                    return r.json()
                logger.error("[BiliBili推送] IP 已被封禁，本轮更新终止，请尝试使用代理")
                return
        logger.error("[BiliBili推送] API 访问连续失败，请检查")
