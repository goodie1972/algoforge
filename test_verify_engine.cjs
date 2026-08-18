const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({
    executablePath: 'C:/Users/Administrator/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe',
    headless: true,
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

  await page.goto('http://127.0.0.1:1783', { waitUntil: 'networkidle', timeout: 60000 });
  await page.waitForTimeout(4000);

  // 引擎状态区域
  const bodyText = await page.evaluate(() => document.body.innerText);
  const hasRunning = /运行中|running|已启动/i.test(bodyText);
  console.log('[`] 页面含引擎运行状态:', hasRunning);

  // 调 API 拿持仓
  const pos = await page.evaluate(async () => {
    const r = await fetch('/api/positions');
    return r.json();
  });
  console.log('[`] API positions 条数:', Array.isArray(pos) ? pos.length : 'N/A');
  if (Array.isArray(pos) && pos.length > 0) {
    const p = pos[0];
    console.log('[`] 持仓: ticket=' + p.ticket, 'type=' + p.order_type, 'magic=' + p.magic, 'strategy=' + p.strategy);
  }

  await page.screenshot({ path: 'test_screenshot_engine_running.png', fullPage: false });
  console.log('[`] JS errors:', errors.length ? errors.slice(0, 5) : '无');
  await browser.close();
})();