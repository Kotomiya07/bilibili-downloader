FROM python:3.12-slim

# FFmpeg インストール
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# uv インストール
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# 依存関係を先にインストール（キャッシュ活用）
COPY pyproject.toml uv.lock* README.md ./
RUN uv sync --no-dev --no-editable

# ソースコードをコピー
COPY src/ src/

# ダウンロードディレクトリ作成
RUN mkdir -p /app/downloads

EXPOSE 8000

CMD uv run python -m bilibili_downloader.app --host 0.0.0.0 --port ${PORT:-8000} --download-dir /app/downloads
