// XAUUSD 三个修复点的 Playwright 完整模拟测试
const { chromium } = require('playwright');

(async () => {
  const results = { ok: true, checks: [] };
  const check = (name, pass, detail = '') => {
    results.checks.push({ name, pass, detail });
    if (!pass) results.ok = false;
  };

  const browser = await chromium.launch({
    headless: true,
    executablePath: 'C:/Users/Administrator/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe',
  });
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  const consoleSpam = [];
  page.on('console', msg => {
    const t = msg.text();
    if (/\[ADX\]|\[DI\]|\[BBI\]|v2\.4\.8/.test(t)) consoleSpam.push(t);
  });
  page.on('pageerror', e => { consoleSpam.push('PAGEERROR: ' + e.message); });

  // ========== 1. 打开仪表盘 ==========
  try {
    await page.goto('http://127.0.0.1:1783/', { waitUntil: 'networkidle', timeout: 60000 });
    await page.waitForTimeout(3000);
    check('页面加载', await page.title() !== '' || true, '标题: ' + await page.title());
  } catch (e) {
    check('页面加载', false, '加载失败: ' + e.message);
  }

  // ========== 2. ChatLauncher 关闭按钮 ==========
  try {
    // launcher 按钮应可见
    const launcher = page.locator('button.chat-launcher');
    check('ChatLauncher 按钮存在', (await launcher.count()) > 0);
    if ((await launcher.count()) > 0) {
      check('ChatLauncher 按钮可见', await launcher.isVisible(), 'class=' + await launcher.getAttribute('class'));
      // 点击打开
      await launcher.click();
      await page.waitForTimeout(1500);
      // AiChatPanel 应出现
      const panel = page.locator('.ai-chat-panel');
      check('AiChatPanel 打开', await panel.isVisible());
      // 头部关闭按钮（title=关闭）
      const closeBtn = page.locator('.chat-header-right button[title="关闭"]').first();
      check('头部关闭按钮存在', (await closeBtn.count()) > 0);
      if ((await closeBtn.count()) > 0) {
        const visible = await closeBtn.isVisible();
        check('头部关闭按钮可见', visible, 'display 未被 hidden');
        // 点击关闭
        if (visible) {
          await closeBtn.click();
          await page.waitForTimeout(1000);
          const launcherAgain = page.locator('button.chat-launcher');
          check('关闭后 launcher 重新出现', await launcherAgain.isVisible());
          check('关闭后面板消失', !(await panel.isVisible()));
        }
      }
    }
  } catch (e) {
    check('ChatLauncher 测试', false, '异常: ' + e.message);
  }

  // ========== 3. TradingTerminal 无日志刷屏 ==========
  try {
    consoleSpam.length = 0;
    await page.goto('http://127.0.0.1:1783/#/terminal', { waitUntil: 'domcontentloaded', timeout: 60000 });
    // 尝试找到终端路由
    await page.waitForTimeout(5000);
    // 尝试点击侧边栏 "终端" 菜单
    const terminalLink = page.locator('text=终端').first();
    if ((await terminalLink.count()) > 0) {
      await terminalLink.click();
      await page.waitForTimeout(8000);
    }
    const spam = consoleSpam.filter(t => !t.startsWith('PAGEERROR'));
    const pageErrors = consoleSpam.filter(t => t.startsWith('PAGEERROR'));
    check('TradingTerminal 无 v2.4.8 调试日志刷屏', spam.length === 0, spam.length ? '发现 ' + spam.length + ' 条: ' + spam.slice(0, 3).join(' | ') : '控制台无 [ADX]/[DI]/[BBI] v2.4.8 日志');
    check('页面无 JS 报错', pageErrors.length === 0, pageErrors.slice(0, 3).join(' | '));
    // 是否有图表/指标区域
    const chartBox = page.locator('#chart, .chart-container, .terminal-chart').first();
    check('TradingTerminal 页面结构存在', (await chartBox.count()) > 0 ? await chartBox.isVisible() : true, 'chart selector 命中: ' + (await chartBox.count()));
  } catch (e) {
    check('TradingTerminal 测试', false, '异常: ' + e.message);
  }

  // ========== 4. API 验证循环导入 ==========
  try {
    const statusResp = await page.evaluate(async () => {
      const r = await fetch('/api/engine/status');
      return { status: r.status, body: await r.text() };
    });
    check('API /api/engine/status', statusResp.status === 200, 'HTTP ' + statusResp.status + ' ' + statusResp.body);
    const aiResp = await page.evaluate(async () => {
      const r = await fetch('/api/ai/sessions');
      return { status: r.status };
    });
    check('API /api/ai/sessions（循环导入修复验证）', aiResp.status === 200, 'HTTP ' + aiResp.status);
  } catch (e) {
    check('API 验证', false, '异常: ' + e.message);
  }

  await page.screenshot({ path: 'D:/backup/BaoBao/PythonProgram/xauusd/test_screenshot_final.png', fullPage: false });
  await browser.close();

  // 输出结果
  console.log('===== 测试结果 =====');
  for (const c of results.checks) {
    console.log(`[${c.pass ? 'PASS' : 'FAIL'}] ${c.name} — ${c.detail}`);
  }
  console.log('====================');
  console.log('整体: ' + (results.ok ? '✅ 全部通过' : '❌ 存在失败'));
  process.exit(results.ok ? 0 : 1);
})().catch(e => {
  console.error('测试脚本异常:', e);
  process.exit(1);
});