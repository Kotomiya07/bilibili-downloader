// --- トースト通知 ---
function showToast(message, type = 'error') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');

    const colors = {
        error: 'bg-red-900/90 border-red-700 text-red-200',
        success: 'bg-green-900/90 border-green-700 text-green-200',
        warning: 'bg-yellow-900/90 border-yellow-700 text-yellow-200',
    };

    toast.className = `border rounded-lg px-4 py-3 text-sm shadow-lg toast-slide-in ${colors[type] || colors.error}`;
    toast.textContent = message;

    container.appendChild(toast);

    setTimeout(() => {
        toast.classList.remove('toast-slide-in');
        toast.classList.add('toast-slide-out');
        toast.addEventListener('animationend', () => toast.remove());
    }, 3000);
}

// --- 入力欄 ---
function toggleClearBtn() {
    const input = document.getElementById('video-url');
    const btn = document.getElementById('btn-clear');
    btn.classList.toggle('hidden', !input.value);
}

function clearInput() {
    const input = document.getElementById('video-url');
    input.value = '';
    toggleClearBtn();
    document.getElementById('video-info').classList.add('hidden');
    document.getElementById('video-placeholder').classList.remove('hidden');
    document.getElementById('download-controls').classList.add('hidden');
    document.getElementById('bilibili-player').src = '';
    input.focus();
}

// --- ボタン状態ヘルパー ---
function setButtonLoading(btn, loadingText) {
    btn.disabled = true;
    btn._originalText = btn.textContent;
    btn.innerHTML = '<span class="spinner"></span> ' + loadingText;
}

function resetButton(btn, text) {
    btn.disabled = false;
    btn.innerHTML = text || btn._originalText || '';
}

// --- クリップボードから貼り付け ---
async function pasteFromClipboard() {
    try {
        const text = await navigator.clipboard.readText();
        document.getElementById('video-url').value = text;
        toggleClearBtn();
        fetchVideoInfo();
    } catch (e) {
        showToast('クリップボードの読み取りに失敗しました', 'error');
    }
}

// --- ログイン ---
let currentVideoInfo = null;
let qrPollingInterval = null;

async function checkLoginStatus() {
    try {
        const resp = await fetch('/api/login/status');
        const data = await resp.json();
        updateLoginBadge(data.logged_in);
    } catch (e) {
        console.error('Login status check failed:', e);
    }
}

function updateLoginBadge(loggedIn) {
    const badge = document.getElementById('login-badge');
    if (loggedIn) {
        badge.textContent = 'ログイン済み';
        badge.className = 'text-xs px-2 py-0.5 rounded-full bg-pink-900/50 text-pink-300';
        document.getElementById('qr-area').classList.add('hidden');
        document.getElementById('qr-display').classList.add('hidden');
    } else {
        badge.textContent = '未ログイン';
        badge.className = 'text-xs px-2 py-0.5 rounded-full bg-gray-700 text-gray-400';
    }
}

async function generateQR() {
    const btn = document.getElementById('btn-show-qr');
    setButtonLoading(btn, '生成中...');

    try {
        const resp = await fetch('/api/login/qr/generate', { method: 'POST' });
        const data = await resp.json();

        document.getElementById('qr-image').src = 'data:image/png;base64,' + data.qr_image_base64;
        document.getElementById('qr-display').classList.remove('hidden');
        document.getElementById('qr-area').classList.add('hidden');

        startQRPolling(data.qrcode_key);
    } catch (e) {
        showToast('QRコード生成に失敗しました', 'error');
        resetButton(btn, 'QRコードを表示');
    }
}

function startQRPolling(qrcodeKey) {
    if (qrPollingInterval) clearInterval(qrPollingInterval);

    qrPollingInterval = setInterval(async () => {
        try {
            const resp = await fetch('/api/login/qr/poll?qrcode_key=' + encodeURIComponent(qrcodeKey));
            const data = await resp.json();
            const statusEl = document.getElementById('qr-status');

            if (data.status === 'success') {
                clearInterval(qrPollingInterval);
                statusEl.textContent = 'ログイン成功！';
                statusEl.className = 'text-xs text-pink-400';
                updateLoginBadge(true);
                showToast('ログインしました', 'success');
            } else if (data.status === 'scanned') {
                statusEl.textContent = 'スキャン済み - アプリで確認してください';
                statusEl.className = 'text-xs text-yellow-400';
            } else if (data.status === 'expired') {
                clearInterval(qrPollingInterval);
                statusEl.textContent = 'QRコードの有効期限が切れました';
                statusEl.className = 'text-xs text-red-400';
                document.getElementById('qr-area').classList.remove('hidden');
                const btn = document.getElementById('btn-show-qr');
                resetButton(btn, 'QRコードを再表示');
                showToast('QRコードの有効期限が切れました', 'warning');
            }
        } catch (e) {
            console.error('QR polling error:', e);
        }
    }, 2000);
}

