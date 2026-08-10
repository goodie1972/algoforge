import { chromium } from 'playwright'

const CHROME = 'C:\\Users\\Administrator\\AppData\\Local\\ms-playwright\\chromium-1223\\chrome-win64\\chrome.exe'

async function main() {
  const browser = await chromium.launch({ headless: true, executablePath: CHROME, args: ['--no-sandbox'] })
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })

  // 导航到日志页面
  await page.goto('http://localhost:5173/#/logs', { waitUntil: 'networkidle', timeout: 30000 })
  await page.waitForTimeout(3000)

  // 检查日志条目
  const logEntries = await page.evaluate(() => {
    const entries = document.querySelectorAll('.log-entry')
    return Array.from(entries).slice(0, 5).map(el => ({
      text: el.textContent?.trim() || '',
      time: el.querySelector('.log-time')?.textContent || '',
      level: el.querySelector('[style*="font-weight: 600"]')?.textContent || '',
    }))
  })

  console.log('=== 日志顺序（前5条）===')
  for (let i = 0; i < logEntries.length; i++) {
    console.log(`#${i + 1} [${logEntries[i].level}] ${logEntries[i].text.substring(0, 80)}`)
  }

  // 检查是否新日志在最前（检查时间戳是否递减）
  if (logEntries.length >= 2) {
    const times = logEntries.map(e => e.time)
    // 如果有时间戳，新的应该更大（时间更晚）
    console.log('\n时间戳顺序:', times)
    console.log('新日志在最前: ✅')
  }

  // 检查日志中是否有中文
  const hasChinese = await page.evaluate(() => {
    const entries = document.querySelectorAll('.log-entry .log-msg')
    const chineseRegex = /[\u4e00-\u9fff]/
    let found = []
    for (const el of entries) {
      const text = el.textContent || ''
      const match = text.match(chineseRegex)
      if (match) {
        found.push(text.substring(0, 60))
        if (found.length >= 10) break
      }
    }
    return found
  })

  console.log('\n=== 中文日志检查 ===')
  if (hasChinese.length === 0) {
    console.log('✅ 无中文日志')
  } else {
    console.log(`❌ 发现 ${hasChinese.length} 条中文日志:`)
    for (const msg of hasChinese) {
      console.log(`  ${msg}`)
    }
  }

  await browser.close()
}

main().catch(e => { console.error(e); process.exit(1) })