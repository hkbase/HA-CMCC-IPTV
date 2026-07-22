import csv
import json
import os
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from iptv_source_checker.review_server import (
    ReviewData,
    ReviewItem,
    build_review_data,
    create_server,
    find_latest_report,
    load_reviews,
    review_paths,
    save_reviews,
    validate_reviews,
)


def _write_playlist(path: Path) -> None:
    path.write_text(
        """#EXTM3U
#EXTINF:-1 tvg-id="频道新名" tvg-name="频道新名" """
        """tvg-logo="logos/频道新名.png" group-title="测试组",频道新名
http://example.com/kept.m3u8
"""
        """#EXTINF:-1 tvg-id="无画面" tvg-name="无画面" """
        """tvg-logo="logos/无画面.png" group-title="测试组",无画面
http://example.com/failed.m3u8
""",
        encoding="utf-8",
    )


def _write_mapping(path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("index", "status", "name", "url", "frame", "crop", "error"),
        )
        writer.writeheader()
        writer.writerows(
            [
                {
                    "index": "7",
                    "status": "ok",
                    "name": "频道旧名",
                    "url": "http://example.com/kept.m3u8",
                    "frame": "frames/0007.jpg",
                    "crop": "crops/0007.jpg",
                    "error": "",
                },
                {
                    "index": "8",
                    "status": "failed",
                    "name": "无画面",
                    "url": "http://example.com/failed.m3u8",
                    "frame": "",
                    "crop": "",
                    "error": "404",
                },
                {
                    "index": "9",
                    "status": "ok",
                    "name": "已删除",
                    "url": "http://example.com/removed.m3u8",
                    "frame": "frames/0009.jpg",
                    "crop": "crops/0009.jpg",
                    "error": "",
                },
            ]
        )


def test_build_review_data_uses_current_playlist_names_and_filters_removed_urls(
    tmp_path: Path,
) -> None:
    root = tmp_path
    playlist = root / "public" / "index.m3u"
    logo_dir = root / "public" / "logos"
    report = root / "reports" / "frame_check_1"
    (report / "frames").mkdir(parents=True)
    (report / "crops").mkdir()
    logo_dir.mkdir(parents=True)
    _write_playlist(playlist)
    _write_mapping(report / "mapping.csv")
    (logo_dir / "频道新名.png").write_bytes(b"logo")
    (report / "frames" / "0007.jpg").write_bytes(b"frame")
    (report / "crops" / "0007.jpg").write_bytes(b"crop")

    data = build_review_data(root, playlist, report)

    assert [item.name for item in data.items] == ["频道新名", "无画面"]
    assert data.items[0].capture_index == "7"
    assert data.items[0].logo_url.endswith("/logo")
    assert data.items[0].frame_url.endswith("/frame")
    assert data.items[1].capture_status == "failed"
    assert data.items[1].frame_url == ""
    assert all("removed" not in item.url for item in data.items)
    assert len(data.assets) == 3

    copied_report = root / "reports" / "frame_check_2"
    copied_report.mkdir()
    _write_mapping(copied_report / "mapping.csv")
    copied_data = build_review_data(root, playlist, copied_report)
    assert copied_data.dataset_id != data.dataset_id


def test_build_review_data_rejects_assets_outside_allowed_directories(tmp_path: Path) -> None:
    root = tmp_path
    playlist = root / "public" / "index.m3u"
    report = root / "reports" / "frame_check_1"
    report.mkdir(parents=True)
    playlist.parent.mkdir(parents=True, exist_ok=True)
    playlist.write_text(
        """#EXTM3U
#EXTINF:-1 tvg-id="../secret" group-title="测试",../secret
http://example.com/live.m3u8
""",
        encoding="utf-8",
    )
    outside_logo = root / "public" / "secret.png"
    outside_logo.write_bytes(b"secret-logo")
    outside_frame = report.parent / "secret.jpg"
    outside_frame.write_bytes(b"secret-frame")
    with (report / "mapping.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("index", "status", "name", "url", "frame", "crop", "error"),
        )
        writer.writeheader()
        writer.writerow(
            {
                "index": "1",
                "status": "ok",
                "name": "../secret",
                "url": "http://example.com/live.m3u8",
                "frame": "../secret.jpg",
                "crop": "../secret.jpg",
                "error": "",
            }
        )

    data = build_review_data(root, playlist, report)

    assert data.items[0].logo_url == ""
    assert data.items[0].frame_url == ""
    assert data.items[0].crop_url == ""
    assert data.assets == {}


def test_validate_reviews_checks_urls_decisions_and_note_length() -> None:
    allowed = {"http://example.com/live.m3u8"}
    assert validate_reviews(
        {
            "http://example.com/live.m3u8": {
                "decision": "一致",
                "note": "  已确认  ",
            }
        },
        allowed,
    ) == {"http://example.com/live.m3u8": {"decision": "一致", "note": "已确认"}}

    with pytest.raises(ValueError, match="未知 URL"):
        validate_reviews({"http://example.com/other": {"decision": "一致"}}, allowed)
    with pytest.raises(ValueError, match="无效复核结论"):
        validate_reviews(
            {"http://example.com/live.m3u8": {"decision": "跳过"}},
            allowed,
        )
    with pytest.raises(ValueError, match="无效复核结论"):
        validate_reviews(
            {"http://example.com/live.m3u8": {"decision": []}},
            allowed,
        )
    with pytest.raises(ValueError, match="500 字"):
        validate_reviews(
            {"http://example.com/live.m3u8": {"decision": "一致", "note": "x" * 501}},
            allowed,
        )


