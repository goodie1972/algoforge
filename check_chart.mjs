import { chromium } from 'file:///C:/Users/Administrator/AppData/Roaming/npm/node_modules/playwright/index.mjs';

const b = await chromium.launch({ headless: true });
const p = await b.newPage({ viewport: { width: 1280, height: 900 } });

// Track all API calls
const apiCalls = [];
p.on('request', r => { if (r.url().includes('/api/')) apiCalls.push({ url: r.url(), method: r.method() }); });
p.on('response', r => { if (r.url().includes('/api/')) { const c = apiCalls.find(x => x.url === r.url()); if (c) c.status = r.status(); } });
p.on('requestfailed', r => { if (r.url().includes('/api/')) { const c = apiCalls.find(x => x.url === r.url()); if (c) c.failure = r.failure()?.errorText; } });
p.on('console', m => { if (m.type() === 'error') console.log('[ERR]', m.text().substring(0, 200)); });

await p.goto('http://localhost:5173', { timeout: 15000 });
await p.waitForTimeout(8000);

// Check all API calls
console.log('\n=== API Calls ===');
apiCalls.forEach(c => console.log(c.method, c.url.replace('http://localhost:5173',''), c.status || c.failure || 'pending'));

// Check DOM content
const body = await p.evaluate(() => document.body.innerText);
const idx = body.indexOf('XAUUSD 价格图表');
console.log('\n=== Chart Section ===');
console.log(body.substring(idx > -1 ? idx : 0, idx > -1 ? idx + 400 : 400));

// Check specific Vue state
const state = await p.evaluate(() => {
  const app = document.querySelector('#app');
  const canvas = document.querySelectorAll('canvas');
  const loading = document.querySelector('.n-spin');
  const empty = document.querySelector('.n-result');
  return {
    hasCanvas: canvas.length,
    hasSpinner: !!loading,
    hasEmptyState: !!empty,
    emptyText: empty?.textContent?.substring(0, 100) || 'none',
    priceValues: Array.from(document.querySelectorAll('.price-up strong, .price-down strong, .price-gold strong')).map(e => e.textContent),
  };
});
console.log('\n=== DOM State ===');
console.log(JSON.stringify(state, null, 2));

await b.close();
