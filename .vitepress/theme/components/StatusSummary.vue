<script setup>
import { computed, onMounted, ref } from 'vue'
import { withBase } from 'vitepress'
import { fetchM3u, parseM3u } from '../m3u'

const rawM3u = ref('')

const summary = computed(() => {
  const entries = parseM3u(rawM3u.value)
  const groups = new Map()
  const channels = new Set()

  for (const entry of entries) {
    channels.add(entry.name)
    groups.set(entry.group, (groups.get(entry.group) || 0) + 1)
  }

  return {
    sources: entries.length,
    channels: channels.size,
    groups: Array.from(groups.entries()).map(([name, count]) => ({ name, count }))
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
  <div class="status-grid">
    <div class="status-card">
      <h3>{{ summary.channels || '...' }} 个频道</h3>
      <p>按 `tvg-name` / 显示名去重后的频道数量。</p>
    </div>
    <div class="status-card">
      <h3>{{ summary.sources || '...' }} 条源</h3>
      <p>当前 `index.m3u` 中保留的候选播放地址。</p>
    </div>
    <div class="status-card">
      <h3>{{ summary.groups.length || '...' }} 个分组</h3>
      <p>按 `group-title` 统计的频道分组。</p>
    </div>
  </div>
</template>
