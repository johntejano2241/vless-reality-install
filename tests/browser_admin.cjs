// Disposable CI account only. No production credentials, fixtures or profiles.
const { chromium } = require('playwright');
const crypto = require('node:crypto');
const fs = require('node:fs');

function totp() {
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000)));
  const digest = crypto.createHmac('sha1', Buffer.from('48656c6c6f21deadbeef', 'hex')).update(counter).digest();
  const offset = digest.at(-1) & 15;
  return String((digest.readUInt32BE(offset) & 0x7fffffff) % 1000000).padStart(6, '0');
}

(async () => {
  if (process.env.GITHUB_ACTIONS !== 'true') throw new Error('Use only on a disposable Actions runner');
  fs.mkdirSync('/tmp/esmi-browser-shots', { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('http://localhost:8080/admin/login');
  await page.locator('input[type=email]').fill('owner@example.test');
  await page.locator('input[type=password]').fill('Strong!Owner12345');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  const codeInput = page.locator('input[autocomplete="one-time-code"]').first();
  await codeInput.waitFor({ timeout: 20000 });
  await codeInput.fill(totp(), { force: true });
  try { await page.waitForURL(/\/admin\/?$/, { timeout: 10000 }); }
  catch {
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    await page.waitForURL(/\/admin\/?$/, { timeout: 20000 });
  }
  await page.getByText('Active VPN accounts', { exact: true }).waitFor();
  await page.screenshot({ path: '/tmp/esmi-browser-shots/dashboard.png', fullPage: true });
  await page.goto('http://localhost:8080/admin/vpn-users');
  await page.getByText('web-smoke', { exact: true }).waitFor();
  await page.screenshot({ path: '/tmp/esmi-browser-shots/vpn-users.png', fullPage: true });
  await page.goto('http://localhost:8080/admin/customers');
  await page.getByLabel('Name', { exact: true }).fill('Browser fixture customer');
  await page.getByRole('button', { name: 'Save record', exact: true }).click();
  await page.getByText('Browser fixture customer', { exact: true }).waitFor();
  if (errors.length) throw new Error('Browser errors: ' + errors.join('; '));
  await browser.close();
  process.stdout.write('Browser login, TOTP challenge, dashboard, imported VPN users and customer editing passed.\n');
})().catch(error => { process.stderr.write(error.stack + '\n'); process.exit(1); });