def test_save_reviews_writes_json_and_csv_and_can_clear_current_records(tmp_path: Path) -> None:
    report = tmp_path / "report"
    item = ReviewItem(
        id="abc",
        name="测试频道",
        group="测试组",
        source_no=1,
        url="http://example.com/live.m3u8",
        capture_index="1",
        capture_status="ok",
        capture_error="",
        logo_url="/asset/abc/logo",
        crop_url="/asset/abc/crop",
        frame_url="/asset/abc/frame",
        logo_path="logo.png",
        crop_path="crop.jpg",
        frame_path="frame.jpg",
    )
    data = ReviewData(
        playlist=tmp_path / "index.m3u",
        report=report,
        items=[item],
        assets={},
        dataset_id="dataset",
    )

    save_reviews(data, {item.url: {"decision": "不一致", "note": "错台"}})

    json_path, csv_path = review_paths(report)
    assert load_reviews(report) == {item.url: {"decision": "不一致", "note": "错台"}}
    assert json.loads(json_path.read_text(encoding="utf-8"))[item.url]["decision"] == "不一致"
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["name"] == "测试频道"
    assert rows[0]["decision"] == "不一致"
    assert rows[0]["frame_path"] == "frame.jpg"

    save_reviews(data, {})

    assert load_reviews(report) == {}
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["decision"] == ""


def test_find_latest_report_requires_mapping_and_uses_mtime(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    old = reports / "frame_check_old"
    new = reports / "frame_check_new"
    ignored = reports / "frame_check_incomplete"
    for path in (old, new, ignored):
        path.mkdir(parents=True)
    (old / "mapping.csv").touch()
    (new / "mapping.csv").touch()
    # Directory mtimes are the report selection signal.
    old_time = new.stat().st_mtime - 20
    os.utime(old, (old_time, old_time))

    assert find_latest_report(tmp_path) == new


def test_http_api_serves_data_assets_and_validates_review_posts(tmp_path: Path) -> None:
    report = tmp_path / "report"
    report.mkdir()
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"logo-bytes")
    item = ReviewItem(
        id="abc",
        name="测试频道",
        group="测试组",
        source_no=1,
        url="http://example.com/live.m3u8",
        capture_index="1",
        capture_status="ok",
        capture_error="",
        logo_url="/asset/abc/logo",
        crop_url="",
        frame_url="",
        logo_path=str(logo),
        crop_path="",
        frame_path="",
    )
    data = ReviewData(
        playlist=tmp_path / "index.m3u",
        report=report,
        items=[item],
        assets={"abc/logo": logo},
        dataset_id="dataset",
    )
    server = create_server(data, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"

    try:
        with urlopen(f"{base_url}/api/data", timeout=5) as response:
            payload = json.load(response)
        assert payload["datasetId"] == "dataset"
        assert payload["items"][0]["name"] == "测试频道"

        foreign_host = Request(
            f"{base_url}/api/data",
            headers={"Host": "example.com"},
        )
        with pytest.raises(HTTPError) as exc_info:
            urlopen(foreign_host, timeout=5)
        assert exc_info.value.code == 403

        with urlopen(f"{base_url}/asset/abc/logo", timeout=5) as response:
            assert response.read() == b"logo-bytes"

        body = json.dumps(
            {"reviews": {item.url: {"decision": "无法确定", "note": "人工复核"}}},
            ensure_ascii=False,
        ).encode("utf-8")
        request = Request(
            f"{base_url}/api/reviews",
            data=body,
            headers={"Content-Type": "application/json", "Origin": base_url},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            saved = json.load(response)
        assert saved["saved"] == 1
        assert load_reviews(report)[item.url]["note"] == "人工复核"

        invalid = Request(
            f"{base_url}/api/reviews",
            data=json.dumps(
                {"reviews": {item.url: {"decision": [], "note": ""}}}
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(HTTPError) as exc_info:
            urlopen(invalid, timeout=5)
        assert exc_info.value.code == 400

        wrong_origin = Request(
            f"{base_url}/api/reviews",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Origin": "https://example.com",
            },
            method="POST",
        )
        with pytest.raises(HTTPError) as exc_info:
            urlopen(wrong_origin, timeout=5)
        assert exc_info.value.code == 403

        wrong_type = Request(
            f"{base_url}/api/reviews",
            data=body,
            headers={"Content-Type": "text/plain"},
            method="POST",
        )
        with pytest.raises(HTTPError) as exc_info:
            urlopen(wrong_type, timeout=5)
        assert exc_info.value.code == 415
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
