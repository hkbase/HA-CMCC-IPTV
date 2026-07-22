from __future__ import annotations

import queue
import threading
from pathlib import Path

import pytest

import iptv_source_checker.app as app_module
from iptv_source_checker.app import (
    SourceCheckerApp,
    _adjacent_channel_index,
    _capture_frame_with_recheck,
)
from iptv_source_checker.core import AssetInspection, Channel, PlaybackPreflight, ProbeResult


@pytest.mark.parametrize(
    ("current", "step", "expected"),
    [
        (10, 1, 20),
        (30, 1, 10),
        (20, -1, 10),
        (10, -1, 30),
        (None, 1, 10),
        (None, -1, 30),
    ],
)
def test_adjacent_channel_index_follows_visible_order_and_wraps(
    current: int | None,
    step: int,
    expected: int,
) -> None:
    assert _adjacent_channel_index([10, 20, 30], current, step) == expected


def test_adjacent_channel_index_handles_empty_and_rejects_zero_step() -> None:
    assert _adjacent_channel_index([], None, 1) is None
    with pytest.raises(ValueError, match="步长"):
        _adjacent_channel_index([1], 1, 0)


def test_frame_failure_rechecks_and_downgrades_stale_valid_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = Channel(0, "频道 0", "http://example.com/live.m3u8")
    original = ProbeResult(0, valid=True, status="可用", latency_ms=120, resolution="1920×1080")
    capture_calls: list[bool] = []

    def fake_capture(*_args: object, force: bool = False, **_kwargs: object) -> AssetInspection:
        capture_calls.append(force)
        return AssetInspection("失败", error="资源不存在")

    monkeypatch.setattr(app_module, "capture_frame", fake_capture)
    monkeypatch.setattr(
        app_module,
        "probe_channel",
        lambda *_args, **_kwargs: ProbeResult(0, status="404", latency_ms=15, error="资源不存在"),
    )

    refreshed, frame = _capture_frame_with_recheck(
        channel,
        original,
        "ffprobe",
        "ffmpeg",
        tmp_path,
        6,
    )

    assert refreshed.valid is False
    assert refreshed.status == "404"
    assert refreshed.latency_ms == 15
    assert frame.status == "源已失效"
    assert capture_calls == [False]


def test_frame_failure_retries_after_source_recheck_recovers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = Channel(0, "频道 0", "http://example.com/live.m3u8")
    original = ProbeResult(0, valid=True, status="可用", latency_ms=120, resolution="1920×1080")
    captures = iter(
        [
            AssetInspection("失败", error="连接超时"),
            AssetInspection("已捕获", str(tmp_path / "frame.png")),
        ]
    )
    capture_calls: list[bool] = []

    def fake_capture(*_args: object, force: bool = False, **_kwargs: object) -> AssetInspection:
        capture_calls.append(force)
        return next(captures)

    monkeypatch.setattr(app_module, "capture_frame", fake_capture)
    monkeypatch.setattr(
        app_module,
        "probe_channel",
        lambda *_args, **_kwargs: ProbeResult(
            0,
            valid=True,
            status="可用",
            latency_ms=25,
            resolution="1920×1080",
        ),
    )

    refreshed, frame = _capture_frame_with_recheck(
        channel,
        original,
        "ffprobe",
        "ffmpeg",
        tmp_path,
        6,
    )

    assert refreshed.valid is True
    assert refreshed.latency_ms == 25
    assert frame.status == "已捕获"
    assert capture_calls == [False, True]


def test_pure_audio_is_not_reported_as_frame_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = Channel(0, "广播", "http://example.com/audio.m3u8")
    original = ProbeResult(0, valid=True, status="可用", resolution="纯音频")

    def unexpected(*_args: object, **_kwargs: object) -> AssetInspection:
        raise AssertionError("纯音频不应调用 FFmpeg 抓帧或重新探测")

    monkeypatch.setattr(app_module, "capture_frame", unexpected)
    monkeypatch.setattr(app_module, "probe_channel", unexpected)

    refreshed, frame = _capture_frame_with_recheck(
        channel,
        original,
        "ffprobe",
        "ffmpeg",
        tmp_path,
        6,
    )

    assert refreshed is original
    assert frame.status == "无视频"


class _FakeTable:
    def __init__(self, items: list[str], focused: str = "") -> None:
        self.items = items
        self.focused = focused
        self.selected: tuple[str, ...] = (focused,) if focused else ()
        self.seen = ""

    def get_children(self) -> tuple[str, ...]:
        return tuple(self.items)

    def focus(self, item: str | None = None) -> str:
        if item is not None:
            self.focused = item
        return self.focused

    def selection(self) -> tuple[str, ...]:
        return self.selected

    def selection_set(self, item: str) -> None:
        self.selected = (item,)

    def see(self, item: str) -> None:
        self.seen = item


