// 模块职责：角色导航白名单；仅控制页面入口，不能替代后端授权。
export const workspaceTabs = {
  employee: ['workbench', 'history', 'knowledge'],
  manager: ['approvals', 'tickets', 'knowledge', 'data'],
}
export const defaultTab = role => workspaceTabs[role]?.[0] || 'workbench'
export const canNavigate = (role, tab) => workspaceTabs[role]?.includes(tab) || false
export const workspaceHash = (role, tab) => `#/${role}/${canNavigate(role, tab) ? tab : defaultTab(role)}`
export function tabFromHash(role, hash) {
  const match = /^#\/(employee|manager)\/([a-z]+)$/.exec(hash)
  return match && match[1] === role && canNavigate(role, match[2]) ? match[2] : defaultTab(role)
}
