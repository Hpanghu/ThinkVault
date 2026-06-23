/* ThinkVault V2.0 — 知识馆长 (The Curator) — 离线知识库对话引擎 */

const API = '/api';
let currentConvId = null;
let currentKb = 'default';
let isStreaming = false;
let abortController = null;

// ============================== Auth (Settings-based) ==============================
let _apiToken = localStorage.getItem('thinkvault-token') || '';

function getToken() { return _apiToken; }

function setToken(token) {
    _apiToken = token;
    if (token) {
        localStorage.setItem('thinkvault-token', token);
    } else {
        localStorage.removeItem('thinkvault-token');
    }
    const input = document.getElementById('apiTokenInput');
    if (input) input.value = token;
}

/** Unified fetch wrapper — auto-attaches Bearer token, handles 401 gracefully */
async function apiFetch(url, options = {}) {
    const token = getToken();
    if (token) {
        options.headers = options.headers || {};
        if (options.headers instanceof Headers) {
            options.headers.set('Authorization', 'Bearer ' + token);
        } else if (typeof options.headers === 'object') {
            options.headers['Authorization'] = 'Bearer ' + token;
        }
    }
    const res = await fetch(url, options);
    // 401/403 时提示用户，但不抛异常——让调用者通过 res.ok 自行处理
    if (res.status === 401 || res.status === 403) {
        showToast('认证失败，请在侧边栏「设置」中配置 API Token', 'error');
    }
    return res;
}

// ============================== Init ==============================
document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    // Load saved token into settings field
    const tokenInput = document.getElementById('apiTokenInput');
    if (tokenInput && _apiToken) tokenInput.value = _apiToken;
    bindEvents();
    updateSendButton();
    // 初始化模型设置
    initModelSettings();
    // Start app directly — no auth gate
    bootstrapApp();
});

function bootstrapApp() {
    loadConversations();
    loadHardwareInfo();
    checkModelStatus();
    loadDocuments();
    loadKnowledgeBases();
    refreshRoleSelector();
}

// ============================== Theme ==============================
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

// ============================== Help Guide ==============================
function toggleHelp(forceState) {
    const overlay = document.getElementById('helpOverlay');
    if (!overlay) return;
    const show = typeof forceState === 'boolean' ? forceState : !overlay.classList.contains('visible');
    if (show) {
        overlay.classList.add('visible');
    } else {
        overlay.classList.remove('visible');
    }
}

// Help tab switching
document.addEventListener('click', (e) => {
    const tab = e.target.closest('.help-tab');
    if (tab) {
        const tabId = tab.dataset.helpTab;
        document.querySelectorAll('.help-tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.help-panel').forEach(p => p.classList.remove('active'));
        tab.classList.add('active');
        const panelMap = { paths: 'helpPanelPaths', flow: 'helpPanelFlow', shortcuts: 'helpPanelShortcuts', safety: 'helpPanelSafety' };
        const panel = document.getElementById(panelMap[tabId]);
        if (panel) panel.classList.add('active');
    }
});

// Copy path buttons
document.addEventListener('click', (e) => {
    const btn = e.target.closest('.btn-copy-path');
    if (btn) {
        const text = btn.dataset.copy;
        navigator.clipboard.writeText(text).then(() => {
            btn.classList.add('copied');
            setTimeout(() => btn.classList.remove('copied'), 1500);
        }).catch(() => {
            // Fallback for older browsers
            const ta = document.createElement('textarea');
            ta.value = text; document.body.appendChild(ta);
            ta.select(); document.execCommand('copy');
            document.body.removeChild(ta);
            btn.classList.add('copied');
            setTimeout(() => btn.classList.remove('copied'), 1500);
        });
    }
});

// Close help on overlay click
document.addEventListener('click', (e) => {
    const overlay = document.getElementById('helpOverlay');
    if (e.target === overlay) toggleHelp(false);
});

// ============================== Sidebar ==============================
document.getElementById('btnToggleSidebar').addEventListener('click', toggleSidebar);
document.getElementById('btnOpenSidebar').addEventListener('click', openSidebar);

function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    sidebar.classList.toggle('collapsed');
    const openBtn = document.getElementById('btnOpenSidebar');
    openBtn.style.display = sidebar.classList.contains('collapsed') ? 'flex' : 'none';
}

function openSidebar() {
    const sidebar = document.getElementById('sidebar');
    sidebar.classList.remove('collapsed');
    document.getElementById('btnOpenSidebar').style.display = 'none';
}

// ============================== Keyboard Shortcuts ==============================
document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'n') {
        e.preventDefault();
        newConversation();
    }
    if ((e.ctrlKey || e.metaKey) && e.key === '/') {
        e.preventDefault();
        toggleSidebar();
    }
    if ((e.ctrlKey || e.metaKey) && e.key === 'h') {
        e.preventDefault();
        toggleHelp();
    }
    if (e.key === 'Escape') {
        const overlay = document.getElementById('helpOverlay');
        if (overlay && overlay.classList.contains('visible')) {
            toggleHelp(false);
            return;
        }
        const sidebar = document.getElementById('sidebar');
        if (window.innerWidth <= 768 && !sidebar.classList.contains('collapsed')) {
            toggleSidebar();
        }
    }
});

