import base64
import hashlib
import json
import io
import platform
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import httpx
import qrcode
from cryptography.fernet import Fernet, InvalidToken

from bilibili_downloader.bilibili_client import BILIBILI_HEADERS


def _derive_key() -> bytes:
    """マシン固有の情報から暗号化キーを導出する。"""
    seed = f"{platform.node()}-{platform.machine()}-bilibili-downloader"
    key_bytes = hashlib.sha256(seed.encode()).digest()
    return base64.urlsafe_b64encode(key_bytes)


class AuthManager:
    def __init__(self, cookie_path: Path | None = None):
        self._cookie_path = cookie_path or Path("cookies.json")
        self._cookies: dict[str, str] = {}
        self._fernet = Fernet(_derive_key())

    def _build_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(headers=BILIBILI_HEADERS, timeout=30.0)

    async def generate_qr(self) -> dict:
        """QRコード生成APIを呼び出し、QR画像をBase64で返す。"""
        async with self._build_client() as client:
            resp = await client.get(
                "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
            )
            resp.raise_for_status()
            data = resp.json()
            if data["code"] != 0:
                raise Exception(f"QR生成エラー: {data.get('message', 'unknown')}")

            qr_url = data["data"]["url"]
            qrcode_key = data["data"]["qrcode_key"]

            img = qrcode.make(qr_url)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            qr_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

            return {
                "qrcode_key": qrcode_key,
                "qr_image_base64": qr_b64,
            }

    async def poll_qr_status(self, qrcode_key: str) -> dict:
        """QRコードのスキャン状態をポーリングする。"""
        async with self._build_client() as client:
            resp = await client.get(
                "https://passport.bilibili.com/x/passport-login/web/qrcode/poll",
                params={"qrcode_key": qrcode_key},
            )
            resp.raise_for_status()
            data = resp.json()["data"]
            code = data["code"]

            if code == 0:
                # ログイン成功 - Cookieを抽出して保存
                cookies = self._extract_cookies_from_url(data.get("url", ""))
                # レスポンスヘッダーからもCookieを取得
                for cookie_header in resp.headers.get_list("set-cookie"):
                    self._parse_set_cookie(cookie_header, cookies)
                if cookies:
                    self.save_cookies(cookies)
                    self._cookies = cookies
                return {"status": "success", "message": data["message"]}
            elif code == 86101:
                return {"status": "waiting", "message": data["message"]}
            elif code == 86090:
                return {"status": "scanned", "message": data["message"]}
            elif code == 86038:
                return {"status": "expired", "message": data["message"]}
            else:
                return {"status": "unknown", "message": data["message"]}

    def _extract_cookies_from_url(self, url: str) -> dict[str, str]:
        """成功時のURLからCookie情報を抽出する。"""
        cookies = {}
        if not url:
            return cookies
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        for key in ("SESSDATA", "bili_jct", "buvid3"):
            if key in params:
                cookies[key] = params[key][0]
        return cookies

    def _parse_set_cookie(self, header: str, cookies: dict[str, str]) -> None:
        """Set-Cookieヘッダーから重要なCookieを抽出する。"""
        parts = header.split(";")
        if parts:
            kv = parts[0].strip().split("=", 1)
            if len(kv) == 2 and kv[0] in ("SESSDATA", "bili_jct", "buvid3"):
                cookies[kv[0]] = kv[1]

    def save_cookies(self, cookies: dict[str, str]) -> None:
        """Cookieを暗号化してファイルに保存する。"""
        self._cookies = cookies
        plaintext = json.dumps(cookies, ensure_ascii=False).encode("utf-8")
        encrypted = self._fernet.encrypt(plaintext)
        self._cookie_path.write_bytes(encrypted)

    def load_cookies(self) -> dict[str, str] | None:
        """保存済みCookieを復号して読み込む。"""
        if not self._cookie_path.exists():
            return None
        try:
            encrypted = self._cookie_path.read_bytes()
            plaintext = self._fernet.decrypt(encrypted)
            data = json.loads(plaintext.decode("utf-8"))
        except (InvalidToken, json.JSONDecodeError):
            return None
        self._cookies = data
        return data

    def is_logged_in(self) -> bool:
        """ログイン状態を確認する。"""
        cookies = self.load_cookies()
        return cookies is not None and len(cookies) > 0

    def get_cookies(self) -> dict[str, str]:
        """現在のCookieを返す。"""
        if not self._cookies:
            loaded = self.load_cookies()
            if loaded:
                self._cookies = loaded
        return self._cookies
