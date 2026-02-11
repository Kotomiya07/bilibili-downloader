import re
from urllib.parse import urlparse

import httpx

BILIBILI_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.bilibili.com",
}

_BVID_PATTERN = re.compile(r"(BV[A-Za-z0-9]{10})")


def extract_bvid(url_or_id: str) -> str:
    """URLまたは文字列からBV IDを抽出する。"""
    match = _BVID_PATTERN.search(url_or_id)
    if not match:
        raise ValueError(f"BV IDが見つかりません: {url_or_id}")
    return match.group(1)


class BilibiliClient:
    def __init__(self, cookies: dict[str, str] | None = None):
        self._cookies = cookies or {}

    def _build_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers=BILIBILI_HEADERS,
            cookies=self._cookies,
            timeout=30.0,
        )

    def set_cookies(self, cookies: dict[str, str]) -> None:
        self._cookies = cookies

    async def get_video_info(self, bvid: str) -> dict:
        """動画のメタデータを取得する。"""
        async with self._build_client() as client:
            resp = await client.get(
                "https://api.bilibili.com/x/web-interface/view",
                params={"bvid": bvid},
            )
            resp.raise_for_status()
            data = resp.json()
            if data["code"] != 0:
                raise Exception(f"API error: {data.get('message', 'unknown')}")
            return data["data"]

    async def get_play_url(self, bvid: str, cid: int, qn: int = 80) -> dict:
        """DASH形式の再生URLを取得する。"""
        async with self._build_client() as client:
            resp = await client.get(
                "https://api.bilibili.com/x/player/playurl",
                params={
                    "bvid": bvid,
                    "cid": cid,
                    "qn": qn,
                    "fnval": 16,
                    "fourk": 1,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if data["code"] != 0:
                raise Exception(f"API error: {data.get('message', 'unknown')}")
            dash = data["data"]["dash"]
            return {
                "video": dash["video"],
                "audio": dash["audio"],
                "accept_quality": data["data"]["accept_quality"],
                "accept_description": data["data"]["accept_description"],
            }
