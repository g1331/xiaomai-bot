from loguru import logger

from utils.browser import get_browser


async def get_dynamic_screenshot(_id):
    url = f"https://t.bilibili.com/{_id}"
    browser = await get_browser()
    page = None
    try:
        page = await browser.new_page()
        for _ in range(3):
            try:
                await page.goto(url, wait_until="networkidle", timeout=10000)
                break
            except Exception as e:
                logger.error(e)
        else:
            return None

        await page.set_viewport_size({"width": 2560, "height": 1080})
        card = await page.query_selector(".card")
        assert card
        clip = await card.bounding_box()
        assert clip
        bar = await page.query_selector(".bili-dyn-action__icon")
        assert bar
        bar_bound = await bar.bounding_box()
        assert bar_bound
        clip["height"] = bar_bound["y"] - clip["y"]
        image = await page.screenshot(
            clip=clip, full_page=True, type="jpeg", quality=85
        )
        await page.close()
        return image
    except Exception:
        if page:
            await page.close()
        raise
