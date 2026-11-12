// 模块职责：统一请求适配：同源会话、超时与安全错误；写请求不自动重试。
export class ApiError extends Error {
  constructor(message, status = 0) { super(message); this.status = status }
}

export function createApi(getUser, { base = import.meta.env?.VITE_API_BASE || '', fetcher = (...args) => fetch(...args) } = {}) {
  return async function request(path, { method = 'GET', body, timeout = 180000 } = {}) {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), timeout)
    const headers = { Accept: 'application/json' }
    const user = getUser()
    if (user) headers['X-Demo-User'] = user
    const isForm = body instanceof FormData
    if (body !== undefined && !isForm) headers['Content-Type'] = 'application/json'
    try {
      const response = await fetcher(`${base.replace(/\/$/, '')}${path}`, {
        method, headers, credentials: 'same-origin', body: body === undefined ? undefined : isForm ? body : JSON.stringify(body), signal: controller.signal,
      })
      let data
      try { data = await response.json() } catch { throw new ApiError('服务未返回有效 JSON，请检查后端地址。', response.status) }
      if (!response.ok) {
        const detail = typeof data.detail === 'string' ? data.detail : Array.isArray(data.detail) ? data.detail.map(item => item.msg).join('；') : '操作未完成，请查询当前状态。'
        throw new ApiError(detail, response.status)
      }
      return data
    } catch (error) {
      if (error instanceof ApiError) throw error
      if (controller.signal.aborted) throw new ApiError('请求超时，后台可能仍在执行。请按原编号查询状态，不要重复创建或写入。')
      throw new ApiError('无法连接后端，请确认 FastAPI 已启动；如果刚才提交了操作，请先查询结果。')
    } finally { clearTimeout(timer) }
  }
}

export const pathId = value => encodeURIComponent(value.trim())
