from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import urljoin, urlparse

APP_NAME = "IPTVSourceChecker"
PLAYLIST_LIMIT = 25 * 1024 * 1024
LOGO_LIMIT = 4 * 1024 * 1024
NETWORK_SCHEMES = {"http", "https", "rtsp", "rtmp", "rtp", "udp", "tcp", "srt"}
HTTP_SCHEMES = {"http", "https"}
USER_AGENT = "HA-CMCC-IPTV-Source-Checker/0.1"


@dataclass(slots=True)
class Channel:
    index: int
    name: str
    url: str
    group: str = "未分类"
    tvg_id: str = ""
    logo: str = ""
    attrs: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ProbeResult:
    index: int
    valid: bool = False
    status: str = "待检测"
    latency_ms: int | None = None
    resolution: str = ""
    frame_rate: str = ""
    video_codec: str = ""
    audio_codec: str = ""
    bitrate: str = ""
    container: str = ""
    pixel_format: str = ""
    hdr: str = ""
    audio_channels: str = ""
    sample_rate: str = ""
    service_name: str = ""
    logo_status: str = "未检测"
    logo_path: str = ""
    frame_status: str = "未检测"
    frame_path: str = ""
    error: str = ""


@dataclass(slots=True)
class AssetInspection:
    status: str
    path: str = ""
    error: str = ""


@dataclass(slots=True)
class StreamResolution:
    original_url: str
    resolved_url: str
    status_code: int | None = None
    error: str = ""

    @property
    def redirected(self) -> bool:
        return self.resolved_url != self.original_url


@dataclass(slots=True)
class PlaybackPreflight:
    result: ProbeResult
    playback_url: str
    http_status: int | None = None
    redirected: bool = False
    resolution_error: str = ""


class _CommandCancelled(Exception):
    pass


def app_data_dir() -> Path:
    root = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME")
    path = Path(root) / APP_NAME if root else Path.home() / ".cache" / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    root = os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME")
    base = Path(root) if root else Path.home() / ".config"
    return base / APP_NAME / "config.json"


def load_config() -> dict[str, str]:
    path = config_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return {str(key): str(value) for key, value in data.items() if isinstance(value, str)}


def save_config(config: dict[str, str]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _read_limited(stream: BinaryIO, limit: int) -> bytes:
    data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"内容超过 {limit // 1024 // 1024} MiB 限制")
    return data


