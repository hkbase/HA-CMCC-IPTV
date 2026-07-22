from pathlib import Path

import pytest

from iptv_source_checker.core import ProbeResult
from iptv_source_checker.quality_sort import (
    apply_playlist,
    bitrate_bps,
    frame_rate_fps,
    parse_playlist_document,
    plan_reorder,
    read_quality_report,
    render_playlist,
    resolution_pixels,
)


def _playlist() -> str:
    return """#EXTM3U url-tvg="https://example.com/epg.xml"
#EXTINF:-1 tvg-id="A" group-title="测试",频道A
http://example.com/a-720.m3u8
#EXTINF:-1 tvg-id="A" group-title="测试",频道A
http://example.com/a-1080-25.m3u8
#EXTINF:-1 tvg-id="A" group-title="测试",频道A
http://example.com/a-1080-50.m3u8
#EXTINF:-1 tvg-id="B" group-title="测试",频道B
http://example.com/b-failed.m3u8
#EXTINF:-1 tvg-id="B" group-title="测试",频道B
http://example.com/b-live.m3u8
#EXTINF:-1 tvg-id="A" group-title="其他",频道A
http://example.com/a-separate.m3u8
"""


def test_quality_values_are_parsed_for_sorting() -> None:
    assert resolution_pixels("3840×2160") == 8_294_400
    assert resolution_pixels("纯音频") == 0
    assert bitrate_bps("12.00 Mbps") == 12_000_000
    assert bitrate_bps("") == 0
    assert frame_rate_fps("59.94 fps") == 59.94


def test_plan_reorder_only_sorts_contiguous_same_name_sources() -> None:
    document = parse_playlist_document(_playlist())
    results = {
        0: ProbeResult(0, valid=True, resolution="1280×720", frame_rate="50 fps"),
        1: ProbeResult(1, valid=True, resolution="1920×1080", frame_rate="25 fps"),
        2: ProbeResult(2, valid=True, resolution="1920×1080", frame_rate="50 fps"),
        3: ProbeResult(3, valid=False, status="超时"),
        4: ProbeResult(4, valid=True, resolution="720×576", frame_rate="25 fps"),
        5: ProbeResult(5, valid=True, resolution="3840×2160", frame_rate="50 fps"),
    }

    reordered, summaries = plan_reorder(document, results)
    rendered = render_playlist(document, reordered)
    urls = [block.channel.url for block in reordered]

    assert urls == [
        "http://example.com/a-1080-50.m3u8",
        "http://example.com/a-1080-25.m3u8",
        "http://example.com/a-720.m3u8",
        "http://example.com/b-live.m3u8",
        "http://example.com/b-failed.m3u8",
        "http://example.com/a-separate.m3u8",
    ]
    assert [summary.name for summary in summaries] == ["频道A", "频道B"]
    assert rendered.count("#EXTINF") == 6
    assert rendered.startswith('#EXTM3U url-tvg="https://example.com/epg.xml"')


def test_equal_quality_keeps_original_order() -> None:
    document = parse_playlist_document(_playlist())
    results = {index: ProbeResult(index, valid=True) for index in range(6)}

    reordered, summaries = plan_reorder(document, results)

    assert [block.index for block in reordered] == list(range(6))
    assert summaries == ()


def test_missing_probe_result_is_rejected() -> None:
    document = parse_playlist_document(_playlist())

    with pytest.raises(ValueError, match="缺少 1 条"):
        plan_reorder(document, {index: ProbeResult(index) for index in range(5)})


def test_read_quality_report_rejects_invalid_valid_flag(tmp_path: Path) -> None:
    channel = parse_playlist_document(_playlist()).blocks[0].channel
    report = tmp_path / "quality.csv"
    report.write_text(
        "index,name,url,valid,status,resolution,frame_rate,bitrate\n"
        f"0,{channel.name},{channel.url},yes,可用,1920×1080,50 fps,\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="valid 必须为 0 或 1"):
        read_quality_report(report, [channel])


def test_apply_playlist_creates_backup_and_writes_atomically(tmp_path: Path) -> None:
    playlist = tmp_path / "index.m3u"
    reports = tmp_path / "reports"
    playlist.write_text("old\n", encoding="utf-8")

    backup = apply_playlist(playlist, "new\n", reports)

    assert playlist.read_text(encoding="utf-8") == "new\n"
    assert backup.read_text(encoding="utf-8") == "old\n"
