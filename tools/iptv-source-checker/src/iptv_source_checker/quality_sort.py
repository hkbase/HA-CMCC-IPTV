from __future__ import annotations

import argparse
import csv
import re
import shutil
import threading
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .core import Channel, ProbeResult, find_binary, parse_playlist, probe_channel

REPORT_FIELDS = (
    "index",
    "name",
    "group",
    "url",
    "valid",
    "status",
    "latency_ms",
    "resolution",
    "pixel_count",
    "frame_rate",
    "fps",
    "video_codec",
    "audio_codec",
    "bitrate",
    "bitrate_bps",
    "container",
    "pixel_format",
    "hdr",
    "audio_channels",
    "sample_rate",
    "service_name",
    "error",
)
REQUIRED_REPORT_FIELDS = {
    "index",
    "name",
    "url",
    "valid",
    "status",
    "resolution",
    "frame_rate",
    "bitrate",
}


@dataclass(slots=True, frozen=True)
class PlaylistBlock:
    index: int
    channel: Channel
    lines: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class PlaylistDocument:
    prefix: tuple[str, ...]
    blocks: tuple[PlaylistBlock, ...]
    newline: str
    trailing_newline: bool


@dataclass(slots=True, frozen=True)
class ReorderSummary:
    name: str
    source_count: int
    old_first_index: int
    new_first_index: int


def parse_playlist_document(content: str, base: str = "") -> PlaylistDocument:
    lines = content.splitlines()
    starts = [index for index, line in enumerate(lines) if line.strip().startswith("#EXTINF:")]
    if not starts:
        raise ValueError("播放列表没有 #EXTINF 条目")

    channels = parse_playlist(content, base)
    if len(channels) != len(starts):
        raise ValueError("仅支持每个 #EXTINF 对应一个直播地址的播放列表")

    blocks: list[PlaylistBlock] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(lines)
        block_lines = tuple(lines[start:end])
        stream_lines = [
            line
            for line in block_lines[1:]
            if line.strip() and not line.lstrip().startswith("#")
        ]
        if len(stream_lines) != 1:
            raise ValueError(f"第 {index + 1} 个频道块不是单一直播地址")
        blocks.append(PlaylistBlock(index, channels[index], block_lines))

    newline = "\r\n" if "\r\n" in content else "\n"
    return PlaylistDocument(
        prefix=tuple(lines[: starts[0]]),
        blocks=tuple(blocks),
        newline=newline,
        trailing_newline=content.endswith(("\n", "\r")),
    )


def resolution_pixels(value: str) -> int:
    match = re.search(r"(\d+)\s*[xX]\s*(\d+)", value.replace("×", "x"))
    return int(match.group(1)) * int(match.group(2)) if match else 0


def bitrate_bps(value: str) -> int:
    match = re.search(r"(\d+(?:\.\d+)?)\s*([KMG]?bps)", value, flags=re.IGNORECASE)
    if not match:
        return 0
    multipliers = {"bps": 1, "kbps": 1_000, "mbps": 1_000_000, "gbps": 1_000_000_000}
    return int(float(match.group(1)) * multipliers[match.group(2).lower()])


def frame_rate_fps(value: str) -> float:
    match = re.search(r"\d+(?:\.\d+)?", value)
    return float(match.group()) if match else 0.0


def quality_key(result: ProbeResult) -> tuple[int, int, int, float]:
    if not result.valid:
        return (1, 0, 0, 0.0)
    return (
        0,
        -resolution_pixels(result.resolution),
        -bitrate_bps(result.bitrate),
        -frame_rate_fps(result.frame_rate),
    )


def plan_reorder(
    document: PlaylistDocument,
    results: dict[int, ProbeResult],
) -> tuple[tuple[PlaylistBlock, ...], tuple[ReorderSummary, ...]]:
    missing = [block.index for block in document.blocks if block.index not in results]
    if missing:
        raise ValueError(f"画质结果缺少 {len(missing)} 条源")

    reordered: list[PlaylistBlock] = []
    summaries: list[ReorderSummary] = []
    start = 0
    while start < len(document.blocks):
        end = start + 1
        name = document.blocks[start].channel.name
        while end < len(document.blocks) and document.blocks[end].channel.name == name:
            end += 1
        original = document.blocks[start:end]
        ordered = tuple(sorted(original, key=lambda block: quality_key(results[block.index])))
        if [block.index for block in original] != [block.index for block in ordered]:
            summaries.append(
                ReorderSummary(name, len(original), original[0].index, ordered[0].index)
            )
        reordered.extend(ordered)
        start = end
    return tuple(reordered), tuple(summaries)


def render_playlist(document: PlaylistDocument, blocks: Sequence[PlaylistBlock]) -> str:
    lines = [*document.prefix]
    for block in blocks:
        lines.extend(block.lines)
    rendered = document.newline.join(lines)
    return rendered + document.newline if document.trailing_newline else rendered


def probe_all(
    channels: Sequence[Channel],
    ffprobe_path: str,
    workers: int,
    timeout: int,
) -> dict[int, ProbeResult]:
    if not 1 <= workers <= 32:
        raise ValueError("并发数必须在 1 到 32 之间")
    if not 1 <= timeout <= 60:
        raise ValueError("超时必须在 1 到 60 秒之间")

    results: dict[int, ProbeResult] = {}
    stop_event = threading.Event()
    executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="quality-probe")
    futures = {
        executor.submit(probe_channel, channel, ffprobe_path, timeout, stop_event): channel.index
        for channel in channels
    }
    try:
        for completed, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            results[result.index] = result
            if completed % 25 == 0 or completed == len(channels):
                print(f"探测进度：{completed}/{len(channels)}", flush=True)
    except KeyboardInterrupt:
        stop_event.set()
        for future in futures:
            future.cancel()
        raise
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
    return results


