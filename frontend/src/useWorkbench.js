// 模块职责：工作空间状态与操作编排；所有业务权限仍由后端校验。
import { reactive, computed } from 'vue'
import { createApi, pathId } from './api'
import { canNavigate, defaultTab, workspaceHash, tabFromHash } from './workspaces'

const EMPLOYEE = 'employee-demo-001'
const MANAGER = 'reviewer-demo-001'

export function useWorkbench() {
  const s = reactive({
    user: '', profile: null, authenticated: false, authLoading: true, loginError: '',
    tab: 'workbench', busy: false, busyLabel: '', notice: null, health: 'checking',
    question: '', taskInput: '', task: null, tasks: [], events: [], moreEvents: false,
    taskTotal: 0, taskOffset: 0, taskLimit: 20,
    approvalInput: '', review: null, execution: null, reviewReady: false,
    reviewInbox: [], reviewTotal: 0, reviewOffset: 0, reviewLimit: 10, reviewFilter: 'pending', reviewQuery: '', reviewAppliedQuery: '',
    reviewsAttempted: false, reviewsError: '', reviewUnavailable: 0,
    ticketInput: '', ticket: null, sync: null, ticketHistory: [], ticketReady: false,
    policyQuestion: '', policyResult: null, documents: [], documentsLoaded: false,
    lookupKind: 'orders', lookupId: 'BF2026001', lookupResult: null,
    modal: null,
  })
  const manager = computed(() => s.profile?.role === 'manager')
  // Browser requests use the HttpOnly session; no client-controlled identity header.
  const api = createApi(() => null)
  let workspaceVersion = 0, polling = false, pollTimer = null
  const notice = (text, type = 'info') => { s.notice = { text, type } }
  async function action(label, fn) {
    if (s.busy) return
    workspaceVersion++ // Discard a background response started before this action.
    s.busy = true; s.busyLabel = label; s.notice = null
    try { return await fn() }
    catch (error) {
      if (error.status === 401) { endSession(); s.loginError = '会话已失效，请重新登录。' }
      else notice(error.message || '操作未完成，请先查询当前状态。', 'error')
    }
    finally { s.busy = false; s.busyLabel = '' }
  }
  function remember(task, isNew = false) {
    if (isNew) { s.tasks = [task, ...s.tasks.filter(item => item.task_id !== task.task_id)].slice(0, s.taskLimit); s.taskTotal++; s.taskOffset = 0 }
    else s.tasks = s.tasks.map(item => item.task_id === task.task_id ? task : item)
  }
  async function getEvents(more = false) {
    if (!s.task) return
    const after = more ? s.events.at(-1)?.event_id || 0 : 0
    const events = await api(`/api/v1/agent/tasks/${pathId(s.task.task_id)}/events?after_id=${after}&limit=50`)
    s.events = more ? [...s.events, ...events] : events
    s.moreEvents = events.length === 50
  }
  async function fetchTask(id) {
    let task = await api(`/api/v1/agent/tasks/${pathId(id)}`)
    if (needsReviewSync(task)) task = await api(`/api/v1/agent/tasks/${pathId(id)}/refresh`, { method: 'POST' })
    s.task = task; s.taskInput = task.task_id; remember(task)
    s.events = []; s.moreEvents = false
    await getEvents()
    return task
  }
  function loadTask(id = s.taskInput) {
    if (!id?.trim()) return notice('请填写任务编号。', 'error')
    return action('读取任务', () => { s.task = null; s.events = []; return fetchTask(id) })
  }
  async function runSelected() {
    if (!s.task) return
    s.task = await api(`/api/v1/agent/tasks/${pathId(s.task.task_id)}/run`, { method: 'POST' })
    remember(s.task); await getEvents()
    if (s.task.error) notice(s.task.error, 'error')
  }
  function submitTask() {
    const question = s.question.trim()
    if (!question || question.length > 2000) return notice('请输入 1～2000 字的业务需求。', 'error')
    return action('正在理解需求并执行', async () => {
      const task = await api('/api/v1/agent/tasks', { method: 'POST', body: { user_input: question } })
      s.task = task; s.taskInput = task.task_id; s.question = ''; s.events = []; remember(task, true)
      await runSelected()
      await readHistory()
    })
  }
  function taskOperation(operation) {
    if (!s.task) return
    return action('更新任务状态', async () => {
      s.task = await api(`/api/v1/agent/tasks/${pathId(s.task.task_id)}/${operation}`, { method: 'POST' })
      remember(s.task); await getEvents()
      if (s.task.error) notice(s.task.error, 'error')
    })
  }
  async function readHistory() {
    const version = workspaceVersion
    const result = await api(`/api/v1/agent/tasks?offset=${s.taskOffset}&limit=${s.taskLimit}`)
    const tasks = await synchronizeSnapshots(result.items)
    if (version !== workspaceVersion || !s.authenticated || manager.value) return
    s.tasks = tasks; s.taskTotal = result.total
    const selected = tasks.find(task => task.task_id === s.task?.task_id)
    if (selected) s.task = selected
  }
  const needsReviewSync = task => task?.approval_id && ['waiting_approval', 'executing', 'failed'].includes(task.status)
  async function synchronizeSnapshots(tasks) {
    // The SQLite review runtime has one lock: parallel refreshes can starve later tasks.
    const synchronized = []
    for (const task of tasks) {
      if (!needsReviewSync(task)) { synchronized.push(task); continue }
      try { synchronized.push(await api(`/api/v1/agent/tasks/${pathId(task.task_id)}/refresh`, { method: 'POST', timeout: 10000 })) }
      catch (error) {
        if (error.status === 401) throw error
        // A busy checkpoint or temporary outage must not erase the last known state.
        synchronized.push(task)
      }
    }
    return synchronized
  }
  async function pollTaskProgress() {
    if (polling || s.busy || !s.authenticated || manager.value || document.hidden || !['workbench', 'history'].includes(s.tab)) return
    if (![s.task, ...s.tasks].some(needsReviewSync)) return
    polling = true
    const version = workspaceVersion
    try {
      const selectedId = s.task?.task_id
      const oldStatus = s.task?.status
      const candidates = s.task && !s.tasks.some(t => t.task_id === selectedId) ? [...s.tasks, s.task] : s.tasks
      const updated = await synchronizeSnapshots(candidates)
      if (version !== workspaceVersion || !s.authenticated || s.busy) return
      const byId = new Map(updated.map(task => [task.task_id, task]))
      s.tasks = s.tasks.map(task => byId.get(task.task_id) || task)
      if (selectedId && byId.has(selectedId)) {
        s.task = byId.get(selectedId)
        if (s.task.status !== oldStatus) await getEvents()
      }
    } catch (error) {
      if (version === workspaceVersion && error.status === 401) { endSession(); s.loginError = '会话已失效，请重新登录。' }
    } finally { polling = false }
  }
  function startTaskPolling() {
    if (pollTimer) return
    pollTimer = window.setInterval(pollTaskProgress, 5000)
    window.addEventListener('focus', pollTaskProgress)
    document.addEventListener('visibilitychange', pollTaskProgress)
  }
  function stopTaskPolling() {
    window.clearInterval(pollTimer); pollTimer = null
    window.removeEventListener('focus', pollTaskProgress)
    document.removeEventListener('visibilitychange', pollTaskProgress)
  }
  function refreshHistory() { return action('读取我的任务', readHistory) }
  function taskPage(direction) {
    if (s.busy) return
    s.taskOffset = Math.max(0, s.taskOffset + direction * s.taskLimit)
    return refreshHistory()
  }
  function clearWorkspace() {
    workspaceVersion++
    Object.assign(s, { task: null, tasks: [], taskInput: '', events: [], moreEvents: false,
      taskTotal: 0, taskOffset: 0,
      question: '', policyQuestion: '', review: null, execution: null, reviewReady: false, approvalInput: '', ticket: null, sync: null, ticketHistory: [], ticketInput: '', ticketReady: false,
      policyResult: null, lookupResult: null, modal: null, notice: null, documents: [], documentsLoaded: false })
    Object.assign(s, { reviewInbox: [], reviewTotal: 0, reviewOffset: 0, reviewFilter: 'pending', reviewQuery: '', reviewAppliedQuery: '',
      reviewsAttempted: false, reviewsError: '', reviewUnavailable: 0 })
  }
  function readRoute() {
    if (!s.authenticated) { if (location.hash !== '#/login') history.replaceState(null, '', '#/login'); return }
    s.tab = tabFromHash(s.profile.role, location.hash)
    const expected = workspaceHash(s.profile.role, s.tab)
    if (location.hash !== expected) history.replaceState(null, '', expected)
  }
  function navigate(tab) {
    if (!s.authenticated || !canNavigate(s.profile.role, tab)) return
    s.tab = tab; location.hash = workspaceHash(s.profile.role, tab)
  }
  function acceptSession(profile) {
    if (![EMPLOYEE, MANAGER].includes(profile.user_id) || !['employee', 'manager'].includes(profile.role)) throw new Error('登录信息无效，请重新登录。')
    clearWorkspace(); s.profile = profile; s.user = profile.user_id; s.authenticated = true
    s.tab = defaultTab(profile.role); readRoute()
  }
  function endSession() {
    clearWorkspace(); s.profile = null; s.user = ''; s.authenticated = false
    history.replaceState(null, '', '#/login')
  }
  async function bootstrap() {
    try {
      acceptSession(await api('/api/v1/auth/me', { timeout: 10000 }))
    } catch (error) { endSession(); if (error.status !== 401) s.loginError = error.message }
    finally { s.authLoading = false }
    if (s.authenticated) { health(); if (!manager.value) await refreshHistory() }
  }
  async function login(user) {
    if (s.busy || ![EMPLOYEE, MANAGER].includes(user)) return
    s.busy = true; s.loginError = ''
    try {
      acceptSession(await api('/api/v1/auth/login', { method: 'POST', body: { user_id: user } }))
      navigate(defaultTab(s.profile.role))
    } catch (error) { endSession(); s.loginError = error.message }
    finally { s.busy = false }
    if (s.authenticated) { health(); if (!manager.value) await refreshHistory() }
  }
  function logout() {
    return action('退出登录', async () => { await api('/api/v1/auth/logout', { method: 'POST' }); endSession(); s.loginError = '' })
  }
  async function fetchReviews() {
    s.reviewsAttempted = true; s.reviewsError = ''
    const query = new URLSearchParams({ status: s.reviewFilter, offset: String(s.reviewOffset), limit: String(s.reviewLimit), query: s.reviewAppliedQuery })
    try {
      const result = await api(`/api/v1/approvals?${query}`)
      s.reviewInbox = result.items; s.reviewTotal = result.total; s.reviewUnavailable = result.unavailable_count || 0
    } catch (error) {
      s.reviewInbox = []; s.reviewsError = error.message
      throw error
    }
  }
  function loadReviews(reset = false) {
    if (!manager.value || s.busy) return
    if (reset) { s.reviewOffset = 0; s.reviewAppliedQuery = s.reviewQuery.trim() }
    return action('读取审核收件箱', fetchReviews)
  }
  function reviewPage(direction) {
    if (s.busy) return
    s.reviewOffset = Math.max(0, s.reviewOffset + direction * s.reviewLimit)
    return loadReviews()
  }
  function selectReview(id) { s.approvalInput = id; return loadReview() }
  async function fetchReview(id) {
    s.reviewReady = false
    const review = await api(`/api/v1/approvals/${pathId(id)}`)
    s.review = review
    try { s.execution = await api(`/api/v1/approvals/${pathId(id)}/execution`) }
    catch (error) { if (error.status !== 404) throw error; s.execution = null }
    s.reviewReady = true
  }
  function loadReview() {
    if (!manager.value || !s.approvalInput.trim()) return notice('请使用负责人身份并填写审核编号。', 'error')
    return action('读取待审核建议', async () => {
      s.review = null; s.execution = null
      await fetchReview(s.approvalInput.trim())
    })
  }
  function confirm(title, description, button, callback, danger = false) {
    if (!s.busy) s.modal = { title, description, button, callback, danger }
  }
  function confirmNow() {
    const callback = s.modal?.callback
    s.modal = null
    return callback?.()
  }
  function decide(decision) {
    if (!manager.value || s.review?.proposal.approval_status !== 'pending') return
    const id = s.review.approval_id
    const approved = decision === 'approved'
    confirm(approved ? '批准这份建议？' : '拒绝这份建议？',
      `订单 ${s.review.proposal.order_id}。${approved ? '批准后仍需单独执行，当前不会创建正式工单。' : '拒绝后将阻止该建议创建正式工单。'}`,
      approved ? '确认批准' : '确认拒绝',
      () => action('保存审核决定', async () => {
        await api(`/api/v1/approvals/${pathId(id)}/decision`, { method: 'POST', body: { decision } })
        await fetchReview(id)
        s.reviewOffset = 0
        await fetchReviews()
        notice(approved ? '建议已批准，正式工单尚需单独执行。' : '建议已拒绝，未创建正式工单。', 'success')
      }), !approved)
  }
  function execute() {
    if (!manager.value || !s.reviewReady || s.review?.proposal.approval_status !== 'approved') return
    const id = s.review.approval_id
    confirm('创建正式工单？', `将执行订单 ${s.review.proposal.order_id} 已批准的建议。后端会重新检查当前订单条件，并保护重复执行。`, '确认执行',
      () => action('创建正式工单', async () => {
        const result = await api(`/api/v1/approvals/${pathId(id)}/execute`, { method: 'POST' })
        s.ticketInput = result.ticket.ticket_id; s.ticket = result.ticket; s.sync = null
        await fetchReview(id)
        notice(result.reused ? '已复用原正式工单，没有重复创建。' : '正式工单已创建。请由任务创建者刷新任务结果。', 'success')
      }))
  }
  async function fetchTicket(id) {
    s.ticketReady = false
    s.ticket = await api(`/api/v1/tickets/${pathId(id)}`)
    s.ticketHistory = await api(`/api/v1/tickets/${pathId(id)}/status-history`)
    try { s.sync = await api(`/api/v1/tickets/${pathId(id)}/feishu-sync`) }
    catch (error) { if (error.status !== 404) throw error; s.sync = null }
    s.ticketReady = true
  }
  function loadTicket() {
    if (!manager.value || !s.ticketInput.trim()) return notice('请使用负责人身份并填写正式工单编号。', 'error')
    return action('读取正式工单', async () => {
      const id = s.ticketInput.trim(); s.ticket = null; s.sync = null; s.ticketHistory = []
      await fetchTicket(id)
    })
  }
  function changeStatus(status) {
    if (!manager.value || !s.ticketReady || !s.ticket) return
    const id = s.ticket.ticket_id
    confirm('更新工单状态？', `工单 ${id} 将更新为${status === 'closed' ? '已关闭' : '处理中'}。这一步只更新本地工单，飞书需要单独同步。`, '确认更新',
      () => action('更新工单', async () => {
        await api(`/api/v1/tickets/${pathId(id)}/status`, { method: 'PATCH', body: { status } })
        await fetchTicket(id); notice('本地状态已更新。', 'success')
      }))
  }
  function syncTicket(reconcile = false) {
    if (!manager.value || !s.ticketReady || !s.ticket) return
    const id = s.ticket.ticket_id
    const fn = () => action(reconcile ? '核对飞书记录' : '同步飞书记录', async () => {
      try {
        s.sync = await api(`/api/v1/tickets/${pathId(id)}/feishu-sync${reconcile ? '/reconcile' : ''}`, { method: 'POST' })
        notice(reconcile ? '核对成功，已记录远端结果。' : '飞书同步成功。', 'success')
      } catch (error) {
        // Only read after an uncertain write. Never retry a POST automatically.
        try { s.sync = await api(`/api/v1/tickets/${pathId(id)}/feishu-sync`) } catch { /* Keep original error. */ }
        throw error
      }
    })
    if (reconcile) return fn()
    confirm('同步到飞书？', `将把正式工单 ${id} 的内容写入配置的飞书测试表，或更新已有记录的状态。`, '确认同步', fn)
  }
  function askPolicy() {
    const question = s.policyQuestion.trim()
    if (!question || question.length > 2000) return notice('请输入 1～2000 字的政策问题。', 'error')
    return action('检索企业政策', async () => {
      s.policyResult = null
      s.policyResult = await api('/api/v1/knowledge/query', { method: 'POST', body: { question, top_k: 5 } })
    })
  }
  function listDocuments() {
    if (!manager.value) return
    return action('读取文档目录', async () => { s.documents = await api('/api/v1/knowledge/documents'); s.documentsLoaded = true })
  }
  function upload(file) {
    if (!manager.value || !file) return
    if (!/\.(md|pdf)$/i.test(file.name) || file.size > 5 * 1024 * 1024 || file.size === 0) return notice('请选择非空的 Markdown 或 PDF，最大 5MB。', 'error')
    const form = new FormData(); form.append('file', file)
    confirm('导入企业知识文档？', `文档 ${file.name} 将发送给后端进行向量化。同名文档将切换为新版本。`, '确认导入',
      () => action('导入知识文档', async () => {
        const result = await api('/api/v1/knowledge/documents', { method: 'POST', body: form })
        s.documents = await api('/api/v1/knowledge/documents'); s.documentsLoaded = true
        notice(result.reused ? '内容未变化，已复用原版本。' : `导入完成，共 ${result.chunk_count} 个片段。`, 'success')
      }))
  }
  function lookup() {
    if (!s.lookupId.trim()) return notice('请填写查询编号。', 'error')
    return action('查询业务数据', async () => {
      s.lookupResult = null
      s.lookupResult = await api(`/api/v1/${s.lookupKind}/${pathId(s.lookupId)}`)
    })
  }
  async function health() {
    s.health = 'checking'
    try { const result = await api('/health', { timeout: 5000 }); s.health = result.status === 'ok' ? 'online' : 'offline' }
    catch { s.health = 'offline' }
  }
  async function copy(value) {
    try { await navigator.clipboard.writeText(value); notice('编号已复制。', 'success') }
    catch { notice('无法访问剪贴板，请选中编号手动复制。') }
  }
  return { state: s, manager, action, notice, health, refreshHistory, taskPage, bootstrap, login, logout, navigate, readRoute, submitTask, loadTask,
    startTaskPolling, stopTaskPolling,
    runTask: () => action('执行任务', runSelected), taskOperation, loadMoreEvents: () => action('读取更多事件', () => getEvents(true)),
    decide, execute, loadReview, loadReviews, reviewPage, selectReview, loadTicket, changeStatus, syncTicket, askPolicy, listDocuments, upload, lookup,
    confirm, confirmNow, copy }
}
