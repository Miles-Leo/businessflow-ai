<!-- 模块职责：状态值映射为显示标签；不自行推断流程结果。 -->
<script setup>
import { label } from '../format'
defineProps({ status: String, text: String })
</script>
<template><span class="badge" :class="`badge-${status || 'neutral'}`"><span class="badge-dot"></span>{{ text || label(status) }}</span></template>
