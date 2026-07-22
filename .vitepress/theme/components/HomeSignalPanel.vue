<script setup>
import { computed, onMounted, ref } from 'vue'
import { withBase } from 'vitepress'
import { fetchM3u, parseM3u } from '../m3u'

const rawM3u = ref('')
const logoRail = ['河南卫视', 'CCTV1', '郑州新闻综合', '河南公共频道']

const entries = computed(() => parseM3u(rawM3u.value))

const stats = computed(() => {
  const channelSet = new Set(entries.value.map((entry) => entry.name))
  const groupSet = new Set(entries.value.map((entry) => entry.group))

  return {
    sources: entries.value.length || '...',
    channels: channelSet.size || '...',
    groups: groupSet.size || '...'
  }
})

onMounted(async () => {
  try {
    rawM3u.value = await fetchM3u(withBase('/'))
  } catch {
    rawM3u.value = ''
  }
})
</script>

<template>
  <aside class="signal-panel" aria-label="当前订阅概览">
    <div class="signal-panel-header">
      <strong>当前订阅概览</strong>
      <span>页面读取发布后的 index.m3u 自动统计</span>
    </div>
    <div class="metric-list">
      <div>
        <strong>{{ stats.channels }}</strong>
        <span>频道</span>
      </div>
      <div>
        <strong>{{ stats.sources }}</strong>
        <span>源地址</span>
      </div>
      <div>
        <strong>{{ stats.groups }}</strong>
        <span>分组</span>
      </div>
    </div>
    <div class="logo-rail" aria-label="频道台标示例">
      <img v-for="name in logoRail" :key="name" :src="withBase(`/logos/${name}.png`)" :alt="`${name} 台标`">
    </div>
  </aside>
</template>
