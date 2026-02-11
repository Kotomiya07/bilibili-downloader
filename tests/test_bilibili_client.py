import pytest

from bilibili_downloader.bilibili_client import (
    extract_bvid,
    BilibiliClient,
)


class TestExtractBvid:
    def test_standard_url(self):
        url = "https://www.bilibili.com/video/BV1xx411c7mD"
        assert extract_bvid(url) == "BV1xx411c7mD"

    def test_url_with_query_params(self):
        url = "https://www.bilibili.com/video/BV1xx411c7mD?p=1&spm_id_from=333.337"
        assert extract_bvid(url) == "BV1xx411c7mD"

    def test_url_with_trailing_slash(self):
        url = "https://www.bilibili.com/video/BV1xx411c7mD/"
        assert extract_bvid(url) == "BV1xx411c7mD"

    def test_mobile_url(self):
        url = "https://m.bilibili.com/video/BV1xx411c7mD"
        assert extract_bvid(url) == "BV1xx411c7mD"

    def test_bare_bvid(self):
        assert extract_bvid("BV1xx411c7mD") == "BV1xx411c7mD"

    def test_invalid_url_raises(self):
        with pytest.raises(ValueError):
            extract_bvid("https://www.youtube.com/watch?v=abc")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            extract_bvid("")


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
                "bvid": "BV1xx411c7mD",
                "title": "テスト動画",
                "pic": "http://example.com/thumb.jpg",
                "cid": 12345,
                "pages": [{"cid": 12345, "part": "Part 1", "page": 1}],
            },
        }
        httpx_mock.add_response(
            url="https://api.bilibili.com/x/web-interface/view?bvid=BV1xx411c7mD",
            json=mock_response,
        )
        info = await client.get_video_info("BV1xx411c7mD")
        assert info["title"] == "テスト動画"
        assert info["bvid"] == "BV1xx411c7mD"
        assert info["cid"] == 12345

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
        result = await client.get_play_url("BV1xx411c7mD", 12345, qn=80)
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
