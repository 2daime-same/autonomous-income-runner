import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const artifact = path.resolve('deliverables/taskmarket-signal-panic/index.html');
const evidenceDir = path.resolve('/tmp/signal-panic-browser-evidence');
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
await page.waitForTimeout(1200);
if (await page.locator('#fatal').isVisible()) errors.push('fatal Three.js fallback became visible');
if (!(await page.locator('#startOverlay').isVisible())) errors.push('start overlay is not visible');
await page.screenshot({ path: path.join(evidenceDir, 'start.png'), fullPage: true });

await page.click('#startBtn');
await page.waitForTimeout(2200);
if (await page.locator('#startOverlay').isVisible()) errors.push('start overlay did not close');
if (!(await page.locator('#controls').isVisible())) errors.push('signal controls are not visible');
await page.keyboard.press('Digit2');
await page.waitForTimeout(1100);
const phaseAfterKey = (await page.locator('#phaseValue').textContent())?.trim() ?? '';
if (!['CLEARING', 'ALL STOP', 'E / W GO'].includes(phaseAfterKey)) {
  errors.push(`unexpected phase after keyboard switch: ${phaseAfterKey}`);
}
await page.locator('#nsBtn').dispatchEvent('pointerdown');
await page.waitForTimeout(900);
const score = (await page.locator('#score').textContent())?.trim() ?? '';
if (!/^\d{6,}$/.test(score)) errors.push(`score is not numeric: ${score}`);
const pressure = (await page.locator('#pressureValue').textContent())?.trim() ?? '';
if (!pressure) errors.push('queue pressure label is empty');
await page.waitForTimeout(5200);
await page.screenshot({ path: path.join(evidenceDir, 'running.png'), fullPage: true });

const runtimeNetwork = requests.filter(url => /^https?:/i.test(url));
if (runtimeNetwork.length) errors.push(`runtime network request(s): ${runtimeNetwork.join(', ')}`);

const reportPath = path.resolve('deliverables/taskmarket-signal-panic/validation-report.json');
const report = JSON.parse(fs.readFileSync(reportPath, 'utf8'));
report.browser_smoke = errors.length ? 'failed' : 'passed';
report.browser = {
  engine: 'chromium',
  version: browser.version(),
  viewport: '1440x960',
  runtime_network_requests: runtimeNetwork.length,
  phase_after_keyboard_switch: phaseAfterKey,
  queue_pressure_label: pressure,
  screenshot_names: ['start.png', 'running.png'],
};
report.browser_errors = errors;
fs.writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`);
await browser.close();

if (errors.length) {
  console.error(errors.join('\n'));
  process.exit(1);
}
