import { test, expect } from '@playwright/test'

const taskId = '23e7a10b-3435-45ca-aae4-897ced0e5a57'
const ticketId = 'TK-demo-ticket'
const baseTask = { task_id: taskId, user_id: 'employee-demo-001', user_input: '为订单 BF2026001 生成待审核建议', status: 'created', approval_id: null, ticket_id: null, error: null, answer: null, created_at: '2026-11-09T08:00:00Z', updated_at: '2026-11-09T08:00:00Z' }
const querySummary = '订单查询结果\n订单编号：BF2026001\n订单状态：pending\n承诺发货时间：2026-10-02 16:00:00 UTC+8\n实际发货时间：尚未发货\n超期未发货判定：是\n政策依据：AS-04、AS-05｜knowledge/after_sales_policy.md'

test('structured facts render independently of the legacy answer', async ({ page }) => {
  const state = await mockBackend(page)
  state.taskCreated = true
  Object.assign(state.task, { status:'completed', answer:'旧的通用文本', result:{
    query_result:{order_id:'BF2026001',status:'shipped',created_at:'2026-10-01T08:00:00Z',promised_ship_at:'2026-10-02T08:00:00Z',shipped_at:'2026-10-01T09:00:00Z'},
    assessment:{checked_at:'2026-11-09T08:00:00Z',is_overdue_unshipped:false},policy_sources:[],proposal:null,execution_result:null,
  } })
  await enter(page)
  await page.locator('.task-row').click()
  const result = page.locator('[data-structured-result]')
  await expect(result).toContainText('shipped')
  await expect(result).toContainText('本次未生成待审核建议')
  await expect(result).toContainText('2026-10-02 16:00:00 UTC+8')
  await expect(page.locator('.result-card')).not.toContainText('旧的通用文本')
})

