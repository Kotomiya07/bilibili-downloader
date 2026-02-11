import asyncio
import logging
import shutil
import time
from pathlib import Path
from typing import Callable

import httpx

from bilibili_downloader.bilibili_client import BILIBILI_HEADERS

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 5 * 1024 * 1024 * 1024  # 5GB
FILE_TTL_SECONDS = 3600  # ダウンロード済みファイルの保持時間（1時間）


def check_ffmpeg() -> bool:
    """FFmpegがインストールされているか確認する。"""
    return shutil.which("ffmpeg") is not None


class Downloader:
    def __init__(self, download_dir: Path | None = None):
        self.download_dir = download_dir or Path("downloads")
        self.download_dir.mkdir(parents=True, exist_ok=True)

    async def download_stream(
        self,
        url: str,
        filename: str,
        on_progress: Callable[[dict], None] | None = None,
    ) -> Path:
        """ストリームをチャンク単位でダウンロードする。"""
        output_path = self.download_dir / filename
        async with httpx.AsyncClient(headers=BILIBILI_HEADERS, timeout=120.0) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length", 0))

                if total > MAX_FILE_SIZE:
                    raise Exception(f"ファイルサイズが上限({MAX_FILE_SIZE // (1024**3)}GB)を超えています")

                downloaded = 0

                with open(output_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=1024 * 256):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if downloaded > MAX_FILE_SIZE:
                            f.close()
                            output_path.unlink(missing_ok=True)
                            raise Exception("ファイルサイズが上限を超えました")
                        if on_progress and total > 0:
                            on_progress(
                                {
                                    "downloaded": downloaded,
                                    "total": total,
                                    "percent": round(downloaded / total * 100, 1),
                                }
                            )
        return output_path

    async def merge_streams(
        self, video_path: Path, audio_path: Path, output_name: str
    ) -> Path:
        """FFmpegで映像と音声をマージする。"""
        output_path = (self.download_dir / output_name).resolve()
        if not output_path.is_relative_to(self.download_dir.resolve()):
            raise ValueError("無効な出力パス")
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-i", str(video_path),
            "-i", str(audio_path),
            "-c", "copy",
            "-y",
            str(output_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise Exception(f"FFmpeg error: {stderr.decode()}")
        return output_path

    def cleanup(self, files: list[Path]) -> None:
        """一時ファイルを削除する。"""
        for f in files:
            if f.exists():
                f.unlink()

    def cleanup_old_files(self) -> int:
        """TTLを超えた古いダウンロードファイルを削除する。"""
        now = time.time()
        removed = 0
        for f in self.download_dir.iterdir():
            if f.is_file() and (now - f.stat().st_mtime) > FILE_TTL_SECONDS:
                f.unlink()
                removed += 1
                logger.info("Removed expired file: %s", f.name)
        return removed
