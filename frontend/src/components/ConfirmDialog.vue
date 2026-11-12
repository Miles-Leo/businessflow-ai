<!-- 模块职责：不可自动提交的操作确认层；用户确认后才调用传入操作。 -->
<script setup>
import { ref, watch, nextTick } from 'vue'
import Icon from './Icon.vue'
const props = defineProps({ modal: Object })
const emit = defineEmits(['cancel', 'confirm'])
const dialog = ref(null)
let previousFocus
watch(() => props.modal, async value => {
  if (value) { previousFocus = document.activeElement; await nextTick(); dialog.value?.querySelector('button')?.focus() }
  else previousFocus?.focus?.()
})
function keyboard(event) {
  if (event.key === 'Escape') emit('cancel')
  if (event.key === 'Tab') {
    const buttons = [...dialog.value.querySelectorAll('button')]
    const current = buttons.indexOf(document.activeElement)
    const index = (current + (event.shiftKey ? -1 : 1) + buttons.length) % buttons.length
    event.preventDefault(); buttons[index]?.focus()
  }
}
</script>
<template><Teleport to="body"><div v-if="modal" class="modal-overlay" @click.self="$emit('cancel')"><section ref="dialog" class="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="confirm-title" @keydown="keyboard"><div class="dialog-icon"><Icon name="shield" :size="26" /></div><h2 id="confirm-title">{{ modal.title }}</h2><p>{{ modal.description }}</p><div class="dialog-actions"><button class="button secondary" @click="$emit('cancel')">取消</button><button class="button" :class="modal.danger ? 'danger' : 'primary'" @click="$emit('confirm')">{{ modal.button }}</button></div></section></div></Teleport></template>