async function mockBackend(page, { failed = false, malicious = false, unknownSync = false } = {}) {
  const state = { profile: null, taskCreated: false, task: { ...baseTask }, decision: 'pending', executed: false, synced: false, uncertain: false, calls: [] }
  await page.route('**/health', route => route.fulfill({ json: { status: 'ok' } }))
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), url = new URL(request.url()), method = request.method(), path = url.pathname
    const user = state.profile?.user_id
    state.calls.push({ method, path, user })
    const reply = (data, status = 200) => route.fulfill({ status, json: data })
    if (path === '/api/v1/auth/me') return state.profile ? reply(state.profile) : reply({ detail: '请先登录' }, 401)
    if (path === '/api/v1/auth/login') {
      const id = request.postDataJSON().user_id
      state.profile = { user_id: id, role: id === 'reviewer-demo-001' ? 'manager' : 'employee', display_name: id === 'reviewer-demo-001' ? '演示负责人' : '演示员工' }
      return reply(state.profile)
    }
    if (path === '/api/v1/auth/logout') { state.profile = null; return reply({ message: '已退出' }) }
    if (!user) return reply({ detail: '缺少演示身份' }, 401)
    if ((path === '/api/v1/approvals' || path.includes('/approvals/') || path.includes('/tickets/') || path === '/api/v1/knowledge/documents') && user !== 'reviewer-demo-001') return reply({ detail: '仅负责人可以操作' }, 403)
    if (path === '/api/v1/approvals') {
      const status = url.searchParams.get('status') || 'pending'
      const needle = url.searchParams.get('query') || ''
      const items = (status === 'all' || status === state.decision) && (!needle || taskId.includes(needle) || 'BF2026001'.includes(needle)) ? [{
        approval_id: taskId, order_id: 'BF2026001', issue_type: 'shipping_delay', description: '超期未发货，建议核查发货原因。',
        approval_status: state.decision, submitted_at: '2026-11-09T08:00:00Z', updated_at: '2026-11-09T08:00:00Z',
      }] : []
      return reply({ items, total: items.length, offset: 0, limit: 10, unavailable_count: 0 })
    }
    if (path === '/api/v1/agent/tasks' && method === 'POST') { state.taskCreated = true; state.task.user_input = request.postDataJSON().user_input; return reply(state.task, 201) }
    if (path === '/api/v1/agent/tasks' && method === 'GET') {
      const items = state.taskCreated && user === 'employee-demo-001' ? [state.task] : []
      return reply({ items, total: items.length, offset: 0, limit: 20 })
    }
    if (path.startsWith(`/api/v1/agent/tasks/${taskId}`)) {
      if (user !== 'employee-demo-001') return reply({ detail: '任务不存在或无权访问' }, 404)
      if (path.endsWith('/run')) {
        Object.assign(state.task, failed ? { status: 'failed', error: '当前不支持该操作，不能绕过审核' } : malicious ? { status: 'completed', answer: '<img src=x onerror=alert(1)>' } : { status: 'waiting_approval', approval_id: taskId, answer: querySummary + '\n\n处理进度：\n建议已提交，等待负责人审核；尚未创建正式工单。' })
        return reply(state.task)
      }
      if (path.endsWith('/refresh')) {
        const summary = state.task.answer?.startsWith('订单查询结果') ? state.task.answer.split('\n\n处理进度：\n')[0] : null
        if (state.executed) Object.assign(state.task, { status: 'completed', ticket_id: ticketId, answer: '正式工单已创建' })
        else if (state.decision === 'approved') Object.assign(state.task, { status: 'executing', answer: '建议已批准，等待创建正式工单。' })
        else if (state.decision === 'rejected') Object.assign(state.task, { status: 'rejected', answer: '负责人已拒绝建议。' })
        if (summary) state.task.answer = summary + '\n\n处理进度：\n' + state.task.answer.split('\n\n处理进度：\n').at(-1)
        return reply(state.task)
      }
      if (path.endsWith('/events')) {
        const kinds = state.task.status === 'created' ? ['task_created'] : ['task_created', 'task_started', failed ? 'task_failed' : malicious ? 'task_completed' : 'review_pending']
        if (state.task.ticket_id) kinds.push('review_approved', 'ticket_created')
        return reply(kinds.map((kind, index) => ({ event_id: index + 1, task_id: taskId, event_type: kind, status: state.task.status, message: '后端事件记录', created_at: '2026-11-09T08:00:00Z' })))
      }
      return reply(state.task)
    }
    if (path === `/api/v1/approvals/${taskId}/decision`) { state.decision = request.postDataJSON().decision; return reply({ approval_id: taskId, approval_status: state.decision, reviewer_id: user, reviewed_at: '2026-11-09T08:01:00Z' }) }
    const ticket = () => ({ ticket_id: ticketId, approval_id: taskId, order_id: 'BF2026001', issue_type: 'shipping_delay', description: '超期未发货，建议核查', status: 'open', created_at: '2026-11-09T08:02:00Z', reviewer_id: 'reviewer-demo-001', executed_by: 'reviewer-demo-001', reviewed_at: '2026-11-09T08:01:00Z', policy_sources: [] })
    if (path === `/api/v1/approvals/${taskId}/execute`) { if (state.decision !== 'approved') return reply({ detail: '尚未批准' }, 409); state.executed = true; return reply({ ticket: ticket(), reused: false }) }
    if (path === `/api/v1/approvals/${taskId}/execution`) return state.executed ? reply({ status: 'success', ticket_id: ticketId }) : reply({ detail: '未找到执行记录' }, 404)
    if (path === `/api/v1/approvals/${taskId}`) return reply({ approval_id: taskId, proposal: { order_id: 'BF2026001', issue_type: 'shipping_delay', description: '超期未发货，建议核查发货原因。', approval_status: state.decision, checked_at: '2026-11-09T08:00:00Z', policy_sources: [{ document_title: '虚构售后政策', section: 'AS-04：处理建议', source: 'knowledge/policy.md', chunk_id: 'demo:4' }] }, reviewer_id: state.decision === 'pending' ? null : 'reviewer-demo-001', reviewed_at: state.decision === 'pending' ? null : '2026-11-09T08:01:00Z' })
    if (path === `/api/v1/tickets/${ticketId}`) return reply(ticket())
    if (path.endsWith('/status-history')) return reply([])
    if (path.endsWith('/feishu-sync/reconcile')) { state.uncertain = false; state.synced = true; return reply({ status: 'success', record_id: 'rec-demo', attempts: 1 }) }
    if (path.endsWith('/feishu-sync')) {
      if (method === 'POST') { state.synced = true; state.uncertain = unknownSync; if (unknownSync) return reply({ detail: '同步未确认成功，请查看同步状态' }, 503) }
      if (!state.synced) return reply({ detail: '尚无同步记录' }, 404)
      return reply({ status: state.uncertain ? 'unknown' : 'success', record_id: state.uncertain ? null : 'rec-demo', attempts: 1, updated_at: '2026-11-09T08:03:00Z', error: state.uncertain ? '远端结果未知，禁止直接重发' : null })
    }
    if (path === '/api/v1/knowledge/query') return reply({ answer: '负责人拒绝时禁止创建正式工单。[1]', sources: [{ citation_id: 1, document_title: '虚构售后政策', section: 'AS-05', source: 'knowledge/policy.md' }] })
    if (path === '/api/v1/knowledge/documents') return method === 'POST' ? reply({ reused: false, chunk_count: 8 }, 201) : reply([{ source: 'knowledge/policy.md', collection: 'test-version' }])
    if (path.startsWith('/api/v1/orders/')) return reply({ order_id: 'BF2026001', customer_id: 'CUST-DEMO-001', status: 'pending', created_at: '2026-10-01T08:00:00Z', promised_ship_at: '2026-10-02T08:00:00Z', shipped_at: null })
    return reply({ detail: '未找到测试记录' }, 404)
  })
  return state
}


