---
title: 快速开始
---

# 快速开始

这页只处理一件事：让播放器尽快读到订阅，并判断当前网络能不能播放。

## 1. 复制主订阅

```text
https://elykia093.github.io/HA-CMCC-IPTV/index.m3u
```

主订阅对应仓库里的 `public/index.m3u`。如果 GitHub Pages 能访问，优先使用这个地址。

## 2. 导入播放器

把订阅地址添加到支持 M3U 的播放器里。桌面端建议先用 VLC 或 PotPlayer 测试，电视端和移动端再按自己的客户端导入。

<div class="route-grid">
  <div class="route-card">
    <h3>桌面测试</h3>
    <p>VLC、PotPlayer 适合快速打开订阅或单条源，判断源本身能否拉流。</p>
  </div>
  <div class="route-card">
    <h3>移动端观看</h3>
    <p>APTV、TVBox、mytv-android 等适合长期订阅，但解析字段支持不完全一致。</p>
  </div>
  <div class="route-card">
    <h3>电视端使用</h3>
    <p>优先选择支持远程 M3U、分组和 tvg-logo 的客户端。</p>
  </div>
</div>

## 3. 确认网络环境

直播源主要面向河南移动宽带环境。非河南移动网络、手机流量、异地出口、代理、加速器、旁路由都可能导致无法播放。

<div class="note-strip">
  能下载到 M3U 不代表直播源能播。订阅文件在 GitHub Pages 上，直播源在运营商 IPTV 网络里，它们不是同一个访问边界。
</div>

## 4. 打不开时先看这里

| 现象 | 先查什么 | 下一步 |
| --- | --- | --- |
| 播放器里没有频道 | 订阅地址是否复制完整 | 换桌面播放器再导入一次 |
| 有频道但全部无法播放 | 当前网络是否为河南移动宽带 | 关闭代理或换宽带环境 |
| 只有个别频道失败 | 单条源可能失效 | 到频道列表看是否有备用源 |
| 台标不显示 | 播放器是否支持 `tvg-logo` | 不影响播放，可忽略 |

更细的情况见 [播放排查](/troubleshooting)。
