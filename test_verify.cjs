const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: 'C:/Users/Administrator/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe' });
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  await page.goto('http://127.0.0.1:1783', { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(6000);

  // 打开 MFI
  await page.locator('.n-checkbox', { hasText: 'MFI' }).first().click();
  await page.waitForTimeout(3000);

  // 找到 RSI/MFI pane div（通过紧邻的 label 文本定位）
  const panes = await page.evaluate(() => {
    const out = [];
    document.querySelectorAll('div').forEach(d => {
      const s = d.style || {};
      if (s.height === '110px' && s.position === 'relative' && d.querySelector('canvas')) {
        const label = (d.previousElementSibling?.textContent || d.parentElement?.textContent || '').trim().slice(0, 30);
        out.push({ idx: out.length, label: label.replace(/\s+/g, ' '), canvasW: d.querySelector('canvas').width });
      }
    });
    return out;
  });
  console.log(JSON.stringify(panes));

  // 通过 canvas 宽度找 MFI pane：像素分析方法——直接对每个 pane 截图并重命名
  const all = page.locator('div[style*="height: 110px"]').filter({ has: page.locator('canvas') });
  const count = await all.count();
  const names = ['RSI', 'STOCH', 'MACD', 'ATR', 'VOL', 'ADX', 'DI', 'MFI', 'BBI'];
  let saved = 0;
  for (let i = 0; i < count; i++) {
    const el = all.nth(i);
    const label = (await el.textContent() || '').trim().slice(0, 30).replace(/\s+/g, ' ');
    const t = await el.locator('canvas').first().screenshot({ path: `pane_canvas_${i}.png` }).catch(e => null);
    if (t) { console.log(`pane ${i}: canvas 保存, 文本="${label}"`); saved++; }
  }
  console.log('保存 pane 数:', saved);
  await browser.close();
})();