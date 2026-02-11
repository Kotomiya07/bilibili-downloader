import asyncio
import json
import logging
import re
import secrets
import time
import uuid
from pathlib import Path

import httpx
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from bilibili_downloader.auth import AuthManager
from bilibili_downloader.bilibili_client import BilibiliClient, extract_bvid, extract_url, resolve_short_url
from bilibili_downloader.downloader import Downloader, check_ffmpeg

logger = logging.getLogger(__name__)

router = APIRouter()

# --- グローバルサービス ---
_downloader: Downloader | None = None
_download_dir: Path | None = None
_cookie_dir: Path | None = None

# セッション管理: session_id -> UserSession
_sessions: dict[str, "UserSession"] = {}

SESSION_COOKIE_NAME = "bilidl_session"
SESSION_TTL_SECONDS = 86400 * 7  # 7日間


class UserSession:
    """ユーザーごとのセッション状態を管理する。"""

    def __init__(self, session_id: str, cookie_dir: Path):
        self.session_id = session_id
        self.auth = AuthManager(cookie_path=cookie_dir / f"{session_id}.dat")
        self.client = BilibiliClient()
        self.tasks: dict[str, dict] = {}
        self.last_accessed: float = time.time()

        # 保存済みCookieがあればクライアントに設定
        cookies = self.auth.load_cookies()
        if cookies:
            self.client.set_cookies(cookies)


def init_services(download_dir: Path | None = None, cookie_path: Path | None = None):
    global _downloader, _download_dir, _cookie_dir
    _download_dir = download_dir or Path("downloads")
    _cookie_dir = cookie_path.parent if cookie_path else Path(".")
    _downloader = Downloader(download_dir=_download_dir)


def get_downloader() -> Downloader:
    if _downloader is None:
        init_services()
    return _downloader


def _get_session(request: Request, response: Response | None = None) -> UserSession:
    """リクエストからセッションを取得または作成する。"""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)

    if session_id and session_id in _sessions:
        _sessions[session_id].last_accessed = time.time()
        return _sessions[session_id]

    # 新規セッション作成
    session_id = secrets.token_urlsafe(32)
    cookie_dir = _cookie_dir or Path(".")
    session = UserSession(session_id, cookie_dir)
    _sessions[session_id] = session
    return session


def _set_session_cookie(response: Response, session_id: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        session_id,
        httponly=True,
        samesite="strict",
        max_age=SESSION_TTL_SECONDS,
    )


def cleanup_expired_sessions() -> int:
    """TTLを超過したセッションをメモリと.datファイルから削除する。"""
    now = time.time()
    expired = [
        sid for sid, s in _sessions.items()
        if (now - s.last_accessed) > SESSION_TTL_SECONDS
    ]
    for sid in expired:
        session = _sessions.pop(sid)
        dat_path = session.auth._cookie_path
        if dat_path.exists():
            dat_path.unlink()
            logger.info("Removed expired session file: %s", dat_path.name)
    return len(expired)


# テスト用ヘルパー
def get_auth_manager() -> AuthManager:
    """後方互換: テストのモック用。"""
    cookie_dir = _cookie_dir or Path(".")
    return AuthManager(cookie_path=cookie_dir / "cookies.dat")


def get_bilibili_client() -> BilibiliClient:
    """後方互換: テストのモック用。"""
    return BilibiliClient()


# --- Request models ---
class VideoInfoRequest(BaseModel):
    url: str


_VALID_QUALITIES = {16, 32, 64, 80, 112, 120}


class DownloadRequest(BaseModel):
    url: str
    quality: int = 80

    def model_post_init(self, __context):
        if self.quality not in _VALID_QUALITIES:
            raise ValueError(f"無効な画質コードです: {self.quality}")


# --- Auth endpoints ---
@router.post("/api/login/qr/generate")
async def generate_qr(request: Request, response: Response):
    session = _get_session(request)
    _set_session_cookie(response, session.session_id)
    result = await session.auth.generate_qr()
    return result


@router.get("/api/login/qr/poll")
async def poll_qr(request: Request, response: Response, qrcode_key: str):
    session = _get_session(request)
    _set_session_cookie(response, session.session_id)
    result = await session.auth.poll_qr_status(qrcode_key)
    if result["status"] == "success":
        cookies = session.auth.get_cookies()
        session.client.set_cookies(cookies)
    return result


