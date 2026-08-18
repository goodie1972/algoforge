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

  let passed = 0, failed = 0;
  function check(name, ok) { if (ok) { passed++; console.log('  [PASS]', name); } else { failed++; console.log('  [FAIL]', name); } }

  console.log('1. 打开页面...');
  await page.goto('http://127.0.0.1:1783', { waitUntil: 'networkidle', timeout: 60000 });
  await page.waitForTimeout(3000);
  check('页面加载', await page.title() === 'AlgoForge - XAUUSD 黄金量化交易系统');

  // 2. 点击 ChatLauncher 打开 AI 面板
  console.log('2. 打开 AI 面板...');
  const launcher = page.locator('.chat-launcher');
  await launcher.waitFor({ state: 'visible', timeout: 5000 });
  check('ChatLauncher 可见', await launcher.isVisible());
  await launcher.click();
  await page.waitForTimeout(1500);

  const panel = page.locator('.ai-chat-panel');
  await panel.waitFor({ state: 'visible', timeout: 5000 });
  check('AI 面板打开', await panel.isVisible());

  // 3. 获取面板初始位置
  const initialBox = await panel.boundingBox();
  check('获取面板初始位置', !!initialBox);
  if (!initialBox) { await browser.close(); return; }
  console.log('   初始位置:', `left=${initialBox.x.toFixed(0)} top=${initialBox.y.toFixed(0)}`);

  // 4. 模拟鼠标拖拽
  console.log('3. 拖拽面板...');
  const header = panel.locator('.chat-header');
  await header.waitFor({ state: 'visible', timeout: 3000 });
  check('头部可见', await header.isVisible());

  const headerBox = await header.boundingBox();
  check('获取头部位置', !!headerBox);
  if (!headerBox) { await browser.close(); return; }
  const startX = headerBox.x + headerBox.width / 2;
  const startY = headerBox.y + headerBox.height / 2;

  await page.mouse.move(startX, startY);
  await page.mouse.down();
  // 分步拖拽
  for (let i = 1; i <= 10; i++) {
    await page.mouse.move(startX + i * 10, startY + i * 8, { steps: 2 });
    await page.waitForTimeout(30);
  }
  await page.waitForTimeout(100);
  await page.mouse.up();
  await page.waitForTimeout(500);

  // 5. 验证面板位置已移动
  const movedBox = await panel.boundingBox();
  check('拖拽后获取位置', !!movedBox);
  if (!movedBox) { await browser.close(); return; }
  const dx = movedBox.x - initialBox.x;
  const dy = movedBox.y - initialBox.y;
  console.log(`   拖拽后: left=${movedBox.x.toFixed(0)} top=${movedBox.y.toFixed(0)} 偏移: dx=${dx.toFixed(0)} dy=${dy.toFixed(0)}`);
  check('面板位置已移动 (dx>=30 && dy>=20)', dx >= 30 && dy >= 20);

  // 6. 无 JS 报错（过滤网络资源加载错误，非代码逻辑问题）
  const jsErrors = errors.filter(e => !e.includes('Failed to load resource') && !e.includes('ERR_CONNECTION'));
  check('无 JS 代码报错', jsErrors.length === 0);
  if (jsErrors.length > 0) console.log('   errors:', jsErrors.slice(0, 3));

  // 7. 关闭面板
  console.log('4. 关闭面板...');
  const closeBtn = panel.locator('.chat-header-right button').first();
  await closeBtn.click();
  await page.waitForTimeout(800);
  check('关闭后 launcher 重新出现', await launcher.isVisible());
  check('关闭后面板消失', !(await panel.isVisible()));

  console.log(`\n===== 结果: ${passed}/${passed+failed} PASS =====`);
  await browser.close();
})();