async function enter(page, role = 'employee') {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '欢迎回来' })).toBeVisible()
  if (role === 'manager') await page.getByRole('radio', { name: /业务负责人/ }).check()
  await page.getByRole('button', { name: '进入工作空间', exact: true }).click()
  await expect(page.getByRole('button', { name: '退出登录', exact: true })).toBeVisible()
}

async function leave(page) {
  await page.getByRole('button', { name: '退出登录', exact: true }).click()
  await expect(page.getByRole('heading', { name: '欢迎回来' })).toBeVisible()
}

test('separate login and minimal employee workspace', async ({ page }) => {
  const state = await mockBackend(page)
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '欢迎回来' })).toBeVisible()
  await expect(page.getByRole('navigation')).toHaveCount(0)
  await page.screenshot({ path: 'test-results/login-desktop.png', fullPage: true })
  await page.getByRole('button', { name: '进入工作空间' }).click()
  await expect(page.getByRole('heading', { name: '你需要处理什么业务？' })).toBeVisible()
  await expect(page.getByRole('button', { name: '提交需求', exact: true })).toBeDisabled()
  await expect(page.getByRole('navigation').getByRole('button')).toHaveCount(3)
  await expect(page.getByRole('button', { name: '审核待办', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '工单处理', exact: true })).toHaveCount(0)
  await expect(page.getByLabel('演示身份')).toHaveCount(0)
  expect(state.calls.some(call => call.path.startsWith('/api/v1/approvals'))).toBeFalsy()
  await page.screenshot({ path: 'test-results/workbench-desktop.png', fullPage: true })
})