def test_quick_switch_uses_filtered_order_and_last_player() -> None:
    app = SourceCheckerApp.__new__(SourceCheckerApp)
    app.channels = [
        Channel(0, "频道 0", "http://example.com/0"),
        Channel(1, "频道 1", "http://example.com/1"),
        Channel(2, "频道 2", "http://example.com/2"),
    ]
    app.table = _FakeTable(["0", "2"], focused="0")  # type: ignore[assignment]
    app.last_player = "PotPlayer"
    app.show_selection = lambda _event=None: None  # type: ignore[method-assign]
    played: list[tuple[int, str, bool]] = []

    def record_play(channel: Channel, player: str, *, quiet_failure: bool = False) -> None:
        played.append((channel.index, player, quiet_failure))

    app._play_channel = record_play  # type: ignore[method-assign]

    app.quick_switch(1)

    assert app.table.selection() == ("2",)
    assert app.table.seen == "2"  # type: ignore[attr-defined]
    assert played == [(2, "PotPlayer", True)]


class _FakeStatus:
    def __init__(self) -> None:
        self.value = ""

    def set(self, value: str) -> None:
        self.value = value


class _FakeValue:
    def __init__(self, value: object) -> None:
        self.value = value

    def get(self) -> object:
        return self.value


class _FakeRoot:
    def winfo_exists(self) -> bool:
        return False


def test_poll_events_ignores_stale_frame_results() -> None:
    app = SourceCheckerApp.__new__(SourceCheckerApp)
    app.events = queue.Queue()
    app.root = _FakeRoot()  # type: ignore[assignment]
    app.frame_generation = 2
    handled: list[int] = []
    app._handle_frame_result = (  # type: ignore[method-assign]
        lambda index, _result, _inspection: handled.append(index)
    )
    inspection = AssetInspection("已捕获", "frame.png")
    app.events.put(("frame_result", 1, 0, ProbeResult(0), inspection))
    app.events.put(("frame_result", 2, 1, ProbeResult(1), inspection))

    app._poll_events()

    assert handled == [1]


def test_quick_switch_reports_when_filter_has_no_channels() -> None:
    app = SourceCheckerApp.__new__(SourceCheckerApp)
    app.table = _FakeTable([])  # type: ignore[assignment]
    app.status_var = _FakeStatus()  # type: ignore[assignment]

    app.quick_switch(1)

    assert app.status_var.value == "当前筛选条件下没有可切换的频道"  # type: ignore[attr-defined]


def test_begin_playback_replaces_pending_preflight_with_latest_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = SourceCheckerApp.__new__(SourceCheckerApp)
    app.config = {}
    app.timeout_var = _FakeValue(6)  # type: ignore[assignment]
    app.events = queue.Queue()
    app.status_var = _FakeStatus()  # type: ignore[assignment]
    app.playback_active = True
    app.playback_generation = 4
    previous_stop_event = threading.Event()
    app.playback_stop_event = previous_stop_event
    captured_stop_events: list[threading.Event] = []

    def fake_preflight(
        channel: Channel,
        _ffprobe_path: str,
        *,
        timeout: int,
        stop_event: threading.Event,
    ) -> PlaybackPreflight:
        assert timeout == 6
        captured_stop_events.append(stop_event)
        return PlaybackPreflight(ProbeResult(channel.index, status="已取消"), channel.url)

    class ImmediateThread:
        def __init__(self, *, target: object, **_kwargs: object) -> None:
            self.target = target

        def start(self) -> None:
            assert callable(self.target)
            self.target()

    monkeypatch.setattr(app_module, "find_binary", lambda *_args, **_kwargs: "ffprobe")
    monkeypatch.setattr(app_module, "preflight_playback", fake_preflight)
    monkeypatch.setattr(app_module.threading, "Thread", ImmediateThread)

    channel = Channel(1, "频道 1", "http://example.com/1")
    app._begin_playback(channel, "FFplay", "ffplay", quiet_failure=True)

    event = app.events.get_nowait()
    assert previous_stop_event.is_set()
    assert app.playback_generation == 5
    assert captured_stop_events == [app.playback_stop_event]
    assert captured_stop_events[0] is not previous_stop_event
    assert event[0:2] == ("playback_ready", 5)
    assert event[-1] is True


def test_begin_playback_keeps_pending_request_when_new_timeout_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = SourceCheckerApp.__new__(SourceCheckerApp)
    app.config = {}
    app.timeout_var = _FakeValue("invalid")  # type: ignore[assignment]
    app.playback_active = True
    app.playback_generation = 7
    previous_stop_event = threading.Event()
    app.playback_stop_event = previous_stop_event
    monkeypatch.setattr(app_module, "find_binary", lambda *_args, **_kwargs: "ffprobe")
    monkeypatch.setattr(app_module.messagebox, "showerror", lambda *_args, **_kwargs: None)

    app._begin_playback(Channel(0, "频道 0", "http://example.com/0"), "FFplay", "ffplay")

    assert not previous_stop_event.is_set()
    assert app.playback_generation == 7
