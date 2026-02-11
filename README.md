# Bilibili Downloader

Bilibili動画をダウンロードするためのWeb GUIアプリケーション。

## 機能

- BilibiliのURLから動画をダウンロード
- QRコードログインで1080p以上の高画質に対応
- DASH形式の映像+音声をFFmpegで自動マージ
- SSEによるリアルタイム進捗表示
- ダーク基調のモダンUI

## 前提条件

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) パッケージマネージャー
- [FFmpeg](https://ffmpeg.org/download.html) （動画マージに必要）

### FFmpegのインストール

**Windows:**
```bash
winget install FFmpeg
```

**macOS:**
```bash
brew install ffmpeg
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt install ffmpeg
```

## セットアップ

```bash
# 依存関係のインストール
uv sync

# サーバー起動
uv run python -m bilibili_downloader.app
```

ブラウザで http://localhost:8000 にアクセス。

## 使い方

1. **（任意）QRログイン**: 「QRコードを表示」→ Bilibiliアプリでスキャン → 1080p以上が解放
2. **URL入力**: BilibiliのURLを貼り付けて「取得」
3. **画質選択**: ドロップダウンから画質を選択
4. **ダウンロード**: 「ダウンロード開始」→ 進捗バーで完了を待つ
5. **保存**: 「ファイルをダウンロード」でMP4を取得

## テスト

```bash
uv run pytest -v
```

## Docker で起動

FFmpegのインストール不要で、Docker だけで起動できます。

```bash
# ビルドして起動
docker compose up -d

# ログ確認
docker compose logs -f
```

ブラウザで http://localhost:8000 にアクセス。

## HTTPS 対応

### 方法1: SSL証明書を直接指定

```bash
uv run python -m bilibili_downloader.app \
  --ssl-certfile cert.pem \
  --ssl-keyfile key.pem
```

### 方法2: リバースプロキシ（推奨）

Nginx等でHTTPS終端し、バックエンドにプロキシする構成が推奨です。

```nginx
server {
    listen 443 ssl;
    server_name example.com;

    ssl_certificate     /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;  # SSE対応
    }
}
```

## コマンドラインオプション

| オプション | デフォルト | 説明 |
|---|---|---|
| `--host` | `0.0.0.0` | バインドホスト |
| `--port` | `8000` | ポート番号 |
| `--ssl-certfile` | なし | SSL証明書ファイルパス |
| `--ssl-keyfile` | なし | SSL秘密鍵ファイルパス |
| `--download-dir` | `downloads/` | ダウンロード先ディレクトリ |

## プロジェクト構造

```
src/bilibili_downloader/
├── app.py              # FastAPIアプリ & エントリーポイント
├── api_routes.py       # APIエンドポイント定義
├── bilibili_client.py  # Bilibili API通信
├── auth.py             # QRログイン & Cookie管理
├── downloader.py       # ダウンロード & FFmpegマージ
└── static/
    └── index.html      # Web GUI
```

## 開発者向け情報

### Bilibili API リファレンス

本プロジェクトは以下のBilibili APIを使用しています。API仕様の詳細や変更履歴については、コミュニティによるドキュメントを参照してください。

- **bilibili-API-collect**: https://github.com/SocialSisterYi/bilibili-API-collect
  - Bilibili APIの非公式リファレンス（最も包括的）

#### 使用しているエンドポイント

| 用途 | エンドポイント | 参考ドキュメント |
|---|---|---|
| 動画情報取得 | `GET /x/web-interface/view?bvid=` | [動画基本情報](https://github.com/SocialSisterYi/bilibili-API-collect/blob/master/docs/video/info.md) |
| 再生URL取得 | `GET /x/player/playurl?bvid=&cid=&qn=&fnval=16` | [視頻流URL](https://github.com/SocialSisterYi/bilibili-API-collect/blob/master/docs/video/videostream_url.md) |
| QRコード生成 | `GET /x/passport-login/web/qrcode/generate` | [QRコードログイン](https://github.com/SocialSisterYi/bilibili-API-collect/blob/master/docs/login/login_action/QR.md) |
| QRポーリング | `GET /x/passport-login/web/qrcode/poll?qrcode_key=` | 同上 |

#### 画質コード一覧

| コード | 画質 | ログイン要否 |
|---|---|---|
| 16 | 360P | 不要 |
| 32 | 480P | 不要 |
| 64 | 720P | 不要 |
| 80 | 1080P | **必要** |
| 112 | 1080P+ | **必要**（大会員） |
| 120 | 4K | **必要**（大会員） |

> **注意**: Bilibili APIは非公式のため、予告なく変更される可能性があります。動作に問題が出た場合は上記リファレンスで最新仕様を確認してください。
