from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from iptv_source_checker.core import (
    Channel,
    PlaybackPreflight,
    ProbeResult,
    StreamResolution,
    _CommandCancelled,
    _creation_flags,
    _run_command,
    capture_frame,
    export_results_csv,
    export_valid_m3u,
    find_binary,
    inspect_logo,
    launch_ffplay,
    load_config,
    parse_playlist,
    parse_probe_payload,
    preflight_playback,
    probe_channel,
    resolve_stream_url,
    save_config,
)


def test_parse_playlist_keeps_metadata_and_resolves_relative_references() -> None:
    content = """#EXTM3U
#EXTINF:-1 tvg-id="cctv1" tvg-logo="logos/cctv1.png" group-title="央视频道",CCTV1, 综合
streams/cctv1.m3u8
"""

    channels = parse_playlist(content, "https://example.com/list/main.m3u")

    assert channels == [
        Channel(
            index=0,
            name="CCTV1, 综合",
            url="https://example.com/list/streams/cctv1.m3u8",
            group="央视频道",
            tvg_id="cctv1",
            logo="https://example.com/list/logos/cctv1.png",
            attrs={
                "tvg-id": "cctv1",
                "tvg-logo": "logos/cctv1.png",
                "group-title": "央视频道",
            },
        )
    ]


@pytest.mark.parametrize(
    ("content", "expected_name", "expected_url"),
    [
        ("新闻,http://example.com/live.m3u8", "新闻", "http://example.com/live.m3u8"),
        ("udp://239.1.1.1:5000", "239.1.1.1:5000", "udp://239.1.1.1:5000"),
    ],
)
def test_parse_playlist_supports_plain_text_sources(
    content: str,
    expected_name: str,
    expected_url: str,
) -> None:
    channel = parse_playlist(content)[0]
    assert channel.name == expected_name
    assert channel.url == expected_url


def test_parse_playlist_rejects_empty_or_invalid_content() -> None:
    with pytest.raises(ValueError, match="未解析到"):
        parse_playlist("#EXTM3U\nnot-a-stream")


def test_parse_probe_payload_extracts_video_audio_and_hdr() -> None:
    payload = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "hevc",
                "width": 3840,
                "height": 2160,
                "avg_frame_rate": "50/1",
                "pix_fmt": "yuv420p10le",
                "color_transfer": "smpte2084",
            },
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "channels": 2,
                "channel_layout": "stereo",
                "sample_rate": "48000",
            },
        ],
        "format": {
            "format_long_name": "MPEG-TS",
            "bit_rate": "12000000",
            "tags": {"service_name": "CCTV-4K"},
        },
    }

    result = parse_probe_payload(7, payload, 321)

    assert result.valid is True
    assert result.status == "可用"
    assert result.resolution == "3840×2160"
    assert result.frame_rate == "50 fps"
    assert result.video_codec == "HEVC"
    assert result.audio_codec == "AAC"
    assert result.bitrate == "12.00 Mbps"
    assert result.hdr == "HDR10"
    assert result.audio_channels == "2 声道 (stereo)"
    assert result.service_name == "CCTV-4K"


def test_local_logo_and_exports_use_real_files(tmp_path: Path) -> None:
    logo_dir = tmp_path / "logos"
    logo_dir.mkdir()
    (logo_dir / "CCTV1.png").write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    channel = Channel(0, "CCTV1", "http://example.com/live.m3u8", "央视频道")
    result = ProbeResult(
        index=0,
        valid=True,
        status="可用",
        resolution="1920×1080",
        video_codec="H264",
        logo_status="本地可用",
    )

    logo = inspect_logo(channel, logo_dir, tmp_path / "cache")
    csv_path = tmp_path / "result.csv"
    m3u_path = tmp_path / "valid.m3u"
    export_results_csv(csv_path, [channel], {0: result})
    exported = export_valid_m3u(m3u_path, [channel], {0: result})

    assert logo.status == "本地可用"
    assert Path(logo.path).name == "CCTV1.png"
    assert "1920×1080" in csv_path.read_text(encoding="utf-8-sig")
    assert exported == 1
    assert "#EXTINF:-1" in m3u_path.read_text(encoding="utf-8")
    assert channel.url in m3u_path.read_text(encoding="utf-8")


def test_ffmpeg_ffprobe_integration_on_synthetic_media(tmp_path: Path) -> None:
    ffmpeg = find_binary("ffmpeg")
    ffprobe = find_binary("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("本机未安装 FFmpeg/FFprobe")

    media = tmp_path / "sample.mp4"
    generated = subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x180:r=25",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=stereo",
            "-t",
            "1",
            "-shortest",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            str(media),
        ],
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert generated.returncode == 0, generated.stderr.decode("utf-8", errors="replace")

    channel = Channel(0, "本地合成流", str(media))
    result = probe_channel(channel, ffprobe, timeout=5)
    preflight = preflight_playback(channel, ffprobe, timeout=5)
    frame = capture_frame(channel, ffmpeg, tmp_path / "cache", timeout=5)

    assert result.valid is True
    assert result.resolution == "320×180"
    assert result.video_codec == "MPEG4"
    assert result.audio_codec == "AAC"
    assert preflight.result.valid is True
    assert preflight.playback_url == str(media)
    assert frame.status == "已捕获"
    assert Path(frame.path).is_file()


