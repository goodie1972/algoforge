const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });

  await page.goto('http://127.0.0.1:1783', { timeout: 30000, waitUntil: 'networkidle' });
  await page.waitForTimeout(8000);

  // Check all 12 ind-lines exist
  const lines = await page.locator('.ind-line').count();
  console.log(`Ind-lines: ${lines}`);
  if (lines !== 12) throw new Error(`Expected 12 ind-lines, got ${lines}`);

  // Check positions - first 6 should be aligned, last 6 aligned
  for (let i = 0; i < 12; i++) {
    const top = await page.locator('.ind-line').nth(i).evaluate(el => el.getBoundingClientRect().top.toFixed(0));
    const label = await page.locator('.ind-line').nth(i).locator('label').first().innerText().catch(() => '?');
    console.log(`  [${i}] top=${top} ${label}`);
  }

  // Click the ADX, MFI, BBI checkboxes to enable them
  const allLabels = await page.locator('label').all();
  let clicked = 0;
  for (const label of allLabels) {
    const txt = await label.innerText();
    if (txt.trim() === 'ADX' || txt.trim() === 'MFI' || txt.trim() === 'BBI') {
      await label.click();
      clicked++;
      console.log(`Clicked: ${txt.trim()}`);
      await page.waitForTimeout(500);
    }
  }
  console.log(`Checkboxes clicked: ${clicked}`);

  // Wait for chart rendering
  await page.waitForTimeout(3000);

  // Count canvas elements (main chart + panes)
  const canvasCount = await page.locator('canvas').count();
  console.log(`Canvas elements: ${canvasCount}`);

  // Check for console errors
  const errors = [];
  page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
  await page.waitForTimeout(2000);
  console.log(`Console errors: ${errors.length}`);
  for (const e of errors.slice(0, 5)) {
    console.log(`  ERROR: ${e.slice(0, 100)}`);
  }

  if (canvasCount < 2) throw new Error('No chart canvases found');
  if (errors.length > 0) throw new Error(`Found ${errors.length} console errors`);

  console.log('\nALL TESTS PASSED');
  await browser.close();
})();