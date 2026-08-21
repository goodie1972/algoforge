const { chromium } = require('playwright');
const fs = require('fs');
const { PNG } = require('pngjs');

(async () => {
  const browser = await chromium.launch({
    executablePath: 'C:/Users/Administrator/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe',
    headless: true,
  });
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
  const errors = [];
  page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

  await page.goto('http://127.0.0.1:1783', { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(5000);

  const canvas = page.locator('canvas').first();
  const box = await canvas.boundingBox();
  if (!box) { console.log('❌ 未找到图表'); await browser.close(); return; }
  const cx = Math.round(box.x), cy = Math.round(box.y), cw = Math.round(box.width), ch = Math.round(box.height);
  console.log('▶ K线图区域:', cx, cy, cw, ch);

  // 拖拽图表向左（查看历史数据）
  const my = cy + ch * 0.5;
  await page.mouse.move(cx + cw * 0.8, my);
  await page.mouse.down();
  for (let i = 0; i < 20; i++) {
    await page.mouse.move(cx + cw * 0.8 - i * 40, my);
    await page.waitForTimeout(30);
  }
  await page.mouse.up();
  await page.waitForTimeout(1500);
  console.log('▶ 已滚动到历史，截图 A');
  const bufA = await page.screenshot({ clip: { x: cx, y: cy, width: cw, height: ch } });

  // 等待 12 秒（超过旧的 10 秒自动回滚定时器）
  console.log('▶ 等待 12 秒...');
  await page.waitForTimeout(12000);
  console.log('▶ 截图 B');
  const bufB = await page.screenshot({ clip: { x: cx, y: cy, width: cw, height: ch } });

  // 计算图表区域像素差异
  const pngA = PNG.sync.read(bufA);
  const pngB = PNG.sync.read(bufB);
  let diff = 0, total = 0;
  for (let i = 0; i < pngA.data.length; i += 4) {
    total++;
    const d = Math.abs(pngA.data[i] - pngB.data[i]) +
              Math.abs(pngA.data[i+1] - pngB.data[i+1]) +
              Math.abs(pngA.data[i+2] - pngB.data[i+2]);
    if (d > 30) diff++;
  }
  const diffPct = (diff / total * 100).toFixed(2);
  console.log('▶ 图表区域像素差异: ' + diffPct + '%');
  console.log(diffPct < 5 ? '✅ 无漂移：12秒后图表位置未变，成功停在历史区域' : '⚠️ 视图有较大变化（可能被拉回最新或价格大动）');

  console.log('▶ 控制台错误数:', errors.length);
  errors.forEach(e => console.log('   ERROR:', e.slice(0, 150)));

  await browser.close();
})().catch(e => { console.error('失败:', e); process.exit(1); });