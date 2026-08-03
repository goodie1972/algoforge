"""完整 i18n + 主题切换回归测试"""
from playwright.sync_api import sync_playwright
import sys

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN"
        )
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)[:200]))

        # Step 1: Load page
        page.goto("http://127.0.0.1:1783", timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(5000)
        print(f"PASS: 页面加载成功, errors={len(errors)}")

        # Step 2: Check sidebar has English/中文 toggle
        btns = page.evaluate("Array.from(document.querySelectorAll('button')).map(b => b.innerText)")
        btn_text = " ".join(btns)
        has_lang = "English" in btn_text or "中文" in btn_text
        has_theme = "亮色" in btn_text or "Dark" in btn_text or "浅色" in btn_text
        print(f"语言切换按钮: {'PASS' if has_lang else 'FAIL'}, 主题切换: {'PASS' if has_theme else 'FAIL'}")
        if not has_lang:
            print(f"  Available buttons: {btns[:15]}")
            sys.exit(1)

        # Step 3: Click language toggle to switch to English
        for btn_txt in ["English", "中文"]:
            for b in btns:
                if b.strip() == btn_txt:
                    btn = page.locator(f"button:has-text('{btn_txt}')").first
                    btn.click()
                    page.wait_for_timeout(1000)
                    print(f"PASS: 点击语言切换 '{btn_txt}'")
                    break

        # Step 4: Check English text appears
        page.wait_for_timeout(2000)
        body_text = page.evaluate("document.body.innerText")
        eng_checks = ["Account Info", "Positions", "Strategies", "XAUUSD", "Dashboard"]
        for key in eng_checks:
            if key in body_text:
                print(f"PASS: 英文 '{key}' 可见")
            else:
                print(f"FAIL: 英文 '{key}' 不可见")

        # Step 5: Switch back to Chinese
        for b in page.evaluate("Array.from(document.querySelectorAll('button')).map(b => b.innerText)"):
            if b.strip() == "中文":
                page.locator("button:has-text('中文')").first.click()
                page.wait_for_timeout(1000)
                print("PASS: 切回中文")
                break

        page.wait_for_timeout(2000)
        body_cn = page.evaluate("document.body.innerText")
        cn_checks = ["账户信息", "持仓", "策略", "仪表盘"]
        for key in cn_checks:
            if key in body_cn:
                print(f"PASS: 中文 '{key}' 可见")
            else:
                print(f"FAIL: 中文 '{key}' 不可见")

        # Step 6: Theme toggle
        for b in page.evaluate("Array.from(document.querySelectorAll('button')).map(b => b.innerText)"):
            if b.strip() in ["亮色", "Light", "浅色"]:
                page.locator(f"button:has-text('{b.strip()}')").first.click()
                page.wait_for_timeout(1000)
                print(f"PASS: 点击主题切换 '{b.strip()}'")
                break

        # Step 7: Navigate to all pages (createWebHistory, no hash)
        for path, name in [
            ("/", "仪表盘"),
            ("/positions", "持仓"),
            ("/strategies", "策略"),
            ("/logs", "日志"),
            ("/config", "配置"),
            ("/trade-history", "历史成交"),
            ("/patrol", "监控"),
            ("/nonexistent-page", "404"),
        ]:
            page.goto(f"http://127.0.0.1:1783{path}", timeout=15000, wait_until="networkidle")
            page.wait_for_timeout(3000)
            print(f"PASS: 页面 '{name}' 加载成功, errors={len(errors)}")

        # Step 8: Summary
        print(f"\n=== 测试完成: {len(errors)} 个页面错误 ===")
        for e in errors[:5]:
            print(f"  ERROR: {e}")

        browser.close()
        return 0 if len(errors) == 0 else 1

if __name__ == "__main__":
    sys.exit(main())