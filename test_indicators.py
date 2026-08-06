"""测试交易终端 12 个指标布局和 ADX/MFI/BBI 渲染"""
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1920, 'height': 1080})
    page.goto('http://127.0.0.1:1783', timeout=30000, wait_until='networkidle')
    page.wait_for_timeout(8000)

    # 1. 检查 12 个 ind-line
    lines = page.query_selector_all('.ind-line')
    print(f'Ind-lines: {len(lines)}')
    assert len(lines) == 12, f'Expected 12, got {len(lines)}'

    # 2. 检查布局对齐（前 6 同一行，后 6 同一行）
    tops = set()
    for i in range(12):
        top = lines[i].evaluate('el => el.getBoundingClientRect().top.toFixed(0)')
        tops.add(top)
    print(f'Row positions: {sorted(tops)}')
    assert len(tops) == 2, f'Expected 2 rows, got {len(tops)}'

    # 3. 点击 ADX, MFI, BBI 的 checkbox
    # 第 8 个 = ADX, 第 10 个 = MFI, 第 11 个 = BBI
    for idx in [8, 10, 11]:
        cb = lines[idx].query_selector('[role=checkbox]')
        if cb:
            cb.click()
            print(f'Clicked checkbox {idx}')
            page.wait_for_timeout(500)
        else:
            print(f'Checkbox {idx} not found')

    # 4. 等待图表渲染
    page.wait_for_timeout(3000)

    # 5. 检查 canvas 数量（主图 + 副图）
    canvases = page.query_selector_all('canvas')
    print(f'Canvas elements: {len(canvases)}')
    assert len(canvases) >= 2, f'Expected >=2 canvases, got {len(canvases)}'

    # 6. 检查控制台错误
    errors = []
    def on_error(msg):
        if msg.type == 'error':
            errors.append(msg.text)
    page.on('console', on_error)
    page.wait_for_timeout(2000)
    print(f'Console errors: {len(errors)}')
    for e in errors[:5]:
        print(f'  ERROR: {e[:120]}')

    # 7. 检查 ADX 副图标签可见
    adx_text = page.evaluate('document.body.innerText.includes("ADX")')
    print(f'ADX text visible: {adx_text}')
    assert adx_text, 'ADX label not visible'

    mfi_text = page.evaluate('document.body.innerText.includes("MFI")')
    print(f'MFI text visible: {mfi_text}')

    print('\nALL TESTS PASSED')
    browser.close()