def _decode_playlist(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def load_playlist(source: str, timeout: int = 15) -> tuple[str, str]:
    source = source.strip().strip('"')
    if not source:
        raise ValueError("请输入 M3U 文件路径或 HTTP(S) 地址")

    parsed = urlparse(source)
    if parsed.scheme.lower() in HTTP_SCHEMES:
        request = urllib.request.Request(
            source,
            headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = _read_limited(response, PLAYLIST_LIMIT)
                final_url = response.geturl()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ValueError(f"播放列表下载失败：{exc}") from exc
        return _decode_playlist(raw), final_url

    path = Path(source).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"播放列表不存在：{path}")
    if path.stat().st_size > PLAYLIST_LIMIT:
        raise ValueError("播放列表超过 25 MiB 限制")
    try:
        return _decode_playlist(path.read_bytes()), str(path)
    except OSError as exc:
        raise ValueError(f"播放列表读取失败：{exc}") from exc


def _split_extinf(value: str) -> tuple[str, str]:
    quote = ""
    comma = -1
    for index, char in enumerate(value):
        if char in {'"', "'"}:
            quote = "" if quote == char else quote or char
        elif char == "," and not quote and comma < 0:
            comma = index
    if comma < 0:
        return value, "未命名"
    return value[:comma], value[comma + 1 :].strip() or "未命名"


def _parse_attributes(value: str) -> dict[str, str]:
    pattern = re.compile(r"([\w-]+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s,]+))")
    attributes: dict[str, str] = {}
    for match in pattern.finditer(value):
        attributes[match.group(1).lower()] = next(
            group for group in match.groups()[1:] if group is not None
        )
    return attributes


def _resolve_reference(value: str, base: str) -> str:
    value = value.strip()
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme.lower() in NETWORK_SCHEMES:
        return value
    if urlparse(base).scheme.lower() in HTTP_SCHEMES:
        return urljoin(base, value)
    candidate = Path(value).expanduser()
    resolved = (
        candidate.resolve()
        if candidate.is_absolute()
        else (Path(base).parent / candidate).resolve()
    )
    return str(resolved)


def _looks_like_stream(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme.lower() in NETWORK_SCHEMES or Path(value).expanduser().exists()


def parse_playlist(content: str, base: str = "") -> list[Channel]:
    channels: list[Channel] = []
    pending: tuple[str, dict[str, str]] | None = None
    current_group = "未分类"

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#EXTGRP:"):
            current_group = line.removeprefix("#EXTGRP:").strip() or "未分类"
            continue
        if line.startswith("#EXTINF:"):
            metadata, name = _split_extinf(line.removeprefix("#EXTINF:"))
            pending = (name, _parse_attributes(metadata))
            continue
        if line.startswith("#"):
            continue

        if pending:
            name, attrs = pending
            pending = None
            url = _resolve_reference(line, base)
            if not _looks_like_stream(url):
                continue
            group = attrs.get("group-title", current_group) or "未分类"
            channels.append(
                Channel(
                    index=len(channels),
                    name=name,
                    url=url,
                    group=group,
                    tvg_id=attrs.get("tvg-id", ""),
                    logo=_resolve_reference(attrs.get("tvg-logo", ""), base),
                    attrs=attrs,
                )
            )
            continue

        if "," in line:
            possible_name, possible_url = (part.strip() for part in line.split(",", 1))
            resolved = _resolve_reference(possible_url, base)
            if _looks_like_stream(resolved):
                channels.append(
                    Channel(len(channels), possible_name or "未命名", resolved, current_group)
                )
                continue

        resolved = _resolve_reference(line, base)
        if _looks_like_stream(resolved):
            parsed = urlparse(resolved)
            fallback_name = (
                parsed.netloc or Path(parsed.path).stem or f"频道 {len(channels) + 1}"
            )
            channels.append(Channel(len(channels), fallback_name, resolved, current_group))

    if not channels:
        raise ValueError("未解析到可检测的频道地址")
    return channels


def load_channels(source: str, timeout: int = 15) -> list[Channel]:
    content, base = load_playlist(source, timeout)
    return parse_playlist(content, base)


def find_binary(name: str, configured: str = "") -> str:
    if configured and Path(configured).is_file():
        return str(Path(configured).resolve())
    found = shutil.which(name)
    if found:
        return str(Path(found).resolve())
    executable = f"{name}.exe" if sys.platform == "win32" else name
    local_candidates = [
        Path.cwd() / "ffmpeg" / executable,
        Path.cwd() / executable,
    ]
    for candidate in local_candidates:
        if candidate.is_file():
            return str(candidate.resolve())
    return ""


def _creation_flags() -> int:
    return subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _run_command(
    command: list[str],
    timeout: float,
    stop_event: threading.Event | None = None,
) -> subprocess.CompletedProcess[bytes]:
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=_creation_flags(),
    )
    deadline = time.monotonic() + timeout
    while True:
        if stop_event and stop_event.is_set():
            process.kill()
            process.communicate()
            raise _CommandCancelled
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            process.kill()
            stdout, stderr = process.communicate()
            raise subprocess.TimeoutExpired(command, timeout, output=stdout, stderr=stderr)
        try:
            stdout, stderr = process.communicate(timeout=min(0.1, remaining))
            return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        except subprocess.TimeoutExpired:
            continue


def _fraction_text(value: Any) -> str:
    if not value or value in {"0/0", "N/A"}:
        return ""
    try:
        number = float(Fraction(str(value)))
    except (ValueError, ZeroDivisionError):
        return ""
    return f"{number:.2f}".rstrip("0").rstrip(".") + " fps"


def _bitrate_text(value: Any) -> str:
    try:
        bitrate = int(value)
    except (TypeError, ValueError):
        return ""
    if bitrate <= 0:
        return ""
    if bitrate >= 1_000_000:
        return f"{bitrate / 1_000_000:.2f} Mbps"
    return f"{bitrate / 1000:.0f} Kbps"


def _hdr_text(stream: dict[str, Any]) -> str:
    codec = str(stream.get("codec_name") or "").lower()
    transfer = str(stream.get("color_transfer") or "").lower()
    side_data = json.dumps(stream.get("side_data_list", []), ensure_ascii=False).lower()
    if any(marker in codec + side_data for marker in ("dovi", "dolby vision", "dvhe", "dvh1")):
        return "Dolby Vision"
    if "smpte2084" in transfer:
        return "HDR10+" if "dynamic hdr plus" in side_data else "HDR10"
    if "arib-std-b67" in transfer:
        return "HLG"
    return ""


def parse_probe_payload(index: int, payload: dict[str, Any], latency_ms: int) -> ProbeResult:
    raw_streams = payload.get("streams") or []
    if not isinstance(raw_streams, list):
        raw_streams = []
    streams: list[dict[str, Any]] = [item for item in raw_streams if isinstance(item, dict)]
    if not streams:
        return ProbeResult(index=index, status="无媒体流", latency_ms=latency_ms, error="无媒体流")

    video: dict[str, Any] = next(
        (item for item in streams if item.get("codec_type") == "video"), {}
    )
    audio: dict[str, Any] = next(
        (item for item in streams if item.get("codec_type") == "audio"), {}
    )
    raw_format = payload.get("format")
    format_info: dict[str, Any] = raw_format if isinstance(raw_format, dict) else {}
    raw_tags = format_info.get("tags")
    tags: dict[str, Any] = raw_tags if isinstance(raw_tags, dict) else {}
    width, height = video.get("width"), video.get("height")
    resolution = f"{width}×{height}" if width and height else "纯音频"
    channels = audio.get("channels")
    channel_layout = str(audio.get("channel_layout") or "")
    audio_channels = f"{channels} 声道" if channels else channel_layout
    if channels and channel_layout:
        audio_channels += f" ({channel_layout})"

    bitrate = _bitrate_text(format_info.get("bit_rate"))
    if not bitrate:
        stream_bitrates = [
            int(item["bit_rate"])
            for item in streams
            if str(item.get("bit_rate", "")).isdigit()
        ]
        bitrate = _bitrate_text(sum(stream_bitrates)) if stream_bitrates else ""

    return ProbeResult(
        index=index,
        valid=True,
        status="可用",
        latency_ms=latency_ms,
        resolution=resolution,
        frame_rate=_fraction_text(video.get("avg_frame_rate") or video.get("r_frame_rate")),
        video_codec=str(video.get("codec_name") or "").upper(),
        audio_codec=str(audio.get("codec_name") or "").upper(),
        bitrate=bitrate,
        container=str(format_info.get("format_long_name") or format_info.get("format_name") or ""),
        pixel_format=str(video.get("pix_fmt") or ""),
        hdr=_hdr_text(video),
        audio_channels=audio_channels,
        sample_rate=(f"{audio.get('sample_rate')} Hz" if audio.get("sample_rate") else ""),
        service_name=str(tags.get("service_name") or tags.get("title") or ""),
    )


def _probe_error(stderr: str, returncode: int) -> tuple[str, str]:
    normalized = stderr.lower()
    mappings = (
        (("timed out", "timeout"), "超时", "连接超时"),
        (("connection refused",), "拒绝", "连接被拒绝"),
        (("404 not found", "server returned 404"), "404", "资源不存在"),
        (("403 forbidden", "server returned 403"), "403", "访问被拒绝"),
        (("invalid data",), "无效", "无效媒体数据"),
        (("name or service not known", "no such host"), "DNS", "域名解析失败"),
    )
    for needles, status, message in mappings:
        if any(needle in normalized for needle in needles):
            return status, message
    last_line = next((line.strip() for line in reversed(stderr.splitlines()) if line.strip()), "")
    return "失败", last_line[:240] or f"ffprobe 返回码 {returncode}"


def probe_channel(
    channel: Channel,
    ffprobe_path: str,
    timeout: int = 6,
    stop_event: threading.Event | None = None,
) -> ProbeResult:
    if not ffprobe_path:
        return ProbeResult(channel.index, status="缺少 FFprobe", error="未找到 ffprobe")
    timeout = max(1, min(timeout, 60))
    microseconds = str(timeout * 1_000_000)
    command = [
        ffprobe_path,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        "-rw_timeout",
        microseconds,
        "-analyzeduration",
        microseconds,
        "-probesize",
        "5000000",
        channel.url,
    ]
    started = time.monotonic()
    try:
        completed = _run_command(command, timeout + 3, stop_event)
    except _CommandCancelled:
        return ProbeResult(channel.index, status="已取消")
    except subprocess.TimeoutExpired:
        return ProbeResult(
            channel.index,
            status="超时",
            latency_ms=int((time.monotonic() - started) * 1000),
            error=f"超过 {timeout + 3} 秒",
        )
    except (OSError, ValueError) as exc:
        return ProbeResult(channel.index, status="启动失败", error=str(exc))

    latency_ms = int((time.monotonic() - started) * 1000)
    try:
        payload = json.loads(completed.stdout.decode("utf-8", errors="replace") or "{}")
    except json.JSONDecodeError:
        payload = {}
    if payload.get("streams"):
        return parse_probe_payload(channel.index, payload, latency_ms)
    stderr = completed.stderr.decode("utf-8", errors="replace")
    status, error = _probe_error(stderr, completed.returncode)
    return ProbeResult(channel.index, status=status, latency_ms=latency_ms, error=error)


def _safe_logo_name(value: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "", value).strip().rstrip(".")


def _image_extension(data: bytes, content_type: str = "") -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    if b"<svg" in data[:1024].lower() or "svg" in content_type.lower():
        return ".svg"
    return ""


def _local_logo_candidates(channel: Channel, logo_dir: Path | None) -> Iterable[Path]:
    if channel.logo and urlparse(channel.logo).scheme.lower() not in HTTP_SCHEMES:
        yield Path(channel.logo)
    if not logo_dir:
        return
    stems = [channel.tvg_id, channel.name]
    for stem in filter(None, (_safe_logo_name(value) for value in stems)):
        for extension in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
            yield logo_dir / f"{stem}{extension}"


def inspect_logo(
    channel: Channel,
    logo_dir: Path | None,
    cache_dir: Path,
    timeout: int = 6,
) -> AssetInspection:
    for candidate in _local_logo_candidates(channel, logo_dir):
        try:
            if candidate.is_file() and candidate.stat().st_size > 0:
                return AssetInspection("本地可用", str(candidate.resolve()))
        except OSError:
            continue

    parsed = urlparse(channel.logo)
    if parsed.scheme.lower() not in HTTP_SCHEMES:
        return AssetInspection("缺失", error="M3U 未提供可用台标，且本地未匹配")

    logo_cache = cache_dir / "logos"
    logo_cache.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(channel.logo.encode("utf-8")).hexdigest()[:24]
    cached = next(logo_cache.glob(f"{key}.*"), None)
    if cached and cached.is_file() and cached.stat().st_size > 0:
        return AssetInspection("在线可用", str(cached))

    request = urllib.request.Request(
        channel.logo,
        headers={"User-Agent": USER_AGENT, "Accept": "image/*"},
    )
    try:
        with urllib.request.urlopen(request, timeout=max(1, timeout)) as response:
            data = _read_limited(response, LOGO_LIMIT)
            content_type = response.headers.get("Content-Type", "")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return AssetInspection("异常", error=str(exc))
    extension = _image_extension(data, content_type)
    if not extension:
        return AssetInspection("异常", error="响应不是受支持的图片格式")
    target = logo_cache / f"{key}{extension}"
    try:
        target.write_bytes(data)
    except OSError as exc:
        return AssetInspection("异常", error=f"台标缓存失败：{exc}")
    return AssetInspection("在线可用", str(target))


def capture_frame(
    channel: Channel,
    ffmpeg_path: str,
    cache_dir: Path,
    timeout: int = 8,
    force: bool = False,
    stop_event: threading.Event | None = None,
) -> AssetInspection:
    if not ffmpeg_path:
        return AssetInspection("缺少 FFmpeg", error="未找到 ffmpeg")
    frame_cache = cache_dir / "frames"
    frame_cache.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(channel.url.encode("utf-8")).hexdigest()[:24]
    target = frame_cache / f"{key}.png"
    if target.is_file() and target.stat().st_size > 0 and not force:
        return AssetInspection("已捕获", str(target))

    timeout = max(2, min(timeout, 60))
    command = [
        ffmpeg_path,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-rw_timeout",
        str(timeout * 1_000_000),
        "-i",
        channel.url,
        "-map",
        "0:v:0",
        "-frames:v",
        "1",
        "-vf",
        "scale=640:-2",
        str(target),
    ]
    try:
        completed = _run_command(command, timeout + 4, stop_event)
    except _CommandCancelled:
        target.unlink(missing_ok=True)
        return AssetInspection("已取消")
    except subprocess.TimeoutExpired:
        target.unlink(missing_ok=True)
        return AssetInspection("超时", error=f"画面捕获超过 {timeout + 4} 秒")
    except (OSError, ValueError) as exc:
        target.unlink(missing_ok=True)
        return AssetInspection("失败", error=str(exc))

    if completed.returncode == 0 and target.is_file() and target.stat().st_size > 0:
        return AssetInspection("已捕获", str(target))
    target.unlink(missing_ok=True)
    stderr = completed.stderr.decode("utf-8", errors="replace")
    _, error = _probe_error(stderr, completed.returncode)
    return AssetInspection("失败", error=error)


def resolve_stream_url(url: str, timeout: int = 6) -> StreamResolution:
    if urlparse(url).scheme.lower() not in HTTP_SCHEMES:
        return StreamResolution(url, url)

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.apple.mpegurl, application/x-mpegURL, */*",
            "Accept-Encoding": "identity",
            "Range": "bytes=0-0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=max(1, min(timeout, 15))) as response:
            resolved_url = response.geturl() or url
            status_code = getattr(response, "status", None)
        return StreamResolution(url, resolved_url, status_code=status_code)
    except urllib.error.HTTPError as exc:
        return StreamResolution(
            url,
            url,
            status_code=exc.code,
            error=f"HTTP {exc.code}：{exc.reason}",
        )
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return StreamResolution(url, url, error=str(exc))


def preflight_playback(
    channel: Channel,
    ffprobe_path: str,
    timeout: int = 6,
    stop_event: threading.Event | None = None,
) -> PlaybackPreflight:
    result = probe_channel(channel, ffprobe_path, timeout, stop_event)
    if not result.valid:
        return PlaybackPreflight(result, channel.url)

    resolution = resolve_stream_url(channel.url, timeout=min(timeout, 8))
    return PlaybackPreflight(
        result=result,
        playback_url=resolution.resolved_url,
        http_status=resolution.status_code,
        redirected=resolution.redirected,
        resolution_error=resolution.error,
    )


def discover_potplayer(configured: str = "") -> str:
    if configured and Path(configured).is_file():
        return str(Path(configured).resolve())
    environment = os.environ.get("POTPLAYER_PATH", "")
    if environment and Path(environment).is_file():
        return str(Path(environment).resolve())
    for name in ("PotPlayerMini64.exe", "PotPlayerMini.exe", "PotPlayer.exe"):
        found = shutil.which(name)
        if found:
            return str(Path(found).resolve())

    if sys.platform == "win32":
        try:
            import winreg

            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                for name in ("PotPlayerMini64.exe", "PotPlayerMini.exe"):
                    key_name = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{name}"
                    try:
                        with winreg.OpenKey(hive, key_name) as key:
                            value = winreg.QueryValue(key, None)
                        if value and Path(value).is_file():
                            return str(Path(value).resolve())
                    except OSError:
                        continue
        except ImportError:
            pass

        program_files = [
            os.environ.get("PROGRAMFILES", ""),
            os.environ.get("PROGRAMFILES(X86)", ""),
        ]
        relative_paths = (
            Path("DAUM/PotPlayer/PotPlayerMini64.exe"),
            Path("DAUM/PotPlayer/PotPlayerMini.exe"),
            Path("PotPlayer/PotPlayerMini64.exe"),
        )
        for root in filter(None, program_files):
            for relative in relative_paths:
                candidate = Path(root) / relative
                if candidate.is_file():
                    return str(candidate.resolve())
    return ""


def launch_player(
    executable: str, channel: Channel, arguments: Iterable[str] = ()
) -> subprocess.Popen[bytes]:
    if not executable or not Path(executable).is_file():
        raise FileNotFoundError("播放器程序不存在")
    return subprocess.Popen(
        [executable, *arguments, channel.url],
        creationflags=_creation_flags(),
        close_fds=True,
    )


def launch_ffplay(executable: str, channel: Channel) -> subprocess.Popen[bytes]:
    return launch_player(
        executable,
        channel,
        (
            "-hide_banner",
            "-loglevel",
            "warning",
            "-window_title",
            f"IPTV 预览 - {channel.name}",
            "-fflags",
            "nobuffer",
            "-flags",
            "low_delay",
            "-rw_timeout",
            "15000000",
            "-reconnect",
            "1",
            "-reconnect_streamed",
            "1",
            "-reconnect_delay_max",
            "5",
            "-framedrop",
            "-autoexit",
        ),
    )


def export_results_csv(
    path: str | Path,
    channels: Iterable[Channel],
    results: dict[int, ProbeResult],
) -> None:
    fields = [
        "name",
        "group",
        "url",
        "status",
        "latency_ms",
        "resolution",
        "frame_rate",
        "video_codec",
        "audio_codec",
        "bitrate",
        "container",
        "pixel_format",
        "hdr",
        "audio_channels",
        "sample_rate",
        "service_name",
        "logo_status",
        "frame_status",
        "error",
    ]
    with Path(path).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for channel in channels:
            result = results.get(channel.index, ProbeResult(channel.index))
            writer.writerow(
                {
                    "name": channel.name,
                    "group": channel.group,
                    "url": channel.url,
                    **{field: getattr(result, field) for field in fields[3:]},
                }
            )


def _m3u_escape(value: str) -> str:
    return value.replace('"', "'").replace("\r", " ").replace("\n", " ")


def export_valid_m3u(
    path: str | Path,
    channels: Iterable[Channel],
    results: dict[int, ProbeResult],
) -> int:
    lines = ["#EXTM3U"]
    count = 0
    for channel in channels:
        if not results.get(channel.index, ProbeResult(channel.index)).valid:
            continue
        attributes = []
        if channel.tvg_id:
            attributes.append(f'tvg-id="{_m3u_escape(channel.tvg_id)}"')
        attributes.append(f'tvg-name="{_m3u_escape(channel.name)}"')
        if channel.logo:
            attributes.append(f'tvg-logo="{_m3u_escape(channel.logo)}"')
        attributes.append(f'group-title="{_m3u_escape(channel.group)}"')
        lines.append(f"#EXTINF:-1 {' '.join(attributes)},{_m3u_escape(channel.name)}")
        lines.append(channel.url)
        count += 1
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return count
