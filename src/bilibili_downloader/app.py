import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from bilibili_downloader.api_routes import router, init_services, get_downloader, _download_tasks, cleanup_expired_sessions

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


async def _periodic_cleanup():
    """定期的に古いファイルと完了タスクをクリーンアップする。"""
    while True:
        await asyncio.sleep(600)  # 10分ごと
        try:
            dl = get_downloader()
            removed = dl.cleanup_old_files()
            if removed:
                logger.info("Cleaned up %d expired files", removed)

            # 完了/エラーのタスクを削除
            expired_keys = [
                k for k, v in _download_tasks.items()
                if v["status"] in ("completed", "error")
            ]
            for k in expired_keys:
                del _download_tasks[k]
            if expired_keys:
                logger.info("Cleaned up %d finished tasks", len(expired_keys))

            # 期限切れセッションと.datファイルを削除
            expired_sessions = cleanup_expired_sessions()
            if expired_sessions:
                logger.info("Cleaned up %d expired sessions", expired_sessions)
        except Exception:
            logger.exception("Cleanup error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_periodic_cleanup())
    yield
    task.cancel()


def create_app(download_dir: Path | None = None, cookie_path: Path | None = None) -> FastAPI:
    app = FastAPI(title="Bilibili Downloader", lifespan=lifespan)

    # セキュリティヘッダー
    app.add_middleware(SecurityHeadersMiddleware)

    # サービス初期化
    init_services(download_dir=download_dir or Path("downloads"), cookie_path=cookie_path)

    # APIルーター登録
    app.include_router(router)

    # 静的ファイル配信
    static_dir = Path(__file__).parent / "static"

    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    async def index():
        return FileResponse(static_dir / "index.html")

    return app


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Bilibili Downloader")
    parser.add_argument("--host", default="0.0.0.0", help="バインドホスト")
    parser.add_argument("--port", type=int, default=8000, help="ポート番号")
    parser.add_argument("--ssl-keyfile", default=None, help="SSL秘密鍵ファイル")
    parser.add_argument("--ssl-certfile", default=None, help="SSL証明書ファイル")
    parser.add_argument("--download-dir", default=None, help="ダウンロード先ディレクトリ")
    args = parser.parse_args()

    download_dir = Path(args.download_dir) if args.download_dir else None
    app = create_app(download_dir=download_dir)

    ssl_kwargs = {}
    if args.ssl_certfile and args.ssl_keyfile:
        ssl_kwargs["ssl_certfile"] = args.ssl_certfile
        ssl_kwargs["ssl_keyfile"] = args.ssl_keyfile

    uvicorn.run(app, host=args.host, port=args.port, **ssl_kwargs)


if __name__ == "__main__":
    main()
