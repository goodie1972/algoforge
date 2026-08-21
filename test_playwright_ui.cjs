const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({
    executablePath: 'C:/Users/Administrator/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe',
    headless: true,
  });
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
  const errors = [];
  page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
  page.on('pageerror', err => errors.push(String(err)));

  console.log('▶ 打开页面...');
  await page.goto('http://127.0.0.1:1783', { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(3000);

  console.log('▶ 页面标题:', await page.title());
  console.log('▶ 截图1 首页');
  await page.screenshot({ path: 'test_home.png' });

  // 检查是否有 K 线图 canvas
  const canvases = await page.locator('canvas').count();
  console.log('▶ canvas 数量:', canvases);

  // 等待图表加载
  await page.waitForTimeout(5000);

  // 滚动测试：移动到 K 线图区域
  const chartSel = page.locator('.tv-lightweight-charts, canvas').first();
  if (await chartSel.count() > 0) {
    const box = await chartSel.boundingBox();
    if (box) {
      console.log('▶ K线图位置:', JSON.stringify(box));
      // 在图表上按下并进行拖拽（模拟滚动查看历史）
      await page.mouse.move(box.x + box.width * 0.7, box.y + box.height * 0.5);
      await page.mouse.down();
      for (let i = 0; i < 10; i++) {
        await page.mouse.move(box.x + box.width * 0.7 - 60 - i * 30, box.y + box.height * 0.5, { steps: 2 });
        await page.waitForTimeout(50);
      }
      await page.mouse.up();
      console.log('▶ 已向左拖拽图表（查看历史）');
      await page.waitForTimeout(2000);
    }
  }

  // 检查滚动后是否有错误
  await page.waitForTimeout(3000);
  console.log('▶ 控制台错误数:', errors.length);
  if (errors.length > 0) {
    errors.forEach(e => console.log('   ERROR:', e.slice(0, 200)));
  }

  // 截图2 滚动后
  await page.screenshot({ path: 'test_scrolled.png' });

  // 检查 API 状态
  const status = await page.evaluate(async () => {
    const r = await fetch('/api/engine/status');
    return r.json();
  });
  console.log('▶ 引擎状态:', JSON.stringify(status));

  await browser.close();
  console.log('\n✅ 测试完成');
})().catch(e => { console.error('测试失败:', e); process.exit(1); });