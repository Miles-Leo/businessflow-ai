// Explicit read-only smoke test against a running, compiled FastAPI deployment.
import { chromium } from '@playwright/test'

const base = process.env.BUSINESSFLOW_URL || 'http://127.0.0.1:8000'
const browser = await chromium.launch({ channel: 'chrome', headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto(`${base}/app/`)
  await page.getByRole('radio', { name: /业务负责人/ }).check()
  await page.getByRole('button', { name: '进入工作空间' }).click()
  await page.getByText('服务已连接', { exact: true }).waitFor()
  await page.getByRole('button', { name: '业务查询', exact: true }).click()
  await page.getByRole('button', { name: '查询记录', exact: true }).click()
  await page.getByRole('heading', { name: '订单详情' }).waitFor()
  const text = await page.locator('.data-card').innerText()
  if (!text.includes('BF2026001') || !text.includes('待处理')) throw Error('Order data did not match the demo fixture')
  if (errors.length) throw Error(errors.join('; '))
  await page.getByRole('button', { name: '退出登录', exact: true }).click()
  await page.getByRole('heading', { name: '欢迎回来' }).waitFor()
  await page.getByRole('button', { name: '进入工作空间' }).click()
  await page.getByRole('heading', { name: '发起需求', exact: true }).waitFor()
  if (await page.getByRole('button', { name: '审核待办', exact: true }).count()) throw Error('Employee can see reviewer workspace')
  const denied = await page.evaluate(async () => (await fetch('/api/v1/approvals', { headers: { 'X-Demo-User': 'reviewer-demo-001' } })).status)
  if (denied !== 403) throw Error('Session role could be overridden by a header')
  await page.getByRole('button', { name: '退出登录', exact: true }).click()
  console.log('PASS: demo login/logout, role workspaces, signed-session precedence and actual read-only order query; no business writes.')
} finally { await browser.close() }
