import { test } from 'node:test'
import assert from 'node:assert/strict'
import { workspaceTabs, canNavigate, defaultTab, tabFromHash, workspaceHash } from '../src/workspaces.js'

test('employees only have their own task and policy workspace', () => {
  assert.deepEqual(workspaceTabs.employee, ['workbench', 'history', 'knowledge'])
  assert.equal(canNavigate('employee', 'approvals'), false)
  assert.equal(canNavigate('employee', 'tickets'), false)
})
test('managers open the inbox rather than the employee composer', () => {
  assert.equal(defaultTab('manager'), 'approvals')
  assert.equal(canNavigate('manager', 'workbench'), false)
})
test('forged role URLs are redirected to the authenticated workspace', () => {
  assert.equal(tabFromHash('employee', '#/manager/approvals'), 'workbench')
  assert.equal(tabFromHash('employee', '#/employee/tickets'), 'workbench')
  assert.equal(tabFromHash('manager', '#/employee/workbench'), 'approvals')
  assert.equal(workspaceHash('employee', 'approvals'), '#/employee/workbench')
  assert.equal(tabFromHash('employee', '#/employee/history'), 'history')
})
