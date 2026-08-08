import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const artifact = path.resolve('deliverables/taskmarket-bubble-brawl/index.html');
const evidenceDir = path.resolve('/tmp/bubble-brawl-browser-evidence');
fs.mkdirSync(evidenceDir, { recursive: true });

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({
  viewport: { width: 1440, height: 960 },
  deviceScaleFactor: 1,
});
const errors = [];
const requests = [];
page.on('pageerror', error => errors.push(`pageerror: ${error.message}`));
page.on('console', message => {
  if (message.type() === 'error') errors.push(`console: ${message.text()}`);
});
page.on('request', request => requests.push(request.url()));

await page.goto(pathToFileURL(artifact).href, { waitUntil: 'load' });
await page.waitForSelector('canvas');
await page.waitForFunction(() => typeof window.__bubbleBrawlStatus === 'function');
await page.waitForTimeout(900);
if (await page.locator('#fatal').isVisible()) errors.push('fatal Three.js fallback became visible');
if (!(await page.locator('#startOverlay').isVisible())) errors.push('start overlay is not visible');
await page.screenshot({ path: path.join(evidenceDir, 'start.png'), fullPage: true });

await page.click('#startBtn');
await page.waitForTimeout(700);
if (await page.locator('#startOverlay').isVisible()) errors.push('start overlay did not close');
const initial = await page.evaluate(() => window.__bubbleBrawlStatus());
if (!initial.running || initial.over) errors.push(`game did not start: ${JSON.stringify(initial)}`);
if (initial.enemies < 2) errors.push(`expected initial enemies, got ${initial.enemies}`);
if (initial.health !== 3) errors.push(`expected three health, got ${initial.health}`);

await page.keyboard.down('ArrowRight');
await page.waitForTimeout(250);
await page.keyboard.up('ArrowRight');
await page.keyboard.press('Space');
await page.waitForTimeout(90);
const afterShot = await page.evaluate(() => window.__bubbleBrawlStatus());
if (afterShot.shots < 1) errors.push(`bubble projectile was not created: ${JSON.stringify(afterShot)}`);

await page.keyboard.down('Shift');
await page.waitForTimeout(520);
const pullWidth = await page.locator('#pullFill').evaluate(element => element.style.width);
await page.keyboard.up('Shift');
if (!pullWidth || pullWidth === '100%') errors.push(`gather field did not consume energy: ${pullWidth}`);

await page.waitForTimeout(3200);
const running = await page.evaluate(() => window.__bubbleBrawlStatus());
if (!running.running || running.over) errors.push(`game stopped unexpectedly: ${JSON.stringify(running)}`);
const score = (await page.locator('#score').textContent())?.trim() ?? '';
if (!/^\d{6,}$/.test(score)) errors.push(`score is not numeric: ${score}`);
const high = (await page.locator('#highScore').textContent())?.trim() ?? '';
if (!/^\d[\d,]*$/.test(high)) errors.push(`high score is not numeric: ${high}`);
if ((await page.locator('#healthRow .heart').count()) !== 3) errors.push('health UI does not contain three hearts');
if ((await page.locator('#shootBtn').count()) !== 1 || (await page.locator('#pullBtn').count()) !== 1) {
  errors.push('touch action controls are missing');
}
await page.screenshot({ path: path.join(evidenceDir, 'running.png'), fullPage: true });

const runtimeNetwork = requests.filter(url => /^https?:/i.test(url));
if (runtimeNetwork.length) errors.push(`runtime network request(s): ${runtimeNetwork.join(', ')}`);

const reportPath = path.resolve('deliverables/taskmarket-bubble-brawl/validation-report.json');
const report = JSON.parse(fs.readFileSync(reportPath, 'utf8'));
report.browser_smoke = errors.length ? 'failed' : 'passed';
report.browser = {
  engine: 'chromium',
  version: browser.version(),
  viewport: '1440x960',
  runtime_network_requests: runtimeNetwork.length,
  initial_state: initial,
  state_after_shot: afterShot,
  running_state: running,
  gather_meter_during_hold: pullWidth,
  screenshot_names: ['start.png', 'running.png'],
};
report.browser_errors = errors;
fs.writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`);
await browser.close();

if (errors.length) {
  console.error(errors.join('\n'));
  process.exit(1);
}