test('employee submission → separate manager login → review → execution → owner progress', async ({ page }) => {
  const state = await mockBackend(page)
  await enter(page)
  await page.getByLabel('业务需求').fill('为订单 BF2026001 生成待审核建议')
  await page.getByRole('button', { name: '提交需求', exact: true }).click()
  await expect(page.locator('.result-card').getByText('待审核', { exact: true })).toBeVisible()
  expect(state.calls.filter(call => call.method === 'POST' && call.path.startsWith('/api/v1/agent/tasks') && !call.path.endsWith('/refresh'))).toHaveLength(2)
  await expect(page.getByRole('button', { name: /切换负责人/ })).toHaveCount(0)
  await leave(page)
  await enter(page, 'manager')
  await page.getByRole('button', { name: `查看建议 ${taskId}`, exact: true }).click()
  await page.getByRole('button', { name: '批准建议', exact: true }).click()
  expect(state.decision).toBe('pending')
  await page.getByRole('dialog').getByRole('button', { name: '确认批准' }).click()
  await expect(page.getByRole('button', { name: '执行已批准建议' })).toBeEnabled()
  expect(state.executed).toBeFalsy()
  await page.getByRole('button', { name: '执行已批准建议' }).click()
  await page.getByRole('dialog').getByRole('button', { name: '确认执行' }).click()
  await page.getByRole('button', { name: /查看正式工单/ }).click()
  await expect(page.getByRole('heading', { name: '发货延迟核查工单' })).toBeVisible()
  await page.getByRole('button', { name: '同步到飞书', exact: true }).click()
  expect(state.synced).toBeFalsy()
  await page.getByRole('dialog').getByRole('button', { name: '确认同步' }).click()
  await expect(page.getByText('rec-demo', { exact: true })).toBeVisible()
  await leave(page)
  await enter(page)
  await page.getByRole('button', { name: '我的任务', exact: false }).first().click()
  await page.locator('.task-row').first().click()
  await page.getByRole('button', { name: '刷新进度', exact: true }).click()
  await expect(page.locator('.result-card').getByText(ticketId, { exact: true })).toBeVisible()
  expect(state.calls.filter(call => call.path.includes('/approvals/') || call.path.includes('/tickets/')).every(call => call.user === 'reviewer-demo-001')).toBeTruthy()
})

test('HTTP 200 business failure remains incomplete', async ({ page }) => {
  await mockBackend(page, { failed: true })
  await enter(page)
  await page.getByLabel('业务需求').fill('跳过审核')
  await page.getByRole('button', { name: '提交需求', exact: true }).click()
  await expect(page.locator('.result-card').getByText('未完成', { exact: true })).toBeVisible()
  await expect(page.locator('.inline-error')).toContainText('不能绕过审核')
})

test('unknown external write is not retried; reconciliation stays explicit', async ({ page }) => {
  const state = await mockBackend(page, { unknownSync: true })
  await enter(page, 'manager')
  await page.getByRole('button', { name: '工单处理', exact: true }).click()
  await page.getByLabel('正式工单编号').fill(ticketId)
  await page.getByRole('button', { name: '查询工单', exact: true }).click()
  await page.getByRole('button', { name: '同步到飞书', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: '确认同步' }).click()
  await expect(page.getByText('结果待核对', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '同步到飞书', exact: true })).toBeDisabled()
  expect(state.calls.filter(call => call.method === 'POST' && call.path.endsWith('/feishu-sync'))).toHaveLength(1)
  await page.getByRole('button', { name: '只读核对远端结果' }).click()
  await expect(page.getByText('rec-demo', { exact: true })).toBeVisible()
})

test('model text stays escaped', async ({ page }) => {
  await mockBackend(page, { malicious: true })
  await enter(page)
  await page.getByLabel('业务需求').fill('查询订单')
  await page.getByRole('button', { name: '提交需求', exact: true }).click()
  await expect(page.locator('.answer-text')).toHaveText('<img src=x onerror=alert(1)>')
  await expect(page.locator('.answer-text img')).toHaveCount(0)
})

