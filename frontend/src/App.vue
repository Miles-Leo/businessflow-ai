<!-- 模块职责：页面组合入口：会话恢复、角色导航和轮询生命周期管理。 -->
<script setup>
import { computed, onMounted, onUnmounted } from 'vue'
import { useWorkbench } from './useWorkbench'
import Icon from './components/Icon.vue'
import TasksView from './views/TasksView.vue'
import ReviewView from './views/ReviewView.vue'
import TicketView from './views/TicketView.vue'
import KnowledgeView from './views/KnowledgeView.vue'
import DataView from './views/DataView.vue'
import ConfirmDialog from './components/ConfirmDialog.vue'
import LoginView from './views/LoginView.vue'

const store = useWorkbench()
const s = store.state
const isManager = store.manager
const nav = computed(() => isManager.value ? [
  { id: 'approvals', name: '审核待办', icon: 'shield' },
  { id: 'tickets', name: '工单处理', icon: 'ticket' },
  { id: 'knowledge', name: '知识管理', icon: 'book' },
  { id: 'data', name: '业务查询', icon: 'database' },
] : [
  { id: 'workbench', name: '发起需求', icon: 'spark' },
  { id: 'history', name: '我的任务', icon: 'list' },
  { id: 'knowledge', name: '政策问答', icon: 'book' },
])
const current = computed(() => nav.value.find(item => item.id === s.tab) || nav.value[0])
onMounted(() => { store.bootstrap(); store.startTaskPolling(); window.addEventListener('hashchange', store.readRoute) })
onUnmounted(() => { store.stopTaskPolling(); window.removeEventListener('hashchange', store.readRoute) })
</script>

<template>
  <div v-if="s.authLoading" class="auth-loading" role="status"><span class="spinner"></span>正在打开工作空间</div>
  <LoginView v-else-if="!s.authenticated" :store="store" />
  <div v-else class="app-shell">
    <aside class="sidebar">
      <a class="brand" href="#" @click.prevent="store.navigate(isManager ? 'approvals' : 'workbench')"><span class="brand-mark"><Icon name="flow" :size="25" /></span><span>BusinessFlow<span class="brand-ai">AI WORKSPACE</span></span></a>
      <div class="workspace-pill"><span class="workspace-avatar">{{ isManager ? '审' : '员' }}</span><div>{{ isManager ? '负责人工作空间' : '员工工作空间' }}<small>{{ s.profile.display_name }}</small></div><span class="tiny-dot"></span></div>
      <div class="nav-caption">工作空间</div>
      <nav aria-label="主导航"><button v-for="item in nav" :key="item.id" class="nav-item" :class="{ active: s.tab === item.id }" :disabled="s.busy" @click="store.navigate(item.id)" :aria-current="s.tab === item.id ? 'page' : undefined"><Icon :name="item.icon" /><span>{{ item.name }}</span><span v-if="item.id === 'history' && s.taskTotal" class="nav-count">{{ s.taskTotal }}</span></button></nav>
      <div class="sidebar-bottom"><div class="sidebar-note"><Icon :name="isManager ? 'shield' : 'flow'" :size="18" /><div>{{ isManager ? '每一个决定，都有据可循' : '专注需求，随时掌握进度' }}<small>{{ isManager ? '审核 · 执行 · 追溯' : '提交需求 · 查看结果' }}</small></div></div><div class="sidebar-version">BusinessFlow AI <span>本地演示</span></div></div>
    </aside>

    <div class="main-shell">
      <header class="topbar"><div class="breadcrumbs">{{ isManager ? '负责人空间' : '员工空间' }} <Icon name="chevron" :size="13" /><strong>{{ current.name }}</strong></div><div class="header-actions"><button class="service-pill" :class="s.health" @click="store.health" title="重新检查服务状态"><span class="service-dot"></span>{{ s.health === 'online' ? '服务已连接' : s.health === 'checking' ? '正在连接' : '服务未连接' }}</button><div class="session-profile"><span class="role-avatar">{{ isManager ? '审' : '员' }}</span><div><strong>{{ s.profile.display_name }}</strong><small>{{ isManager ? '业务负责人' : '业务员工' }}</small></div><button class="text-button logout-button" :disabled="s.busy" @click="store.logout">退出登录</button></div></div></header>
      <main>
        <div class="page-heading"><div><div class="eyebrow">{{ isManager ? 'REVIEW & OPERATIONS' : 'YOUR WORKSPACE' }}</div><h1>{{ current.name }}</h1><p>{{ { workbench: '描述你需要处理的业务，其余交给流程。', history: '查看自己的全部任务，随时更新处理进度。', approvals: '待处理的建议集中在这里，先看依据，再做决定。', tickets: '处理正式工单，按需同步到飞书。', knowledge: isManager ? '管理企业政策，也可以直接检索问答。' : '查询企业政策，每个回答都有可核对的来源。', data: '核对订单与客户资料，辅助业务决策。' }[s.tab] }}</p></div></div>

        <div v-if="s.notice" class="notice" :class="s.notice.type" role="status" aria-live="polite"><Icon :name="s.notice.type === 'error' ? 'shield' : 'check'" :size="18" /><span>{{ s.notice.text }}</span><button class="icon-button" aria-label="关闭提示" @click="s.notice = null"><Icon name="close" :size="16" /></button></div>
        <div v-if="s.busy" class="busy-banner" role="status"><span class="spinner"></span>{{ s.busyLabel }}<small>处理完成后即可继续操作</small></div>

        <TasksView v-if="s.tab === 'workbench' || s.tab === 'history'" :store="store" />
        <ReviewView v-else-if="s.tab === 'approvals'" :store="store" />
        <TicketView v-else-if="s.tab === 'tickets'" :store="store" />
        <KnowledgeView v-else-if="s.tab === 'knowledge'" :store="store" />
        <DataView v-else :store="store" />
        <footer class="page-footer"><span>BusinessFlow AI · 让业务自动化，也让执行可控</span><span>本地演示工作空间</span></footer>
      </main>
    </div>
    <ConfirmDialog :modal="s.modal" @cancel="s.modal = null" @confirm="store.confirmNow" />
  </div>
</template>
