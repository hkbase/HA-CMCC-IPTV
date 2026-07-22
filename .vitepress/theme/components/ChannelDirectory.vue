<script setup>
import { computed, onMounted, ref } from 'vue'
import { withBase } from 'vitepress'
import { fetchM3u, parseM3u } from '../m3u'

const rawM3u = ref('')
const loading = ref(true)
const error = ref('')
const query = ref('')
const selectedGroup = ref('全部分组')

function logoSrc(logo) {
  const filename = decodeURIComponent((logo || '').split('/').pop() || '')
  return filename ? withBase(`/logos/${filename}`) : ''
}

const entries = computed(() => parseM3u(rawM3u.value))

const groups = computed(() => {
  const groupMap = new Map()

  for (const entry of entries.value) {
    if (!groupMap.has(entry.group)) {
      groupMap.set(entry.group, {
        name: entry.group,
        sourceCount: 0,
        channels: new Map()
      })
    }

    const group = groupMap.get(entry.group)
    group.sourceCount += 1

    if (!group.channels.has(entry.name)) {
      group.channels.set(entry.name, {
        name: entry.name,
        group: entry.group,
        logo: entry.logo,
        sourceCount: 0
      })
    }

    const channel = group.channels.get(entry.name)
    channel.sourceCount += 1
    if (!channel.logo && entry.logo) channel.logo = entry.logo
  }

  return Array.from(groupMap.values()).map((group) => ({
    ...group,
    channels: Array.from(group.channels.values())
  }))
})

const groupOptions = computed(() => ['全部分组', ...groups.value.map((group) => group.name)])

const visibleGroups = computed(() => {
  const keyword = query.value.trim().toLowerCase()

  return groups.value
    .filter((group) => selectedGroup.value === '全部分组' || group.name === selectedGroup.value)
    .map((group) => {
      const channels = group.channels.filter((channel) => {
        if (!keyword) return true
        return channel.name.toLowerCase().includes(keyword) || group.name.toLowerCase().includes(keyword)
      })

      return {
        ...group,
        channels,
        visibleSourceCount: channels.reduce((total, channel) => total + channel.sourceCount, 0)
      }
    })
    .filter((group) => group.channels.length > 0)
})

const stats = computed(() => {
  const channelCount = groups.value.reduce((total, group) => total + group.channels.length, 0)

  return {
    groups: groups.value.length,
    channels: channelCount,
    sources: entries.value.length
  }
})

const visibleStats = computed(() => ({
  groups: visibleGroups.value.length,
  channels: visibleGroups.value.reduce((total, group) => total + group.channels.length, 0),
  sources: visibleGroups.value.reduce((total, group) => total + group.visibleSourceCount, 0)
}))

onMounted(async () => {
  try {
    rawM3u.value = await fetchM3u(withBase('/'))
  } catch (caughtError) {
    error.value = caughtError instanceof Error ? caughtError.message : '频道列表读取失败'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div v-if="loading" class="channel-state">正在读取频道列表...</div>
  <div v-else-if="error" class="channel-state channel-state-error">{{ error }}</div>
  <div v-else>
    <div class="channel-summary" aria-label="频道统计">
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

    <div class="channel-filter-panel">
      <div class="channel-tools">
        <label>
          <span>搜索频道</span>
          <input v-model="query" type="search" placeholder="例如 河南卫视、CCTV、郑州">
        </label>
        <label>
          <span>分组</span>
          <select v-model="selectedGroup">
            <option v-for="group in groupOptions" :key="group" :value="group">{{ group }}</option>
          </select>
        </label>
      </div>

      <p class="channel-filter-note" aria-live="polite">
        当前显示 {{ visibleStats.channels }} 个频道、{{ visibleStats.sources }} 条源，来自 {{ visibleStats.groups }} 个分组。
      </p>

      <div class="group-overview" aria-label="频道分组快速筛选">
        <button
          type="button"
          class="group-chip"
          :class="{ 'group-chip-active': selectedGroup === '全部分组' }"
          :aria-pressed="selectedGroup === '全部分组'"
          @click="selectedGroup = '全部分组'"
        >
          <strong>全部频道</strong>
          <span>{{ stats.channels }} 频道 / {{ stats.sources }} 源</span>
        </button>
        <button
          v-for="group in groups"
          :key="group.name"
          type="button"
          class="group-chip"
          :class="{ 'group-chip-active': selectedGroup === group.name }"
          :aria-pressed="selectedGroup === group.name"
          @click="selectedGroup = group.name"
        >
          <strong>{{ group.name }}</strong>
          <span>{{ group.channels.length }} 频道 / {{ group.sourceCount }} 源</span>
        </button>
      </div>
    </div>

    <div v-if="visibleGroups.length === 0" class="channel-state">没有匹配的频道。</div>

    <section v-for="group in visibleGroups" :key="group.name" class="channel-section">
      <div class="channel-heading">
        <h2>{{ group.name }}</h2>
        <span>{{ group.channels.length }} 个频道 / {{ group.visibleSourceCount }} 条源</span>
      </div>
      <div class="channel-grid">
        <article v-for="channel in group.channels" :key="`${group.name}-${channel.name}`" class="channel-item">
          <img v-if="logoSrc(channel.logo)" class="channel-logo" :src="logoSrc(channel.logo)" :alt="`${channel.name} 台标`" loading="lazy">
          <span v-else class="channel-logo channel-logo-empty" aria-hidden="true"></span>
          <span class="channel-name">{{ channel.name }}</span>
          <span class="channel-count">{{ channel.sourceCount }} 源</span>
        </article>
      </div>
    </section>
  </div>
</template>
