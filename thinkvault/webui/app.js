/* ThinkVault V2.0 — SSE 流式推理 + 多会话管理 */

const API = '/api';
let currentConvId = null;
let isStreaming = false;
let abortController = null;

// ============================== 初始化 ==============================
document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    loadConversations();
    loadHardwareInfo();
    loadModelStatus();
    loadDocuments();
    bindEvents();
});

// ============================== 主题 ==============================
function initTheme() {
    const saved = localStorage.getItem('thinkvault-theme');
    if (saved) document.documentElement.setAttribute('data-theme', saved);
}

document.getElementById('btnToggleTheme').addEventListener('click', () => {
    const cur = document.documentElement.getAttribute('data-theme');
    const next = cur === 'light' ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('thinkvault-theme', next);
});

// ============================== 侧边栏 ==============================
document.getElementById('btnToggleSidebar').addEventListener('click', () => {
    document.getElementById('sidebar').classList.toggle('collapsed');
});

// ============================== 事件绑定 ==============================
function bindEvents() {
    document.getElementById('btnNewConv').addEventListener('click', newConversation);

    const triggerUpload = () => document.getElementById('fileInput').click();
    document.getElementById('btnFileUpload').addEventListener('click', triggerUpload);
    document.getElementById('btnUploadDoc').addEventListener('click', triggerUpload);
    document.getElementById('btnWelcomeUpload').addEventListener('click', triggerUpload);

    document.getElementById('fileInput').addEventListener('change', (e) => {
        handleFiles(e.target.files);
        e.target.value = '';
    });

    const mainArea = document.querySelector('.main-area');
    mainArea.addEventListener('dragover', (e) => { e.preventDefault(); mainArea.classList.add('drag-over'); });
    mainArea.addEventListener('dragleave', () => mainArea.classList.remove('drag-over'));
    mainArea.addEventListener('drop', (e) => {
        e.preventDefault();
        mainArea.classList.remove('drag-over');
        handleFiles(e.dataTransfer.files);
    });

    document.getElementById('btnSend').addEventListener('click', sendMessage);
    document.getElementById('chatInput').addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });

    const chatInput = document.getElementById('chatInput');
    chatInput.addEventListener('input', () => {
        chatInput.style.height = 'auto';
        chatInput.style.height = Math.min(chatInput.scrollHeight, 160) + 'px';
    });

    document.getElementById('btnLoadModel').addEventListener('click', loadModel);
    document.getElementById('btnUnloadModel').addEventListener('click', unloadModel);
}

// ============================== 会话管理 (V2.0) ==============================

async function loadConversations() {
    try {
        const res = await fetch(`${API}/conversations`);
        renderConvList(await res.json());
    } catch (e) { console.error('加载会话列表失败:', e); }
}

function renderConvList(convs) {
    const list = document.getElementById('convList');
    if (!convs || convs.length === 0) {
        list.innerHTML = '<li class="conv-empty">暂无会话</li>';
        return;
    }
    list.innerHTML = convs.map(c =>
        `<li class="conv-item${c.id === currentConvId ? ' active' : ''}" data-id="${c.id}">
            <span class="conv-title" title="${esc(c.title)}">${esc(c.title)}</span>
            <span class="conv-meta">${c.message_count}</span>
            <button class="conv-delete" data-id="${c.id}" title="删除">&times;</button>
        </li>`
    ).join('');

    list.querySelectorAll('.conv-item').forEach(item => {
        item.addEventListener('click', (e) => {
            if (e.target.classList.contains('conv-delete')) return;
            switchConversation(item.dataset.id);
        });
    });
    list.querySelectorAll('.conv-delete').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            await deleteConversation(btn.dataset.id);
        });
    });
}

async function newConversation() {
    try {
        const res = await fetch(`${API}/conversations`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: 'New Chat' }),
        });
        const conv = await res.json();
        currentConvId = conv.id;
        clearMessages();
        showWelcome();
        await loadConversations();
    } catch (e) { showToast('创建会话失败', 'error'); }
}

