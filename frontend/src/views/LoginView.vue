<!-- 模块职责：本地演示身份入口；不提供真实企业密码认证。 -->
<script setup>
import { ref } from 'vue'
import Icon from '../components/Icon.vue'
const props = defineProps({ store: Object })
const s = props.store.state
const selected = ref('employee-demo-001')
const accounts = [
  { id: 'employee-demo-001', name: '业务员工', icon: 'user', description: '发起业务需求，查看自己的处理进度', features: '发起需求 · 我的任务 · 政策问答' },
  { id: 'reviewer-demo-001', name: '业务负责人', icon: 'shield', description: '处理审核待办，管理正式工单与知识', features: '审核待办 · 工单处理 · 知识管理' },
]
</script>
<template>
  <main class="login-page">
    <section class="login-story"><a class="brand" href="#/login"><span class="brand-mark"><Icon name="flow" :size="25" /></span><span>BusinessFlow<span class="brand-ai">AI WORKSPACE</span></span></a><div class="login-story-main"><div class="login-eyebrow">MAKE WORK FLOW.</div><h1>让每一条需求，<br />成为有序的行动。</h1><p>从业务查询到审核执行，<br />在属于你的工作空间里，专注下一步。</p><div class="login-flow"><div><span>01</span><strong>提出需求</strong><small>用自然语言描述业务问题</small></div><div><span>02</span><strong>有据可审</strong><small>结合业务事实与企业政策</small></div><div><span>03</span><strong>受控执行</strong><small>审核通过后再完成正式操作</small></div></div></div><div class="login-story-footer"><Icon name="shield" :size="16" /> 每一次执行，有据可循</div></section>
    <section class="login-panel"><div class="login-form-wrap"><span class="login-environment"><span class="tiny-dot"></span>本地演示环境</span><h2>欢迎回来</h2><p class="login-intro">选择演示账户，进入对应的工作空间。</p><form @submit.prevent="store.login(selected)"><fieldset :disabled="s.busy"><legend class="sr-only">选择演示账户</legend><label v-for="account in accounts" :key="account.id" class="account-option" :class="{ selected: selected === account.id }"><input v-model="selected" type="radio" name="demo-account" :value="account.id" /><span class="account-icon"><Icon :name="account.icon" :size="23" /></span><span class="account-text"><strong>{{ account.name }}</strong><span>{{ account.description }}</span><small>{{ account.features }}</small></span></label></fieldset><div v-if="s.loginError" class="login-error" role="alert">{{ s.loginError }}</div><button class="button primary login-submit" type="submit" :disabled="s.busy"><span v-if="s.busy" class="spinner"></span>{{ s.busy ? '正在登录' : '进入工作空间' }}<Icon v-if="!s.busy" name="arrow" :size="18" /></button></form><p class="demo-login-note">这是本地演示登录，不验证企业账号或密码。登录后由服务端保存会话，并按角色区分操作权限。</p></div><footer class="login-panel-footer">BusinessFlow AI · 企业业务流程工作台</footer></section>
  </main>
</template>
