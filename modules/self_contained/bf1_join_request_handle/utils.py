import aiohttp
import httpx
from creart import create

from core.config import GlobalConfig

global_config = create(GlobalConfig)
default_account = global_config.functions.get("bf1").get("default_account", 0)


async def tyc_bfeac_api(player_name):
    check_eacInfo_url = f"https://api.bfeac.com/case/EAID/{player_name}"
    header = {
        "Connection": "keep-alive"
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(check_eacInfo_url, headers=header, timeout=10)
    return response


async def get_stat_by_name(player_name: str) -> dict:
    url = f"https://api.gametools.network/bf1/stats/?format_values=true&name={player_name}&platform=pc"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            return await response.json()
