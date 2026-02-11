import pytest

from bilibili_downloader.bilibili_client import (
    extract_bvid,
    extract_url,
    resolve_short_url,
    BilibiliClient,
)


class TestExtractBvid:
    def test_standard_url(self):
        url = "https://www.bilibili.com/video/BV1Gk4y1y7A5"
        assert extract_bvid(url) == "BV1Gk4y1y7A5"

    def test_url_with_query_params(self):
        url = "https://www.bilibili.com/video/BV1Gk4y1y7A5?p=1&spm_id_from=333.337"
        assert extract_bvid(url) == "BV1Gk4y1y7A5"

    def test_url_with_trailing_slash(self):
        url = "https://www.bilibili.com/video/BV1Gk4y1y7A5/"
        assert extract_bvid(url) == "BV1Gk4y1y7A5"

    def test_mobile_url(self):
        url = "https://m.bilibili.com/video/BV1Gk4y1y7A5"
        assert extract_bvid(url) == "BV1Gk4y1y7A5"

    def test_bare_bvid(self):
        assert extract_bvid("BV1Gk4y1y7A5") == "BV1Gk4y1y7A5"

    def test_invalid_url_raises(self):
        with pytest.raises(ValueError):
            extract_bvid("https://www.youtube.com/watch?v=abc")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            extract_bvid("")


class TestExtractUrl:
    def test_plain_url(self):
        assert extract_url("https://www.bilibili.com/video/BV1xx411c7mD") == "https://www.bilibili.com/video/BV1xx411c7mD"

    def test_share_text_with_title(self):
        text = "【260211 田村真佑 Message-哔哩哔哩】 https://b23.tv/0qcc8LG"
        assert extract_url(text) == "https://b23.tv/0qcc8LG"

    def test_share_text_bilibili_url(self):
        text = "【乃木坂46日语教室~斋藤飞鸟篇~-哔哩哔哩】 https://www.bilibili.com/video/BV1Gk4y1y7A5?spm=123"
        assert extract_url(text) == "https://www.bilibili.com/video/BV1Gk4y1y7A5?spm=123"

    def test_no_url_raises(self):
        with pytest.raises(ValueError):
            extract_url("URLが含まれないテキスト")

    def test_bare_bvid(self):
        assert extract_url("BV1Gk4y1y7A5") == "BV1Gk4y1y7A5"


class TestResolveShortUrl:
    async def test_resolve_b23_url(self, httpx_mock):
        httpx_mock.add_response(
            url="https://b23.tv/tbNh7wk",
            status_code=302,
            headers={"Location": "https://www.bilibili.com/video/BV1Gk4y1y7A5"},
        )
        result = await resolve_short_url("https://b23.tv/tbNh7wk")
        assert result == "https://www.bilibili.com/video/BV1Gk4y1y7A5"

    async def test_non_short_url_returns_as_is(self):
        url = "https://www.bilibili.com/video/BV1Gk4y1y7A5"
        result = await resolve_short_url(url)
        assert result == url


class TestBilibiliClient:
    @pytest.fixture
    def client(self):
        return BilibiliClient()

    @pytest.mark.asyncio
    async def test_get_video_info_returns_metadata(self, client, httpx_mock):
        """動画情報APIが正しいレスポンスを返すことを確認"""
        mock_response = {
            "code": 0,
            "data": {
                "bvid": "BV1Gk4y1y7A5",
                "title": "乃木坂46日语教室~斋藤飞鸟篇~",
                "pic": "http://i0.hdslb.com/bfs/archive/thumb.jpg",
                "cid": 228989171,
                "pages": [{"cid": 228989171, "part": "asuka_reSE0818", "page": 1}],
            },
        }
        httpx_mock.add_response(
            url="https://api.bilibili.com/x/web-interface/view?bvid=BV1Gk4y1y7A5",
            json=mock_response,
        )
        info = await client.get_video_info("BV1Gk4y1y7A5")
        assert info["title"] == "乃木坂46日语教室~斋藤飞鸟篇~"
        assert info["bvid"] == "BV1Gk4y1y7A5"
        assert info["cid"] == 228989171

    @pytest.mark.asyncio
    async def test_get_play_url_returns_dash(self, client, httpx_mock):
        """再生URL取得APIがDASH情報を返すことを確認"""
        mock_response = {
            "code": 0,
            "data": {
                "dash": {
                    "video": [
                        {
                            "id": 80,
                            "baseUrl": "http://example.com/video.m4s",
                            "bandwidth": 2000000,
                            "codecid": 7,
                        }
                    ],
                    "audio": [
                        {
                            "id": 30280,
                            "baseUrl": "http://example.com/audio.m4s",
                            "bandwidth": 320000,
                            "codecid": 0,
                        }
                    ],
                },
                "accept_quality": [80, 64, 32, 16],
                "accept_description": ["1080P", "720P", "480P", "360P"],
            },
        }
        httpx_mock.add_response(json=mock_response)
        result = await client.get_play_url("BV1Gk4y1y7A5", 228989171, qn=80)
        assert "video" in result
        assert "audio" in result
        assert result["video"][0]["id"] == 80

    @pytest.mark.asyncio
    async def test_get_video_info_api_error(self, client, httpx_mock):
        """APIがエラーを返した場合にExceptionが発生することを確認"""
        mock_response = {"code": -404, "message": "啥都木有"}
        httpx_mock.add_response(json=mock_response)
        with pytest.raises(Exception, match="API error"):
            await client.get_video_info("BV_invalid")
