import { chromium } from 'file:///C:/Users/Administrator/AppData/Roaming/npm/node_modules/playwright/index.mjs';

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });

page.on('console', msg => {
  if (msg.type() === 'error' || msg.type() === 'warning')
    console.log(`[${msg.type()}] ${msg.text()}`);
});

await page.goto('http://localhost:5173', { timeout: 15000 });
await page.waitForTimeout(3000);

// 1. Engine status text in sidebar
const bodyText = await page.evaluate(() => document.body.innerText);
console.log('1. 页面文本(前200字):', bodyText.substring(0, 200).replace(/\n/g, ' | '));

const engineRunning = bodyText.includes('引擎运行中');
const engineStopped = bodyText.includes('引擎已停止');
console.log('2. 引擎状态:', engineRunning ? 'RUNNING ✓' : engineStopped ? 'STOPPED ✗' : 'UNKNOWN');

// 2. Check API through Vite proxy (same origin as page)
const apiViaVite = await page.evaluate(async () => {
  try {
    const r = await fetch('/api/engine/status');
    return await r.json();
  } catch(e) { return {error: e.message}; }
});
console.log('3. API via Vite proxy:', JSON.stringify(apiViaVite));

// 3. Check API directly
const apiDirect = await page.evaluate(async () => {
  try {
    const r = await fetch('http://localhost:8000/api/engine/status');
    return await r.json();
  } catch(e) { return {error: e.message}; }
});
console.log('4. API direct 8000:', JSON.stringify(apiDirect));

// 4. WebSocket through Vite proxy (/ws → proxied to :8000/ws)
console.log('5. WebSocket via Vite proxy:');
const wsViaVite = await page.evaluate(async () => {
  return new Promise(resolve => {
    const msgs = [];
    try {
      const ws = new WebSocket('ws://localhost:5173/ws');
      ws.onopen = () => { msgs.push('open'); };
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          msgs.push(`${data.channel}:${data.data?.status || 'data'}`);
        } catch(e) { msgs.push('parse-error'); }
      };
      ws.onerror = () => { msgs.push('error'); };
      setTimeout(() => { ws.close(); resolve(msgs); }, 4000);
    } catch(e) { resolve(['exception: ' + e.message]); }
  });
});
console.log('   WS消息:', JSON.stringify(wsViaVite));

// 5. Check price data
const priceData = await page.evaluate(async () => {
  try {
    const r = await fetch('/api/market/price');
    return await r.json();
  } catch(e) { return {error: e.message}; }
});
console.log('6. 价格数据:', JSON.stringify(priceData));

// 6. Check account
const accountData = await page.evaluate(async () => {
  try {
    const r = await fetch('/api/account');
    return await r.json();
  } catch(e) { return {error: e.message}; }
});
console.log('7. 账户信息:', JSON.stringify(accountData));

// 7. Check positions
const posData = await page.evaluate(async () => {
  try {
    const r = await fetch('/api/positions');
    return await r.json();
  } catch(e) { return {error: e.message}; }
});
console.log('8. 持仓数据:', JSON.stringify(posData));

// 8. Wait for WebSocket status update and re-check sidebar
await page.waitForTimeout(4000);
const bodyText2 = await page.evaluate(() => document.body.innerText);
console.log('9. 延迟后引擎状态:', bodyText2.includes('引擎运行中') ? 'RUNNING ✓' : 'STOPPED ✗');

await browser.close();
