// 模块职责：展示层格式化；业务时间固定 UTC+8，不依赖浏览器系统时区。
export const statusNames = {
  created: '已创建', running: '执行中', waiting_approval: '待审核', executing: '已批准 · 待执行',
  completed: '已完成', failed: '未完成', rejected: '已拒绝', pending: '待审核', approved: '已批准',
  open: '待处理', shipped: '已发货', in_progress: '处理中', closed: '已关闭', success: '已成功', unknown: '结果待核对',
}
export const eventNames = {
  task_created: '创建任务', task_started: '开始执行', task_completed: '任务完成', task_failed: '任务未完成',
  review_pending: '等待审核', review_approved: '审核通过', review_rejected: '审核拒绝', ticket_created: '正式工单已创建',
  ticket_failed: '工单执行失败', node_result: '工作流节点', tool_completed: '工具返回成功', tool_failed: '工具未成功',
}
export const stageNames = { parse: '理解需求', query: '查询信息', proposal: '生成建议', review: '提交审核', lookup_order: '订单查询', lookup_customer: '客户查询', search_policy: '政策检索', sync_ticket: '飞书同步' }
export const label = status => statusNames[status] || status || '—'
export function dateTime(value) {
  if (!value) return '—'
  // Reject ambiguous local timestamps; all API dates must carry an offset.
  if (typeof value !== 'string' || !/(Z|[+-]\d{2}:\d{2})$/i.test(value)) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  }).format(date).replaceAll('/', '-') + ' UTC+8'
}
export const shortId = value => value ? `${value.slice(0, 8)}…${value.slice(-4)}` : '—'
