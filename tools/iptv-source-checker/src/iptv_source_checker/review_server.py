from __future__ import annotations

import argparse
import csv
import hashlib
import json
import mimetypes
import threading
import webbrowser
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .core import Channel, load_channels

DECISIONS = {"一致", "不一致", "无法确定"}
REQUEST_LIMIT = 5 * 1024 * 1024
SAVE_LOCK = threading.Lock()
LOCAL_HOSTS = {"127.0.0.1", "localhost"}


@dataclass(frozen=True, slots=True)
class ReviewItem:
    id: str
    name: str
    group: str
    source_no: int
    url: str
    capture_index: str
    capture_status: str
    capture_error: str
    logo_url: str
    crop_url: str
    frame_url: str
    logo_path: str
    crop_path: str
    frame_path: str


@dataclass(frozen=True, slots=True)
class ReviewData:
    playlist: Path
    report: Path
    items: list[ReviewItem]
    assets: dict[str, Path]
    dataset_id: str


def _repo_root(start: Path) -> Path | None:
    for candidate in (start.resolve(), *start.resolve().parents):
        if (candidate / "public" / "index.m3u").is_file():
            return candidate
    return None


def find_repo_root() -> Path:
    for start in (Path.cwd(), Path(__file__)):
        root = _repo_root(start)
        if root:
            return root
    raise ValueError("未找到包含 public/index.m3u 的仓库根目录")


def find_latest_report(repo_root: Path) -> Path:
    candidates = [
        path
        for path in (repo_root / "reports").glob("frame_check_*")
        if (path / "mapping.csv").is_file()
    ]
    if not candidates:
        raise ValueError("reports/ 下没有包含 mapping.csv 的 frame_check 报告")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _local_logo(channel: Channel, logo_dir: Path) -> Path | None:
    logo_root = logo_dir.resolve()
    stems = [channel.name, channel.tvg_id]
    parsed = urlparse(channel.logo)
    if parsed.path:
        stems.append(Path(unquote(parsed.path)).stem)
    for stem in filter(None, stems):
        for extension in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
            candidate = (logo_root / f"{stem}{extension}").resolve()
            if logo_root in candidate.parents and candidate.is_file():
                return candidate
    return None


def _report_asset(report: Path, relative: str) -> Path | None:
    if not relative:
        return None
    candidate = (report / relative).resolve()
    return candidate if report in candidate.parents else None


def _asset_url(item_id: str, kind: str, path: Path | None, assets: dict[str, Path]) -> str:
    if not path or not path.is_file():
        return ""
    key = f"{item_id}/{kind}"
    assets[key] = path.resolve()
    return f"/asset/{key}"


def build_review_data(repo_root: Path, playlist: Path, report: Path) -> ReviewData:
    playlist = playlist.resolve()
    report = report.resolve()
    if not playlist.is_file():
        raise ValueError(f"播放列表不存在：{playlist}")
    mapping_path = report / "mapping.csv"
    if not mapping_path.is_file():
        raise ValueError(f"报告缺少 mapping.csv：{report}")

    channels = load_channels(str(playlist))
    with mapping_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = {row.get("url", ""): row for row in csv.DictReader(handle)}

    source_counts: dict[str, int] = {}
    assets: dict[str, Path] = {}
    items: list[ReviewItem] = []
    logo_dir = repo_root / "public" / "logos"
    for channel in channels:
        source_counts[channel.name] = source_counts.get(channel.name, 0) + 1
        row = rows.get(channel.url, {})
        item_id = hashlib.sha256(channel.url.encode("utf-8")).hexdigest()[:16]
        frame_rel = row.get("frame", "")
        crop_rel = row.get("crop", "")
        logo_path = _local_logo(channel, logo_dir)
        frame_path = _report_asset(report, frame_rel)
        crop_path = _report_asset(report, crop_rel)
        items.append(
            ReviewItem(
                id=item_id,
                name=channel.name,
                group=channel.group,
                source_no=source_counts[channel.name],
                url=channel.url,
                capture_index=row.get("index", ""),
                capture_status=row.get("status", "missing") or "missing",
                capture_error=row.get("error", ""),
                logo_url=_asset_url(item_id, "logo", logo_path, assets),
                crop_url=_asset_url(item_id, "crop", crop_path, assets),
                frame_url=_asset_url(item_id, "frame", frame_path, assets),
                logo_path=str(logo_path or ""),
                crop_path=str(crop_path or ""),
                frame_path=str(frame_path or ""),
            )
        )

    dataset_id = hashlib.sha256(
        "\n".join((str(report), *(channel.url for channel in channels))).encode("utf-8")
    ).hexdigest()[:16]
    return ReviewData(playlist, report, items, assets, dataset_id)


def review_paths(report: Path) -> tuple[Path, Path]:
    return report / "manual_reviews.json", report / "manual_reviews.csv"


def load_reviews(report: Path) -> dict[str, dict[str, str]]:
    json_path, _ = review_paths(report)
    if not json_path.is_file():
        return {}
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"复核记录无法读取：{exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("复核记录格式错误：根节点必须是对象")
    return validate_reviews(payload, None)


def validate_reviews(
    payload: object, allowed_urls: set[str] | None
) -> dict[str, dict[str, str]]:
    if not isinstance(payload, dict):
        raise ValueError("reviews 必须是对象")
    validated: dict[str, dict[str, str]] = {}
    for url, value in payload.items():
        if not isinstance(url, str) or (allowed_urls is not None and url not in allowed_urls):
            raise ValueError("复核结果包含未知 URL")
        if not isinstance(value, dict):
            raise ValueError("每条复核结果必须是对象")
        decision = value.get("decision", "")
        note = value.get("note", "")
        if not isinstance(decision, str) or decision not in DECISIONS:
            raise ValueError(f"无效复核结论：{decision}")
        if not isinstance(note, str) or len(note) > 500:
            raise ValueError("备注必须是 500 字以内的文本")
        validated[url] = {"decision": decision, "note": note.strip()}
    return validated


