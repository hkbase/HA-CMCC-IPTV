from __future__ import annotations

import math
import queue
import subprocess
import threading
import tkinter as tk
from collections.abc import Sequence
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from contextlib import suppress
from dataclasses import replace
from functools import partial
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import cast

from .core import (
    AssetInspection,
    Channel,
    PlaybackPreflight,
    ProbeResult,
    app_data_dir,
    capture_frame,
    discover_potplayer,
    export_results_csv,
    export_valid_m3u,
    find_binary,
    inspect_logo,
    launch_ffplay,
    launch_player,
    load_channels,
    load_config,
    preflight_playback,
    probe_channel,
    save_config,
)


def _config_int(config: dict[str, str], key: str, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(int(config.get(key, str(default))), maximum))
    except ValueError:
        return default


def _config_bool(config: dict[str, str], key: str, default: bool) -> bool:
    value = config.get(key)
    return default if value is None else value == "1"


def _adjacent_channel_index(
    visible_indices: Sequence[int], current_index: int | None, step: int
) -> int | None:
    if not visible_indices:
        return None
    if step == 0:
        raise ValueError("切换步长不能为 0")
    direction = 1 if step > 0 else -1
    if current_index not in visible_indices:
        return visible_indices[0] if direction > 0 else visible_indices[-1]
    position = visible_indices.index(current_index)
    return visible_indices[(position + direction) % len(visible_indices)]


def _capture_frame_with_recheck(
    channel: Channel,
    result: ProbeResult,
    ffprobe_path: str,
    ffmpeg_path: str,
    cache_dir: Path,
    timeout: int,
    *,
    force: bool = False,
    stop_event: threading.Event | None = None,
) -> tuple[ProbeResult, AssetInspection]:
    if result.resolution == "纯音频":
        return result, AssetInspection("无视频")

    frame = capture_frame(
        channel,
        ffmpeg_path,
        cache_dir,
        timeout,
        force=force,
        stop_event=stop_event,
    )
    if frame.status in {"已捕获", "已取消", "缺少 FFmpeg"}:
        return result, frame

    rechecked = probe_channel(channel, ffprobe_path, timeout, stop_event)
    if rechecked.status == "已取消":
        return result, AssetInspection("已取消")

    rechecked = replace(
        rechecked,
        logo_status=result.logo_status,
        logo_path=result.logo_path,
        frame_status=result.frame_status,
        frame_path=result.frame_path,
        error=rechecked.error or result.error,
    )
    if not rechecked.valid:
        return rechecked, AssetInspection("源已失效")

    return rechecked, capture_frame(
        channel,
        ffmpeg_path,
        cache_dir,
        timeout,
        force=True,
        stop_event=stop_event,
    )


class SourceCheckerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("IPTV 源检测器")
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        dpi_scale = max(1.0, float(self.root.winfo_fpixels("1i")) / 96.0)
        logical_screen_width = int(screen_width / dpi_scale)
        logical_screen_height = int(screen_height / dpi_scale)
        window_width = max(960, min(1480, logical_screen_width - 64))
        window_height = max(640, min(860, logical_screen_height - 80))
        self.root.geometry(f"{window_width}x{window_height}")
        self.root.minsize(min(1120, window_width), min(700, window_height))

        self.channels: list[Channel] = []
        self.results: dict[int, ProbeResult] = {}
        self.events: queue.Queue[tuple[object, ...]] = queue.Queue()
        self.executor: ThreadPoolExecutor | None = None
        self.stop_event = threading.Event()
        self.scan_generation = 0
        self.load_generation = 0
        self.frame_generation = 0
        self.scan_completed = 0
        self.scan_total = 0
        self.cache_dir = app_data_dir()
        self.repo_root = self._find_repo_root()
        self.logo_dir = self.repo_root / "public" / "logos" if self.repo_root else None
        self.config = load_config()
        self.logo_photo: tk.PhotoImage | None = None
        self.frame_photo: tk.PhotoImage | None = None
        self.playback_active = False
        self.playback_generation = 0
        self.playback_stop_event = threading.Event()
        self.player_process: subprocess.Popen[bytes] | None = None
        configured_player = self.config.get("last_player", "FFplay")
        self.last_player = (
            configured_player if configured_player in {"FFplay", "PotPlayer"} else "FFplay"
        )

        self.source_var = tk.StringVar(value=self.config.get("last_source", ""))
        self.worker_var = tk.IntVar(value=_config_int(self.config, "workers", 8, 1, 32))
        self.timeout_var = tk.IntVar(value=_config_int(self.config, "timeout", 6, 2, 60))
        self.logo_check_var = tk.BooleanVar(
            value=_config_bool(self.config, "check_logo", True)
        )
        self.frame_check_var = tk.BooleanVar(
            value=_config_bool(self.config, "check_frame", True)
        )
        self.search_var = tk.StringVar()
        self.filter_var = tk.StringVar(value="全部")
        self.summary_var = tk.StringVar(value="等待载入播放列表")
        self.status_var = tk.StringVar(value="就绪")

        self._configure_style()
        self._build_ui()
        self._bind_shortcuts()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(100, self._poll_events)

        default_playlist = self.repo_root / "public" / "index.m3u" if self.repo_root else None
        if not self.source_var.get() and default_playlist and default_playlist.is_file():
            self.source_var.set(str(default_playlist))
        if self.source_var.get():
            self.root.after(250, self._load_default_source)

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TButton", padding=(10, 6))
        style.configure("Primary.TButton", padding=(12, 7), font=("Microsoft YaHei UI", 9, "bold"))
        style.configure("Treeview", rowheight=28, font=("Microsoft YaHei UI", 9))
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 9, "bold"))
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 15, "bold"))
        style.configure("Muted.TLabel", foreground="#5f6b7a")

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)

        title_row = ttk.Frame(outer)
        title_row.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(title_row, text="IPTV 源检测器", style="Title.TLabel").pack(side=tk.LEFT)
        ttk.Label(
            title_row,
            text="FFprobe 流信息 · Logo 检测 · FFmpeg 画面 · PotPlayer / FFplay",
            style="Muted.TLabel",
        ).pack(side=tk.LEFT, padx=14)
        ttk.Label(title_row, textvariable=self.summary_var).pack(side=tk.RIGHT)

        source_frame = ttk.LabelFrame(outer, text="检测源", padding=9)
        source_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Entry(source_frame, textvariable=self.source_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )
        ttk.Button(source_frame, text="打开 M3U", command=self.choose_playlist).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Button(source_frame, text="载入", command=self.load_source).pack(
            side=tk.LEFT, padx=(6, 0)
        )

        options = ttk.Frame(outer)
        options.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(options, text="并发").pack(side=tk.LEFT)
        ttk.Spinbox(options, from_=1, to=32, width=5, textvariable=self.worker_var).pack(
            side=tk.LEFT, padx=(5, 12)
        )
        ttk.Label(options, text="超时（秒）").pack(side=tk.LEFT)
        ttk.Spinbox(options, from_=2, to=60, width=5, textvariable=self.timeout_var).pack(
            side=tk.LEFT, padx=(5, 12)
        )
        ttk.Checkbutton(options, text="检测 Logo", variable=self.logo_check_var).pack(side=tk.LEFT)
        ttk.Checkbutton(options, text="捕获画面", variable=self.frame_check_var).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        self.start_button = ttk.Button(
            options,
            text="开始检测",
            command=self.start_scan,
            style="Primary.TButton",
        )
        self.start_button.pack(side=tk.LEFT, padx=(16, 0))
        self.stop_button = ttk.Button(
            options, text="停止", command=self.stop_scan, state=tk.DISABLED
        )
        self.stop_button.pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(options, text="导出 CSV", command=self.export_csv).pack(side=tk.RIGHT)
        ttk.Button(options, text="导出可用 M3U", command=self.export_m3u).pack(
            side=tk.RIGHT, padx=(0, 6)
        )

        filter_row = ttk.Frame(outer)
        filter_row.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(filter_row, text="筛选").pack(side=tk.LEFT)
        filter_box = ttk.Combobox(
            filter_row,
            textvariable=self.filter_var,
            values=("全部", "可用", "异常", "未检测"),
            width=8,
            state="readonly",
        )
        filter_box.pack(side=tk.LEFT, padx=(5, 10))
        filter_box.bind("<<ComboboxSelected>>", lambda _event: self.refresh_table())
        search = ttk.Entry(filter_row, textvariable=self.search_var, width=42)
        search.pack(side=tk.LEFT)
        search.bind("<KeyRelease>", lambda _event: self.refresh_table())
        ttk.Label(filter_row, text="可按频道名、分组或 URL 搜索", style="Muted.TLabel").pack(
            side=tk.LEFT, padx=10
        )
        self.retry_button = ttk.Button(
            filter_row, text="重试异常", command=self.retry_failed
        )
        self.retry_button.pack(side=tk.RIGHT)
        self.scan_selected_button = ttk.Button(
            filter_row, text="检测选中", command=self.scan_selected
        )
        self.scan_selected_button.pack(side=tk.RIGHT, padx=(0, 6))

        paned = ttk.Panedwindow(outer, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)
        table_frame = ttk.Frame(paned)
        preview_frame = ttk.Frame(paned, width=340)
        paned.add(table_frame, weight=5)
        paned.add(preview_frame, weight=2)

        columns = (
            "name",
            "group",
            "status",
            "latency",
            "resolution",
            "fps",
            "video",
            "audio",
            "bitrate",
            "logo",
            "frame",
            "url",
        )
        self.table = ttk.Treeview(
            table_frame, columns=columns, show="headings", selectmode="extended"
        )
        headings = {
            "name": "频道",
            "group": "分组",
            "status": "状态",
            "latency": "耗时",
            "resolution": "分辨率",
            "fps": "帧率",
            "video": "视频",
            "audio": "音频",
            "bitrate": "码率",
            "logo": "Logo",
            "frame": "画面",
            "url": "地址",
        }
        widths = {
            "name": 130,
            "group": 100,
            "status": 78,
            "latency": 72,
            "resolution": 92,
            "fps": 72,
            "video": 68,
            "audio": 68,
            "bitrate": 88,
            "logo": 82,
            "frame": 82,
            "url": 360,
        }
        for column in columns:
            self.table.heading(column, text=headings[column])
            self.table.column(column, width=widths[column], minwidth=55, stretch=column == "url")
        self.table.tag_configure("ok", foreground="#087f5b")
        self.table.tag_configure("error", foreground="#c92a2a")
        self.table.tag_configure("pending", foreground="#667085")
        self.table.bind("<<TreeviewSelect>>", self.show_selection)
        self.table.bind("<Double-1>", lambda _event: self.play_ffplay())

        vertical = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.table.yview)
        horizontal = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL, command=self.table.xview)
        self.table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        preview = ttk.LabelFrame(preview_frame, text="人工复核", padding=10)
        preview.pack(fill=tk.BOTH, expand=True, padx=(10, 0))
        ttk.Label(preview, text="Logo", style="Muted.TLabel").pack(anchor=tk.W)
        self.logo_label = ttk.Label(preview, text="选择频道后显示", anchor=tk.CENTER)
        self.logo_label.pack(fill=tk.X, ipady=16, pady=(2, 8))
        ttk.Separator(preview).pack(fill=tk.X, pady=4)
        ttk.Label(preview, text="捕获画面", style="Muted.TLabel").pack(anchor=tk.W)
        self.frame_label = ttk.Label(preview, text="尚未捕获", anchor=tk.CENTER)
        self.frame_label.pack(fill=tk.X, ipady=40, pady=(2, 8))

        switch_row = ttk.Frame(preview)
        switch_row.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(
            switch_row,
            text="上一频道",
            command=partial(self.quick_switch, -1),
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(
            switch_row,
            text="下一频道",
            command=partial(self.quick_switch, 1),
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))

        player_row = ttk.Frame(preview)
        player_row.pack(fill=tk.X)
        self.ffplay_button = ttk.Button(
            player_row,
            text="FFplay 智能播放",
            command=self.play_ffplay,
            style="Primary.TButton",
        )
        self.ffplay_button.pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )
        self.potplayer_button = ttk.Button(
            player_row, text="PotPlayer 播放", command=self.play_potplayer
        )
        self.potplayer_button.pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0)
        )
        action_row = ttk.Frame(preview)
        action_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(action_row, text="刷新画面", command=self.refresh_selected_frame).pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )
        ttk.Button(action_row, text="复制 URL", command=self.copy_selected_url).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0)
        )

        self.details = tk.Text(
            preview,
            height=7,
            wrap=tk.WORD,
            relief=tk.FLAT,
            background="#f5f7fa",
            font=("Microsoft YaHei UI", 9),
            padx=8,
            pady=8,
        )
        self.details.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self.details.configure(state=tk.DISABLED)

        bottom = ttk.Frame(outer)
        bottom.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0), before=paned)
        self.progress = ttk.Progressbar(bottom, mode="determinate")
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(bottom, textvariable=self.status_var, width=42, anchor=tk.E).pack(
            side=tk.RIGHT, padx=(10, 0)
        )

    def _bind_shortcuts(self) -> None:
        self.root.bind("<Control-o>", lambda _event: self.choose_playlist())
        self.root.bind("<Control-r>", lambda _event: self.start_scan())
        self.root.bind("<Control-e>", lambda _event: self.export_csv())
        self.root.bind("<Control-Up>", lambda _event: self.quick_switch(-1))
        self.root.bind("<Control-Down>", lambda _event: self.quick_switch(1))

    def _find_repo_root(self) -> Path | None:
        for parent in Path(__file__).resolve().parents:
            if (parent / "public" / "index.m3u").is_file():
                return parent
        return None

    def choose_playlist(self) -> None:
        initial = str(self.repo_root / "public") if self.repo_root else str(Path.home())
        selected = filedialog.askopenfilename(
            title="选择 IPTV 播放列表",
            initialdir=initial,
            filetypes=(("播放列表", "*.m3u *.m3u8 *.txt"), ("所有文件", "*.*")),
        )
        if selected:
            self.source_var.set(selected)
            self.load_source()

    def _load_default_source(self) -> None:
        if self.load_generation == 0 and not self.channels and not self.executor:
            self.load_source()

    def _save_preferences(self, source: str | None = None) -> None:
        if source is not None:
            self.config["last_source"] = source
        try:
            workers = _config_int(
                {"value": str(self.worker_var.get())}, "value", 8, 1, 32
            )
            timeout = _config_int(
                {"value": str(self.timeout_var.get())}, "value", 6, 2, 60
            )
        except tk.TclError:
            workers = _config_int(self.config, "workers", 8, 1, 32)
            timeout = _config_int(self.config, "timeout", 6, 2, 60)
        self.config.update(
            {
                "workers": str(workers),
                "timeout": str(timeout),
                "check_logo": "1" if self.logo_check_var.get() else "0",
                "check_frame": "1" if self.frame_check_var.get() else "0",
                "last_player": self.last_player,
            }
        )
        try:
            save_config(self.config)
        except OSError as exc:
            self.status_var.set(f"设置保存失败：{exc}")

    def load_source(self) -> None:
        if self.executor:
            messagebox.showinfo("正在检测", "请先停止当前检测并等待任务收口，再载入新列表。")
            return
        source = self.source_var.get().strip()
        if not source:
            messagebox.showwarning("缺少来源", "请输入 M3U 文件路径或 HTTP(S) 地址。")
            return
        self.load_generation += 1
        generation = self.load_generation
        self.status_var.set("正在载入播放列表…")
        self.start_button.configure(state=tk.DISABLED)

        def task() -> None:
            try:
                channels = load_channels(source)
            except ValueError as exc:
                self.events.put(("load_error", generation, str(exc)))
                return
            self.events.put(("loaded", generation, source, channels))

        threading.Thread(target=task, name="playlist-loader", daemon=True).start()

    def _handle_loaded(self, source: str, channels: list[Channel]) -> None:
        self.frame_generation += 1
        if self.playback_active:
            self.playback_stop_event.set()
            self.playback_generation += 1
            self.playback_active = False
        self.channels = channels
        self.results = {channel.index: ProbeResult(channel.index) for channel in channels}
        self.summary_var.set(f"已载入 {len(channels)} 条源")
        self.status_var.set("播放列表载入完成")
        self.start_button.configure(state=tk.NORMAL)
        self.progress.configure(maximum=max(1, len(channels)), value=0)
        self.refresh_table()
        self._save_preferences(source)

    def _visible(self, channel: Channel) -> bool:
        result = self.results.get(channel.index, ProbeResult(channel.index))
        selected_filter = self.filter_var.get()
        if selected_filter == "可用" and not result.valid:
            return False
        if selected_filter == "异常" and (result.valid or result.status == "待检测"):
            return False
        if selected_filter == "未检测" and result.status not in {"待检测", "排队中"}:
            return False
        query = self.search_var.get().strip().casefold()
        return not query or query in f"{channel.name} {channel.group} {channel.url}".casefold()

    def _row_values(self, channel: Channel, result: ProbeResult) -> tuple[str, ...]:
        latency = f"{result.latency_ms} ms" if result.latency_ms is not None else ""
        return (
            channel.name,
            channel.group,
            result.status,
            latency,
            result.resolution,
            result.frame_rate,
            result.video_codec,
            result.audio_codec,
            result.bitrate,
            result.logo_status,
            result.frame_status,
            channel.url,
        )

    @staticmethod
    def _row_tag(result: ProbeResult) -> str:
        if result.valid:
            return "ok"
        if result.status in {"待检测", "排队中"}:
            return "pending"
        return "error"

    def refresh_table(self) -> None:
        self.table.delete(*self.table.get_children())
        for channel in self.channels:
            if not self._visible(channel):
                continue
            result = self.results.get(channel.index, ProbeResult(channel.index))
            self.table.insert(
                "",
                tk.END,
                iid=str(channel.index),
                values=self._row_values(channel, result),
                tags=(self._row_tag(result),),
            )

    def scan_selected(self) -> None:
        selection = self.table.selection()
        if not selection:
            messagebox.showinfo("未选择频道", "请先选择一个或多个频道。")
            return
        self.start_scan([self.channels[int(item)] for item in selection])

    def retry_failed(self) -> None:
        failed = [
            channel
            for channel in self.channels
            if not self.results.get(channel.index, ProbeResult(channel.index)).valid
            and self.results.get(channel.index, ProbeResult(channel.index)).status
            not in {"待检测", "排队中"}
        ]
        if not failed:
            messagebox.showinfo("没有异常源", "当前没有需要重试的异常源。")
            return
        self.start_scan(failed)

    def _set_scan_controls(self, running: bool) -> None:
        normal_state = tk.DISABLED if running else tk.NORMAL
        self.start_button.configure(state=normal_state)
        self.scan_selected_button.configure(state=normal_state)
        self.retry_button.configure(state=normal_state)
        self.stop_button.configure(state=tk.NORMAL if running else tk.DISABLED)

    def start_scan(self, channels: list[Channel] | None = None) -> None:
        if not self.channels:
            messagebox.showwarning("没有频道", "请先载入播放列表。")
            return
        if self.executor:
            messagebox.showinfo("正在检测", "当前检测尚未结束。")
            return
        ffprobe_path = find_binary("ffprobe", self.config.get("ffprobe_path", ""))
        if not ffprobe_path:
            messagebox.showerror("缺少 FFprobe", "未找到 ffprobe，请安装 FFmpeg 或在 PATH 中配置。")
            return
        ffmpeg_path = find_binary("ffmpeg", self.config.get("ffmpeg_path", ""))
        if self.frame_check_var.get() and not ffmpeg_path:
            messagebox.showerror("缺少 FFmpeg", "已勾选捕获画面，但未找到 ffmpeg。")
            return
        try:
            workers = max(1, min(int(self.worker_var.get()), 32))
            timeout = max(2, min(int(self.timeout_var.get()), 60))
        except (tk.TclError, ValueError):
            messagebox.showerror("参数错误", "并发数和超时必须是整数。")
            return

        targets = self.channels if channels is None else channels
        if not targets:
            messagebox.showinfo("没有频道", "没有符合条件的待检测频道。")
            return

        self.scan_generation += 1
        generation = self.scan_generation
        self.scan_completed = 0
        self.scan_total = len(targets)
        self.stop_event = threading.Event()
        self.executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="iptv-check")
        self._set_scan_controls(True)
        self.progress.configure(maximum=self.scan_total, value=0)
        self.status_var.set(f"开始检测 {self.scan_total} 条：并发 {workers}，超时 {timeout} 秒")
        self._save_preferences()

        for channel in targets:
            queued = ProbeResult(channel.index, status="排队中")
            self._store_result(queued)
            future = self.executor.submit(
                self._inspect_one,
                channel,
                ffprobe_path,
                ffmpeg_path,
                timeout,
                self.logo_check_var.get(),
                self.frame_check_var.get(),
                generation,
            )
            future.add_done_callback(
                partial(self._scan_callback, channel=channel, generation=generation)
            )

    def _inspect_one(
        self,
        channel: Channel,
        ffprobe_path: str,
        ffmpeg_path: str,
        timeout: int,
        check_logo: bool,
        check_frame: bool,
        generation: int,
    ) -> ProbeResult:
        if self.stop_event.is_set():
            return ProbeResult(channel.index, status="已取消")
        result = probe_channel(channel, ffprobe_path, timeout, self.stop_event)
        if result.status == "已取消":
            return result
        if check_logo:
            result.logo_status = "检测中"
        if check_frame:
            result.frame_status = "检测中" if result.valid else "已跳过"
        if check_logo or (check_frame and result.valid):
            self.events.put(("scan_update", generation, replace(result)))
        if self.stop_event.is_set():
            result.logo_status = "已取消" if result.logo_status == "检测中" else result.logo_status
            result.frame_status = (
                "已取消" if result.frame_status == "检测中" else result.frame_status
            )
            return result
        if check_logo and not self.stop_event.is_set():
            logo = inspect_logo(channel, self.logo_dir, self.cache_dir, timeout)
            result.logo_status = logo.status
            result.logo_path = logo.path
            if logo.error and not result.error:
                result.error = f"Logo：{logo.error}"
        if check_frame and result.valid and not self.stop_event.is_set():
            result, frame = _capture_frame_with_recheck(
                channel,
                result,
                ffprobe_path,
                ffmpeg_path,
                self.cache_dir,
                timeout,
                stop_event=self.stop_event,
            )
            result.frame_status = frame.status
            result.frame_path = frame.path
            if frame.error and not result.error:
                result.error = f"画面：{frame.error}"
        return result

    def _scan_callback(
        self,
        future: Future[ProbeResult],
        channel: Channel,
        generation: int,
    ) -> None:
        try:
            result = future.result()
        except CancelledError:
            result = ProbeResult(channel.index, status="已取消")
        except Exception as exc:  # GUI worker boundary: preserve progress and surface the failure.
            result = ProbeResult(channel.index, status="内部错误", error=str(exc))
        self.events.put(("scan_result", generation, result))

    def stop_scan(self) -> None:
        if not self.executor:
            return
        self.stop_event.set()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.status_var.set("正在终止 FFmpeg/FFprobe 并收口结果…")
        self.stop_button.configure(state=tk.DISABLED)

    def _finish_scan(self) -> None:
        if self.executor:
            self.executor.shutdown(wait=False)
        self.executor = None
        self._set_scan_controls(False)
        valid = sum(result.valid for result in self.results.values())
        invalid = sum(
            result.status not in {"待检测", "已取消"} and not result.valid
            for result in self.results.values()
        )
        cancelled = sum(
            "已取消" in {result.status, result.logo_status, result.frame_status}
            for result in self.results.values()
        )
        self.summary_var.set(
            f"可用 {valid} · 异常 {invalid} · 取消 {cancelled} · 总计 {len(self.channels)}"
        )
        self.status_var.set("检测已停止" if self.stop_event.is_set() else "检测完成")

    def _poll_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "loaded":
                    _, generation, source, channels = event
                    if generation == self.load_generation:
                        self._handle_loaded(str(source), cast(list[Channel], channels))
                elif kind == "load_error":
                    _, generation, error = event
                    if generation == self.load_generation:
                        self.status_var.set("播放列表载入失败")
                        self.start_button.configure(state=tk.NORMAL)
                        messagebox.showerror("载入失败", str(error))
                elif kind == "scan_result":
                    _, generation, result = event
                    if generation == self.scan_generation:
                        self._handle_scan_result(cast(ProbeResult, result))
                elif kind == "scan_update":
                    _, generation, result = event
                    if generation == self.scan_generation:
                        self._store_result(cast(ProbeResult, result))
                elif kind == "frame_result":
                    _, generation, index, result, inspection = event
                    if generation == self.frame_generation:
                        self._handle_frame_result(
                            cast(int, index),
                            cast(ProbeResult, result),
                            cast(AssetInspection, inspection),
                        )
                elif kind == "playback_ready":
                    (
                        _,
                        generation,
                        player,
                        executable,
                        channel,
                        preflight,
                        quiet_failure,
                    ) = event
                    if generation == self.playback_generation:
                        self._handle_playback_ready(
                            str(player),
                            str(executable),
                            cast(Channel, channel),
                            cast(PlaybackPreflight, preflight),
                            bool(quiet_failure),
                        )
        except queue.Empty:
            pass
        if self.root.winfo_exists():
            self.root.after(100, self._poll_events)

    def _store_result(self, result: ProbeResult) -> None:
        self.results[result.index] = result
        iid = str(result.index)
        if self.table.exists(iid):
            channel = self.channels[result.index]
            self.table.item(
                iid,
                values=self._row_values(channel, result),
                tags=(self._row_tag(result),),
            )

    def _handle_scan_result(self, result: ProbeResult) -> None:
        self._store_result(result)
        self.scan_completed += 1
        self.progress.configure(value=self.scan_completed)
        valid = sum(item.valid for item in self.results.values())
        self.summary_var.set(f"进度 {self.scan_completed}/{self.scan_total} · 可用 {valid}")
        self.status_var.set(f"正在检测 {self.scan_completed}/{self.scan_total}")
        if self.scan_completed >= self.scan_total:
            self._finish_scan()

    def selected_channel(self) -> Channel | None:
        selection = self.table.selection()
        if not selection:
            return None
        index = int(selection[0])
        return self.channels[index] if 0 <= index < len(self.channels) else None

    def show_selection(self, _event: object | None = None) -> None:
        channel = self.selected_channel()
        if not channel:
            return
        result = self.results.get(channel.index, ProbeResult(channel.index))
        self.logo_photo = self._show_image(
            self.logo_label,
            result.logo_path,
            220,
            60,
            result.logo_status,
        )
        self.frame_photo = self._show_image(
            self.frame_label,
            result.frame_path,
            280,
            120,
            result.frame_status,
        )
        details = [
            f"频道：{channel.name}",
            f"分组：{channel.group}",
            f"状态：{result.status}",
            f"耗时：{result.latency_ms or '-'} ms",
            (
                f"视频：{result.video_codec or '-'} · {result.resolution or '-'} · "
                f"{result.frame_rate or '-'}"
            ),
            (
                f"音频：{result.audio_codec or '-'} · {result.audio_channels or '-'} · "
                f"{result.sample_rate or '-'}"
            ),
            f"码率：{result.bitrate or '-'}",
            f"封装：{result.container or '-'}",
            f"像素/HDR：{result.pixel_format or '-'} · {result.hdr or '-'}",
            f"服务名：{result.service_name or '-'}",
            f"Logo：{result.logo_status}",
            f"画面：{result.frame_status}",
            f"错误：{result.error or '-'}",
            "",
            f"URL：{channel.url}",
        ]
        self.details.configure(state=tk.NORMAL)
        self.details.delete("1.0", tk.END)
        self.details.insert("1.0", "\n".join(details))
        self.details.configure(state=tk.DISABLED)

    @staticmethod
    def _show_image(
        label: ttk.Label,
        path: str,
        max_width: int,
        max_height: int,
        fallback: str,
    ) -> tk.PhotoImage | None:
        if not path or not Path(path).is_file():
            label.configure(image="", text=fallback or "无")
            return None
        try:
            original = tk.PhotoImage(file=path)
        except tk.TclError:
            label.configure(image="", text=f"{fallback}\n（格式无法内置显示）")
            return None
        factor = max(
            1,
            math.ceil(original.width() / max_width),
            math.ceil(original.height() / max_height),
        )
        photo = original.subsample(factor) if factor > 1 else original
        label.configure(image=photo, text="")
        return photo

    def refresh_selected_frame(self) -> None:
        channel = self.selected_channel()
        if not channel:
            messagebox.showinfo("未选择频道", "请先选择一个频道。")
            return
        ffmpeg_path = find_binary("ffmpeg", self.config.get("ffmpeg_path", ""))
        if not ffmpeg_path:
            messagebox.showerror("缺少 FFmpeg", "未找到 ffmpeg。")
            return
        ffprobe_path = find_binary("ffprobe", self.config.get("ffprobe_path", ""))
        if not ffprobe_path:
            messagebox.showerror("缺少 FFprobe", "刷新画面失败后复检源需要 ffprobe。")
            return
        try:
            timeout = max(2, min(int(self.timeout_var.get()), 60))
        except (tk.TclError, ValueError):
            messagebox.showerror("参数错误", "超时必须是整数。")
            return
        self.frame_generation += 1
        generation = self.frame_generation
        self.status_var.set(f"正在刷新 {channel.name} 的画面…")
        current_result = replace(self.results.get(channel.index, ProbeResult(channel.index)))

        def task() -> None:
            result, inspection = _capture_frame_with_recheck(
                channel,
                current_result,
                ffprobe_path,
                ffmpeg_path,
                self.cache_dir,
                timeout,
                force=True,
            )
            self.events.put(("frame_result", generation, channel.index, result, inspection))

        threading.Thread(target=task, name="frame-refresh", daemon=True).start()

    def _handle_frame_result(
        self, index: int, result: ProbeResult, inspection: AssetInspection
    ) -> None:
        self.results[index] = result
        result.frame_status = inspection.status
        result.frame_path = inspection.path
        if inspection.error:
            result.error = f"画面：{inspection.error}"
        self.status_var.set(f"画面刷新：{result.frame_status}")
        self.show_selection()

    def _begin_playback(
        self,
        channel: Channel,
        player: str,
        executable: str,
        *,
        quiet_failure: bool = False,
    ) -> None:
        ffprobe_path = find_binary("ffprobe", self.config.get("ffprobe_path", ""))
        if not ffprobe_path:
            messagebox.showerror("缺少 FFprobe", "播放前复检需要 ffprobe。")
            return

        try:
            timeout = max(2, min(int(self.timeout_var.get()), 60))
        except (tk.TclError, ValueError):
            messagebox.showerror("参数错误", "超时必须是整数。")
            return
        if self.playback_active:
            self.playback_stop_event.set()
        self.playback_generation += 1
        generation = self.playback_generation
        stop_event = threading.Event()
        self.playback_stop_event = stop_event
        self.playback_active = True
        self.status_var.set(f"正在复检 {channel.name}，通过后自动启动 {player}…")

        def task() -> None:
            preflight = preflight_playback(
                channel,
                ffprobe_path,
                timeout=timeout,
                stop_event=stop_event,
            )
            self.events.put(
                (
                    "playback_ready",
                    generation,
                    player,
                    executable,
                    channel,
                    preflight,
                    quiet_failure,
                )
            )

        threading.Thread(target=task, name="playback-preflight", daemon=True).start()

    def _handle_playback_ready(
        self,
        player: str,
        executable: str,
        channel: Channel,
        preflight: PlaybackPreflight,
        quiet_failure: bool,
    ) -> None:
        self.playback_active = False

        current_result = self.results.get(channel.index)
        fresh_result = preflight.result
        if current_result:
            fresh_result = replace(
                fresh_result,
                logo_status=current_result.logo_status,
                logo_path=current_result.logo_path,
                frame_status=current_result.frame_status,
                frame_path=current_result.frame_path,
            )
        if (
            0 <= channel.index < len(self.channels)
            and self.channels[channel.index].url == channel.url
        ):
            self._store_result(fresh_result)
            self.show_selection()

        if not fresh_result.valid:
            reason = fresh_result.error or fresh_result.status
            self.status_var.set(f"播放前复检失败：{fresh_result.status} · {reason}")
            if not quiet_failure:
                messagebox.showerror(
                    "源当前不可播放",
                    f"{channel.name} 播放前复检失败。\n\n"
                    f"状态：{fresh_result.status}\n原因：{reason}\n\n"
                    "该源可能已过期或临时下线，播放器未启动。",
                )
            return

        playback_channel = replace(channel, url=preflight.playback_url)
        self._stop_active_player()
        try:
            if player == "FFplay":
                process = launch_ffplay(executable, playback_channel)
            else:
                process = launch_player(executable, playback_channel)
        except (OSError, ValueError) as exc:
            self.status_var.set(f"{player} 启动失败")
            messagebox.showerror("启动失败", str(exc))
            return
        self.player_process = process

        notes = ["复检通过"]
        if preflight.http_status:
            notes.append(f"HTTP {preflight.http_status}")
        if preflight.redirected:
            notes.append("已使用跳转后的最终地址")
        elif preflight.resolution_error:
            notes.append("最终地址解析失败，使用原地址")
        self.status_var.set(f"{player} 已启动：" + " · ".join(notes))

    def _stop_active_player(self) -> None:
        process = self.player_process
        self.player_process = None
        if not process or process.poll() is not None:
            return
        with suppress(OSError):
            process.terminate()

    def _play_channel(
        self, channel: Channel, player: str, *, quiet_failure: bool = False
    ) -> None:
        if player == "PotPlayer":
            executable = discover_potplayer(self.config.get("potplayer_path", ""))
            if not executable:
                selected = filedialog.askopenfilename(
                    title="选择 PotPlayer 可执行文件",
                    filetypes=(("PotPlayer", "PotPlayer*.exe"), ("可执行文件", "*.exe")),
                )
                if not selected:
                    messagebox.showwarning(
                        "未找到 PotPlayer",
                        "未自动发现 PotPlayer。可安装后重试，或手动选择 PotPlayerMini64.exe。",
                    )
                    return
                executable = selected
                self.config["potplayer_path"] = selected
        else:
            executable = find_binary("ffplay", self.config.get("ffplay_path", ""))
            if not executable:
                messagebox.showerror("缺少 FFplay", "未找到 ffplay；它通常随 FFmpeg 一起安装。")
                return

        self.last_player = player
        self._save_preferences()
        self._begin_playback(
            channel,
            player,
            executable,
            quiet_failure=quiet_failure,
        )

    def play_potplayer(self) -> None:
        channel = self.selected_channel()
        if not channel:
            messagebox.showinfo("未选择频道", "请先选择一个频道。")
            return
        self._play_channel(channel, "PotPlayer")

    def play_ffplay(self) -> None:
        channel = self.selected_channel()
        if not channel:
            messagebox.showinfo("未选择频道", "请先选择一个频道。")
            return
        self._play_channel(channel, "FFplay")

    def quick_switch(self, step: int) -> None:
        visible_items = list(self.table.get_children())
        visible_indices = [int(item) for item in visible_items]
        if not visible_indices:
            self.status_var.set("当前筛选条件下没有可切换的频道")
            return

        focused = self.table.focus()
        selected = self.selected_channel()
        current_index = (
            int(focused)
            if focused in visible_items
            else selected.index if selected is not None else None
        )
        target_index = _adjacent_channel_index(visible_indices, current_index, step)
        if target_index is None:
            return

        target_item = str(target_index)
        self.table.selection_set(target_item)
        self.table.focus(target_item)
        self.table.see(target_item)
        self.show_selection()
        self._play_channel(
            self.channels[target_index],
            self.last_player,
            quiet_failure=True,
        )

    def copy_selected_url(self) -> None:
        channel = self.selected_channel()
        if not channel:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(channel.url)
        self.status_var.set("URL 已复制")

    def _export_initial_dir(self) -> str:
        if self.repo_root:
            reports = self.repo_root / "reports"
            reports.mkdir(exist_ok=True)
            return str(reports)
        return str(Path.home())

    def export_csv(self) -> None:
        if not self.channels:
            messagebox.showinfo("没有结果", "请先载入并检测播放列表。")
            return
        target = filedialog.asksaveasfilename(
            title="导出检测结果",
            initialdir=self._export_initial_dir(),
            initialfile="iptv-check-results.csv",
            defaultextension=".csv",
            filetypes=(("CSV", "*.csv"),),
        )
        if not target:
            return
        try:
            export_results_csv(target, self.channels, self.results)
        except OSError as exc:
            messagebox.showerror("导出失败", str(exc))
            return
        self.status_var.set(f"CSV 已导出：{target}")

    def export_m3u(self) -> None:
        if not any(result.valid for result in self.results.values()):
            messagebox.showinfo("没有可用源", "当前没有已检测为可用的频道。")
            return
        target = filedialog.asksaveasfilename(
            title="导出可用源",
            initialdir=self._export_initial_dir(),
            initialfile="iptv-valid.m3u",
            defaultextension=".m3u",
            filetypes=(("M3U", "*.m3u"),),
        )
        if not target:
            return
        try:
            count = export_valid_m3u(target, self.channels, self.results)
        except OSError as exc:
            messagebox.showerror("导出失败", str(exc))
            return
        self.status_var.set(f"已导出 {count} 条可用源")

    def close(self) -> None:
        self._save_preferences()
        self.stop_event.set()
        self.playback_stop_event.set()
        if self.executor:
            self.executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    try:
        SourceCheckerApp(root)
        root.mainloop()
    except tk.TclError as exc:
        raise SystemExit(f"无法启动图形界面：{exc}") from exc


if __name__ == "__main__":
    main()
