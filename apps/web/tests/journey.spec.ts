import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
// These browser tests deliberately use HTTP test fixtures. They never export model telemetry.
test.beforeEach(async ({ page }) => {
  let signedIn = false, confirmed = false, turns = false;
  const proposal = () => ({ proposal_id:'proposal-test',product_name:'Arc One Headphones',arrival_date:'2026-09-18',shipping_method:'Express',status:confirmed ? 'confirmed' : 'proposed' });
  await page.route('**/collect', route => route.fulfill({status:202,body:'{}'}));
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    const json = (body: unknown, status = 200) => route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
    if (path === '/api/demo-session') { signedIn = true; return json({customer_id:'C1'}); }
    if (path === '/api/orders') return signedIn ? json({orders:[{order_id:'PD-1042',product_name:'Arc One Headphones',delivered_at:'2026-09-12',status:'Delivered'}]}) : json({},401);
    if (path.endsWith('/confirm')) { confirmed = true; return json({status:'confirmed'}); }
    if (path.endsWith('/turns')) { turns = true; return route.fulfill({contentType:'text/event-stream',body:`event: text_delta\nid: 1\ndata: {"payload":{"delta":"I can arrange a replacement for September 18."}}\n\nevent: proposal\nid: 2\ndata: ${JSON.stringify({payload:proposal()})}\n\nevent: completed\nid: 3\ndata: {}\n\n`}); }
    if (path.startsWith('/api/conversations')) return json({conversation_id:'conv-test',order_id:'PD-1042',messages:turns ? [{role:'user',content:'My headphones arrived damaged.'},{role:'assistant',content:'I can arrange a replacement for September 18.'}] : [],proposal:turns ? proposal() : null,status:confirmed ? 'confirmed' : 'active'});
    return json({},404);
  });
});
test('replacement is explicit, idempotent in UI and survives refresh', async ({ page }) => {
  await page.goto('/'); await page.getByRole('button',{name:'Continue as demo customer'}).click(); await page.getByRole('button',{name:'View headphones order',exact:true}).click();
  await page.getByRole('textbox',{name:'Message'}).fill('My headphones arrived damaged.'); await page.getByRole('button',{name:'Send message'}).click();
  const confirm = page.getByRole('button',{name:'Confirm replacement',exact:true}); await expect(confirm).toBeVisible();
  let confirmations = 0; page.on('request', request => { if (request.url().endsWith('/confirm')) confirmations++; });
  await confirm.click(); await expect(page.getByRole('heading',{name:'Replacement confirmed'})).toBeVisible(); expect(confirmations).toBe(1);
  await page.reload(); await expect(page.getByRole('heading',{name:'Replacement confirmed'})).toBeVisible();
  const result = await new AxeBuilder({page}).analyze(); expect(result.violations).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({path:`test-results/confirmed-${test.info().project.name}.png`,fullPage:true});
});
test('landing is accessible and visually stable', async ({ page }) => {
  await page.goto('/'); await expect(page.getByRole('button',{name:'Continue as demo customer'})).toBeEnabled();
  const result = await new AxeBuilder({page}).analyze(); expect(result.violations).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({path:`test-results/landing-${test.info().project.name}.png`,fullPage:true});
});
test('failed confirmation stays unconfirmed with recovery', async ({ page }) => {
  await page.route('**/api/proposals/*/confirm', route => route.fulfill({status:503,body:'unavailable'}));
  await page.goto('/'); await page.getByRole('button',{name:'Continue as demo customer'}).click(); await page.getByRole('button',{name:'View headphones order',exact:true}).click(); await page.getByRole('button',{name:'My item arrived damaged'}).click();
  await page.getByRole('button',{name:'Confirm replacement',exact:true}).click(); await expect(page.getByRole('alert')).toContainText('could not complete'); await expect(page.getByRole('heading',{name:'Replacement confirmed'})).toHaveCount(0);
});
test('offline state prevents sending and preserves the conversation', async ({ page, context }) => {
  await page.goto('/'); await page.getByRole('button',{name:'Continue as demo customer'}).click(); await page.getByRole('button',{name:'View headphones order',exact:true}).click();
  await context.setOffline(true); await expect(page.getByText('You’re offline. Your saved conversation will be here when you reconnect.')).toBeVisible(); await expect(page.getByRole('textbox',{name:'Message'})).toBeDisabled();
  await context.setOffline(false); await expect(page.getByRole('textbox',{name:'Message'})).toBeEnabled();
});
test('landing performance and keyboard focus meet the local budget', async ({ page }) => {
  await page.addInitScript(() => {
    const state = {lcp:0,cls:0}; (window as unknown as {measurements:typeof state}).measurements = state;
    new PerformanceObserver(list => { for (const entry of list.getEntries()) state.lcp = entry.startTime; }).observe({type:'largest-contentful-paint',buffered:true});
    new PerformanceObserver(list => { for (const entry of list.getEntries()) { const shift=entry as PerformanceEntry & {hadRecentInput:boolean;value:number}; if (!shift.hadRecentInput) state.cls+=shift.value; } }).observe({type:'layout-shift',buffered:true});
  });
  await page.goto('/'); await expect(page.getByRole('button',{name:'Continue as demo customer'})).toBeEnabled(); await page.locator('.hero-photo img').evaluate(async image => { await (image as HTMLImageElement).decode(); });
  // Image decoding precedes paint. Wait for a measured paint before keyboard input,
  // because Chrome stops collecting LCP candidates on the first interaction.
  await page.waitForFunction(() => (window as unknown as {measurements:{lcp:number}}).measurements.lcp > 0);
  await page.keyboard.press('Tab'); await expect(page.getByRole('link',{name:'Skip to content'})).toBeFocused();
  const measurements = await page.evaluate(() => (window as unknown as {measurements:{lcp:number;cls:number}}).measurements);
  expect(measurements.lcp).toBeGreaterThan(0); expect(measurements.lcp).toBeLessThanOrEqual(2500); expect(measurements.cls).toBeLessThanOrEqual(.1);
  await test.info().attach('performance.json',{body:JSON.stringify({...measurements,environment:'local Vite with HTTP fixtures',viewport:test.info().project.name}),contentType:'application/json'});
});