@router.get("/api/login/status")
async def login_status(request: Request, response: Response):
    session = _get_session(request)
    _set_session_cookie(response, session.session_id)
    return {"logged_in": session.auth.is_logged_in()}


# --- Video endpoints ---
@router.post("/api/video/info")
async def video_info(request: Request, response: Response, req: VideoInfoRequest):
    session = _get_session(request)
    _set_session_cookie(response, session.session_id)
    bc = session.client
    raw_url = extract_url(req.url)
    resolved_url = await resolve_short_url(raw_url)
    bvid = extract_bvid(resolved_url)
    info = await bc.get_video_info(bvid)
    play_url = await bc.get_play_url(bvid, info["cid"])

    quality_options = []
    for qn, desc in zip(
        play_url["accept_quality"], play_url["accept_description"]
    ):
        quality_options.append({"qn": qn, "description": desc})

    # プレビュー用: 最低画質の映像と最初の音声
    preview_video_url = sorted(play_url["video"], key=lambda v: v["id"])[0]["baseUrl"]
    preview_audio_url = play_url["audio"][0]["baseUrl"]

    return {
        "bvid": info["bvid"],
        "title": info["title"],
        "pic": info["pic"],
        "cid": info["cid"],
        "pages": info.get("pages", []),
        "quality_options": quality_options,
        "preview_video_url": preview_video_url,
        "preview_audio_url": preview_audio_url,
    }


# --- Stream proxy ---
_ALLOWED_DOMAINS = ("bilivideo.com", "bilivideo.cn", "akamaized.net", "hdslb.com")


def _is_allowed_url(url: str) -> bool:
    """URLがBilibili CDNドメインかつHTTP(S)であることを検証する。"""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.hostname or ""
    return any(host == d or host.endswith("." + d) for d in _ALLOWED_DOMAINS)


@router.get("/api/proxy/stream")
async def proxy_stream(request: Request, url: str):
    """Bilibili CDNのストリームをプロキシし、Rangeリクエストに対応する。"""
    if not _is_allowed_url(url):
        return JSONResponse(status_code=400, content={"error": "許可されていないURLです"})

    from bilibili_downloader.bilibili_client import BILIBILI_HEADERS

    # ブラウザからのRangeヘッダーをCDNに転送
    proxy_headers = dict(BILIBILI_HEADERS)
    range_header = request.headers.get("range")
    if range_header:
        proxy_headers["Range"] = range_header

    client = httpx.AsyncClient(
        headers=proxy_headers, timeout=60.0, follow_redirects=False,
    )
    req = client.build_request("GET", url)
    resp = await client.send(req, stream=True)

    # リダイレクトされた場合、リダイレクト先も検証
    if resp.status_code in (301, 302, 307, 308):
        await resp.aclose()
        await client.aclose()
        return JSONResponse(status_code=400, content={"error": "リダイレクトは許可されていません"})

    async def stream_generator():
        try:
            async for chunk in resp.aiter_bytes(chunk_size=1024 * 256):
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    # レスポンスヘッダーを構築
    response_headers = {}
    for key in ("content-length", "content-range", "accept-ranges"):
        if key in resp.headers:
            response_headers[key] = resp.headers[key]
    if "accept-ranges" not in response_headers:
        response_headers["accept-ranges"] = "bytes"

    status_code = resp.status_code  # 200 or 206
    content_type = resp.headers.get("content-type", "video/mp4")

    return StreamingResponse(
        stream_generator(),
        status_code=status_code,
        media_type=content_type,
        headers=response_headers,
    )


# --- Download endpoints ---
MAX_CONCURRENT_DOWNLOADS = 3

# グローバルタスク一覧（クリーンアップ用に参照）
_download_tasks: dict[str, dict] = {}


