const { chromium } = require('playwright')
const p = 'C:\\Users\\Administrator\\AppData\\Local\\ms-playwright\\chromium-1223\\chrome-win64\\chrome.exe'

;(async () => {
  const b = await chromium.launch({ headless: true, executablePath: p, args: ['--no-sandbox'] })
  const ctx = await b.newContext({ viewport: { width: 1440, height: 900 } })
  const page = await ctx.newPage()
  const errs: string[] = []
  page.on('console', msg => { if (msg.type() === 'error') errs.push(msg.text()) })
  page.on('pageerror', err => errs.push('PAGE: ' + err.message))

  // 1. 导航到策略中心
  await page.goto('http://localhost:5173/#/strategies', { waitUntil: 'networkidle', timeout: 30000 })
  await page.waitForTimeout(4000)
  console.log('1. 策略中心页面加载完成')

  // 检查 API 请求
  const apiCalls = await page.evaluate(async () => {
    const r1 = await fetch('/api/strategies/available')
    const d1 = await r1.json()
    const r2 = await fetch('/api/engine/strategies')
    const d2 = await r2.json()
    return {
      available: d1.strategies?.length || 0,
      running: d2.running?.length || 0,
      runningNames: d2.running?.map((s: any) => s.name) || []
    }
  })
  console.log(`2. API获取: 可用${apiCalls.available}个, 引擎运行${apiCalls.running}个`)
  if (apiCalls.running !== 9) {
    console.log(`   ⚠ 期望9个运行中, 实际${apiCalls.running}个`)
  }

  // 3. 检查页面上运行中的策略标签
  const runningTags = await page.locator('.n-tag:has-text("运行中")').count()
  console.log(`3. 页面显示"运行中"标签: ${runningTags}个`)
  if (runningTags !== 9) {
    console.log(`   ⚠ 期望9个, 实际${runningTags}个`)
  }

  // 4. 检查导入按钮存在
  const importBtn = await page.locator('button:has-text("导入策略")').count()
  console.log(`4. 导入策略按钮: ${importBtn > 0 ? '✅' : '❌'}`)

  // 5. 检查删除按钮存在
  const deleteBtn = await page.locator('button:has-text("删除策略")').count()
  console.log(`5. 删除策略按钮: ${deleteBtn > 0 ? '✅' : '❌'}`)

  // 6. 点击删除策略进入删除模式
  await page.locator('button:has-text("删除策略")').click()
  await page.waitForTimeout(1000)
  const cancelBtn = await page.locator('button:has-text("取消")').count()
  console.log(`6. 删除模式 - 取消按钮: ${cancelBtn > 0 ? '✅' : '❌'}`)

  // 7. 取消删除模式
  await page.locator('button:has-text("取消")').click()
  await page.waitForTimeout(500)
  const deleteBtnAfter = await page.locator('button:has-text("删除策略")').count()
  console.log(`7. 退出删除模式后删除按钮: ${deleteBtnAfter > 0 ? '✅' : '❌'}`)

  // 8. 测试上传 - 上传一个有效的.py文件
  await page.evaluate(() => {
    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    if (input) {
      // 创建一个最小有效的策略文件
      const content = 'class TestStrategy:\n    name = "test"\n    pass\n'
      const blob = new Blob([content], { type: 'text/plain' })
      const file = new File([blob], '20260811_test_strategy_v1.py', { type: 'text/plain' })
      const dt = new DataTransfer()
      dt.items.add(file)
      input.files = dt.files
      input.dispatchEvent(new Event('change', { bubbles: true }))
    }
  })
  await page.waitForTimeout(2000)
  console.log('8. 上传测试文件完成')

  // 9. 检查控制台错误
  if (errs.length > 0) {
    console.log(`9. 控制台错误 (${errs.length}):`)
    errs.forEach(e => console.log(`   ${e}`))
  } else {
    console.log('9. 控制台错误: 无 ✅')
  }

  await b.close()
  console.log('\n测试完成')
})()