// ============================== Events ==============================
function bindEvents() {
    document.getElementById('btnNewConv').addEventListener('click', newConversation);
    document.getElementById('btnDeleteAllConvs').addEventListener('click', confirmDeleteAllConvs);

    // 确认对话框事件绑定
    document.getElementById('confirmOk').addEventListener('click', () => {
        if (_confirmResolver) { _confirmResolver(true); hideConfirm(); }
    });
    document.getElementById('confirmCancel').addEventListener('click', () => {
        if (_confirmResolver) { _confirmResolver(false); hideConfirm(); }
    });
    document.getElementById('confirmOverlay').addEventListener('click', (e) => {
        if (e.target === e.currentTarget) {
            if (_confirmResolver) { _confirmResolver(false); hideConfirm(); }
        }
    });

    const triggerUpload = () => document.getElementById('fileInput').click();
    document.getElementById('btnFileUpload').addEventListener('click', triggerUpload);
    document.getElementById('btnUploadDoc').addEventListener('click', triggerUpload);
    document.getElementById('chipUpload').addEventListener('click', triggerUpload);

    document.getElementById('fileInput').addEventListener('change', (e) => {
        handleFiles(e.target.files);
        e.target.value = '';
    });

    const mainArea = document.getElementById('mainArea');
    mainArea.addEventListener('dragover', (e) => { e.preventDefault(); mainArea.classList.add('drag-over'); });
    mainArea.addEventListener('dragleave', () => mainArea.classList.remove('drag-over'));
    mainArea.addEventListener('drop', (e) => {
        e.preventDefault();
        mainArea.classList.remove('drag-over');
        handleFiles(e.dataTransfer.files);
    });

    const chatInput = document.getElementById('chatInput');

    document.getElementById('btnSend').addEventListener('click', () => {
        if (isStreaming) { stopStreaming(); } else { sendMessage(); }
    });

    chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });

    chatInput.addEventListener('input', () => {
        chatInput.style.height = 'auto';
        chatInput.style.height = Math.min(chatInput.scrollHeight, 160) + 'px';
        updateSendButton();
    });

    // ── 双模式事件绑定 ──
    // 本地模式
    document.getElementById('btnQuickStart').addEventListener('click', quickStartServices);
    document.getElementById('btnRefreshModels').addEventListener('click', refreshModels);
    document.getElementById('modelName').addEventListener('change', onModelSelect);
    // 远程模式
    document.getElementById('btnConnectRemote').addEventListener('click', connectRemote);
    document.getElementById('btnDisconnectRemote').addEventListener('click', disconnectRemote);
    // 模式切换
    document.querySelectorAll('.mode-tab').forEach(tab => {
        tab.addEventListener('click', () => switchMode(tab.dataset.mode));
    });

    // 操作指引
    document.getElementById('btnHelp').addEventListener('click', () => toggleHelp());
    document.getElementById('btnCloseHelp').addEventListener('click', () => toggleHelp(false));

    // Role Management
    document.getElementById('btnManageRoles').addEventListener('click', openRoleModal);
    document.getElementById('btnCloseRoleModal').addEventListener('click', closeRoleModal);
    document.getElementById('roleModalOverlay').addEventListener('click', (e) => {
        if (e.target === e.currentTarget) closeRoleModal();
    });
    document.getElementById('btnCreateRole').addEventListener('click', openRoleEditModal);
    document.getElementById('btnCloseRoleEditModal').addEventListener('click', closeRoleEditModal);
    document.getElementById('btnCancelRoleEdit').addEventListener('click', closeRoleEditModal);
    document.getElementById('roleEditModalOverlay').addEventListener('click', (e) => {
        if (e.target === e.currentTarget) closeRoleEditModal();
    });
    document.getElementById('btnSaveRole').addEventListener('click', saveRole);
    document.getElementById('btnDeleteRole').addEventListener('click', deleteRole);

    // Role selector change
    document.getElementById('roleSelect').addEventListener('change', async (e) => {
        if (!currentConvId) {
            await showWelcome();
        }
    });

    // API Token input in settings
    document.getElementById('apiTokenInput').addEventListener('change', (e) => {
        setToken(e.target.value.trim());
        if (e.target.value.trim()) {
            showToast('API Token 已保存', 'success');
        }
    });

    // Knowledge base selector
    document.getElementById('kbSelect').addEventListener('change', (e) => {
        currentKb = e.target.value;
        loadDocuments();
    });

    // Watched directories: event delegation for remove buttons
    document.getElementById('watchList').addEventListener('click', (e) => {
        const btn = e.target.closest('.remove-dir-btn');
        if (btn) {
            removeWatchDir(btn.dataset.dir);
        }
    });
    document.getElementById('btnCreateKb').addEventListener('click', showKbCreateForm);
    document.getElementById('btnDeleteKb').addEventListener('click', deleteCurrentKb);
    document.getElementById('btnKbCreateConfirm').addEventListener('click', createKnowledgeBase);
    document.getElementById('btnKbCreateCancel').addEventListener('click', hideKbCreateForm);
    document.getElementById('kbCreateInput').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); createKnowledgeBase(); }
        if (e.key === 'Escape') hideKbCreateForm();
    });

    // Prompt chips on welcome screen
    document.querySelectorAll('.prompt-chip[data-prompt]').forEach(chip => {
        if (chip.id === 'chipUpload') return; // handled above
        chip.addEventListener('click', () => {
            const prompt = chip.dataset.prompt;
            if (prompt) {
                document.getElementById('chatInput').value = prompt;
                updateSendButton();
                document.getElementById('chatInput').focus();
            }
        });
    });

    // KB Management Panel
    document.getElementById('btnManageKb')?.addEventListener('click', openKbPanel);
    document.getElementById('btnCloseKbPanel')?.addEventListener('click', closeKbPanel);
    document.querySelectorAll('.kb-tab').forEach(tab => {
        tab.addEventListener('click', () => switchKbTab(tab.dataset.tab));
    });
    document.getElementById('btnStartScan')?.addEventListener('click', startScan);
    document.getElementById('btnReindexFile')?.addEventListener('click', reindexFile);
    document.getElementById('btnAddWatch')?.addEventListener('click', addWatchDir);
    document.getElementById('btnGenerateSummaries')?.addEventListener('click', generateSummaries);
    document.getElementById('btnRefreshChanges')?.addEventListener('click', loadKbChanges);
    document.getElementById('btnRefreshSummaries')?.addEventListener('click', loadKbSummaries);
}

function updateSendButton() {
    const btn = document.getElementById('btnSend');
    const input = document.getElementById('chatInput');
    if (isStreaming) {
        btn.classList.add('streaming');
        btn.classList.remove('ready');
        btn.disabled = false;
        btn.title = '停止生成';
    } else {
        btn.classList.remove('streaming');
        if (input.value.trim().length > 0) {
            btn.classList.add('ready');
            btn.disabled = false;
        } else {
            btn.classList.remove('ready');
            btn.disabled = true;
        }
        btn.title = '发送';
    }
}

function stopStreaming() {
    if (abortController) {
        abortController.abort();
        abortController = null;
    }
    isStreaming = false;
    updateSendButton();
}

// ============================== Knowledge Bases ==============================

async function loadKnowledgeBases() {
    try {
        const res = await apiFetch(`${API}/knowledge-bases`);
        if (!res.ok) { if (res.status !== 401) showToast('加载知识库失败', 'error'); return; }
        const data = await res.json();
        const kbs = data.knowledge_bases || data;
        renderKbList(kbs);
        updateArchiveStats(kbs);
    } catch (e) { console.error('Failed to load knowledge bases:', e); }
}

function updateArchiveStats(kbs) {
    const kbCount = kbs.length;
    let docCount = 0;
    let chunkCount = 0;
    // We'll approximate from KB data
    kbs.forEach(kb => { chunkCount += kb.chunk_count; });
    // Load doc count from documents API
    loadDocCount();

    const kbEl = document.getElementById('statKbCount');
    const chunkEl = document.getElementById('statChunkCount');
    if (kbEl) kbEl.textContent = kbCount;
    if (chunkEl) chunkEl.textContent = chunkCount;
}

async function loadDocCount() {
    try {
        const res = await apiFetch(`${API}/documents?knowledge_base=${encodeURIComponent(currentKb)}`);
        if (!res.ok) return;
        const data = await res.json();
        const docEl = document.getElementById('statDocCount');
        if (docEl) docEl.textContent = data.total ?? (data.documents || []).length;
    } catch (e) {}
}

function renderKbList(kbs) {
    const select = document.getElementById('kbSelect');
    const current = select.value || currentKb;
    select.innerHTML = kbs.map(kb =>
        `<option value="${escAttr(kb.name)}"${kb.name === current ? ' selected' : ''}>${esc(kb.name)} (${kb.chunk_count} 片段)</option>`
    ).join('');
    if (kbs.length === 0) {
        select.innerHTML = '<option value="default">default (0 片段)</option>';
    }
    currentKb = select.value;
    const delBtn = document.getElementById('btnDeleteKb');
    if (delBtn) {
        delBtn.disabled = (kbs.length === 0 || currentKb === 'default');
        delBtn.style.opacity = delBtn.disabled ? '0.3' : '1';
    }
}

function showKbCreateForm() {
    document.getElementById('kbCreateForm').classList.remove('hidden');
    const input = document.getElementById('kbCreateInput');
    input.value = '';
    input.focus();
}

function hideKbCreateForm() {
    document.getElementById('kbCreateForm').classList.add('hidden');
}

