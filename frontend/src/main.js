// 模块职责：挂载 Vue 应用与全局样式，不执行后端数据初始化。
import { createApp } from 'vue'
import App from './App.vue'
import './style.css'

createApp(App).mount('#app')