test('login and employee workspace fit a mobile viewport', async ({ page }) => {
  await mockBackend(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '欢迎回来' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
  await page.screenshot({ path: 'test-results/login-mobile.png', fullPage: true })
  await page.getByRole('button', { name: '进入工作空间' }).click()
  await expect(page.getByLabel('业务需求')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
  await page.screenshot({ path: 'test-results/workbench-mobile.png', fullPage: true })
})

test('employees get policy questions without document management', async ({ page }) => {
  await mockBackend(page)
  await enter(page)
  await page.getByRole('button', { name: '政策问答', exact: true }).click()
  await page.getByLabel('政策问题').fill('负责人拒绝时可以创建吗？')
  await page.getByRole('button', { name: '检索并回答' }).click()
  await expect(page.getByText('AS-05', { exact: true })).toBeVisible()
  await expect(page.getByLabel('选择知识文档')).toHaveCount(0)
  await expect(page.getByText('负责人管理', { exact: true })).toHaveCount(0)
})

test('managers have knowledge upload with explicit confirmation', async ({ page }) => {
  const state = await mockBackend(page)
  await enter(page, 'manager')
  await page.getByRole('button', { name: '知识管理', exact: true }).click()
  await page.getByLabel('选择知识文档').setInputFiles({ name: 'policy.md', mimeType: 'text/markdown', buffer: Buffer.from('# Policy\nDemo') })
  expect(state.calls.filter(call => call.method === 'POST' && call.path.endsWith('/documents'))).toHaveLength(0)
  await page.getByRole('dialog').getByRole('button', { name: '确认导入' }).click()
  await expect(page.getByText('导入完成，共 8 个片段。')).toBeVisible()
})

test('manager login opens the inbox rather than the employee workspace', async ({ page }) => {
  const state = await mockBackend(page)
  await enter(page, 'manager')
  await expect(page.locator('.inbox-table tbody tr')).toHaveCount(1)
  await expect(page.getByRole('heading', { name: '审核待办', exact: true })).toBeVisible()
  await expect(page.getByLabel('业务需求')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '我的任务', exact: true })).toHaveCount(0)
  await page.screenshot({ path: 'test-results/approval-inbox.png', fullPage: true })
  await page.getByRole('button', { name: `查看建议 ${taskId}`, exact: true }).click()
  await page.getByRole('button', { name: '批准建议', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: '确认批准' }).click()
  await expect(page.getByText('当前没有待审核建议', { exact: true })).toBeVisible()
  expect(state.decision).toBe('approved')
  await page.getByLabel('审核状态').selectOption('approved')
  await expect(page.locator('.inbox-table tbody tr')).toHaveCount(1)
})

test('inbox errors do not create automatic retry loops', async ({ page }) => {
  await mockBackend(page)
  let attempts = 0
  await page.route('**/api/v1/approvals?*', route => {
    attempts++
    return attempts === 1 ? route.fulfill({ status: 503, json: { detail: '审核列表暂不可用' } }) : route.fallback()
  })
  await enter(page, 'manager')
  await expect(page.getByText('暂时无法读取审核列表', { exact: true })).toBeVisible()
  expect(attempts).toBe(1)
  await page.getByRole('button', { name: '重新加载列表' }).click()
  await expect(page.locator('.inbox-table tbody tr')).toHaveCount(1)
  expect(attempts).toBe(2)
})

