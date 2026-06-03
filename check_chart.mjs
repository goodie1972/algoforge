import { chromium } from 'file:///C:/Users/Administrator/AppData/Roaming/npm/node_modules/playwright/index.mjs';

const b = await chromium.launch({ headless: true });
const p = await b.newPage({ viewport: { width: 1280, height: 900 } });

const apiCalls = [];
p.on('request', r => { if (r.url().includes('/api/')) apiCalls.push({ url: r.url(), method: r.method() }); });
p.on('response', r => { if (r.url().includes('/api/')) { const c = apiCalls.find(x => x.url === r.url()); if (c) c.status = r.status(); } });
p.on('console', m => { if (m.type() === 'error') console.log('[ERR]', m.text().substring(0, 200)); });

await p.goto('http://localhost:5173', { timeout: 15000 });
await p.waitForTimeout(8000);

// Check indicator toolbar
const checkboxes = await p.evaluate(() => {
  return Array.from(document.querySelectorAll('.n-checkbox')).map(e => ({
    label: e.textContent?.trim(),
    checked: e.classList.contains('n-checkbox--checked'),
  }));
});
console.log('=== Indicator Checkboxes ===');
checkboxes.forEach(c => console.log(`  ${c.checked ? '[x]' : '[ ]'} ${c.label}`));

// Check input fields are present
const inputs = await p.evaluate(() => {
  return Array.from(document.querySelectorAll('input[type="text"], input[type="number"]'))
    .filter(e => e.closest('.n-input') && !e.disabled)
    .map(e => ({ placeholder: e.placeholder || '', value: e.value }));
});
console.log('\n=== Input Fields ===');
inputs.forEach(i => { if (i.placeholder || i.value) console.log(`  placeholder="${i.placeholder}" value="${i.value}"`); });

// Check canvas count
const canvasCount = await p.evaluate(() => document.querySelectorAll('canvas').length);
console.log(`\n=== Canvases: ${canvasCount} ===`);

await b.close();
