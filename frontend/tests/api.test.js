import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createApi, ApiError, pathId } from '../src/api.js'

test('adds the selected demo identity and serializes JSON', async () => {
  let actual
  const api = createApi(() => 'employee-demo-001', { fetcher: async (...args) => { actual = args; return Response.json({ status: 'created' }, { status: 201 }) } })
  assert.deepEqual(await api('/api/v1/agent/tasks', { method: 'POST', body: { user_input: 'query' } }), { status: 'created' })
  assert.equal(actual[1].headers['X-Demo-User'], 'employee-demo-001')
  assert.equal(actual[1].body, '{"user_input":"query"}')
})

test('does not retry writes after errors', async () => {
  let calls = 0
  const api = createApi(() => 'reviewer-demo-001', { fetcher: async () => { calls++; return Response.json({ detail: '结果未知' }, { status: 503 }) } })
  await assert.rejects(api('/write', { method: 'POST' }), error => error instanceof ApiError && error.status === 503 && error.message === '结果未知')
  assert.equal(calls, 1)
})

test('does not set a JSON header on multipart requests', async () => {
  let headers
  const api = createApi(() => 'reviewer-demo-001', { fetcher: async (_, options) => { headers = options.headers; return Response.json({ ok: true }) } })
  const form = new FormData(); form.append('file', new Blob(['demo']), 'test.md')
  await api('/upload', { method: 'POST', body: form })
  assert.equal(headers['Content-Type'], undefined)
})

test('reports timeouts without pretending an operation was rolled back', async () => {
  const api = createApi(() => 'employee-demo-001', { fetcher: async (_, { signal }) => new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(new Error('aborted')))) })
  await assert.rejects(api('/run', { method: 'POST', timeout: 10 }), /后台可能仍在执行/)
})

test('encodes path identifiers and handles validation errors', async () => {
  assert.equal(pathId(' a/b '), 'a%2Fb')
  const api = createApi(() => 'employee-demo-001', { fetcher: async () => Response.json({ detail: [{ msg: '编号无效' }] }, { status: 422 }) })
  await assert.rejects(api('/read'), /编号无效/)
})

test('browser session requests can omit identity headers and use same-origin cookies', async () => {
  let options
  const api = createApi(() => null, { fetcher: async (_, actual) => { options = actual; return Response.json({ role: 'employee' }) } })
  await api('/api/v1/auth/me')
  assert.equal(options.headers['X-Demo-User'], undefined)
  assert.equal(options.credentials, 'same-origin')
})