async function switchConversation(convId) {
    if (convId === currentConvId || isStreaming) return;
    currentConvId = convId;
    clearMessages();
    try {
        const res = await fetch(`${API}/conversations/${convId}`);
        const conv = await res.json();
        const messages = conv.messages || [];
        if (messages.length > 0) {
            hideWelcome();
            messages.forEach(m => addMessage(m.role, m.content));
        } else {
            showWelcome();
        }
    } catch (e) {
        showToast('加载会话失败', 'error');
        showWelcome();
    }
    await loadConversations();
    scrollToBottom();
}

async function deleteConversation(convId) {
    try {
        await fetch(`${API}/conversations/${convId}`, { method: 'DELETE' });
        if (convId === currentConvId) { currentConvId = null; clearMessages(); showWelcome(); }
        await loadConversations();
        showToast('会话已删除', 'success');
    } catch (e) { showToast('删除失败', 'error'); }
}

function clearMessages() {
    document.getElementById('chatMessages').querySelectorAll('.message, .system-msg').forEach(el => el.remove());
}

function showWelcome() { document.getElementById('welcomeScreen').classList.remove('hidden'); }
function hideWelcome() { document.getElementById('welcomeScreen').classList.add('hidden'); }

// ============================== 模型管理 ==============================
let modelProgressSource = null;

async function loadModelStatus() {
    try {
        const res = await fetch(`${API}/model`);
        const info = await res.json();
        updateModelStatus(info.loaded, info.model_path);
    } catch (e) {}
}

function updateModelStatus(loaded, path) {
    const dot = document.querySelector('.status-dot');
    const text = document.querySelector('.status-text');
    dot.className = 'status-dot ' + (loaded ? 'online' : 'offline');
    text.textContent = loaded ? '模型已加载: ' + path.split(/[\\/]/).pop() : '模型未加载';
}

function showModelProgress() {
    document.getElementById('modelProgress').style.display = 'block';
    document.getElementById('progressFill').style.width = '0%';
    document.getElementById('progressText').textContent = '';
}

function updateModelProgress(progress, message) {
    document.getElementById('progressFill').style.width = Math.round(progress * 100) + '%';
    document.getElementById('progressText').textContent = message;
}

function hideModelProgress() {
    document.getElementById('modelProgress').style.display = 'none';
}

async function loadModel() {
    const p = document.getElementById('modelPath').value.trim();
    const n = parseInt(document.getElementById('nCtx').value) || 2048;
    if (!p) { showToast('请输入模型路径', 'error'); return; }

    document.querySelector('.status-dot').className = 'status-dot loading';
    showModelProgress();
    updateModelProgress(0, '正在连接...');

    // 启动 SSE 进度监听
    if (modelProgressSource) modelProgressSource.close();
    modelProgressSource = new EventSource(`${API}/model/load/progress`);
    modelProgressSource.onmessage = (e) => {
        try {
            const d = JSON.parse(e.data);
            if (d.status === 'loading') {
                updateModelProgress(d.progress, d.message);
            } else if (d.status === 'loaded') {
                updateModelProgress(1.0, d.message);
                setTimeout(hideModelProgress, 1500);
                updateModelStatus(true, p);
                showToast('模型加载成功', 'success');
                modelProgressSource.close();
            } else if (d.status === 'error') {
                updateModelProgress(0, d.message);
                setTimeout(hideModelProgress, 2000);
                updateModelStatus(false, '');
                showToast('模型加载失败', 'error');
                modelProgressSource.close();
            }
        } catch (ex) {}
    };

    // 发送加载请求
    try {
        const res = await fetch(`${API}/model/load`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model_path: p, n_ctx: n }),
        });
        const d = await res.json();
        if (d.status !== 'ok') {
            updateModelStatus(false, '');
            showToast('模型加载失败', 'error');
            hideModelProgress();
            if (modelProgressSource) modelProgressSource.close();
        }
    } catch (e) {
        updateModelStatus(false, '');
        showToast('加载失败', 'error');
        hideModelProgress();
        if (modelProgressSource) modelProgressSource.close();
    }
}

