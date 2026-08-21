const { chromium } = require('playwright');

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

  // 找到第一个 K 线图 canvas
  const canvas = page.locator('canvas').first();
  const box = await canvas.boundingBox();
  if (!box) { console.log('❌ 未找到图表'); await browser.close(); return; }

  // 拖拽图表向左（查看历史数据）
  const y = box.y + box.height * 0.5;
  await page.mouse.move(box.x + box.width * 0.8, y);
  await page.mouse.down();
  for (let i = 0; i < 20; i++) {
    await page.mouse.move(box.x + box.width * 0.8 - i * 40, y);
    await page.waitForTimeout(30);
  }
  await page.mouse.up();
  await page.waitForTimeout(1500);
  console.log('▶ 已滚动到历史区域，截图 A');
  await page.screenshot({ path: 'test_history_a.png' });

  // 等待超过 10 秒自动回滚定时器（原逻辑会强制拉回最新）
  console.log('▶ 等待 12 秒（超过旧的自动回滚定时器）...');
  await page.waitForTimeout(12000);
  console.log('▶ 再次截图 B');
  await page.screenshot({ path: 'test_history_b.png' });

  // 对比两张截图（用像素级比较判断是否有漂移）
  const page2 = await browser.newPage({ viewport: { width: 1600, height: 900 } });
  const hashA = await hashImage(page, 'test_history_a.png');
  const hashB = await hashImage(page2, 'test_history_b.png');
  await page2.close();

  console.log('▶ 截图A hash:', hashA);
  console.log('▶ 截图B hash:', hashB);
  console.log(hashA === hashB ? '✅ 无漂移：12秒后视图未变' : '⚠️ 视图有变化（可能需要人工确认是否正常刷新）');

  // 检查控制台错误
  console.log('▶ 控制台错误数:', errors.length);
  errors.forEach(e => console.log('   ERROR:', e.slice(0, 150)));

  await browser.close();
})().catch(e => { console.error('失败:', e); process.exit(1); });

async function hashImage(page, path) {
  const fs = require('fs');
  const crypto = require('crypto');
  const buf = fs.readFileSync(path);
  // 只取中间部分区域做 hash（避免时间戳等无关差异）
  return crypto.createHash('md5').update(buf).digest('hex');
}