---
title: 河南移动 IPTV
aside: false
sidebar: false
---

<script setup>
import { withBase } from 'vitepress'
</script>

<section class="home-hero">
  <div>
    <p class="hero-kicker">河南移动宽带 · HTTP 单播 · 人工复核</p>
    <h1>河南移动 IPTV，<br>从订阅到维护都在这里</h1>
    <p class="hero-lead">
      复制 M3U 即可导入播放器，也能在这里浏览当前频道、检查源状态并查看维护规则。
    </p>
    <div class="hero-actions">
      <a class="site-button" :href="withBase('/index.m3u')">打开 M3U 订阅</a>
      <a class="site-button-alt" :href="withBase('/start')">快速开始</a>
      <a class="site-button-alt" :href="withBase('/channels')">浏览频道</a>
    </div>
    <p class="hero-note">公网或非河南移动网络通常不能播放，这是运营商 IPTV 网络边界，不是页面错误。</p>
  </div>

  <HomeSignalPanel />
</section>

<section class="section-band">
  <p class="section-kicker">第一次来</p>
  <h2>先完成一次播放验证</h2>
  <p class="section-lead">
    先确认播放器能读取订阅，再确认当前网络能够访问河南移动 IPTV 源。按下面四步走，可以快速定位问题落在哪一层。
  </p>
  <div class="flow-steps">
    <div class="flow-step">
      <strong>打开主订阅</strong>
      <span>优先使用 GitHub Pages 发布的 index.m3u。</span>
    </div>
    <div class="flow-step">
      <strong>导入桌面播放器</strong>
      <span>先用 VLC 或 PotPlayer 确认能读取频道列表。</span>
    </div>
    <div class="flow-step">
      <strong>确认播放网络</strong>
      <span>在河南移动宽带内测试，避免代理和异地出口。</span>
    </div>
    <div class="flow-step">
      <strong>根据现象排查</strong>
      <span>频道为空、全部不能播或单条失效，需要分别处理。</span>
    </div>
  </div>
</section>

<section class="section-band">
  <p class="section-kicker">按任务进入</p>
  <h2>从这里找到需要的页面</h2>
  <p class="section-lead">
    使用者从快速开始、订阅地址和频道列表进入；遇到问题时查看播放排查，维护者再进入状态与维护说明。
  </p>
  <div class="doc-grid">
    <div class="doc-card">
      <h3>快速开始</h3>
      <p>按顺序导入订阅、测试播放并确认网络环境。</p>
      <a :href="withBase('/start')">查看步骤</a>
    </div>
    <div class="doc-card">
      <h3>订阅地址</h3>
      <p>复制主地址或备用地址，查看 EPG、台标和播放器建议。</p>
      <a :href="withBase('/usage')">复制地址</a>
    </div>
    <div class="doc-card">
      <h3>频道列表</h3>
      <p>直接读取当前 M3U，按分组查看频道、台标和源数。</p>
      <a :href="withBase('/channels')">浏览频道</a>
    </div>
    <div class="doc-card">
      <h3>播放排查</h3>
      <p>按现象区分订阅、播放器、网络和单条源问题。</p>
      <a :href="withBase('/troubleshooting')">排查问题</a>
    </div>
    <div class="doc-card">
      <h3>源状态</h3>
      <p>查看当前整理状态、人工复核口径和已知限制。</p>
      <a :href="withBase('/status')">查看状态</a>
    </div>
    <div class="doc-card">
      <h3>维护说明</h3>
      <p>查看频道命名、台标、分组和提交前检查规则。</p>
      <a :href="withBase('/maintain')">查看规则</a>
    </div>
  </div>
</section>

<section class="section-band">
  <p class="section-kicker">维护原则</p>
  <h2>让清单保持可读、可复核</h2>
  <div class="status-grid">
    <div class="status-card">
      <h3>坚持人工复核</h3>
      <p>不自动采集和发布，避免错台、重复或不可用结果直接进入主订阅。</p>
    </div>
    <div class="status-card">
      <h3>明确网络边界</h3>
      <p>直播源依赖河南移动 IPTV 网络，普通公网访问失败属于常见情况。</p>
    </div>
    <div class="status-card">
      <h3>只维护地址与台标</h3>
      <p>仓库不存储流媒体内容，只整理 M3U 地址、频道信息和台标。</p>
    </div>
  </div>
</section>
