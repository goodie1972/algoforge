const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({
    executablePath: 'C:/Users/Administrator/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe',
    headless: true,
  });
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
  const errors = [];
  const beforeRequests = [];
  page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
  page.on('request', req => {
    if (req.url().includes('/api/market/candles') && req.url().includes('before=')) {
      beforeRequests.push(req.url());
    }
  });

  await page.goto('http://127.0.0.1:1783', { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(6000);

  const canvas = page.locator('canvas').first();
  const box = await canvas.boundingBox();
  if (!box) { console.log('❌ 未找到图表'); await browser.close(); return; }
  const cx = Math.round(box.x), cy = Math.round(box.y), cw = Math.round(box.width), ch = Math.round(box.height);
  console.log('▶ K线图区域:', cx, cy, cw, ch);

  // 反复拖拽：向右拖 = 查看更早的历史（content follows mouse）
  const my = cy + ch * 0.5;
  let laps = 0;
  for (let round = 0; round < 6; round++) {
    // 从左侧向右拖
    await page.mouse.move(cx + cw * 0.05, my);
    await page.mouse.down();
    for (let i = 0; i < 12; i++) {
      await page.mouse.move(cx + cw * 0.05 + i * 60, my);
      await page.waitForTimeout(15);
    }
    await page.mouse.up();
    await page.waitForTimeout(2500);  // 等待 fetchMoreCandles 触发
    laps++;
  }

  console.log('▶ 拖拽次数:', laps);
  console.log('▶ before 请求数:', beforeRequests.length);
  beforeRequests.slice(0, 6).forEach((u, i) => {
    const m = u.match(/before=(\d+)/);
    console.log(`   [${i+1}] before=${m ? m[1] : '?'}`);
  });

  // 检查是否加载到了更早的数据
  const state = await page.evaluate(async () => {
    // 尝试获取图表的可见范围信息（通过页面上可能的暴露接口）
    return { note: '见控制台请求' };
  });
  console.log('▶ 控制台错误数:', errors.length);
  errors.forEach(e => console.log('   ERROR:', e.slice(0, 150)));

  await browser.close();
  console.log('\n✅ 完成');
})().catch(e => { console.error('失败:', e); process.exit(1); });