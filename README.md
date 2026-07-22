# 河南移动 IPTV

面向河南移动宽带环境整理的 IPTV HTTP 单播源。仓库只维护播放列表、台标、说明文档和配套工具，不提供、不代理，也不存储任何直播内容。

[文档站](https://elykia093.github.io/HA-CMCC-IPTV/) · [快速开始](https://elykia093.github.io/HA-CMCC-IPTV/start) · [频道列表](https://elykia093.github.io/HA-CMCC-IPTV/channels) · [播放排查](https://elykia093.github.io/HA-CMCC-IPTV/troubleshooting)

## 开始使用

### M3U 订阅

```text
https://elykia093.github.io/HA-CMCC-IPTV/index.m3u
```

将上面的地址添加到支持远程 M3U 的播放器即可。当前播放列表已经在文件头引用节目单，也可以在播放器中单独填写 EPG 地址：

```text
https://epg.zsdc.eu.org/t.xml
```

> [!IMPORTANT]
> 订阅文件托管在 GitHub Pages，但直播源位于河南移动 IPTV 网络。能够下载 M3U 只说明订阅可访问，不代表当前网络可以访问直播源。其他运营商、手机流量、普通公网和异地出口通常无法播放。

<details>
<summary>备用订阅地址</summary>

```text
https://cdn.jsdelivr.net/gh/Elykia093/HA-CMCC-IPTV@main/public/index.m3u
https://fastly.jsdelivr.net/gh/Elykia093/HA-CMCC-IPTV@main/public/index.m3u
https://mirror.ghproxy.com/raw.githubusercontent.com/Elykia093/HA-CMCC-IPTV/main/public/index.m3u
```

备用节点只用于解决订阅下载问题，不能改善直播源的网络可达性。节点可能存在缓存延迟，仓库更新后不一定立即生效。

</details>

### 播放器建议

| 平台 | 播放器 | 适合场景 |
| --- | --- | --- |
| Windows / Linux / macOS | [VLC](https://www.videolan.org/vlc/) | 首次导入、验证单条源和排查播放问题 |
| Windows | [PotPlayer](https://potplayer.daum.net/) | Windows 日常播放和快速切台 |
| Android TV | [mytv-android](https://github.com/yaoxieyoulei/mytv-android/releases) | 电视端长期订阅与播放 |
| Android TV | [TVBox](https://github.com/CatVodTVOfficial/TVBoxOSC) | 已使用 TVBox 生态并需要导入 M3U |
| iOS / macOS | [APTV](https://apps.apple.com/cn/app/aptv/id1630403500) | Apple 设备订阅与播放 |

首次使用建议先通过 VLC 或 PotPlayer 确认订阅能读取、单条源能播放，再配置电视端或移动端。不同播放器对频道分组、台标和 EPG 的支持可能不同。

### 无法播放时先判断

- **订阅无法下载**：尝试备用地址，并查看[快速开始](https://elykia093.github.io/HA-CMCC-IPTV/start)。
- **频道列表正常但全部无法播放**：优先检查是否处于河南移动宽带及对应 IPTV 网络环境。
- **只有部分频道失效或错台**：查看[源状态](https://elykia093.github.io/HA-CMCC-IPTV/status)和[播放排查](https://elykia093.github.io/HA-CMCC-IPTV/troubleshooting)。

## 仓库内容

| 内容 | 作用 |
| --- | --- |
| `public/index.m3u` | 唯一维护的 M3U 播放列表 |
| `public/logos/` | 随 GitHub Pages 发布的频道台标 |
| VitePress 文档 | 快速开始、频道浏览、订阅说明、状态、排查与维护文档 |
| `tools/iptv-source-checker/` | 用于源检测和人工复核的桌面工具 |

频道页直接解析当前 M3U，不在 README 维护容易过期的频道或线路数量。M3U 字段、台标路径和网络边界见[订阅说明](https://elykia093.github.io/HA-CMCC-IPTV/usage)，维护口径见[维护文档](https://elykia093.github.io/HA-CMCC-IPTV/maintain)。

## IPTV 源检测器

仓库内置 Windows 优先的 Python + Tkinter 桌面工具，通过 FFprobe/FFmpeg 检测媒体信息和真实画面：

```powershell
python tools/iptv-source-checker/run.py
```

主要能力：

- 并发检查播放状态、耗时、分辨率、编码、码率、HDR 和音频信息。
- 检查在线或本地 Logo，并使用 FFmpeg 抓帧辅助人工确认频道内容。
- 播放前重新检查当前源，再交给 FFplay 或 PotPlayer 播放。
- 导出完整 CSV，或导出仅包含本轮可用源的 M3U。

工具的产品方向和检测字段参考了 [IPTV-Scanner-Editor-Pro](https://github.com/sumingyd/IPTV-Scanner-Editor-Pro)，当前实现为面向本仓库维护流程的独立精简版本。详细说明见[检测器文档](tools/iptv-source-checker/README.md)，参考项目归属和许可见[第三方许可说明](tools/iptv-source-checker/THIRD_PARTY_NOTICES.md)。

## 维护原则

- `public/index.m3u` 是唯一的播放列表事实来源，不维护平行副本。
- 频道、线路、台标和检测结论均以人工复核为准。
- 明确错台的线路才移动或删除；单次超时或抓帧失败不直接作为删除依据。
- `reports/` 只保存本地检测报告、截图和复核结果，由 Git 忽略。
- 不自动采集、同步或发布直播源；GitHub Actions 只负责项目检查和文档站发布。

## 项目结构

```text
HA-CMCC-IPTV
├─ 直播资源
│  ├─ public/index.m3u          # 主订阅
│  └─ public/logos/             # 频道台标
│
├─ 文档站
│  ├─ .vitepress/               # 站点配置与主题
│  └─ *.md                      # 使用、频道、状态与维护文档
│
├─ 维护工具
│  └─ tools/iptv-source-checker/
│     ├─ 源检测与画质排序
│     ├─ 播放、抓帧与结果导出
│     └─ 本地人工复核
│
└─ 自动化
   └─ .github/workflows/        # 项目检查与文档站发布
```

## 本地开发

启动 VitePress 文档站：

```bash
npm ci
npm run docs:dev
```

提交前执行完整构建检查：

```bash
npm run check
```

检测器的 Python 环境、测试、Ruff 和 mypy 命令见[开发验证说明](tools/iptv-source-checker/README.md#开发验证)。

## 免责声明与许可

本仓库仅整理公开可获得的直播源地址，不保证频道、线路、台标或节目单长期可用。
直播内容、直播地址、EPG、频道台标及相关权利归各自权利人所有，不在本项目许可证授权范围内。

- 原创代码按 [GPL-3.0](https://github.com/Elykia093/HA-CMCC-IPTV/blob/main/LICENSE) 发布；
- 原创文档按 [CC BY-NC-SA 4.0](https://github.com/Elykia093/HA-CMCC-IPTV/blob/main/LICENSE-DOCS.md) 发布；
- 第三方项目和素材按其各自条款使用，已知归属见对应的 `THIRD_PARTY_NOTICES.md`。

完整的适用范围、署名要求与排除项见
[许可范围说明](https://github.com/Elykia093/HA-CMCC-IPTV/blob/main/LICENSING.md)。