// --- 動画情報取得 ---
async function fetchVideoInfo() {
    const url = document.getElementById('video-url').value.trim();
    if (!url) {
        showToast('URLを入力してください', 'warning');
        return;
    }

    const btn = document.getElementById('btn-fetch');
    setButtonLoading(btn, '取得中...');
    document.getElementById('video-info').classList.add('hidden');
    document.getElementById('download-controls').classList.add('hidden');

    try {
        const resp = await fetch('/api/video/info', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url }),
        });

        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.detail || 'Failed to fetch video info');
        }

        currentVideoInfo = await resp.json();

        document.getElementById('video-title').textContent = currentVideoInfo.title;

        // Bilibili埋め込みプレイヤーを設定
        const player = document.getElementById('bilibili-player');
        player.src = 'https://player.bilibili.com/player.html?bvid=' + currentVideoInfo.bvid
            + '&cid=' + currentVideoInfo.cid
            + '&high_quality=1&danmaku=0&autoplay=0';

        const select = document.getElementById('quality-select');
        select.innerHTML = '';
        currentVideoInfo.quality_options.forEach(opt => {
            const option = document.createElement('option');
            option.value = opt.qn;
            option.textContent = opt.description;
            select.appendChild(option);
        });

        document.getElementById('video-placeholder').classList.add('hidden');
        document.getElementById('video-info').classList.remove('hidden');
        document.getElementById('download-controls').classList.remove('hidden');
    } catch (e) {
        showToast('動画情報の取得に失敗しました: ' + e.message, 'error');
    } finally {
        resetButton(btn, '取得');
    }
}

// --- ダウンロード ---
async function startDownload() {
    if (!currentVideoInfo) return;

    const url = document.getElementById('video-url').value.trim();
    const quality = parseInt(document.getElementById('quality-select').value);

    const btn = document.getElementById('btn-download');
    setButtonLoading(btn, 'ダウンロード中...');

    document.getElementById('progress-section').classList.remove('hidden');
    document.getElementById('complete-section').classList.add('hidden');
    document.getElementById('download-error').classList.add('hidden');

    try {
        const resp = await fetch('/api/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url, quality }),
        });
        const data = await resp.json();

        if (data.error) {
            throw new Error(data.error);
        }

        monitorProgress(data.task_id);
    } catch (e) {
        showDownloadError('ダウンロード開始に失敗しました: ' + e.message);
        resetButton(btn, 'ダウンロード開始');
    }
}

function monitorProgress(taskId) {
    const evtSource = new EventSource('/api/download/progress/' + taskId);

    evtSource.addEventListener('progress', (e) => {
        const data = JSON.parse(e.data);
        const phaseEl = document.getElementById('progress-phase');
        const barEl = document.getElementById('progress-bar');
        const percentEl = document.getElementById('progress-percent');

        if (data.phase === 'video') {
            phaseEl.textContent = '映像をダウンロード中...';
            const percent = data.progress_video * 0.7;
            barEl.style.width = percent + '%';
            percentEl.textContent = Math.round(percent) + '%';
        } else if (data.phase === 'audio') {
            phaseEl.textContent = '音声をダウンロード中...';
            const percent = 70 + data.progress_audio * 0.2;
            barEl.style.width = percent + '%';
            percentEl.textContent = Math.round(percent) + '%';
        } else if (data.phase === 'merging') {
            phaseEl.textContent = 'マージ処理中...';
            barEl.style.width = '95%';
            percentEl.textContent = '95%';
        } else if (data.phase === 'done') {
            phaseEl.textContent = '完了！';
            barEl.style.width = '100%';
            percentEl.textContent = '100%';
        }

        if (data.status === 'completed') {
            evtSource.close();
            document.getElementById('progress-section').classList.add('hidden');
            document.getElementById('complete-section').classList.remove('hidden');
            const link = document.getElementById('download-link');
            link.href = '/api/download/file/' + encodeURIComponent(data.filename);
            link.download = data.filename;

            resetButton(document.getElementById('btn-download'), 'ダウンロード開始');
            showToast('ダウンロードが完了しました', 'success');
        } else if (data.status === 'error') {
            evtSource.close();
            showDownloadError(data.error || '不明なエラーが発生しました');
            resetButton(document.getElementById('btn-download'), 'ダウンロード開始');
        }
    });

    evtSource.addEventListener('error', (e) => {
        showDownloadError('SSE接続エラー');
        evtSource.close();
        resetButton(document.getElementById('btn-download'), 'ダウンロード開始');
    });
}

function showDownloadError(msg) {
    const el = document.getElementById('download-error');
    el.textContent = msg;
    el.classList.remove('hidden');
}

// --- 初期化 ---
checkLoginStatus();