def write_quality_report(
    path: Path,
    channels: Sequence[Channel],
    results: dict[int, ProbeResult],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REPORT_FIELDS)
        writer.writeheader()
        for channel in channels:
            result = results[channel.index]
            writer.writerow(
                {
                    "index": channel.index,
                    "name": channel.name,
                    "group": channel.group,
                    "url": channel.url,
                    "valid": "1" if result.valid else "0",
                    "status": result.status,
                    "latency_ms": result.latency_ms if result.latency_ms is not None else "",
                    "resolution": result.resolution,
                    "pixel_count": resolution_pixels(result.resolution),
                    "frame_rate": result.frame_rate,
                    "fps": frame_rate_fps(result.frame_rate),
                    "video_codec": result.video_codec,
                    "audio_codec": result.audio_codec,
                    "bitrate": result.bitrate,
                    "bitrate_bps": bitrate_bps(result.bitrate),
                    "container": result.container,
                    "pixel_format": result.pixel_format,
                    "hdr": result.hdr,
                    "audio_channels": result.audio_channels,
                    "sample_rate": result.sample_rate,
                    "service_name": result.service_name,
                    "error": result.error,
                }
            )


def read_quality_report(path: Path, channels: Sequence[Channel]) -> dict[int, ProbeResult]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing_fields = REQUIRED_REPORT_FIELDS - set(reader.fieldnames or ())
        if missing_fields:
            raise ValueError(f"报告缺少列：{', '.join(sorted(missing_fields))}")
        rows = list(reader)
    if len(rows) != len(channels):
        raise ValueError(f"报告有 {len(rows)} 条，当前播放列表有 {len(channels)} 条")

    results: dict[int, ProbeResult] = {}
    for index, (row, channel) in enumerate(zip(rows, channels, strict=True)):
        if row.get("index") != str(index) or row.get("name") != channel.name:
            raise ValueError(f"报告第 {index + 1} 条与当前频道顺序不一致")
        if row.get("url") != channel.url:
            raise ValueError(f"报告第 {index + 1} 条直播地址与当前播放列表不一致")
        valid = row.get("valid")
        if valid not in {"0", "1"}:
            raise ValueError(f"报告第 {index + 1} 条 valid 必须为 0 或 1")
        results[index] = ProbeResult(
            index=index,
            valid=valid == "1",
            status=row.get("status", ""),
            resolution=row.get("resolution", ""),
            frame_rate=row.get("frame_rate", ""),
            bitrate=row.get("bitrate", ""),
        )
    return results


def apply_playlist(path: Path, content: str, backup_dir: Path) -> Path:
    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{path.stem}_before_quality_{timestamp}{path.suffix}"
    shutil.copy2(path, backup_path)

    temporary = path.with_name(f".{path.name}.quality.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return backup_path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def build_parser() -> argparse.ArgumentParser:
    root = _repo_root()
    parser = argparse.ArgumentParser(
        description="按真实探测画质稳定重排同名频道源",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("playlist", nargs="?", default=str(root / "public" / "index.m3u"))
    parser.add_argument("--workers", type=int, default=8, help="FFprobe 并发数")
    parser.add_argument("--timeout", type=int, default=6, help="单源探测超时秒数")
    parser.add_argument("--report", help="保存画质 CSV 的路径")
    parser.add_argument("--reuse-report", help="复用已生成的画质 CSV，不重新探测")
    parser.add_argument("--apply", action="store_true", help="写回播放列表；默认只预演")
    return parser


def run(args: argparse.Namespace) -> int:
    root = _repo_root()
    playlist_path = Path(args.playlist).expanduser().resolve()
    content = playlist_path.read_text(encoding="utf-8-sig")
    document = parse_playlist_document(content, str(playlist_path))
    channels = [block.channel for block in document.blocks]

    if args.reuse_report:
        report_path = Path(args.reuse_report).expanduser().resolve()
        results = read_quality_report(report_path, channels)
    else:
        ffprobe_path = find_binary("ffprobe")
        if not ffprobe_path:
            raise ValueError("未找到 ffprobe")
        results = probe_all(channels, ffprobe_path, args.workers, args.timeout)
        timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
        report_path = (
            Path(args.report).expanduser().resolve()
            if args.report
            else root / "reports" / f"source_quality_{timestamp}.csv"
        )
        write_quality_report(report_path, channels, results)

    reordered, summaries = plan_reorder(document, results)
    changed_sources = sum(
        old.index != new.index for old, new in zip(document.blocks, reordered, strict=True)
    )
    valid_count = sum(result.valid for result in results.values())
    print(f"探测结果：{valid_count} 条可用，{len(results) - valid_count} 条失败")
    print(f"排序预演：{len(summaries)} 个频道、{changed_sources} 个位置会变化")
    for summary in summaries[:10]:
        best = results[summary.new_first_index]
        details = " / ".join(
            filter(None, (best.resolution, best.bitrate, best.frame_rate))
        ) or "无画质数据"
        print(f"  {summary.name}（{summary.source_count} 源）：{details}")
    if len(summaries) > 10:
        print(f"  另有 {len(summaries) - 10} 个频道")
    print(f"画质报告：{report_path}")

    if not args.apply:
        print("当前为预演，播放列表未写回；确认后使用 --reuse-report <报告> --apply")
        return 0

    rendered = render_playlist(document, reordered)
    if rendered == content:
        print("当前顺序已符合规则，无需写回")
        return 0
    backup = apply_playlist(playlist_path, rendered, root / "reports")
    print(f"已写回：{playlist_path}")
    print(f"写回前备份：{backup}")
    return 0


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        raise SystemExit(run(args))
    except (OSError, UnicodeError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
