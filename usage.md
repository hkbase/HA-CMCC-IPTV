---
title: 订阅地址
---

# 订阅地址

这里集中放 M3U 订阅、备用地址、EPG、播放器建议和台标路径。第一次使用可以先看 [快速开始](/start)。

## 主地址

<div class="address-grid">
  <div class="address-card">
    <strong>GitHub Pages</strong>
    <code>https://elykia093.github.io/HA-CMCC-IPTV/index.m3u</code>
  </div>
</div>

这是推荐优先使用的订阅地址。GitHub Pages 发布后，播放器访问到的是站点根目录下的 `index.m3u`。

## 备用加速地址

<div class="address-grid">
  <div class="address-card">
    <strong>jsDelivr</strong>
    <code>https://cdn.jsdelivr.net/gh/Elykia093/HA-CMCC-IPTV@main/public/index.m3u</code>
  </div>
  <div class="address-card">
    <strong>jsDelivr Fastly</strong>
    <code>https://fastly.jsdelivr.net/gh/Elykia093/HA-CMCC-IPTV@main/public/index.m3u</code>
  </div>
  <div class="address-card">
    <strong>ghproxy 镜像</strong>
    <code>https://mirror.ghproxy.com/raw.githubusercontent.com/Elykia093/HA-CMCC-IPTV/main/public/index.m3u</code>
  </div>
</div>

备用地址适合主地址下载慢或播放器无法拉取时使用。加速节点通常有缓存延迟，刚更新后的内容不一定立刻同步。

## EPG 节目单

<div class="address-grid">
  <div class="address-card">
    <strong>XMLTV</strong>
    <code>https://epg.zsdc.eu.org/t.xml</code>
  </div>
</div>

当前 `public/index.m3u` 在文件头引用这个节目单。播放器是否显示节目名称、进度和预告，还取决于客户端对 XMLTV 以及频道标识的匹配支持。

## 推荐播放器

| 平台 | 播放器 | 适合场景 |
| --- | --- | --- |
| PC | [VLC](https://www.videolan.org/vlc/) | 首次导入和单条源排查 |
| PC | [PotPlayer](https://potplayer.org/) | Windows 播放与快速切台 |
| Android TV | [mytv-android](https://github.com/yaoxieyoulei/mytv-android/releases) | 电视端导入 M3U |
| Android TV | [TVBox](https://github.com/CatVodTVOfficial/TVBoxOSC) | 支持 M3U 的电视端客户端 |
| iOS / macOS | [APTV](https://apps.apple.com/cn/app/aptv/id1630403500) | Apple 设备播放 |

建议先在 VLC 或 PotPlayer 中导入主地址，确认订阅能读取、单条源能播放后，再配置电视端或移动端客户端。不同播放器对分组、台标和 EPG 的支持可能不同。

## 台标路径

台标随站点发布在：

```text
https://elykia093.github.io/HA-CMCC-IPTV/logos/
```

订阅里的频道会尽量使用类似下面的台标地址：

```text
https://elykia093.github.io/HA-CMCC-IPTV/logos/河南卫视.png
```

台标不显示通常不影响播放。常见原因是播放器不支持 `tvg-logo`、图片缓存未刷新、图片路径被网络拦截。

## 字段说明

| 字段 | 作用 |
| --- | --- |
| `#EXTM3U` | M3U 文件头 |
| `#EXTINF` | 单个频道的元信息 |
| `tvg-name` | 频道名 |
| `tvg-logo` | 台标地址 |
| `group-title` | 播放器中的频道分组 |
| 下一行 URL | 实际播放源地址 |

## 适用环境

本项目整理的是河南移动 IPTV HTTP 单播源，主要适用于河南移动宽带环境。其他运营商、手机流量、普通公网或异地网络通常无法播放。

<div class="note-strip">
  如果订阅能下载但频道不能播，请先到播放排查页按“订阅文件”和“直播源网络”两层分别确认。
</div>
