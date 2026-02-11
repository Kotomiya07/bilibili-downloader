import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from bilibili_downloader.downloader import Downloader, check_ffmpeg


class TestCheckFfmpeg:
    def test_ffmpeg_found(self):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            assert check_ffmpeg() is True

    def test_ffmpeg_not_found(self):
        with patch("shutil.which", return_value=None):
            assert check_ffmpeg() is False


class TestDownloader:
    @pytest.fixture
    def downloader(self, tmp_path):
        return Downloader(download_dir=tmp_path)

    @pytest.mark.asyncio
    async def test_download_stream_creates_file(self, downloader, httpx_mock):
        """ストリームダウンロードでファイルが作成されること"""
        content = b"fake video data" * 100
        httpx_mock.add_response(
            url="http://example.com/video.m4s",
            content=content,
            headers={"content-length": str(len(content))},
        )

        progress_values = []

        def on_progress(p):
            progress_values.append(p)

        output = await downloader.download_stream(
            "http://example.com/video.m4s",
            "test_video.m4s",
            on_progress=on_progress,
        )
        assert output.exists()
        assert output.read_bytes() == content

    @pytest.mark.asyncio
    async def test_download_stream_no_content_length(self, downloader, httpx_mock):
        """Content-Lengthなしでもダウンロードできること"""
        content = b"fake data"
        httpx_mock.add_response(
            url="http://example.com/audio.m4s",
            content=content,
        )
        output = await downloader.download_stream(
            "http://example.com/audio.m4s",
            "test_audio.m4s",
        )
        assert output.exists()
        assert output.read_bytes() == content

    @pytest.mark.asyncio
    async def test_merge_streams_calls_ffmpeg(self, downloader, tmp_path):
        """マージ処理がFFmpegを正しく呼び出すこと"""
        video_path = tmp_path / "video.m4s"
        audio_path = tmp_path / "audio.m4s"
        video_path.write_bytes(b"video")
        audio_path.write_bytes(b"audio")

        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b"", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
            result = await downloader.merge_streams(
                video_path, audio_path, "output.mp4"
            )
            mock_exec.assert_called_once()
            args = mock_exec.call_args[0]
            assert args[0] == "ffmpeg"
            assert "output.mp4" in str(args)

    @pytest.mark.asyncio
    async def test_merge_streams_ffmpeg_failure(self, downloader, tmp_path):
        """FFmpegが失敗した場合にExceptionが発生すること"""
        video_path = tmp_path / "video.m4s"
        audio_path = tmp_path / "audio.m4s"
        video_path.write_bytes(b"video")
        audio_path.write_bytes(b"audio")

        mock_process = AsyncMock()
        mock_process.returncode = 1
        mock_process.communicate = AsyncMock(return_value=(b"", b"error msg"))

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            with pytest.raises(Exception, match="FFmpeg"):
                await downloader.merge_streams(
                    video_path, audio_path, "output.mp4"
                )

    def test_cleanup_removes_temp_files(self, downloader, tmp_path):
        """一時ファイルのクリーンアップが正しく動作すること"""
        f1 = tmp_path / "temp1.m4s"
        f2 = tmp_path / "temp2.m4s"
        f1.write_bytes(b"data")
        f2.write_bytes(b"data")
        downloader.cleanup([f1, f2])
        assert not f1.exists()
        assert not f2.exists()
