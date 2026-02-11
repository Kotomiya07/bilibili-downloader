import json
from pathlib import Path
from unittest.mock import patch

import pytest

from bilibili_downloader.auth import AuthManager


class TestAuthManager:
    @pytest.fixture
    def auth(self, tmp_path):
        return AuthManager(cookie_path=tmp_path / "cookies.json")

    @pytest.mark.asyncio
    async def test_generate_qr_returns_url_and_key(self, auth, httpx_mock):
        """QRコード生成APIが正しく処理されること"""
        httpx_mock.add_response(
            json={
                "code": 0,
                "data": {
                    "url": "https://passport.bilibili.com/h5-app/passport/login/scan?navhide=1&qrcode_key=abc123",
                    "qrcode_key": "abc123",
                },
            }
        )
        result = await auth.generate_qr()
        assert result["qrcode_key"] == "abc123"
        assert "qr_image_base64" in result

    @pytest.mark.asyncio
    async def test_poll_qr_status_waiting(self, auth, httpx_mock):
        """QRコード未スキャン時のステータスを確認"""
        httpx_mock.add_response(
            json={
                "code": 0,
                "data": {
                    "code": 86101,
                    "message": "未扫码",
                    "url": "",
                },
            }
        )
        result = await auth.poll_qr_status("abc123")
        assert result["status"] == "waiting"

    @pytest.mark.asyncio
    async def test_poll_qr_status_scanned(self, auth, httpx_mock):
        """QRコードスキャン済み（未確認）時のステータスを確認"""
        httpx_mock.add_response(
            json={
                "code": 0,
                "data": {
                    "code": 86090,
                    "message": "已扫码未确认",
                    "url": "",
                },
            }
        )
        result = await auth.poll_qr_status("abc123")
        assert result["status"] == "scanned"

    @pytest.mark.asyncio
    async def test_poll_qr_status_success(self, auth, httpx_mock):
        """ログイン成功時にCookieが保存されること"""
        httpx_mock.add_response(
            json={
                "code": 0,
                "data": {
                    "code": 0,
                    "message": "登录成功",
                    "url": "https://passport.bilibili.com?SESSDATA=abc&bili_jct=def&buvid3=ghi",
                },
            },
            headers={
                "set-cookie": "SESSDATA=abc; Path=/; Domain=.bilibili.com, bili_jct=def; Path=/; Domain=.bilibili.com"
            },
        )
        result = await auth.poll_qr_status("abc123")
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_poll_qr_status_expired(self, auth, httpx_mock):
        """QRコード期限切れ時のステータスを確認"""
        httpx_mock.add_response(
            json={
                "code": 0,
                "data": {
                    "code": 86038,
                    "message": "二维码已过期",
                    "url": "",
                },
            }
        )
        result = await auth.poll_qr_status("abc123")
        assert result["status"] == "expired"

    def test_save_and_load_cookies(self, auth, tmp_path):
        """Cookieの保存と読み込みが正しく動作すること"""
        cookies = {"SESSDATA": "abc", "bili_jct": "def", "buvid3": "ghi"}
        auth.save_cookies(cookies)

        loaded = auth.load_cookies()
        assert loaded == cookies

    def test_load_cookies_no_file(self, auth):
        """Cookie ファイルが存在しない場合Noneを返すこと"""
        result = auth.load_cookies()
        assert result is None

    def test_is_logged_in_with_cookies(self, auth):
        """Cookieがある場合、ログイン済みと判定されること"""
        auth.save_cookies({"SESSDATA": "abc", "bili_jct": "def"})
        assert auth.is_logged_in() is True

    def test_is_logged_in_without_cookies(self, auth):
        """Cookieがない場合、未ログインと判定されること"""
        assert auth.is_logged_in() is False