async function createKnowledgeBase() {
    const input = document.getElementById('kbCreateInput');
    const name = input.value.trim().toLowerCase().replace(/\s+/g, '-');
    if (!name) return;
    if (!/^[a-z0-9][a-z0-9_-]{2,49}$/.test(name)) {
        showToast('名称: 小写字母、数字、连字符、下划线，3-50 字符', 'error');
        return;
    }
    try {
        const res = await apiFetch(`${API}/knowledge-bases`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name }),
        });
        if (res.status === 409) { showToast('馆藏已存在', 'error'); return; }
        if (!res.ok) { const d = await res.json(); showToast(d.detail || '创建失败', 'error'); return; }
        hideKbCreateForm();
        await loadKnowledgeBases();
        document.getElementById('kbSelect').value = name;
        currentKb = name;
        loadDocuments();
        showToast('已创建馆藏: ' + name, 'success');
    } catch (e) { showToast('创建失败', 'error'); }
}

async function deleteCurrentKb() {
    if (currentKb === 'default') { showToast('无法删除默认馆藏', 'error'); return; }
    if (!confirm(`确定删除馆藏「${currentKb}」及其所有文献？`)) return;
    try {
        await apiFetch(`${API}/knowledge-bases/${encodeURIComponent(currentKb)}`, { method: 'DELETE' });
        currentKb = 'default';
        await loadKnowledgeBases();
        loadDocuments();
        showToast('馆藏已删除', 'success');
    } catch (e) { showToast('删除失败', 'error'); }
}

// ============================== Hardware Info ==============================

async function loadHardwareInfo() {
    try {
        const res = await apiFetch(`${API}/hardware`);
        if (!res.ok) return;
        const hw = await res.json();
        document.getElementById('hwCpu').textContent = hw.cpu_count + ' 核';
        document.getElementById('hwRam').textContent = hw.available_ram_gb.toFixed(1) + ' / ' + hw.total_ram_gb.toFixed(1) + ' GB';
        document.getElementById('hwGpu').textContent = hw.gpu_name || '无';
        document.getElementById('hwVram').textContent = hw.vram_gb > 0 ? hw.vram_gb.toFixed(1) + ' GB' : '无';
        document.getElementById('hwTier').textContent = hw.recommended_tier || '-';
    } catch (e) {}
}

// ============================== Conversations ==============================

const CONV_PAGE_SIZE = 30;
let convTotal = 0;
let convOffset = 0;

async function loadConversations(append = false) {
    try {
        const url = `${API}/conversations?limit=${CONV_PAGE_SIZE}&offset=${append ? convOffset : 0}`;
        const res = await apiFetch(url);
        if (!res.ok) { if (res.status !== 401) showToast('加载对话列表失败', 'error'); return; }
        const data = await res.json();
        const convs = data.conversations || data.items || data;
        convTotal = data.total ?? convs.length;
        if (!append) convOffset = 0;
        convOffset += convs.length;
        renderConvList(convs, append);
    } catch (e) { console.error('Failed to load conversations:', e); }
}

function renderConvList(convs, append = false) {
    const list = document.getElementById('convList');
    if (!append) {
        if (!convs || convs.length === 0) {
            list.innerHTML = '<li class="empty-state compact"><span class="empty-state-text">开始你的第一次探索</span></li>';
            removeLoadMore();
            return;
        }
        list.innerHTML = '';
    }

    convs.forEach((c, i) => {
        const li = document.createElement('li');
        li.className = 'conv-item' + (c.id === currentConvId ? ' active' : '');
        li.dataset.id = c.id;
        li.style.animationDelay = Math.min(i * 40, 300) + 'ms';
        li.innerHTML = `
            <span class="conv-title" title="双击重命名">${esc(c.title)}</span>
            <span class="conv-meta">${c.message_count}</span>
            <button class="conv-delete" data-id="${escAttr(c.id)}" title="删除" aria-label="删除对话">&times;</button>
        `;
        list.appendChild(li);

        li.addEventListener('click', (e) => {
            if (e.target.classList.contains('conv-delete')) return;
            if (e.target.classList.contains('conv-title-input')) return;
            switchConversation(li.dataset.id);
        });
        li.querySelector('.conv-title').addEventListener('dblclick', (e) => {
            e.stopPropagation();
            startRename(li);
        });
        li.querySelector('.conv-delete').addEventListener('click', async (e) => {
            e.stopPropagation();
            await deleteConversation(li.dataset.id);
        });
    });

    removeLoadMore();
    if (convOffset < convTotal) {
        const footer = document.createElement('li');
        footer.className = 'conv-list-footer';
        footer.id = 'convLoadMore';
        footer.innerHTML = `<button class="btn-load-more">加载更多 (剩余 ${convTotal - convOffset})</button>`;
        footer.querySelector('.btn-load-more').addEventListener('click', () => loadConversations(true));
        list.appendChild(footer);
    }
}

function removeLoadMore() {
    const existing = document.getElementById('convLoadMore');
    if (existing) existing.remove();
}

