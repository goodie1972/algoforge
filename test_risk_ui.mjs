// Playwright E2E test: Risk Config UI
// Usage: node test_risk_ui.mjs
// Requires: backend running on :8000, frontend on :5173
import { chromium } from 'file:///C:/Users/Administrator/AppData/Roaming/npm/node_modules/playwright/index.mjs';

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
page.on('console', msg => console.log(`[${msg.type()}] ${msg.text()}`));
page.on('pageerror', err => console.log(`[ERROR] ${err.message}`));

// 1. Load dashboard
await page.goto('http://localhost:5173', { timeout: 15000 });
await page.waitForTimeout(2000);

// 2. Navigate to Config
await page.locator('text=运行配置').first().click();
await page.waitForTimeout(2000);

// 3. Verify tabs render
const tabLabels = ['策略参数', '风控参数', '连接配置', '新闻过滤'];
for (const tab of tabLabels) {
  const el = page.locator(`text=${tab}`).first();
  const visible = await el.isVisible().catch(() => false);
  console.log(`Tab "${tab}": ${visible ? 'PASS' : 'FAIL'}`);
}

// 4. Click 风控参数 tab
await page.locator('text=风控参数').first().click();
await page.waitForTimeout(1000);

// 5. Verify risk config sections
const sections = ['仓位管理', '止损止盈', '浮动亏损', '已实现亏损', '快速出场检测', '安全锁'];
for (const s of sections) {
  const visible = await page.locator(`text=${s}`).first().isVisible().catch(() => false);
  console.log(`Section "${s}": ${visible ? 'PASS' : 'FAIL'}`);
}

// 6. Screenshot
await page.screenshot({ path: 'risk_ui_debug.png', fullPage: true });
console.log('\nAll checks complete');

await browser.close();
