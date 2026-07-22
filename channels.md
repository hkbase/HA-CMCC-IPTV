---
title: 频道列表
aside: false
---

# 频道列表

这里直接读取当前发布的 `index.m3u`，按分组整理频道、台标和源数，其中地方卫视和河南地市频道均按照地方区号排序。它不是第二份手写清单，所以订阅文件更新后页面会跟着变化。

<ClientOnly>
  <ChannelDirectory />

  <template #fallback>
    <div class="channel-state">正在读取频道列表...</div>
  </template>
</ClientOnly>

<style>
.channel-state {
  margin: 24px 0;
  padding: 16px;
  border: 1px solid var(--site-line);
  border-radius: 10px;
  background: var(--vp-c-bg-soft);
  color: var(--vp-c-text-2);
}

.channel-state-error {
  border-color: var(--vp-c-danger-2);
  color: var(--vp-c-danger-1);
}

.channel-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin: 22px 0 18px;
  overflow: hidden;
  border: 1px solid var(--site-line);
  border-radius: 12px;
  background: var(--vp-c-bg-soft);
  box-shadow: 0 1px 2px color-mix(in srgb, var(--vp-c-text-1) 4%, transparent);
}

.group-chip,
.channel-item {
  min-width: 0;
  border: 1px solid var(--site-line);
  border-radius: 10px;
  background: var(--vp-c-bg);
}

.channel-summary > div {
  padding: 16px 18px;
  border-right: 1px solid var(--site-line);
}

.channel-summary > div:last-child {
  border-right: 0;
}

.channel-summary strong {
  display: block;
  color: var(--vp-c-brand-1);
  font-size: 30px;
  font-variant-numeric: tabular-nums;
  line-height: 1.1;
}

.channel-summary span {
  display: block;
  margin-top: 6px;
  color: var(--vp-c-text-2);
  font-size: 14px;
}

.channel-tools {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(180px, 0.6fr);
  gap: 12px;
  margin: 0;
}

.channel-filter-panel {
  margin: 18px 0 30px;
  padding: 16px;
  border: 1px solid var(--site-line);
  border-radius: 12px;
  background: var(--site-brand-soft);
}

.channel-tools label {
  display: grid;
  gap: 6px;
  min-width: 0;
  color: var(--vp-c-text-2);
  font-size: 14px;
  font-weight: 650;
}

.channel-tools input,
.channel-tools select {
  width: 100%;
  min-height: 42px;
  padding: 0 12px;
  border: 1px solid var(--site-line);
  border-radius: 9px;
  background: var(--vp-c-bg);
  color: var(--vp-c-text-1);
  font-size: 15px;
  transition: border-color 0.16s ease, box-shadow 0.16s ease;
}

.channel-tools input::placeholder {
  color: var(--vp-c-text-3);
}

.channel-tools input:focus-visible,
.channel-tools select:focus-visible {
  border-color: var(--vp-c-brand-1);
  outline: 2px solid color-mix(in srgb, var(--vp-c-brand-1) 22%, transparent);
  outline-offset: 1px;
}

.channel-filter-note {
  margin: 14px 0 0;
  color: var(--vp-c-text-2);
  font-size: 14px;
}

.group-overview {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(168px, 1fr));
  gap: 10px;
  margin: 16px 0 0;
}

.group-chip {
  appearance: none;
  width: 100%;
  min-height: 60px;
  padding: 12px 14px;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.16s ease, background-color 0.16s ease, color 0.16s ease;
}

.group-chip:hover,
.group-chip-active {
  border-color: var(--vp-c-brand-1);
  background: var(--site-brand-soft);
}

.group-chip-active {
  box-shadow: inset 3px 0 0 var(--vp-c-brand-1);
}

.group-chip-active strong {
  color: var(--vp-c-brand-1);
}

.group-chip:focus-visible {
  outline: 2px solid var(--vp-c-brand-1);
  outline-offset: 2px;
}

.group-chip strong {
  display: block;
  color: var(--vp-c-text-1);
}

.group-chip span {
  display: block;
  margin-top: 4px;
  color: var(--vp-c-text-2);
  font-size: 13px;
}

.channel-section {
  margin-top: 34px;
  scroll-margin-top: 88px;
}

.channel-heading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.channel-heading h2 {
  margin: 0;
  padding: 0;
  border: 0;
}

.channel-heading span {
  flex: none;
  color: var(--vp-c-text-2);
  font-size: 14px;
}

.channel-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(196px, 1fr));
  gap: 10px;
}

.channel-item {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 56px;
  padding: 9px 10px;
  box-shadow: 0 1px 1px color-mix(in srgb, var(--vp-c-text-1) 3%, transparent);
  transition: border-color 0.16s ease, background-color 0.16s ease;
}

.channel-item:hover {
  border-color: color-mix(in srgb, var(--vp-c-brand-1) 45%, var(--site-line));
  background: var(--site-brand-soft);
}

.channel-logo {
  flex: none;
  width: 36px;
  height: 36px;
  object-fit: contain;
  padding: 3px;
  border: 1px solid color-mix(in srgb, var(--site-line) 72%, transparent);
  border-radius: 8px;
  background: var(--vp-c-bg-soft);
}

.channel-logo-empty {
  border-radius: 9px;
  background: var(--vp-c-default-soft);
}

.channel-name {
  min-width: 0;
  flex: 1;
  color: var(--vp-c-text-1);
  font-weight: 650;
  overflow-wrap: anywhere;
}

.channel-count {
  flex: none;
  padding: 2px 6px;
  border-radius: 999px;
  background: var(--vp-c-default-soft);
  color: var(--vp-c-text-2);
  font-size: 13px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

@media (max-width: 700px) {
  .channel-tools {
    grid-template-columns: 1fr;
  }

  .channel-summary {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .channel-summary > div {
    padding: 12px 10px;
  }

  .channel-summary strong {
    font-size: 24px;
  }

  .group-overview {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .channel-filter-panel {
    padding: 14px;
  }

  .channel-heading {
    display: block;
  }

  .channel-heading span {
    display: block;
    margin-top: 4px;
  }

  .channel-grid {
    grid-template-columns: 1fr;
  }
}

@media (prefers-reduced-motion: reduce) {
  .channel-tools input,
  .channel-tools select,
  .group-chip,
  .channel-item {
    transition: none;
  }
}
</style>