def save_reviews(data: ReviewData, reviews: dict[str, dict[str, str]]) -> None:
    with SAVE_LOCK:
        _save_reviews(data, reviews)


def _save_reviews(data: ReviewData, reviews: dict[str, dict[str, str]]) -> None:
    json_path, csv_path = review_paths(data.report)
    current_urls = {item.url for item in data.items}
    merged = {
        url: review
        for url, review in load_reviews(data.report).items()
        if url not in current_urls
    }
    merged.update(reviews)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = json_path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(json_path)

    csv_temporary = csv_path.with_suffix(".csv.tmp")
    with csv_temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        fields = [
            "name",
            "group",
            "source_no",
            "url",
            "decision",
            "note",
            "capture_status",
            "capture_index",
            "logo_path",
            "crop_path",
            "frame_path",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in data.items:
            review = merged.get(item.url, {})
            writer.writerow(
                {
                    **{field: getattr(item, field) for field in fields if hasattr(item, field)},
                    "decision": review.get("decision", ""),
                    "note": review.get("note", ""),
                }
            )
    csv_temporary.replace(csv_path)


class ReviewHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], data: ReviewData, web_root: Path) -> None:
        super().__init__(address, ReviewHandler)
        self.data = data
        self.web_root = web_root.resolve()


class ReviewHandler(BaseHTTPRequestHandler):
    server: ReviewHTTPServer

    def do_GET(self) -> None:  # noqa: N802
        if not self._local_host_allowed():
            self._json({"error": "只接受本机页面请求"}, HTTPStatus.FORBIDDEN)
            return
        path = self.path.split("?", 1)[0]
        if path == "/api/data":
            try:
                reviews = load_reviews(self.server.data.report)
            except ValueError as exc:
                self._json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            self._json(
                {
                    "datasetId": self.server.data.dataset_id,
                    "playlist": str(self.server.data.playlist),
                    "report": str(self.server.data.report),
                    "items": [asdict(item) for item in self.server.data.items],
                    "reviews": reviews,
                }
            )
            return
        if path.startswith("/asset/"):
            key = unquote(path.removeprefix("/asset/"))
            asset = self.server.data.assets.get(key)
            if not asset:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self._file(asset)
            return
        relative = "index.html" if path == "/" else unquote(path.lstrip("/"))
        target = (self.server.web_root / relative).resolve()
        if self.server.web_root not in target.parents or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self._file(target)

    def do_POST(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0] != "/api/reviews":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        host_header = self.headers.get("Host", "")
        origin_header = self.headers.get("Origin")
        origin = urlparse(origin_header) if origin_header else None
        if not self._local_host_allowed() or (
            origin
            and (origin.scheme != "http" or origin.netloc.casefold() != host_header.casefold())
        ):
            self._json({"error": "只接受本机页面请求"}, HTTPStatus.FORBIDDEN)
            return
        if self.headers.get_content_type() != "application/json":
            self._json(
                {"error": "Content-Type 必须是 application/json"},
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
            )
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._json({"error": "Content-Length 无效"}, HTTPStatus.BAD_REQUEST)
            return
        if not 0 < length <= REQUEST_LIMIT:
            self._json({"error": "请求体为空或过大"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            reviews = validate_reviews(
                payload.get("reviews") if isinstance(payload, dict) else None,
                {item.url for item in self.server.data.items},
            )
            save_reviews(self.server.data, reviews)
        except (UnicodeError, json.JSONDecodeError, ValueError, OSError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self._json(
            {
                "saved": len(reviews),
                "savedAt": datetime.now(UTC).isoformat(),
                "csv": str(review_paths(self.server.data.report)[1]),
            }
        )

    def _local_host_allowed(self) -> bool:
        return urlparse(f"//{self.headers.get('Host', '')}").hostname in LOCAL_HOSTS

    def _json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _file(self, path: Path) -> None:
        data = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        return


def create_server(data: ReviewData, host: str, port: int) -> ReviewHTTPServer:
    web_root = Path(__file__).with_name("review_web")
    if not (web_root / "index.html").is_file():
        raise ValueError(f"复核页面资源缺失：{web_root}")
    try:
        return ReviewHTTPServer((host, port), data, web_root)
    except OSError:
        if port == 0:
            raise
        return ReviewHTTPServer((host, 0), data, web_root)


def _resolve_argument(value: str | None, default: Path) -> Path:
    return Path(value).expanduser().resolve() if value else default.resolve()


def main() -> None:
    parser = argparse.ArgumentParser(description="本地 IPTV Logo 与捕获画面人工复核工具")
    parser.add_argument("--playlist", help="M3U 路径，默认 public/index.m3u")
    parser.add_argument("--report", help="frame_check 报告目录，默认使用最新报告")
    parser.add_argument("--port", type=int, default=8765, help="监听端口，默认 8765")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()

    try:
        root = find_repo_root()
        playlist = _resolve_argument(args.playlist, root / "public" / "index.m3u")
        report = _resolve_argument(args.report, find_latest_report(root))
        data = build_review_data(root, playlist, report)
        server = create_server(data, "127.0.0.1", args.port)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    host, port = server.server_address[:2]
    bound_host = host.decode("ascii") if isinstance(host, bytes) else host
    display_host = "127.0.0.1" if bound_host in {"0.0.0.0", "::"} else bound_host
    url = f"http://{display_host}:{port}"
    print(f"Logo 画面复核工具：{url}")
    print(f"当前条目：{len(data.items)}，报告：{data.report}")
    if not args.no_browser:
        threading.Timer(0.4, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
