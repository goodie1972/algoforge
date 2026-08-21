const { chromium } = require('playwright')
const BASE = 'http://127.0.0.1:1783'
const EXEC = 'C:/Users/Administrator/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe'

async function main() {
  const browser = await chromium.launch({ headless: true, executablePath: EXEC })
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } })
  const logs = []
  page.on('console', msg => { if (msg.type() === 'error') logs.push(msg.text()) })
  page.on('pageerror', err => logs.push(err.message))

  const pass = (name, ok = true) => console.log(`[${ok ? 'PASS' : 'FAIL'}] ${name}`)
  const fail = (name) => pass(name, false)

  // 1. 页面加载
  await page.goto(BASE, { waitUntil: 'networkidle', timeout: 30000 })
  const title = await page.title()
  pass('页面加载 — 标题: ' + title, title.includes('AlgoForge'))

  // 2. API 验证
  const resp = await page.evaluate(() => fetch('/api/engine/status').then(r => r.status))
  pass('API /api/engine/status — HTTP ' + resp, resp === 200)

  const resp2 = await page.evaluate(() => fetch('/api/ai/sessions').then(r => r.status))
  pass('API /api/ai/sessions — HTTP ' + resp2, resp2 === 200)

  // 3. ChatLauncher
  const launcher = await page.$('.chat-launcher')
  pass('ChatLauncher 存在', !!launcher)
  pass('ChatLauncher 可见', launcher ? await launcher.isVisible() : false)

  // 4. 打开 AI 面板
  await launcher.click()
  await page.waitForTimeout(500)
  const panel = await page.$('.ai-chat-panel')
  pass('AiChatPanel 打开', !!panel)

  // 5. 关闭按钮
  const closeBtn = await page.$('.chat-icon-btn[title="关闭"], .chat-close-btn, .chat-header-right button')
  pass('头部关闭按钮存在', !!closeBtn)
  if (closeBtn) {
    const visible = await closeBtn.isVisible()
    pass('头部关闭按钮可见', visible)
    await closeBtn.click()
    await page.waitForTimeout(500)
    const launcher2 = await page.$('.chat-launcher')
    pass('关闭后 launcher 重新出现', !!launcher2)
    const panel2 = await page.$('.ai-chat-panel')
    pass('关闭后面板消失', !panel2)
  }

  // 6. 无 JS 报错
  pass('页面无 JS 报错', logs.length === 0)

  // 7. TradingTerminal 标题
  const hasTerminal = await page.evaluate(() => document.body.innerText.includes('XAUUSD 交易终端'))
  pass('TradingTerminal 组件存在', hasTerminal)

  console.log('\n====================')
  console.log(`整体: ${logs.length === 0 ? '✅ 全部通过' : '⚠️ 有 ' + logs.length + ' 个报错'}`)
  if (logs.length > 0) {
    console.log('报错:', logs.join('\n'))
  }
  console.log('====================')
  await browser.close()
}

main().catch(err => { console.error(err); process.exit(1) })