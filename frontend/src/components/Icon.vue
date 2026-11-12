<!-- 模块职责：复用界面图标；不承载业务状态或权限判断。 -->
<script setup>
defineProps({ name: String, size: { type: Number, default: 20 } })
const paths = {
  flow: 'M4 5h6v6H4z M14 13h6v6h-6z M10 8h7v5 M7 11v5h7',
  home: 'm3 10 9-7 9 7 M5 9v12h5v-7h4v7h5V9',
  list: 'M9 5h12 M9 12h12 M9 19h12 M3 5h1 M3 12h1 M3 19h1',
  check: 'm5 12 4 4L19 6',
  shield: 'M12 3 3 7v5c0 5 9 9 9 9s9-4 9-9V7z m-5 9 3 3 5-5',
  ticket: 'M3 7h18v4a2 2 0 0 0 0 4v4H3v-4a2 2 0 0 0 0-4z M9 7v3 m0 4v2 m0 1v2',
  book: 'M12 6c-3-2-6-2-9-1v15c3-1 6-1 9 1 3-2 6-2 9-1V5c-3-1-6-1-9 1z M12 6v15',
  database: 'M20 6c0 2-16 2-16 0s16-2 16 0v12c0 3-16 3-16 0V6 M4 12c0 3 16 3 16 0',
  arrow: 'M5 12h14 m-5-5 5 5-5 5',
  plus: 'M12 5v14 M5 12h14',
  refresh: 'M20 11a8 8 0 0 0-14-5L3 9 M3 3v6h6 M4 13a8 8 0 0 0 14 5l3-3 m0 6v-6h-6',
  search: 'M16 16l5 5 M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0',
  clock: 'M12 8v5l3 2 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
  copy: 'M8 8h13v13H8z M16 8V3H3v13h5',
  cloud: 'M7 18a5 5 0 1 1 0-10 6 6 0 0 1 12 1 4 4 0 0 1 0 8 M12 12v9 m-3-3 3 3 3-3',
  spark: 'm12 2 3 7 7 3-7 3-3 7-3-7-7-3 7-3z',
  close: 'm6 6 12 12 M6 18 18 6',
  chevron: 'm9 5 7 7-7 7',
  file: 'M14 2H5v20h14V7z M14 2v6h5 M8 13h8 M8 17h8',
  user: 'M20 21v-3c0-5-16-5-16 0v3 M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0',
}
</script>
<template><svg :width="size" :height="size" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path :d="paths[name] || paths.file" /></svg></template>