def test_public_fixture_is_valid_json_for_documented_probe_shape() -> None:
    payload = json.loads('{"streams":[{"codec_type":"audio","codec_name":"aac"}],"format":{}}')
    result = parse_probe_payload(0, payload, 10)
    assert result.valid is True
    assert result.resolution == "纯音频"
    assert result.audio_codec == "AAC"


def test_no_shell_executable_is_needed_for_binary_discovery() -> None:
    python_name = "python.exe" if shutil.which("python.exe") else "python"
    assert Path(find_binary(python_name)).is_file()


def test_creation_flags_uses_windows_constant_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 123, raising=False)

    assert _creation_flags() == 123


def test_creation_flags_falls_back_when_windows_constant_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delattr(subprocess, "CREATE_NO_WINDOW", raising=False)

    assert _creation_flags() == 0


def test_running_command_can_be_cancelled_without_waiting_for_timeout() -> None:
    stop_event = threading.Event()
    timer = threading.Timer(0.2, stop_event.set)
    timer.start()
    started = time.monotonic()

    try:
        with pytest.raises(_CommandCancelled):
            _run_command(
                [sys.executable, "-c", "import time; time.sleep(10)"],
                timeout=5,
                stop_event=stop_event,
            )
    finally:
        timer.cancel()

    assert time.monotonic() - started < 1.5


def test_config_round_trip_preserves_player_and_scan_preferences(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    expected = {
        "potplayer_path": r"D:\PotPlayer\PotPlayerMini64.exe",
        "workers": "12",
        "timeout": "8",
        "check_logo": "1",
        "check_frame": "0",
        "last_player": "PotPlayer",
    }

    save_config(expected)

    assert load_config() == expected


def test_resolve_stream_url_keeps_final_redirect_and_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        status = 200

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        @staticmethod
        def geturl() -> str:
            return "http://[2409:8087::1]/live/index.m3u8"

    monkeypatch.setattr(
        "iptv_source_checker.core.urllib.request.urlopen",
        lambda _request, timeout: FakeResponse(),
    )

    result = resolve_stream_url("http://example.com/live.m3u8")

    assert result == StreamResolution(
        original_url="http://example.com/live.m3u8",
        resolved_url="http://[2409:8087::1]/live/index.m3u8",
        status_code=200,
    )
    assert result.redirected is True


def test_preflight_playback_blocks_invalid_source(monkeypatch: pytest.MonkeyPatch) -> None:
    channel = Channel(3, "失效源", "http://example.com/missing.m3u8")
    invalid = ProbeResult(3, status="404", error="资源不存在")

    monkeypatch.setattr(
        "iptv_source_checker.core.probe_channel",
        lambda *_args, **_kwargs: invalid,
    )

    result = preflight_playback(channel, "ffprobe", timeout=3)

    assert result == PlaybackPreflight(invalid, channel.url)


def test_preflight_playback_passes_resolved_url_after_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = Channel(1, "可用源", "http://example.com/live.m3u8")
    valid = ProbeResult(1, valid=True, status="可用", video_codec="HEVC")
    resolved = "http://[2409:8087::1]/live/index.m3u8"

    monkeypatch.setattr(
        "iptv_source_checker.core.probe_channel",
        lambda *_args, **_kwargs: valid,
    )
    monkeypatch.setattr(
        "iptv_source_checker.core.resolve_stream_url",
        lambda *_args, **_kwargs: StreamResolution(channel.url, resolved, 200),
    )

    result = preflight_playback(channel, "ffprobe", timeout=3)

    assert result.result is valid
    assert result.playback_url == resolved
    assert result.http_status == 200
    assert result.redirected is True


def test_launch_ffplay_enables_live_stream_reconnect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "ffplay.exe"
    executable.touch()
    launched: list[list[str]] = []
    process = object()

    def fake_popen(command: list[str], **_kwargs: object) -> object:
        launched.append(command)
        return process

    monkeypatch.setattr("iptv_source_checker.core.subprocess.Popen", fake_popen)

    channel = Channel(0, "测试频道", "http://example.com/live.m3u8")
    returned = launch_ffplay(str(executable), channel)

    assert launched
    assert returned is process
    command = launched[0]
    assert command[-1] == channel.url
    assert command[command.index("-reconnect") + 1] == "1"
    assert command[command.index("-reconnect_streamed") + 1] == "1"
    assert command[command.index("-rw_timeout") + 1] == "15000000"
