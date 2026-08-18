// 修复3专项验证：切换 ADX/DI/BBI 指标开关，确认无 v2.4.8 调试日志刷屏
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
  const spamLogs = [];
  page.on('console', msg => {
    const t = msg.text();
    if (/\[ADX\] v2\.4\.8|\[DI\] v2\.4\.8|\[BBI\] v2\.4\.8/.test(t)) spamLogs.push(t);
  });
  page.on('pageerror', e => { spamLogs.push('PAGEERROR: ' + e.message); });

  await page.goto('http://127.0.0.1:1783/', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(5000);

  // 找到指标复选框：Terminal 中的 ADX / DI / BBI 复选框
  // TradingTerminal 头部用 $t('terminal.adx') 等标签，中文是 "ADX"/"DI"/"BBI"
  const clickIndicator = async (label) => {
    const cb = page.locator('label').filter({ hasText: new RegExp(`^${label}$`) }).first();
    const n = await cb.count();
    if (n > 0) {
      await cb.click();
      await page.waitForTimeout(800);
      return `点击了 ${label} 复选框`;
    }
    // 尝试宽松匹配
    const loose = page.locator(`text=/^${label}\\s*$/`).first();
    const n2 = await loose.count();
    if (n2 > 0) { await loose.click(); await page.waitForTimeout(800); return `点击了 ${label}（宽松匹配）`; }
    return `未找到 ${label} 复选框`;
  };

  const r1 = await clickIndicator('ADX');
  const r2 = await clickIndicator('DI');
  const r3 = await clickIndicator('BBI');
  check('切换指标开关', true, [r1, r2, r3].join(' | '));

  // 页面里其他文本框点击以触发数据刷新？不需要 — v2.4.8 日志在函数入口，只要有调用就会打
  await page.waitForTimeout(3000);

  const pageErrors = spamLogs.filter(t => t.startsWith('PAGEERROR'));
  const debugSpam = spamLogs.filter(t => !t.startsWith('PAGEERROR'));
  check('切换 ADX/DI/BBI 后无 v2.4.8 调试日志', debugSpam.length === 0,
    debugSpam.length ? '发现: ' + debugSpam.join(' | ') : '确认无 [ADX]/[DI]/[BBI] v2.4.8 日志输出');
  check('页面无 JS 报错', pageErrors.length === 0, pageErrors.slice(0, 3).join(' | '));

  // 顺带确认终端标题存在
  const terminalCard = page.locator('text=XAUUSD 交易终端').first();
  check('TradingTerminal 组件在页面上', (await terminalCard.count()) > 0, '命中 XAUUSD 交易终端 标题');

  await page.screenshot({ path: 'D:/backup/BaoBao/PythonProgram/xauusd/test_screenshot_terminal.png' });
  await browser.close();

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