function startRename(item) {
    const convId = item.dataset.id;
    const titleEl = item.querySelector('.conv-title');
    const currentTitle = titleEl.textContent;

    const input = document.createElement('input');
    input.className = 'conv-title-input';
    input.value = currentTitle;
    input.setAttribute('aria-label', '重命名对话');

    titleEl.style.display = 'none';
    titleEl.parentNode.insertBefore(input, titleEl.nextSibling);
    input.focus();
    input.select();

    const finishRename = async () => {
        const newTitle = input.value.trim() || currentTitle;
        input.remove();
        titleEl.style.display = '';
        if (newTitle !== currentTitle) {
            try {
                await apiFetch(`${API}/conversations/${convId}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ title: newTitle }),
                });
                titleEl.textContent = newTitle;
                showToast('已重命名', 'success');
            } catch (e) {
                titleEl.textContent = currentTitle;
                showToast('重命名失败', 'error');
            }
        } else {
            titleEl.textContent = currentTitle;
        }
    };

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); finishRename(); }
        if (e.key === 'Escape') { input.value = currentTitle; finishRename(); }
    });
    input.addEventListener('blur', finishRename);
}

async function newConversation() {
    try {
        const roleSelect = document.getElementById('roleSelect');
        const roleId = roleSelect ? roleSelect.value : '';
        const res = await apiFetch(`${API}/conversations`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: '新对话', role_id: roleId }),
        });
        const conv = await res.json();
        if (!res.ok) { showToast(conv.detail || '创建对话失败', 'error'); return; }
        currentConvId = conv.id;
        clearMessages();
        showWelcome();
        await loadConversations();
    } catch (e) { showToast('创建对话失败', 'error'); }
}

async function switchConversation(convId) {
    if (convId === currentConvId || isStreaming) return;
    currentConvId = convId;
    clearMessages();
    try {
        const res = await apiFetch(`${API}/conversations/${convId}`);
        if (!res.ok) { showToast('加载对话失败', 'error'); showWelcome(); return; }
        const conv = await res.json();
        const messages = conv.messages || [];
        if (messages.length > 0) {
            hideWelcome();
            messages.forEach(m => addMessage(m.role, m.content));
        } else {
            showWelcome();
        }
    } catch (e) {
        showToast('加载对话失败', 'error');
        showWelcome();
    }
    await loadConversations();
    scrollToBottom();
}

async function deleteConversation(convId) {
    try {
        await apiFetch(`${API}/conversations/${convId}`, { method: 'DELETE' });
        if (convId === currentConvId) { currentConvId = null; clearMessages(); showWelcome(); }
        await loadConversations();
        showToast('对话已删除', 'success');
    } catch (e) { showToast('删除失败', 'error'); }
}

// ── 确认对话框 ──
let _confirmResolver = null;

function showConfirm(title, message, okText = '确认删除') {
    return new Promise((resolve) => {
        _confirmResolver = resolve;
        document.getElementById('confirmTitle').textContent = title;
        document.getElementById('confirmMessage').textContent = message;
        document.getElementById('confirmOk').textContent = okText;
        document.getElementById('confirmOverlay').classList.remove('hidden');
    });
}

function hideConfirm() {
    document.getElementById('confirmOverlay').classList.add('hidden');
    _confirmResolver = null;
}

async function confirmDeleteAllConvs() {
    const confirmed = await showConfirm(
        '删除所有聊天记录',
        '确定要删除所有历史聊天记录吗？此操作不可恢复。',
        '确认删除'
    );
    if (!confirmed) return;

    const btn = document.getElementById('btnDeleteAllConvs');
    btn.disabled = true;
    try {
        const res = await apiFetch(`${API}/conversations`, { method: 'DELETE' });
        const data = await res.json();
        currentConvId = null;
        clearMessages();
        showWelcome();
        await loadConversations();
        showToast(`已删除 ${data.deleted_count || 0} 条聊天记录`, 'success');
    } catch (e) {
        showToast('删除所有聊天记录失败', 'error');
    } finally {
        btn.disabled = false;
    }
}

function clearMessages() {
    document.getElementById('chatMessages').querySelectorAll('.message, .system-msg').forEach(el => el.remove());
}

async function showWelcome() {
    const welcomeScreen = document.getElementById('welcomeScreen');
    welcomeScreen.classList.remove('hidden');

    const roleSelect = document.getElementById('roleSelect');
    if (!roleSelect || !roleSelect.value) return;

    try {
        const res = await apiFetch(`${API}/roles/${roleSelect.value}`);
        if (!res.ok) return;
        const role = await res.json();
        updateWelcomeContent(role);
    } catch (e) {
        console.error('Failed to load role for welcome:', e);
    }
}

function hideWelcome() { document.getElementById('welcomeScreen').classList.add('hidden'); }

function updateWelcomeContent(role) {
    const titleEl = document.querySelector('.welcome-title');
    const descEl = document.querySelector('.welcome-desc');
    if (!titleEl || !descEl || !role) return;

    const defaultTitle = '探索你的<br>知识宇宙';
    const defaultDesc = '我是你的知识馆长，就像《头号玩家》中的档案管理员。上传文献，向我提问，我会在庞大的知识库中帮你精准定位所需内容。';

    if (role.welcome_message) {
        descEl.textContent = role.welcome_message;
    } else if (role.description) {
        descEl.textContent = role.description;
    } else {
        descEl.innerHTML = defaultDesc;
    }

    titleEl.innerHTML = role.name ? `${role.name}<br>欢迎你` : defaultTitle;
}

// ============================== Model ==============================

// ── 模型列表 & 选择 ──────────────────────────────────────────────

async function refreshModels() {
    const sel = document.getElementById('modelName');
    const btn = document.getElementById('btnRefreshModels');
    btn.style.animation = 'spin 0.6s linear';

    try {
        const res = await apiFetch(`${API}/model/list`);
        if (!res.ok) return;
        const data = await res.json();
        const models = data.models || [];

        const current = sel.value;
        sel.innerHTML = '<option value="">-- 选择模型 --</option>';

        if (models.length === 0) {
            sel.innerHTML += '<option value="" disabled>未找到模型文件</option>';
        } else {
            models.forEach(m => {
                const label = m.size_mb > 0
                    ? `${m.name} (${m.size_mb}MB, ${m.source})`
                    : `${m.name} (${m.source})`;
                sel.innerHTML += `<option value="${escAttr(m.id)}">${esc(label)}</option>`;
            });
            if (current && models.some(m => m.id === current)) {
                sel.value = current;
            }
        }
    } catch (e) {
        // 静默失败
    } finally {
        btn.style.animation = '';
    }
}

function onModelSelect() {
    // 模型选择变更时保存偏好
    const sel = document.getElementById('modelName');
    if (sel.value) {
        localStorage.setItem('thinkvault-local-model', sel.value);
    }
}

// ── 初始化：加载保存的设置 & 模型列表 ──

// ── 模式切换 ────────────────────────────────────────────────────

function switchMode(mode) {
    // 更新 Tab 状态
    document.querySelectorAll('.mode-tab').forEach(t => t.classList.toggle('active', t.dataset.mode === mode));
    // 切换面板
    document.getElementById('panelLocal').classList.toggle('active', mode === 'local');
    document.getElementById('panelRemote').classList.toggle('active', mode === 'remote');
    // 保存偏好
    localStorage.setItem('thinkvault-mode', mode);
}

// ── 本地模型 ─────────────────────────────────────────────────────

// ── 一键启动本地服务 ──

async function quickStartServices() {
    const btn = document.getElementById('btnQuickStart');
    btn.disabled = true;
    const model = document.getElementById('modelName').value;

    updateServiceBanner('connecting', '正在启动...', '扫描本地模型');

    try {
        const res = await apiFetch(`${API}/services/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model_name: model, port: 8080, n_ctx: 2048 }),
        });

        if (!res.ok) {
            let errMsg = `HTTP ${res.status}`;
            try { const errData = await res.json(); errMsg = errData.detail || errData.message || errMsg; } catch {}
            updateServiceBanner('offline', '启动失败', errMsg);
            showToast('一键启动失败: ' + errMsg, 'error');
            return;
        }

        const d = await res.json();

        if (d.status === 'ok') {
            updateServiceBanner('online', '推理服务运行中', d.model || model);
            showToast('本地服务已启动并连接成功', 'success');
        } else if (d.status === 'partial') {
            updateServiceBanner('connecting', '连接中...', '后端尚未就绪');
            showToast('推理服务已启动但连接失败，请稍后重试', 'warning');
        } else {
            updateServiceBanner('offline', '启动失败', d.message || '未知错误');
            showToast(d.message || '服务启动失败', 'error');
        }
    } catch (e) {
        updateServiceBanner('offline', '启动失败', e.message || '网络错误');
        showToast('一键启动失败: ' + (e.message || '网络错误'), 'error');
    } finally {
        btn.disabled = false;
    }
}

// ── 远程接入 ─────────────────────────────────────────────────────

