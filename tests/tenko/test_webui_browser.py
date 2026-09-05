from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright


def test_webui_navigation_and_form_stability(tmp_path):
    """检查正文滚动、导航工具和刷新周期内的表单状态。"""
    html = Path("tenko/webui/static/index.html").read_text()
    with sync_playwright() as playwright:
        if not Path(playwright.chromium.executable_path).exists():
            pytest.skip("浏览器验证需要 playwright install chromium")
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        errors = []
        requests = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def respond(route):
            path = route.request.url.split("/webui")[-1]
            if not path:
                route.fulfill(content_type="text/html", body=html)
                return
            requests.append(path)
            data = {
                "/api/session": {"role": "admin", "management_configured": True},
                "/api/accounts": {"accounts": []},
                "/api/features": {"plugins": [], "groups": []},
                "/api/manage/settings": {"default_enabled": True, "stored": True},
            }.get(path, {})
            route.fulfill(json={"ok": True, "data": data})

        page.route("https://tenko.test/webui**", respond)
        page.goto("https://tenko.test/webui#/settings")
        select = page.locator('[name="default_enabled"]')
        select.wait_for()
        page.locator("#token").fill("browser-test-admin")
        page.locator("#auth-form button[type=submit]").click()
        page.locator("#connection-dot.ok").wait_for()
        select.select_option("false")
        page.locator("h3").click()
        page.evaluate(
            "window.originalForm = document.querySelector('#runtime-settings')"
        )
        count = len(requests)
        page.wait_for_timeout(11000)
        assert select.input_value() == "false"
        assert page.evaluate(
            "window.originalForm === document.querySelector('#runtime-settings')"
        )
        assert len(requests) == count
        page.locator("#auth-form button[type=submit]").click()
        page.wait_for_function(
            "document.querySelector('[name=default_enabled]')?.value === 'true'"
        )
        assert len(requests) > count

        for item in page.locator(".sidebar-nav .nav-item").all():
            item.hover()
            page.wait_for_timeout(180)
            assert page.locator(".sidebar-nav").evaluate(
                "nav => nav.scrollWidth === nav.clientWidth"
            )

        page.set_viewport_size({"width": 1280, "height": 1200})
        page.evaluate("window.scrollTo(0, 0)")
        footer = page.locator("#page-footer")
        box = footer.bounding_box()
        assert abs(box["y"] + box["height"] - 1200) <= 1
        page.set_viewport_size({"width": 1280, "height": 720})
        page.evaluate("document.querySelector('#page-root').style.minHeight = '2400px'")
        assert footer.bounding_box()["y"] >= page.locator("main").evaluate(
            "main => main.getBoundingClientRect().bottom"
        )
        page.evaluate("window.scrollTo(0, 1200)")
        page.wait_for_timeout(350)
        sidebar = page.locator(".sidebar").bounding_box()
        assert sidebar["y"] == 0
        assert sidebar["height"] == 720
        theme = page.locator('.sidebar [data-theme-choice="dark"]')
        theme.click()
        assert page.locator("html").get_attribute("data-theme") == "dark"
        assert page.evaluate("localStorage.getItem('tenko-webui-theme')") == "dark"
        link = page.locator(".sidebar .github-link")
        assert link.get_attribute("href") == "https://github.com/g1331/tenko"
        assert link.locator("svg").count() == 1
        assert link.bounding_box()["y"] + link.bounding_box()["height"] <= 720
        page.evaluate("document.querySelector('#page-root').style.minHeight = ''")
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=str(tmp_path / "desktop.png"))
        system = page.locator('.sidebar [data-theme-choice="system"]')
        system.click()
        page.emulate_media(color_scheme="light")
        page.wait_for_function("document.documentElement.dataset.theme === 'light'")
        page.emulate_media(color_scheme="dark")
        page.wait_for_function("document.documentElement.dataset.theme === 'dark'")

        page.set_viewport_size({"width": 390, "height": 844})
        page.evaluate("window.scrollTo(0, 0)")
        mobile_theme = page.locator('.mobile-topbar [data-theme-choice="light"]')
        assert mobile_theme.is_visible()
        mobile_theme.click()
        assert theme.get_attribute("aria-pressed") == "false"
        assert page.locator("html").get_attribute("data-theme") == "light"
        assert page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth"
        )
        page.screenshot(path=str(tmp_path / "mobile.png"))
        assert not errors
        browser.close()