@router.post("/api/download")
async def start_download(request: Request, response: Response, req: DownloadRequest):
    session = _get_session(request)
    _set_session_cookie(response, session.session_id)

    if not check_ffmpeg():
        return JSONResponse(
            status_code=500,
            content={"error": "FFmpegがインストールされていません"},
        )

    active = sum(
        1 for t in _download_tasks.values()
        if t["status"] in ("starting", "downloading")
    )
    if active >= MAX_CONCURRENT_DOWNLOADS:
        return JSONResponse(
            status_code=429,
            content={"error": f"同時ダウンロードは最大{MAX_CONCURRENT_DOWNLOADS}件です。しばらくお待ちください。"},
        )

    task_id = str(uuid.uuid4())
    task_data = {
        "status": "starting",
        "progress_video": 0,
        "progress_audio": 0,
        "phase": "init",
        "filename": None,
        "error": None,
        "session_id": session.session_id,
    }
    session.tasks[task_id] = task_data
    _download_tasks[task_id] = task_data

    asyncio.create_task(_run_download(task_id, req.url, req.quality, session))
    return {"task_id": task_id}


async def _run_download(task_id: str, url: str, quality: int, session: UserSession):
    """バックグラウンドでダウンロードを実行する。"""
    task = _download_tasks[task_id]
    try:
        bc = session.client
        dl = get_downloader()

        bvid = extract_bvid(await resolve_short_url(extract_url(url)))
        info = await bc.get_video_info(bvid)
        title = info["title"]
        # ファイル名を安全な文字のみに制限
        safe_title = re.sub(r'[^\w\s\-]', '', title, flags=re.UNICODE).strip()[:100]
        if not safe_title:
            safe_title = bvid
        cid = info["cid"]

        play_url = await bc.get_play_url(bvid, cid, qn=quality)

        # 最適な映像ストリームを選択（指定画質以下で最高）
        video_streams = sorted(play_url["video"], key=lambda v: v["id"], reverse=True)
        video_stream = None
        for vs in video_streams:
            if vs["id"] <= quality:
                video_stream = vs
                break
        if not video_stream:
            video_stream = video_streams[-1]

        audio_stream = play_url["audio"][0]  # 最高音質

        # 映像ダウンロード
        task["phase"] = "video"
        task["status"] = "downloading"

        def on_video_progress(p):
            task["progress_video"] = p["percent"]

        video_path = await dl.download_stream(
            video_stream["baseUrl"],
            f"{task_id}_video.m4s",
            on_progress=on_video_progress,
        )

        # 音声ダウンロード
        task["phase"] = "audio"

        def on_audio_progress(p):
            task["progress_audio"] = p["percent"]

        audio_path = await dl.download_stream(
            audio_stream["baseUrl"],
            f"{task_id}_audio.m4s",
            on_progress=on_audio_progress,
        )

        # マージ
        task["phase"] = "merging"
        output_name = f"{safe_title}.mp4"
        await dl.merge_streams(video_path, audio_path, output_name)

        # クリーンアップ
        dl.cleanup([video_path, audio_path])

        task["status"] = "completed"
        task["phase"] = "done"
        task["filename"] = output_name

    except Exception as e:
        logger.error("Download error for task %s: %s", task_id, e, exc_info=True)
        task["status"] = "error"
        task["error"] = "ダウンロード中にエラーが発生しました"


@router.get("/api/download/progress/{task_id}")
async def download_progress(request: Request, task_id: str):
    """SSEで進捗を配信する。自分のタスクのみ参照可能。"""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    task = _download_tasks.get(task_id)

    if task is None or (session_id and task.get("session_id") != session_id):
        async def error_gen():
            yield {"event": "error", "data": json.dumps({"error": "Task not found"})}
        return EventSourceResponse(error_gen())

    async def event_generator():
        while True:
            t = _download_tasks.get(task_id)
            if t is None:
                yield {"event": "error", "data": json.dumps({"error": "Task not found"})}
                return

            # session_id をクライアントに送らない
            safe_data = {k: v for k, v in t.items() if k != "session_id"}
            yield {
                "event": "progress",
                "data": json.dumps(safe_data),
            }

            if t["status"] in ("completed", "error"):
                return

            await asyncio.sleep(0.5)

    return EventSourceResponse(event_generator())


@router.get("/api/download/file/{filename:path}")
async def download_file(filename: str):
    dl = get_downloader()
    file_path = (dl.download_dir / filename).resolve()
    if not file_path.is_relative_to(dl.download_dir.resolve()):
        return JSONResponse(status_code=403, content={"error": "アクセス拒否"})
    if not file_path.exists():
        return JSONResponse(status_code=404, content={"error": "ファイルが見つかりません"})
    return FileResponse(
        path=file_path,
        filename=file_path.name,
        media_type="video/mp4",
    )