async function connectRemote() {
    const url = document.getElementById('remoteUrl').value.trim();
    const model = document.getElementById('remoteModel').value.trim();
    const apiToken = document.getElementById('apiTokenInput').value.trim();

    if (!url) { showToast('请输入后端地址', 'error'); return; }

    localStorage.setItem('thinkvault-remote-url', url);
    localStorage.setItem('thinkvault-remote-model', model);

    updateServiceBanner('connecting', '连接中...', url);
    showToast('正在连接远程服务...', 'info');

    try {
        const res = await apiFetch(`${API}/model/load`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model_path: url, model_name: model, n_ctx: 2048, api_key: apiToken }),
        });
        if (!res.ok) { const d = await res.json().catch(() => ({})); updateServiceBanner('offline', '连接失败', d.detail || '请检查地址和Token'); showToast(d.detail || '连接失败，请检查地址和Token是否正确', 'error'); return; }
        const d = await res.json();
        if (d.status === 'ok') {
            updateServiceBanner('online', '远程服务已连接', model || url);
            showToast('远程服务已连接', 'success');
        } else {
            updateServiceBanner('offline', '连接失败', '请检查地址和Token');
            showToast('连接失败，请检查地址和Token是否正确', 'error');
        }
    } catch (e) {
        updateServiceBanner('offline', '连接失败', '请确认远程服务可访问');
        showToast('连接失败，请确认远程服务可访问', 'error');
    }
}

async function disconnectRemote() {
    try {
        await apiFetch(`${API}/model/unload`, { method: 'POST' });
        updateServiceBanner('offline', '推理服务离线', '点击下方按钮启动');
        showToast('已断开远程连接', 'success');
    } catch (e) {
        updateServiceBanner('offline', '推理服务离线', '');
    }
}

// ── 初始化 ───────────────────────────────────────────────────────

function initModelSettings() {
    // 恢复模式偏好
    const savedMode = localStorage.getItem('thinkvault-mode') || 'local';
    switchMode(savedMode);

    // 恢复远程设置
    const savedRemoteUrl = localStorage.getItem('thinkvault-remote-url') || '';
    const savedRemoteModel = localStorage.getItem('thinkvault-remote-model') || '';
    document.getElementById('remoteUrl').value = savedRemoteUrl;
    document.getElementById('remoteModel').value = savedRemoteModel;

    // 恢复本地模型选择
    const savedLocalModel = localStorage.getItem('thinkvault-local-model') || '';

    // 加载模型列表
    refreshModels().then(() => {
        if (savedLocalModel) {
            const sel = document.getElementById('modelName');
            for (let i = 0; i < sel.options.length; i++) {
                if (sel.options[i].value === savedLocalModel) {
                    sel.value = savedLocalModel;
                    break;
                }
            }
        }
    });

    // 查询后端状态
    checkModelStatus();
}

async function checkModelStatus() {
    try {
        const res = await apiFetch(`${API}/model`);
        if (!res.ok) { updateServiceBanner('offline', '推理服务离线', '点击下方按钮启动'); return; }
        const info = await res.json();
        if (info.loaded) {
            updateServiceBanner('online', '推理服务运行中', info.model_name || info.model_path);
        } else {
            updateServiceBanner('offline', '推理服务离线', '点击下方按钮启动');
        }
    } catch (e) {
        updateServiceBanner('offline', '推理服务离线', '点击下方按钮启动');
    }
}

// ── 服务状态横幅更新 ──
function updateServiceBanner(state, title, desc) {
    const banner = document.getElementById('serviceStatusBanner');
    const iconEl = document.getElementById('serviceStatusIcon');
    const titleEl = document.getElementById('serviceStatusTitle');
    const descEl = document.getElementById('serviceStatusDesc');

    banner.className = 'service-status-banner';
    if (state === 'online') banner.classList.add('online');
    else if (state === 'connecting') banner.classList.add('connecting');

    titleEl.textContent = title;
    descEl.textContent = desc || '';

    // 更新图标
    if (state === 'online') {
        iconEl.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>';
    } else if (state === 'connecting') {
        iconEl.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="animation:spin 1s linear infinite"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>';
    } else {
        iconEl.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>';
    }
}

// ============================== File Upload ==============================
async function handleFiles(files) {
    if (!files || !files.length) return;
    for (const file of files) {
        const fd = new FormData();
        fd.append('file', file);
        const kbSelect = document.getElementById('kbSelect');
        const kb = kbSelect ? kbSelect.value : 'default';
        showToast('正在索引: ' + file.name + '...');
        try {
            const res = await apiFetch(`${API}/documents/upload?knowledge_base=${encodeURIComponent(kb)}`, { method: 'POST', body: fd });
            if (!res.ok) { const d = await res.json().catch(() => ({})); showToast('上传失败: ' + (d.detail || d.error || '未知错误'), 'error'); return; }
            const d = await res.json();
            if (d.status === 'ok') {
                showToast('已索引: ' + file.name + ' (' + d.chunk_count + ' 片段)', 'success');
            } else {
                showToast('失败: ' + (d.error || '?'), 'error');
            }
        } catch (e) { showToast('上传失败', 'error'); }
    }
    loadDocuments();
    loadKnowledgeBases();
}

async function loadDocuments() {
    try {
        const res = await apiFetch(`${API}/documents?knowledge_base=${encodeURIComponent(currentKb)}`);
        if (!res.ok) return;
        const data = await res.json();
        renderDocList(data.documents || []);
    } catch (e) {}
}

function renderDocList(docs) {
    const list = document.getElementById('docList');
    if (!docs || !docs.length) {
        list.innerHTML = '<li class="empty-state compact"><span class="empty-state-text">上传文献以开启知识之旅</span></li>';
        return;
    }
    const icon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M4 19.5A2.5 2.5 0 016.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z"/></svg>';
    list.innerHTML = docs.map((d, i) =>
        `<li class="doc-item" data-id="${escAttr(d.id)}" style="animation-delay:${Math.min(i * 40, 300)}ms">
            <span class="doc-icon">${icon}</span>
            <span class="doc-name" title="${esc(d.file_name)}">${esc(d.file_name)}</span>
            <span class="doc-meta">${d.chunk_count} 片段</span>
            <button class="btn-delete" data-id="${escAttr(d.id)}" title="删除" aria-label="删除文献">&times;</button>
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
        const res = await apiFetch(`${API}/documents/${docId}`, { method: 'DELETE' });
        if (!res.ok) { const d = await res.json().catch(() => ({})); showToast(d.detail || '删除失败', 'error'); return; }
        const d = await res.json();
        if (d.status === 'ok') { showToast(d.message, 'success'); loadDocuments(); loadKnowledgeBases(); }
    } catch (e) { showToast('删除失败', 'error'); }
}

// ============================== Chat (SSE Streaming) ==============================
async function sendMessage() {
    const input = document.getElementById('chatInput');
    const message = input.value.trim();
    if (!message || isStreaming) return;

    input.value = '';
    input.style.height = 'auto';
    isStreaming = true;
    updateSendButton();
    hideWelcome();
    addMessage('user', message);
    const streamMsg = addStreamingBubble();

    try {
        abortController = new AbortController();
        const res = await apiFetch(`${API}/chat/stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message,
                conversation_id: currentConvId,
                knowledge_base: currentKb,
            }),
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
            const content = streamMsg.querySelector('.message-content');
            const cursor = content.querySelector('.cursor-blink');
            if (cursor) cursor.remove();
            content.insertAdjacentHTML('beforeend', '<div class="system-msg">[已停止]</div>');
        } else if (e.message !== 'Unauthorized') {
            streamMsg.querySelector('.message-content').textContent = '[错误] ' + e.message;
        }
    }
    isStreaming = false;
    updateSendButton();
    abortController = null;
}

