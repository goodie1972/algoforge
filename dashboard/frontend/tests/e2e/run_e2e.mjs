/**
 * E2E 测试套件 — AlgoForge 核心场景
 *
 * 运行方式: node tests/e2e/run_e2e.mjs
 * 前置条件: 后端 127.0.0.1:1783 + 前端 127.0.0.1:5173 运行中
 */
import { chromium } from 'playwright-core'

const BROWSER_PATH = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const BASE_URL = 'http://127.0.0.1:5173'

const results = []
function log(name, passed, detail = '') {
  results.push({ name, passed, detail })
  console.log(`${passed ? '✅' : '❌'} ${name}${detail ? ' — ' + detail : ''}`)
}

async function run() {
  const browser = await chromium.launch({ executablePath: BROWSER_PATH, headless: true })
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } })
  const errors = []
  page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()) })

  // === 1. 首页加载 ===
  await page.goto(BASE_URL, { waitUntil: 'domcontentloaded', timeout: 15000 })
  await page.waitForTimeout(3000)
  const title = await page.title()
  log('1. 首页加载', title.includes('AlgoForge'))

  // === 2. 版本号显示 ===
  const versionEl = await page.locator('text=v2.9').first()
  const versionText = await versionEl.textContent().catch(() => '')
  log('2. 版本号', versionText.includes('v2.9'))

  // === 3. K线图渲染 ===
  const canvasCount = await page.locator('canvas').count()
  log('3. K线图渲染', canvasCount >= 1, `${canvasCount} canvas`)

  // === 4. 指标面板 ===
  const cbCount = await page.locator('.n-checkbox').count()
  log('4. 指标面板', cbCount >= 12, `${cbCount} 复选框`)

  // === 5. 开启 RSI 副图 ===
  const rsiCb = page.locator('.n-checkbox:has-text("RSI") input').first()
  if (await rsiCb.count() > 0) {
    const beforeCount = canvasCount
    await rsiCb.click()
    await page.waitForTimeout(1500)
    const afterCount = await page.locator('canvas').count()
    log('5. RSI副图', afterCount > beforeCount, `${beforeCount}→${afterCount}`)
  } else {
    log('5. RSI副图', false, '未找到RSI复选框')
  }

  // === 6. 十字光标联动 ===
  await page.mouse.move(600, 300)
  await page.waitForTimeout(500)
  const crosshair = await page.locator('#tc-crosshair-time').count()
  log('6. 十字光标', crosshair > 0)

  // === 7. 经济日历跑马灯 ===
  const marquee = await page.locator('text=FOMC').count()
  log('7. 跑马灯', marquee > 0, `${marquee} 条事件`)

  // === 8. 策略中心 ===
  await page.locator('[class*="menuitem"]:has-text("策略")').first().click().catch(() => {})
  await page.waitForTimeout(2000)
  const strategyCards = await page.locator('.n-card').count()
  log('8. 策略中心', strategyCards > 0, `${strategyCards} 卡片`)

  // === 9. 配置页 ===
  await page.locator('[class*="menuitem"]:has-text("配置")').first().click().catch(() => {})
  await page.waitForTimeout(2000)
  const formItems = await page.locator('.n-form-item, .n-card').count()
  log('9. 配置页', formItems > 0, `${formItems} 表单项`)

  // === 10. 日报周报 ===
  await page.locator('[class*="menuitem"]:has-text("日报")').first().click().catch(() => {})
  await page.waitForTimeout(2000)
  const reportItems = await page.locator('.n-card, .n-data-table, .n-list').count()
  log('10. 日报周报', reportItems > 0)

  // === 11. Console 零错误 ===
  log('11. Console零错误', errors.length === 0, errors.length > 0 ? errors[0].substring(0, 80) : '')

  // === 12. 切换周期 ===
  await page.locator('[class*="menuitem"]:has-text("交易")').first().click().catch(() => {})
  await page.waitForTimeout(2000)
  const m5Btn = page.locator('button:has-text("M5")').first()
  if (await m5Btn.count() > 0) {
    await m5Btn.click()
    await page.waitForTimeout(2000)
    const m5Active = await page.locator('button.n-button--primary:has-text("M5")').count()
    log('12. 切换M5', m5Active > 0)
  } else {
    log('12. 切换M5', false, '未找到M5按钮')
  }

  // 截图
  await page.screenshot({ path: '../../data/test_screenshots/e2e_final.png' })

  // 汇总
  const passed = results.filter(r => r.passed).length
  const total = results.length
  console.log(`\n=== E2E 结果: ${passed}/${total} 通过 ===`)

  await browser.close()
  return passed === total ? 0 : 1
}

run().then(exitCode => process.exit(exitCode)).catch(e => { console.error(e); process.exit(1) })