async function unloadModel() {
    try { await fetch(`${API}/model/unload`, { method: 'POST' }); } catch (e) {}
    updateModelStatus(false, '');
    showToast('模型已卸载', 'success');
}

// ============================== 文件上传 ==============================
async function handleFiles(files) {
    if (!files || !files.length) return;
    for (const file of files) {
        const fd = new FormData();
        fd.append('file', file);
        showToast('上传中: ' + file.name + '...');
        try {
            const res = await fetch(`${API}/documents/upload`, { method: 'POST', body: fd });
            const d = await res.json();
            showToast(d.status === 'ok'
                ? '已索引: ' + file.name + ' (' + d.chunk_count + ' 段)'
                : '失败: ' + (d.error || '?'), d.status === 'ok' ? 'success' : 'error');
        } catch (e) { showToast('上传失败', 'error'); }
    }
    loadDocuments();
}

async function loadDocuments() {
    try {
        const res = await fetch(`${API}/documents`);
        const docs = await res.json();
        renderDocList(docs);
    } catch (e) {}
}

function renderDocList(docs) {
    const list = document.getElementById('docList');
    if (!docs || !docs.length) { list.innerHTML = '<li class="doc-empty">暂无文档</li>'; return; }
    const icon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>';
    list.innerHTML = docs.map(d =>
        `<li class="doc-item" data-id="${d.id}">
            <span class="doc-icon">${icon}</span>
            <span class="doc-name" title="${esc(d.file_name)}">${esc(d.file_name)}</span>
            <span class="doc-meta">${d.chunk_count}块</span>
            <button class="btn-delete" data-id="${d.id}" title="删除">&times;</button>
        </li>`
    ).join('');
    list.querySelectorAll('.btn-delete').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            await deleteDocument(btn.dataset.id);
        });
    });
}

async function deleteDocument(docId) {
    try {
        const res = await fetch(`${API}/documents/${docId}`, { method: 'DELETE' });
        const d = await res.json();
        if (d.status === 'ok') { showToast(d.message, 'success'); loadDocuments(); }
    } catch (e) { showToast('删除失败', 'error'); }
}