function addStreamingBubble() {
    const c = document.getElementById('chatMessages');
    const d = document.createElement('div');
    d.className = 'message assistant streaming';
    d.innerHTML = `<div class="message-avatar"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M4 19.5A2.5 2.5 0 016.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z"/><path d="M9 7h6"/><path d="M9 11h4"/></svg></div><div class="message-content"><div class="thinking-dots"><span></span><span></span><span></span></div></div>`;
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
    content.innerHTML = renderMarkdown(text || '[空回复]');

    const actions = document.createElement('div');
    actions.className = 'msg-actions';
    actions.innerHTML = '<button class="btn-copy" title="复制" aria-label="复制消息"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg></button>';
    const copyBtn = actions.querySelector('.btn-copy');
    copyBtn.addEventListener('click', () => {
        navigator.clipboard.writeText(text || '').then(() => {
            copyBtn.classList.add('copied');
            copyBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><polyline points="20 6 9 17 4 12"/></svg>';
            setTimeout(() => {
                copyBtn.classList.remove('copied');
                copyBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>';
            }, 2000);
        });
    });
    content.appendChild(actions);

    if (sources && sources.length) {
        const sd = document.createElement('div');
        sd.className = 'source-tags';
        sources.forEach(s => { const t = document.createElement('span'); t.className = 'source-tag'; t.textContent = s; sd.appendChild(t); });
        content.appendChild(sd);
    }
    if (stats && stats.tokens_per_sec) {
        const st = document.createElement('div');
        st.className = 'msg-stats';
        st.textContent = stats.output_tokens + ' tokens \u00B7 ' + stats.tokens_per_sec + ' tok/s \u00B7 ' + stats.elapsed_sec + 's';
        content.appendChild(st);
    }
    el.classList.remove('streaming');
    scrollToBottom();
}

// ============================== Message Rendering ==============================
function addMessage(role, text, sources, stats) {
    const c = document.getElementById('chatMessages');
    const d = document.createElement('div');
    d.className = 'message ' + role;
    const avatar = role === 'user'
        ? '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>'
        : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M4 19.5A2.5 2.5 0 016.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z"/><path d="M9 7h6"/><path d="M9 11h4"/></svg>';
    const av = document.createElement('div');
    av.className = 'message-avatar';
    av.innerHTML = avatar;
    const ct = document.createElement('div');
    ct.className = 'message-content';
    if (role === 'user') ct.textContent = text;
    else if (text) ct.innerHTML = renderMarkdown(text);

    if (role === 'assistant' && text) {
        const actions = document.createElement('div');
        actions.className = 'msg-actions';
        actions.innerHTML = '<button class="btn-copy" title="复制" aria-label="复制消息"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg></button>';
        const copyBtn = actions.querySelector('.btn-copy');
        copyBtn.addEventListener('click', () => {
            navigator.clipboard.writeText(text).then(() => {
                copyBtn.classList.add('copied');
                copyBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><polyline points="20 6 9 17 4 12"/></svg>';
                setTimeout(() => {
                    copyBtn.classList.remove('copied');
                    copyBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>';
                }, 2000);
            });
        });
        ct.appendChild(actions);
    }

    if (sources && sources.length) {
        const sd = document.createElement('div');
        sd.className = 'source-tags';
        sources.forEach(s => { const t = document.createElement('span'); t.className = 'source-tag'; t.textContent = s; sd.appendChild(t); });
        ct.appendChild(sd);
    }
    if (stats && stats.tokens_per_sec) {
        const st = document.createElement('div');
        st.className = 'msg-stats';
        st.textContent = stats.output_tokens + ' tokens \u00B7 ' + stats.tokens_per_sec + ' tok/s \u00B7 ' + stats.elapsed_sec + 's';
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
        if (typeof DOMPurify !== 'undefined') return DOMPurify.sanitize(raw);
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

/** 转义 HTML 属性值（额外处理引号） */
function escAttr(s) {
    return esc(s).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// ============================== Toast ==============================
function showToast(msg, type) {
    const c = document.getElementById('toastContainer');
    const t = document.createElement('div');
    t.className = 'toast ' + (type || '');
    t.textContent = msg;
    c.appendChild(t);
    setTimeout(() => t.remove(), 3200);
}

function scrollToBottom() {
    const c = document.getElementById('chatMessages');
    requestAnimationFrame(() => { c.scrollTop = c.scrollHeight; });
}

// ============================== KB Management Panel ==============================

function openKbPanel() {
    const panel = document.getElementById('kbPanel');
    panel.classList.remove('hidden');
    document.getElementById('kbPanelName').textContent = currentKb;
    loadKbOverview();
}

function closeKbPanel() {
    document.getElementById('kbPanel').classList.add('hidden');
}

function switchKbTab(tabName) {
    document.querySelectorAll('.kb-tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tabName));
    document.querySelectorAll('.kb-tab-content').forEach(c => c.classList.toggle('active', c.id === 'tab' + tabName.charAt(0).toUpperCase() + tabName.slice(1)));

    // Load data for the tab
    if (tabName === 'overview') loadKbOverview();
    else if (tabName === 'changes') loadKbChanges();
    else if (tabName === 'summaries') loadKbSummaries();
    else if (tabName === 'watch') loadWatchDirs();
}

async function loadKbOverview() {
    try {
        // Load KB list for stats
        const res = await apiFetch(`${API}/knowledge-bases`);
        if (!res.ok) return;
        const data = await res.json();
        const kb = (data || []).find(k => k.name === currentKb);
        if (kb) {
            document.getElementById('kbStatDocs').textContent = kb.document_count || 0;
            document.getElementById('kbStatChunks').textContent = kb.chunk_count || 0;
        }

        // Load changes count
        const changesRes = await apiFetch(`${API}/kb/manage/${currentKb}/changes`);
        if (!changesRes.ok) return;
        const changesData = await changesRes.json();
        document.getElementById('kbStatChanges').textContent = (changesData.changes || []).length;

        // Load summaries count
        const sumRes = await apiFetch(`${API}/kb/manage/${currentKb}/summaries`);
        if (!sumRes.ok) return;
        const sumData = await sumRes.json();
        const generated = (sumData.summaries || []).filter(s => s.status === 'generated').length;
        document.getElementById('kbStatSummaries').textContent = generated;
    } catch (e) {
        console.error('Failed to load KB overview:', e);
    }
}

async function startScan() {
    const dir = document.getElementById('scanDirInput').value.trim();
    const recursive = document.getElementById('scanRecursive').checked;
    if (!dir) { showToast('请输入扫描目录路径', 'error'); return; }

    try {
        const res = await apiFetch(`${API}/kb/manage/scan`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ knowledge_base: currentKb, directory_path: dir, recursive })
        });
        if (!res.ok) { const d = await res.json().catch(() => ({})); showToast('扫描失败: ' + (d.detail || '未知错误'), 'error'); return; }
        const data = await res.json();
        const stats = data.stats || data;
        document.getElementById('scanResult').classList.remove('hidden');
        document.getElementById('scanStats').innerHTML =
            `扫描: ${stats.scanned || 0} | 新增: ${stats.new || 0} | 更新: ${stats.updated || 0} | 删除: ${stats.deleted || 0} | 跳过: ${stats.skipped || 0} | 错误: ${stats.errors || 0}`;
        showToast('扫描完成', 'success');
        loadKbOverview();
        loadDocuments(); // refresh doc list in sidebar
    } catch (e) {
        showToast('扫描失败: ' + e.message, 'error');
    }
}

async function reindexFile() {
    const filePath = document.getElementById('reindexFileInput').value.trim();
    if (!filePath) { showToast('请输入文件路径', 'error'); return; }

    try {
        const res = await apiFetch(`${API}/kb/manage/reindex`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ knowledge_base: currentKb, file_path: filePath })
        });
        if (!res.ok) { const d = await res.json().catch(() => ({})); showToast('重新索引失败: ' + (d.detail || '未知错误'), 'error'); return; }
        const data = await res.json();
        showToast('重新索引完成', 'success');
        loadDocuments();
    } catch (e) {
        showToast('重新索引失败: ' + e.message, 'error');
    }
}

