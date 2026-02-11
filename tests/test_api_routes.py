import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock, MagicMock

from bilibili_downloader.app import create_app
from bilibili_downloader import api_routes


@pytest.fixture
def app(tmp_path):
    # グローバル状態をリセットしてテスト分離を確保
    api_routes._downloader = None
    api_routes._download_dir = None
    api_routes._cookie_dir = None
    api_routes._sessions = {}
    api_routes._download_tasks = {}
    return create_app(download_dir=tmp_path, cookie_path=tmp_path / "cookies.json")


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestAPIRoutes:
    @pytest.mark.asyncio
    async def test_index_page(self, client):
        """トップページが正しく配信されること"""
        resp = await client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    @pytest.mark.asyncio
    async def test_login_status_not_logged_in(self, client):
        """未ログイン時のステータス確認"""
        resp = await client.get("/api/login/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["logged_in"] is False

    @pytest.mark.asyncio
    async def test_login_status_sets_session_cookie(self, client):
        """セッションCookieが設定されること"""
        resp = await client.get("/api/login/status")
        assert resp.status_code == 200
        assert "bilidl_session" in resp.cookies

    @pytest.mark.asyncio
    async def test_generate_qr(self, client):
        """QRコード生成エンドポイントのテスト"""
        mock_result = {"qrcode_key": "test_key", "qr_image_base64": "base64data"}
        with patch.object(
            api_routes.UserSession, "__init__", lambda self, *a, **kw: None
        ):
            # セッションを直接注入
            session = object.__new__(api_routes.UserSession)
            session.session_id = "test_session"
            session.auth = AsyncMock()
            session.auth.generate_qr = AsyncMock(return_value=mock_result)
            session.auth.load_cookies = MagicMock(return_value=None)
            session.client = AsyncMock()
            session.tasks = {}
            api_routes._sessions["test_session"] = session

            resp = await client.post(
                "/api/login/qr/generate",
                cookies={"bilidl_session": "test_session"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["qrcode_key"] == "test_key"

    @pytest.mark.asyncio
    async def test_video_info(self, client):
        """動画情報取得エンドポイントのテスト"""
        mock_info = {
            "bvid": "BV1Gk4y1y7A5",
            "title": "乃木坂46日语教室~斋藤飞鸟篇~",
            "pic": "http://i0.hdslb.com/bfs/archive/thumb.jpg",
            "cid": 228989171,
            "pages": [{"cid": 228989171, "part": "asuka_reSE0818", "page": 1}],
        }
        mock_play_url = {
            "video": [{"id": 80, "baseUrl": "http://example.com/video.m4s"}],
            "audio": [{"id": 30280, "baseUrl": "http://example.com/audio.m4s"}],
            "accept_quality": [80, 64, 32],
            "accept_description": ["1080P", "720P", "480P"],
        }
        session = object.__new__(api_routes.UserSession)
        session.session_id = "test_session2"
        session.auth = AsyncMock()
        session.auth.load_cookies = MagicMock(return_value=None)
        session.client = AsyncMock()
        session.client.get_video_info = AsyncMock(return_value=mock_info)
        session.client.get_play_url = AsyncMock(return_value=mock_play_url)
        session.tasks = {}
        api_routes._sessions["test_session2"] = session

        resp = await client.post(
            "/api/video/info",
            json={"url": "https://www.bilibili.com/video/BV1Gk4y1y7A5"},
            cookies={"bilidl_session": "test_session2"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "乃木坂46日语教室~斋藤飞鸟篇~"
        assert len(data["quality_options"]) > 0

    @pytest.mark.asyncio
    async def test_download_progress_denied_for_other_session(self, client):
        """他ユーザーのタスク進捗は参照できないこと"""
        api_routes._download_tasks["task123"] = {
            "status": "downloading",
            "session_id": "other_session",
        }
        resp = await client.get(
            "/api/download/progress/task123",
            cookies={"bilidl_session": "my_session"},
        )
        assert resp.status_code == 200
        # SSEでエラーイベントが返される
        body = resp.text
        assert "Task not found" in body