// ============================== 聊天 (V2.0 SSE 流式) ==============================
async function sendMessage() {
    const input = document.getElementById('chatInput');
    const message = input.value.trim();
    if (!message || isStreaming) return;

    input.value = '';
    input.style.height = 'auto';
    isStreaming = true;
    document.getElementById('btnSend').disabled = true;
    hideWelcome();

    addMessage('user', message);
    const streamMsg = addStreamingBubble();

    try {
        abortController = new AbortController();
        const res = await fetch(`${API}/chat/stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message, conversation_id: currentConvId }),
            signal: abortController.signal,
        });
        if (!res.ok) throw new Error('HTTP ' + res.status);

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buf = '', full = '', stats = null, sources = [], convId = null;

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buf += decoder.decode(value, { stream: true });
            const lines = buf.split('\n');
            buf = lines.pop() || '';
            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                try {
                    const d = JSON.parse(line.slice(6));
                    if (d.done) { stats = d.stats; sources = d.sources || []; convId = d.conversation_id; }
                    else if (d.token) { full += d.token; updateStreaming(streamMsg, full); }
                } catch (e) {}
            }
        }
        if (buf.startsWith('data: ')) {
            try { const d = JSON.parse(buf.slice(6)); if (d.done) { stats = d.stats; sources = d.sources || []; convId = d.conversation_id; } } catch (e) {}
        }
        finalizeStreaming(streamMsg, full, sources, stats);
        if (convId && !currentConvId) currentConvId = convId;
        await loadConversations();
    } catch (e) {
        if (e.name === 'AbortError') {
            streamMsg.querySelector('.message-content').textContent += '\n\n[已取消]';
        } else {
            streamMsg.querySelector('.message-content').textContent = '[错误] ' + e.message;
        }
    }
    isStreaming = false;
    document.getElementById('btnSend').disabled = false;
    abortController = null;
}

function addStreamingBubble() {
    const c = document.getElementById('chatMessages');
    const d = document.createElement('div');
    d.className = 'message assistant streaming';
    d.innerHTML = `<div class="message-avatar"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg></div><div class="message-content"><span class="cursor-blink"></span></div>`;
    c.appendChild(d);
    scrollToBottom();
    return d;
}

function updateStreaming(el, text) {
    el.querySelector('.message-content').innerHTML = renderMarkdown(text) + '<span class="cursor-blink"></span>';
    scrollToBottom();
}

function finalizeStreaming(el, text, sources, stats) {
    const content = el.querySelector('.message-content');
    content.innerHTML = renderMarkdown(text || '[空响应]');
    if (sources && sources.length) {
        const sd = document.createElement('div');
        sd.className = 'source-tags';
        sources.forEach(s => { const t = document.createElement('span'); t.className = 'source-tag'; t.textContent = s; sd.appendChild(t); });
        content.appendChild(sd);
    }
    if (stats && stats.tokens_per_sec) {
        const st = document.createElement('div');
        st.style.cssText = 'font-size:11px;color:var(--text-muted);margin-top:6px;';
        st.textContent = stats.output_tokens + ' tokens, ' + stats.tokens_per_sec + ' tok/s, ' + stats.elapsed_sec + 's';
        content.appendChild(st);
    }
    el.classList.remove('streaming');
    scrollToBottom();
}

// ============================== 消息渲染 ==============================
function addMessage(role, text, sources, stats) {
    const c = document.getElementById('chatMessages');
    const d = document.createElement('div');
    d.className = 'message ' + role;
    const avatar = role === 'user'
        ? '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>'
        : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>';
    const av = document.createElement('div');
    av.className = 'message-avatar';
    av.innerHTML = avatar;
    const ct = document.createElement('div');
    ct.className = 'message-content';
    if (role === 'user') ct.textContent = text;
    else if (text) ct.innerHTML = renderMarkdown(text);

    if (sources && sources.length) {
        const sd = document.createElement('div');
        sd.className = 'source-tags';
        sources.forEach(s => { const t = document.createElement('span'); t.className = 'source-tag'; t.textContent = s; sd.appendChild(t); });
        ct.appendChild(sd);
    }
    if (stats && stats.tokens_per_sec) {
        const st = document.createElement('div');
        st.style.cssText = 'font-size:11px;color:var(--text-muted);margin-top:6px;';
        st.textContent = stats.output_tokens + ' tokens, ' + stats.tokens_per_sec + ' tok/s, ' + stats.elapsed_sec + 's';
        ct.appendChild(st);
    }
    d.appendChild(av);
    d.appendChild(ct);
    c.appendChild(d);
    scrollToBottom();
    return d;
}

// ============================== Markdown ==============================
function renderMarkdown(text) {
    if (typeof marked !== 'undefined') {
        marked.setOptions({ breaks: true, gfm: true });
        const raw = marked.parse(text);
        if (typeof DOMPurify !== 'undefined') {
            return DOMPurify.sanitize(raw);
        }
        // DOMPurify CDN 不可用时回退到纯文本，杜绝正则 XSS 绕过
        const d = document.createElement('div');
        d.textContent = text;
        return d.innerHTML.replace(/\n/g, '<br>');
    }
    const d = document.createElement('div');
    d.textContent = text;
    return d.innerHTML.replace(/\n/g, '<br>');
}

function esc(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
}

// ============================== Toast ==============================
function showToast(msg, type) {
    const c = document.getElementById('toastContainer');
    const t = document.createElement('div');
    t.className = 'toast ' + (type || '');
    t.textContent = msg;
    c.appendChild(t);
    setTimeout(() => t.remove(), 3000);
}

function scrollToBottom() {
    const c = document.getElementById('chatMessages');
    setTimeout(() => { c.scrollTop = c.scrollHeight; }, 50);
}

async function loadHardwareInfo() {
    try { await fetch(`${API}/hardware`); } catch (e) {}
}