async function addWatchDir() {
    const dir = document.getElementById('watchDirInput').value.trim();
    if (!dir) { showToast('请输入监听目录路径', 'error'); return; }

    try {
        const res = await apiFetch(`${API}/kb/manage/watch`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ knowledge_base: currentKb, directory_path: dir })
        });
        if (!res.ok) { const d = await res.json().catch(() => ({})); showToast('添加监听失败: ' + (d.detail || '未知错误'), 'error'); return; }
        const data = await res.json();
        showToast('已添加监听', 'success');
        document.getElementById('watchDirInput').value = '';
        loadWatchDirs();
    } catch (e) {
        showToast('添加监听失败: ' + e.message, 'error');
    }
}

async function removeWatchDir(dirPath) {
    try {
        const kb = document.getElementById('kbSelect').value;
        await apiFetch(`${API}/kb/manage/watch`, {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ knowledge_base: kb, directory_path: dirPath })
        });
        showToast('已移除监听', 'success');
        loadWatchDirs();
    } catch (e) {
        showToast('移除监听失败: ' + e.message, 'error');
    }
}

async function loadWatchDirs() {
    const list = document.getElementById('watchList');
    try {
        const kb = document.getElementById('kbSelect').value;
        if (!kb) { list.innerHTML = '<li class="empty-state compact"><span class="empty-state-text">请先选择知识库</span></li>'; return; }
        const res = await apiFetch(`${API}/kb/manage/watch?knowledge_base=${encodeURIComponent(kb)}`);
        if (!res.ok) { list.innerHTML = '<li class="empty-state compact"><span class="empty-state-text">暂无监听目录</span></li>'; return; }
        const data = await res.json();
        const dirs = data.directories || [];
        if (dirs.length === 0) {
            list.innerHTML = '<li class="empty-state compact"><span class="empty-state-text">暂无监听目录</span></li>';
        } else {
            list.innerHTML = dirs.map(d => `<li class="kb-watch-item"><span class="kb-watch-path">${esc(d)}</span><button class="btn-ghost btn-icon-xs remove-dir-btn" data-dir="${escAttr(d)}" title="移除"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button></li>`).join('');
        }
    } catch (e) {
        list.innerHTML = '<li class="empty-state compact"><span class="empty-state-text">暂无监听目录</span></li>';
    }
}

async function loadKbChanges() {
    try {
        const res = await apiFetch(`${API}/kb/manage/${currentKb}/changes`);
        if (!res.ok) return;
        const data = await res.json();
        const changes = data.changes || [];
        const list = document.getElementById('changeList');

        if (changes.length === 0) {
            list.innerHTML = '<li class="empty-state compact"><span class="empty-state-text">暂无变更记录</span></li>';
            return;
        }

        list.innerHTML = changes.map(c => `
            <li class="kb-change-item">
                <div class="kb-change-file">${esc(c.file_path || c.filePath || '')}</div>
                <div class="kb-change-status">
                    <span class="status-badge ${esc(c.status || '')}">${esc(c.status || 'unknown')}</span>
                    ${c.chunk_count ? `<span style="margin-left:8px">${c.chunk_count} chunks</span>` : ''}
                </div>
            </li>
        `).join('');
    } catch (e) {
        console.error('Failed to load changes:', e);
    }
}

async function loadKbSummaries() {
    try {
        const res = await apiFetch(`${API}/kb/manage/${currentKb}/summaries`);
        if (!res.ok) return;
        const data = await res.json();
        const summaries = data.summaries || [];
        const list = document.getElementById('summaryList');

        if (summaries.length === 0) {
            list.innerHTML = '<li class="empty-state compact"><span class="empty-state-text">暂无文档摘要</span></li>';
            return;
        }

        list.innerHTML = summaries.map(s => `
            <li class="kb-summary-item">
                <div class="kb-summary-doc">${esc(s.doc_id || s.docId || '')}</div>
                ${s.summary ? `<div class="kb-summary-text">${esc(s.summary)}</div>` : ''}
                <div class="kb-summary-meta">
                    <span class="status-badge ${esc(s.status || '')}">${esc(s.status || 'pending')}</span>
                </div>
            </li>
        `).join('');
    } catch (e) {
        console.error('Failed to load summaries:', e);
    }
}

async function generateSummaries() {
    try {
        showToast('正在生成摘要...', 'info');
        const res = await apiFetch(`${API}/kb/manage/summaries`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ knowledge_base: currentKb })
        });
        if (!res.ok) { const d = await res.json().catch(() => ({})); showToast('生成摘要失败: ' + (d.detail || '未知错误'), 'error'); return; }
        const data = await res.json();
        showToast(`摘要生成完成: ${data.generated || 0} 生成, ${data.skipped || 0} 跳过`, 'success');
        loadKbOverview();
    } catch (e) {
        showToast('生成摘要失败: ' + e.message, 'error');
    }
}

// ============================== Role Management ==============================
async function loadRoles() {
    try {
        const res = await apiFetch(`${API}/roles`);
        if (!res.ok) { console.error('Failed to load roles'); return []; }
        const roles = await res.json();
        return roles;
    } catch (e) {
        console.error('Failed to load roles:', e);
        return [];
    }
}

async function refreshRoleSelector() {
    const select = document.getElementById('roleSelect');
    if (!select) return;
    const roles = await loadRoles();
    const currentVal = select.value;
    select.innerHTML = '<option value="">选择角色...</option>' + roles.map(r =>
        `<option value="${esc(r.id)}">${esc(r.name)}</option>`
    ).join('');
    select.value = currentVal;
}

async function openRoleModal() {
    document.getElementById('roleModalOverlay').classList.remove('hidden');
    await renderRoleList();
}

function closeRoleModal() {
    document.getElementById('roleModalOverlay').classList.add('hidden');
}

async function renderRoleList() {
    const list = document.getElementById('roleList');
    if (!list) return;
    const roles = await loadRoles();
    const currentRoleId = document.getElementById('roleSelect')?.value;
    if (roles.length === 0) {
        list.innerHTML = '<li class="empty-state compact"><span class="empty-state-text">暂无角色</span></li>';
        return;
    }
    list.innerHTML = roles.map(r => `
        <li class="role-item ${currentRoleId === r.id ? 'selected' : ''}" data-role-id="${esc(r.id)}" onclick="selectRole('${esc(r.id)}')">
            <div class="role-item-info">
                <div class="role-item-name">${esc(r.name)}${r.is_builtin ? ' <span class="role-item-badge">预置</span>' : ''}</div>
                <div class="role-item-desc">${esc(r.description || '暂无描述')}</div>
            </div>
            <div class="role-item-actions">
                <button class="btn-ghost btn-icon-sm" onclick="event.stopPropagation(); editRole('${esc(r.id)}')" title="编辑">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                </button>
                ${!r.is_builtin ? `<button class="btn-ghost btn-icon-sm btn-danger-sm" onclick="event.stopPropagation(); deleteRoleConfirm('${esc(r.id)}', '${esc(r.name)}')" title="删除">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>
                </button>` : ''}
            </div>
        </li>
    `).join('');
}