test('session restoration ignores old role storage and rejects forged manager routes', async ({ page }) => {
  const state = await mockBackend(page)
  await enter(page)
  await page.getByLabel('业务需求').fill('查询订单')
  await page.getByRole('button', { name: '提交需求', exact: true }).click()
  await expect(page.locator('.result-card')).toBeVisible()
  await page.evaluate(() => { sessionStorage.setItem('bf-role', JSON.stringify('reviewer-demo-001')); location.hash = '#/manager/approvals' })
  await expect(page).toHaveURL(/#\/employee\/workbench$/)
  expect(state.calls.some(call => call.path === '/api/v1/approvals')).toBeFalsy()
  await page.reload()
  await expect(page.getByRole('button', { name: '我的任务', exact: false })).toBeVisible()
  await expect(page.locator('.task-row')).toHaveCount(1)
  await leave(page)
  await expect(page.locator('.result-card')).toHaveCount(0)
  await expect(page.getByRole('navigation')).toHaveCount(0)
})

test('expired sessions return to login without keeping private task state', async ({ page }) => {
  const state = await mockBackend(page)
  await enter(page)
  state.profile = null
  await page.getByRole('button', { name: '我的任务', exact: false }).click()
  await page.getByRole('button', { name: '更新', exact: true }).click()
  await expect(page.getByRole('heading', { name: '欢迎回来' })).toBeVisible()
  await expect(page.getByRole('alert')).toContainText('会话已失效')
})

test('employee progress automatically follows approval then ticket creation without a manual refresh', async ({ page }) => {
  const state = await mockBackend(page)
  state.taskCreated = true
  Object.assign(state.task, { status: 'waiting_approval', approval_id: taskId })
  await page.clock.install()
  await enter(page)
  await page.locator('.task-row').click()
  await expect(page.locator('.result-card').getByText('待审核', { exact: true })).toBeVisible()
  state.decision = 'approved'
  await page.clock.runFor(5100)
  await expect(page.locator('.result-card').getByText('已批准 · 待执行', { exact: true })).toBeVisible()
  await expect(page.locator('.ticket-result-label')).toHaveCount(0)
  state.executed = true
  await page.clock.runFor(5100)
  await expect(page.locator('.ticket-result-label')).toContainText(ticketId)
  await expect(page.locator('.result-card').getByText('已完成', { exact: true })).toBeVisible()
  await expect(page.locator('.timeline')).toContainText('正式工单已创建')
  const polls = state.calls.filter(c => c.path.endsWith('/refresh')).length
  await page.clock.runFor(11000)
  expect(state.calls.filter(c => c.path.endsWith('/refresh'))).toHaveLength(polls)
  expect(state.calls.some(c => c.path.startsWith('/api/v1/approvals'))).toBeFalsy()
})

test('conditional proposal displays queried facts and sources rather than a generic pending message', async ({ page }) => {
  const state = await mockBackend(page)
  await enter(page)
  await page.getByLabel('业务需求').fill('查询订单 BF2026001，如果超期未发货，请根据政策生成待审核工单建议。')
  await page.getByRole('button', { name: '提交需求', exact: true }).click()
  const answer = page.locator('.result-card .answer-text')
  await expect(answer).toContainText('订单状态：pending')
  await expect(answer).toContainText('尚未发货')
  await expect(answer).toContainText('超期未发货判定：是')
  await expect(answer).toContainText('AS-04、AS-05')
  await expect(answer).toContainText('等待负责人审核')
  state.decision = 'approved'; state.executed = true
  await page.getByRole('button', { name: '刷新进度', exact: true }).click()
  await expect(answer).toContainText('订单状态：pending')
  await expect(answer).toContainText('正式工单已创建')
  await expect(answer).not.toContainText('等待负责人审核')
})

test('reopening employee workspace reconciles stale saved tasks; rejection updates automatically', async ({ page }) => {
  const state = await mockBackend(page)
  state.taskCreated = true
  Object.assign(state.task, { status: 'waiting_approval', approval_id: taskId })
  await page.clock.install()
  await enter(page)
  await page.locator('.task-row').click()
  state.decision = 'rejected'
  await page.clock.runFor(5100)
  await expect(page.locator('.result-card').getByText('已拒绝', { exact: true })).toBeVisible()
  state.decision = 'approved'; state.executed = true
  Object.assign(state.task, { status: 'waiting_approval', ticket_id: null })
  await page.reload()
  await expect(page.locator('.task-row')).toContainText('已完成')
})
