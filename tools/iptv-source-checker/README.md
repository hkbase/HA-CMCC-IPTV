# IPTV 源检测器

面向 `HA-CMCC-IPTV` 播放列表的 Windows 优先桌面检测工具。实现思路参考了
[IPTV-Scanner-Editor-Pro](https://github.com/sumingyd/IPTV-Scanner-Editor-Pro)，但本工具只保留源复核所需的最小链路，运行时不需要安装 Python 三方包。

## 能做什么

- 读取本地或 HTTP(S) 的 M3U/M3U8/TXT 播放列表。
- 并发检测源是否可用，并显示耗时、分辨率、帧率、视频/音频编码、码率、封装、像素格式、HDR、声道和服务名。
- 检测 `tvg-logo` 在线图片；优先匹配仓库 `public/logos/` 中的本地台标。
- 使用 FFmpeg 为每个可用源捕获一帧，在右侧直接预览真实画面。
- 双击频道或点击“FFplay 智能播放”实时预览，播放前会再次用 FFprobe 复检。
- 一键用 PotPlayer 播放；复检通过后会尽量把 HTTP 跳转后的最终地址交给播放器。
- 使用“上一频道 / 下一频道”或 `Ctrl+↑` / `Ctrl+↓` 快速切台，并沿用最近选择的播放器。
- 播放前发现 404、403、超时等异常时直接更新频道状态并阻止启动失效源。
- 支持多选检测与一键重试异常源，按状态/关键字筛选结果。
- 流信息完成后立即刷新，Logo 与画面继续后台补齐；停止时主动终止 FFprobe/FFmpeg。
- 抓帧失败时自动复检源：源已失效会同步更新主状态，源仍可用则自动重试一次画面；纯音频显示“无视频”。
- 导出完整 CSV 或仅含可用源的 M3U。

## 运行要求

- Windows 10/11（核心逻辑也可在 macOS/Linux 运行）。
- Python 3.11 或更高版本，需包含 Tkinter。
- `ffprobe` 和 `ffmpeg` 位于 `PATH`；实时预览还需要 `ffplay`。
- PotPlayer 为可选项。

确认工具可见：

```powershell
ffprobe -version
ffmpeg -version
ffplay -version
```

## 直接运行

在本目录执行：

```powershell
python run.py
```

从仓库根目录执行：

```powershell
python tools/iptv-source-checker/run.py
```

程序会自动载入仓库的 `public/index.m3u`。也可以打开其他本地文件，或在顶部粘贴在线订阅地址后点击“载入”。

## Logo 与画面人工复核

已有 `reports/frame_check_*` 捕获报告时，可直接启动专用复核页，无需重新扫描直播源：

```powershell
python run_review.py
```

从仓库根目录执行：

```powershell
python tools/iptv-source-checker/run_review.py
```

工具默认读取当前 `public/index.m3u` 和最新的 `frame_check_*` 报告，并自动打开
`http://127.0.0.1:8765`。页面按当前 M3U 过滤已删除的旧源，并排显示 Logo、画面左上角和完整捕获帧，可标记“一致 / 不一致 / 无法确定”、填写备注和筛选待复核条目。

结论会自动保存到对应报告目录的 `manual_reviews.json` 和 `manual_reviews.csv`；页面右上角也可下载 CSV。指定其他报告时使用：

```powershell
python run_review.py --report ..\..\reports\frame_check_20260707_021408
```

## 同频道按画质排序

排序工具会真实调用 FFprobe，并且只调整连续的同名频道源。排序顺序为：可用优先、
分辨率像素数、码率、帧率，指标相同则保持原顺序。失败源不会删除，只会排到同频道末尾。

先运行预演并生成 CSV 报告，不写播放列表：

```powershell
python sort_quality.py
```

核对预演结果后，复用报告写回；写回前会在 `reports/` 自动备份原播放列表：

```powershell
python sort_quality.py --reuse-report ..\..\reports\source_quality_YYYYMMDD_HHMMSS.csv --apply
```

建议首次全量检测时使用：

- 并发：`8`
- 超时：`6` 秒
- Logo 检测：开启
- 捕获画面：开启；如只想快速筛查连通性，可临时关闭

双击结果行默认使用 FFplay；也可点击“PotPlayer 播放”。两个入口都会先复检当前源，避免扫描时可用、点击时已经失效造成播放器报错。

播放后可用“上一频道 / 下一频道”快速切换当前筛选结果；到达首尾时会循环。连续切换会取消尚未完成的上一条复检，只启动最后选中的频道，并自动关闭本工具启动的旧播放器窗口。快速切台遇到失效源时不会弹窗打断，可继续切换并在状态栏查看原因。

需要局部复核时可按 `Ctrl` / `Shift` 多选频道，再点击“检测选中”；完成后点击“重试异常”只重新检测失败和已取消的源。并发数、超时、Logo/画面选项和上次播放列表会自动保存。

## 缓存与导出

- Logo、抓帧和播放器路径配置保存在用户目录下的 `IPTVSourceChecker`，不写回订阅文件。
- CSV/M3U 默认建议导出到仓库的 `reports/`，该目录已被 Git 忽略。
- “导出可用 M3U”只包含本轮检测结果中 `valid=true` 的频道。

## 开发验证

项目使用 `pyproject.toml` + `uv.lock` 管理开发工具：

```powershell
cd tools/iptv-source-checker
uv sync
uv run pytest
uv run ruff check .
uv run mypy src
```

测试中的媒体集成用例会在临时目录生成 1 秒合成视频，真实调用本机 FFmpeg/FFprobe，不访问公网源。

## 边界

- 内置画面区是静帧复核，不是完整播放器；实时画面使用 FFplay 或 PotPlayer。
- 组播/运营商内网源只能在具备对应网络路由的机器上得到有效结果。
- 任意 URL 都由本机 FFmpeg/FFprobe 主动访问；只导入可信播放列表。

参考项目采用 MIT 许可，归属说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
本工具随主仓库按
[GPL-3.0](https://github.com/Elykia093/HA-CMCC-IPTV/blob/main/LICENSE) 发布，具体范围见
[仓库许可说明](https://github.com/Elykia093/HA-CMCC-IPTV/blob/main/LICENSING.md)。