function selectRole(roleId) {
    const select = document.getElementById('roleSelect');
    if (select) {
        select.value = roleId;
        closeRoleModal();
        showToast('已选择角色', 'success');
    }
}

const PROMPT_TEMPLATES = {
    professional: {
        name: '专业顾问',
        prompt: '你是一位专业、严谨的顾问。请根据提供的文档内容，为用户提供准确、专业的回答。保持客观中立，基于事实说话。如果文档中没有足够信息，请明确说明。',
        desc: '适合需要专业、严谨回答的场景',
        welcome: '您好！我是您的专业顾问。请告诉我您的问题，我将基于知识库为您提供专业解答。'
    },
    creative: {
        name: '创意助手',
        prompt: '你是一位富有创意和想象力的助手。请以积极、热情的态度与用户交流，鼓励创新思维。回答时可以加入适当的比喻和生动的语言，让对话更有趣。',
        desc: '适合创意 brainstorming 和灵感激发',
        welcome: '嗨！我是您的创意助手。让我们一起探索无限可能，激发创新灵感！'
    },
    teacher: {
        name: '知识导师',
        prompt: '你是一位耐心、细致的导师。请用通俗易懂的语言解释复杂概念，善于引导用户思考。回答时可以分步骤讲解，并提供实际例子帮助理解。',
        desc: '适合学习辅导和知识传授',
        welcome: '您好！我是您的知识导师。让我们一起学习和成长，有什么问题我来帮您解答。'
    },
    writer: {
        name: '文案写手',
        prompt: '你是一位优秀的文案写手。请用优美、流畅的语言表达观点，注重文字的感染力和说服力。根据不同场景调整语气和风格，确保内容吸引人。',
        desc: '适合内容创作和文案撰写',
        welcome: '您好！我是您的文案写手。让我帮您用文字传递价值，创造精彩内容。'
    }
};

function applyPromptTemplate(templateKey) {
    const template = PROMPT_TEMPLATES[templateKey];
    if (!template) return;

    const nameInput = document.getElementById('editRoleName');
    const descInput = document.getElementById('editRoleDescription');
    const promptInput = document.getElementById('editRolePrompt');
    const welcomeInput = document.getElementById('editRoleWelcome');

    if (!nameInput.value) nameInput.value = template.name;
    if (!descInput.value) descInput.value = template.desc;
    promptInput.value = template.prompt;
    if (!welcomeInput.value) welcomeInput.value = template.welcome;

    showToast('已应用模板', 'success');
}

function openRoleEditModal(roleId = null) {
    const modal = document.getElementById('roleEditModalOverlay');
    const title = document.getElementById('roleEditModalTitle');
    const idInput = document.getElementById('editRoleId');
    const nameInput = document.getElementById('editRoleName');
    const descInput = document.getElementById('editRoleDescription');
    const promptInput = document.getElementById('editRolePrompt');
    const welcomeInput = document.getElementById('editRoleWelcome');
    const deleteBtn = document.getElementById('btnDeleteRole');

    if (roleId) {
        title.textContent = '编辑角色';
        idInput.value = roleId;
        loadRoles().then(roles => {
            const role = roles.find(r => r.id === roleId);
            if (role) {
                nameInput.value = role.name;
                descInput.value = role.description || '';
                promptInput.value = role.system_prompt || '';
                welcomeInput.value = role.welcome_message || '';
                deleteBtn.classList.toggle('hidden', role.is_builtin);
            }
        });
    } else {
        title.textContent = '创建角色';
        idInput.value = '';
        nameInput.value = '';
        descInput.value = '';
        promptInput.value = '';
        welcomeInput.value = '';
        deleteBtn.classList.add('hidden');
    }
    modal.classList.remove('hidden');
}

function editRole(roleId) {
    openRoleEditModal(roleId);
}

function closeRoleEditModal() {
    document.getElementById('roleEditModalOverlay').classList.add('hidden');
}

async function saveRole() {
    const roleId = document.getElementById('editRoleId').value;
    const nameInput = document.getElementById('editRoleName');
    const promptInput = document.getElementById('editRolePrompt');
    const name = nameInput.value.trim();
    const description = document.getElementById('editRoleDescription').value.trim();
    const systemPrompt = promptInput.value.trim();
    const welcomeMessage = document.getElementById('editRoleWelcome').value.trim();

    removeFieldError(nameInput);
    removeFieldError(promptInput);

    let isValid = true;

    if (!name) {
        showFieldError(nameInput, '请输入角色名称');
        isValid = false;
    } else if (name.length > 50) {
        showFieldError(nameInput, '角色名称不能超过50个字符');
        isValid = false;
    }

    if (!systemPrompt) {
        showFieldError(promptInput, '请输入系统提示词');
        isValid = false;
    } else if (systemPrompt.length < 10) {
        showFieldError(promptInput, '系统提示词至少需要10个字符');
        isValid = false;
    }

    if (!isValid) {
        showToast('请修正表单中的错误', 'error');
        return;
    }

    try {
        const url = roleId ? `${API}/roles/${roleId}` : `${API}/roles`;
        const method = roleId ? 'PUT' : 'POST';
        const body = JSON.stringify({ name, description, system_prompt: systemPrompt, welcome_message: welcomeMessage });

        const res = await apiFetch(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body
        });

        if (!res.ok) {
            const d = await res.json().catch(() => ({}));
            if (d.detail && d.detail.includes('已存在')) {
                showFieldError(nameInput, '角色名称已存在');
            }
            showToast(d.detail || '保存失败', 'error');
            return;
        }

        showToast(roleId ? '角色已更新' : '角色已创建', 'success');
        closeRoleEditModal();
        await renderRoleList();
        await refreshRoleSelector();
    } catch (e) {
        showToast('保存失败: ' + e.message, 'error');
    }
}

function showFieldError(input, message) {
    input.classList.add('field-error');
    const existingHint = input.parentNode.querySelector('.field-error-hint');
    if (existingHint) existingHint.remove();
    const hint = document.createElement('span');
    hint.className = 'field-error-hint';
    hint.textContent = message;
    input.parentNode.appendChild(hint);
}

function removeFieldError(input) {
    input.classList.remove('field-error');
    const hint = input.parentNode.querySelector('.field-error-hint');
    if (hint) hint.remove();
}

function deleteRoleConfirm(roleId, roleName) {
    showConfirm('删除角色', `确定要删除角色「${roleName}」吗？此操作不可恢复。`, '确认删除').then(async (confirmed) => {
        if (confirmed) {
            await deleteRole(roleId);
        }
    });
}

async function deleteRole() {
    const roleId = document.getElementById('editRoleId').value;
    if (!roleId) return;

    try {
        const res = await apiFetch(`${API}/roles/${roleId}`, { method: 'DELETE' });
        if (!res.ok) {
            const d = await res.json().catch(() => ({}));
            showToast(d.detail || '删除失败', 'error');
            return;
        }
        showToast('角色已删除', 'success');
        closeRoleEditModal();
        await renderRoleList();
        await refreshRoleSelector();
    } catch (e) {
        showToast('删除失败: ' + e.message, 'error');
    }
}


