// ── Config ───────────────────────────────────────────────────────────────────
const API_BASE = window.location.hostname === 'localhost'
    ? 'http://localhost:8000'
    : '';  // production: same-origin, nginx proxy

// ── Global State ─────────────────────────────────────────────────────────────
let _currentUser     = null;
let _products        = [];
let _activeDetailProduct = null;

// ── Firebase Auth ─────────────────────────────────────────────────────────────
const _auth = firebase.auth();

async function _getToken() {
    if (!_currentUser) throw new Error('Oturum açılmamış.');
    return _currentUser.getIdToken(/* forceRefresh= */ false);
}

// ── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    // Auth state listener — show/hide login overlay
    _auth.onAuthStateChanged(async user => {
        _currentUser = user;
        if (user) {
            document.getElementById('loginOverlay').style.display = 'none';
            document.getElementById('mainApp').style.display      = '';
            document.getElementById('userEmail').textContent       = user.email;
            // Firestore'da kullanıcı kaydını oluştur/güncelle
            try { await apiFetch('/api/user/me', undefined, 'GET'); } catch (_) {}
            loadDashboardStats();
            loadProducts();
        } else {
            document.getElementById('loginOverlay').style.display = 'flex';
            document.getElementById('mainApp').style.display      = 'none';
        }
    });

    // Login form
    document.getElementById('loginBtn').addEventListener('click', _handleLogin);
    document.getElementById('loginPassword').addEventListener('keydown', e => {
        if (e.key === 'Enter') _handleLogin();
    });

    // Logout
    document.getElementById('logoutBtn').addEventListener('click', () => _auth.signOut());

    // Chat input Enter
    const chatInput = document.getElementById('chatInput');
    if (chatInput) {
        chatInput.addEventListener('keydown', e => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
        });
    }
});

async function _handleLogin() {
    const email    = document.getElementById('loginEmail').value.trim();
    const password = document.getElementById('loginPassword').value;
    const errEl    = document.getElementById('loginError');
    const btn      = document.getElementById('loginBtn');

    if (!email || !password) { _showLoginError('E-posta ve şifre gerekli.'); return; }

    btn.disabled = true;
    errEl.style.display = 'none';

    try {
        await _auth.signInWithEmailAndPassword(email, password);
    } catch (err) {
        const msg = {
            'auth/user-not-found':  'Bu e-posta kayıtlı değil.',
            'auth/wrong-password':  'Şifre hatalı.',
            'auth/invalid-email':   'Geçersiz e-posta formatı.',
            'auth/too-many-requests': 'Çok fazla deneme. Biraz bekleyin.',
            'auth/invalid-credential': 'E-posta veya şifre hatalı.',
        }[err.code] || err.message;
        _showLoginError(msg);
    } finally {
        btn.disabled = false;
    }
}

function _showLoginError(msg) {
    const el = document.getElementById('loginError');
    el.textContent    = msg;
    el.style.display  = 'block';
}

async function apiFetch(path, body, method = 'POST') {
    const token = await _getToken();
    const opts = {
        method,
        headers: {
            'Content-Type':  'application/json',
            'Authorization': `Bearer ${token}`,
        },
    };
    if (body !== undefined) opts.body = JSON.stringify(body);
    const res = await fetch(API_BASE + path, opts);
    if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        if (res.status === 401) { _auth.signOut(); throw new Error('Oturum süresi doldu, lütfen tekrar giriş yapın.'); }
        throw new Error(`API Hatası (${res.status}): ${err.detail || 'Bilinmeyen hata'}`);
    }
    return res.json();
}

// ── AI Chat ───────────────────────────────────────────────────────────────────
function askQuestion(question) {
    document.getElementById('chatInput').value = question;
    sendChat();
}

async function sendChat() {
    const input      = document.getElementById('chatInput');
    const messagesEl = document.getElementById('chatMessages');
    const sendBtn    = document.getElementById('chatSendBtn');
    const message    = input.value.trim();
    if (!message) return;
    if (!_products.length) {
        appendMessage(messagesEl, 'ai', 'Önce Ürünlerim sayfasından bir ürün ekleyin. Sonra eklediğiniz ürünler hakkında konuşabiliriz.');
        return;
    }

    appendMessage(messagesEl, 'user', message);
    input.value = '';
    sendBtn.disabled = true;
    const typingId = appendTyping(messagesEl);

    try {
        const select = document.getElementById('copilotProductSelect');
        const productId = select?.value || null;
        const res  = await apiFetch('/api/products/chat', { message, product_id: productId });
        removeTyping(messagesEl, typingId);
        appendMessage(messagesEl, 'ai', res.answer || 'Yanıt alınamadı.');
    } catch (err) {
        removeTyping(messagesEl, typingId);
        appendMessage(messagesEl, 'ai', 'Bağlantı hatası: ' + err.message);
    } finally {
        sendBtn.disabled = false;
    }
}

function appendMessage(container, role, text) {
    const div = document.createElement('div');
    div.className = `chat-msg ${role === 'user' ? 'chat-msg-user' : 'chat-msg-ai'}`;
    const icon = role === 'user'
        ? '<i class="fa-solid fa-user"></i>'
        : '<i class="fa-solid fa-robot"></i>';
    const html = escHtml(text).replace(/\n/g, '<br>');
    div.innerHTML = `<div class="chat-msg-icon">${icon}</div><div class="chat-msg-bubble">${html}</div>`;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

function appendTyping(container) {
    const id  = 'typing-' + Date.now();
    const div = document.createElement('div');
    div.className = 'chat-msg chat-msg-ai';
    div.id = id;
    div.innerHTML = `
        <div class="chat-msg-icon"><i class="fa-solid fa-robot"></i></div>
        <div class="chat-msg-bubble typing-bubble"><span></span><span></span><span></span></div>
    `;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
    return id;
}

function removeTyping(container, id) {
    const el = document.getElementById(id);
    if (el) el.remove();
}

// ── Yardımcı ─────────────────────────────────────────────────────────────────
function escHtml(str) {
    return (str || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

// ── Sidebar SPA Router ────────────────────────────────────────────────────────
const _pageTitles = {
    dashboard:  'Dashboard',
    kopilot:    'Kopilot',
    urunlerim:  'Ürünlerim',
    yakinda:    'Yakında',
    ayarlar:    'Ayarlar',
};

function navigateTo(pageId) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));

    const page = document.getElementById('page-' + pageId);
    if (page) page.classList.add('active');

    const navItem = document.querySelector(`.nav-item[data-page="${pageId}"]`);
    if (navItem) navItem.classList.add('active');

    const titleEl = document.getElementById('pageTitle');
    if (titleEl) titleEl.textContent = _pageTitles[pageId] || '';

    // Sync settings page
    if (pageId === 'ayarlar' && _currentUser) {
        const el = document.getElementById('settingsEmail');
        if (el) el.textContent = _currentUser.email;
        loadApiKeys();
        fetchUserPlan();
        loadConnectedStores();
    }
    if (pageId === 'urunlerim' && _currentUser) {
        loadProducts();
    }
    if (pageId === 'kopilot' && _currentUser) {
        initKopilotPage();
    }
    if (pageId === 'dashboard' && _currentUser) {
        loadDashboardStats();
    }

    _closeSidebar();
}

function _openSidebar() {
    document.getElementById('sidebar')?.classList.add('open');
    document.getElementById('sidebarOverlay')?.classList.add('open');
}

function _closeSidebar() {
    document.getElementById('sidebar')?.classList.remove('open');
    document.getElementById('sidebarOverlay')?.classList.remove('open');
}

document.addEventListener('DOMContentLoaded', () => {
    // Nav item clicks
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', () => {
            const pageId = item.dataset.page;
            if (pageId) navigateTo(pageId);
        });
    });

    // Hamburger
    document.getElementById('hamburgerBtn')?.addEventListener('click', _openSidebar);

    // Overlay click closes sidebar
    document.getElementById('sidebarOverlay')?.addEventListener('click', _closeSidebar);

    // Secondary logout button (settings page)
    document.getElementById('logoutBtn2')?.addEventListener('click', () => _auth.signOut());

});

// ── Ürünlerim + Kopilot Ürün Chat ───────────────────────────────────────────
function _productTitle(product) {
    return (product.scraped_data?.title || product.product_title || 'Başlıksız ürün').trim();
}

function _productDescription(product) {
    return product.scraped_data?.description || '';
}

function _productImages(product) {
    return product.scraped_data?.image_urls || [];
}

function _scorePill(product) {
    if (product.score === null || product.score === undefined) {
        return '<span class="product-pill"><i class="fa-solid fa-hourglass-half"></i> Skor bekliyor</span>';
    }
    return `<span class="product-pill product-score-ready"><i class="fa-solid fa-star"></i> ${product.score}/100</span>`;
}

async function loadProducts() {
    const list = document.getElementById('productsList');
    if (list) {
        list.innerHTML = `
            <div class="empty-state" style="padding:4rem 2rem;">
                <i class="fa-solid fa-spinner fa-spin"></i>
                <p>Ürünler yükleniyor...</p>
            </div>`;
    }
    try {
        const res = await apiFetch('/api/products', undefined, 'GET');
        _products = res.data || [];
        renderProducts();
        initKopilotPage();
    } catch (err) {
        if (list) {
            list.innerHTML = `<div class="empty-state"><i class="fa-solid fa-triangle-exclamation"></i><p>Ürünler yüklenemedi: ${escHtml(err.message)}</p></div>`;
        }
    }
}

function renderProducts() {
    const list = document.getElementById('productsList');
    if (!list) return;
    if (!_products.length) {
        list.innerHTML = `
            <div class="glass-panel empty-state" style="padding:4rem 2rem;">
                <i class="fa-solid fa-box-open"></i>
                <p>Henüz ürün yok. Mağazadan içe aktarın.</p>
                <button class="btn-primary" style="padding:0.65rem 1.2rem;font-size:0.85rem;" onclick="openImportModal()">
                    <i class="fa-solid fa-cloud-arrow-down"></i>
                    <span>Mağazadan İçe Aktar</span>
                </button>
            </div>`;
        return;
    }

    list.innerHTML = _products.map(product => {
        const title = _productTitle(product);
        const thumb = product.thumbnail
            ? `<img class="product-thumb" src="${escHtml(product.thumbnail)}" alt="${escHtml(title)}">`
            : `<div class="product-thumb product-thumb-placeholder"><i class="fa-solid fa-box"></i></div>`;
        const platform = product.platform || 'Manuel';
        const status = product.status === 'improved' ? 'İyileştirildi'
            : product.status === 'analyzed' ? 'Analiz edildi'
            : product.status === 'inspected' ? 'İncelendi'
            : 'Taslak';
        return `
            <article class="product-card">
                ${thumb}
                <div>
                    <h3 class="product-card-title">${escHtml(title)}</h3>
                    <div class="product-card-meta">
                        <span class="product-pill"><i class="fa-solid fa-store"></i> ${escHtml(platform)}</span>
                        ${_scorePill(product)}
                        <span class="product-pill"><i class="fa-solid fa-circle-check"></i> ${escHtml(status)}</span>
                    </div>
                </div>
                <div class="product-card-actions">
                    <button class="product-action-btn" onclick="openProductDetail('${product.id}', 'inspect')"><i class="fa-solid fa-eye"></i> İncele</button>
                    <button class="product-action-btn" onclick="openProductDetail('${product.id}', 'analyze')"><i class="fa-solid fa-chart-simple"></i> Analiz Et</button>
                    <button class="product-action-btn product-action-primary" onclick="openProductDetail('${product.id}', 'improve')"><i class="fa-solid fa-rocket"></i> İyileştir</button>
                    <button class="icon-btn" onclick="deleteProduct('${product.id}')" title="Sil"><i class="fa-solid fa-trash"></i></button>
                </div>
            </article>`;
    }).join('');
}

function initKopilotPage() {
    const select = document.getElementById('copilotProductSelect');
    const empty = document.getElementById('copilotEmptyState');
    const chatInput = document.getElementById('chatInput');
    if (select) {
        const current = select.value;
        select.innerHTML = '<option value="">Tüm ürünler</option>' + _products.map(p =>
            `<option value="${p.id}">${escHtml(_productTitle(p))}</option>`
        ).join('');
        if (_products.some(p => p.id === current)) select.value = current;
    }
    if (empty) empty.style.display = _products.length ? 'none' : 'flex';
    if (chatInput) chatInput.disabled = !_products.length;
}


async function deleteProduct(productId) {
    if (!confirm('Ürün silinsin mi?')) return;
    try {
        await apiFetch(`/api/products/${encodeURIComponent(productId)}`, undefined, 'DELETE');
        await loadProducts();
        loadDashboardStats();
    } catch (err) {
        alert('Silinemedi: ' + err.message);
    }
}

async function openProductDetail(productId, mode = 'inspect') {
    if (!productId) return;
    const overlay = document.getElementById('productDetailOverlay');
    const body = document.getElementById('productDetailBody');
    overlay.style.display = 'flex';
    body.innerHTML = `<div class="product-loading"><i class="fa-solid fa-circle-notch"></i><span>Ürün verisi hazırlanıyor...</span></div>`;

    try {
        const res = await apiFetch(`/api/products/${encodeURIComponent(productId)}`, undefined, 'GET');
        _activeDetailProduct = res.data;
        renderProductDetail(_activeDetailProduct);
        if (mode === 'analyze') await analyzeActiveProduct();
        if (mode === 'improve') await improveActiveProduct();
    } catch (err) {
        body.innerHTML = `<div class="empty-state"><i class="fa-solid fa-triangle-exclamation"></i><p>${escHtml(err.message)}</p></div>`;
    }
}

function closeProductDetail() {
    document.getElementById('productDetailOverlay').style.display = 'none';
    _activeDetailProduct = null;
}

function renderProductDetail(product) {
    const title = _productTitle(product);
    document.getElementById('detailTitle').textContent = title;
    document.getElementById('detailPlatform').textContent = product.platform || 'Manuel';
    document.getElementById('detailScore').textContent = product.score === null || product.score === undefined ? 'Skor bekliyor' : `${product.score}/100`;

    // Deploy butonu: mağazadan içe aktarılmış + analiz edilmiş ürünlerde görünür
    const deployBtn = document.getElementById('deployBtn');
    if (deployBtn) {
        const canDeploy = product.source_store_id && product.data?.content_analysis?.new_title;
        deployBtn.style.display = canDeploy ? 'flex' : 'none';
        deployBtn.disabled = false;
        deployBtn.querySelector('span').textContent = 'Mağazaya Gönder';
        deployBtn.style.background = '';
        deployBtn.style.borderColor = '';
    }

    const images = _productImages(product);
    const reviews = product.scraped_data?.review_sample || [];
    const analysis = product.data?.content_analysis || null;
    const improved = product.image_paths || [];
    const body = document.getElementById('productDetailBody');

    body.innerHTML = `
        <section class="detail-section">
            <h3>Görseller</h3>
            ${images.length ? `<div class="detail-gallery">${images.map(url => `<img src="${escHtml(url)}" alt="${escHtml(title)}">`).join('')}</div>` : '<p class="section-sub">Görsel bulunamadı.</p>'}
        </section>
        <section class="detail-section">
            <h3>Başlık</h3>
            <p class="detail-description">${escHtml(title)}</p>
        </section>
        <section class="detail-section">
            <h3>Ürün Açıklaması</h3>
            <p class="detail-description">${escHtml(_productDescription(product) || 'Açıklama bulunamadı.')}</p>
        </section>
        <section class="detail-section">
            <h3>Yorumlar (${product.scraped_data?.review_count || reviews.length || 0})</h3>
            ${reviews.length ? reviews.slice(0, 8).map(r => `<div class="detail-review"><strong>${r.rating ? '★'.repeat(Math.round(r.rating)) : ''}</strong><br>${escHtml(r.text || '')}</div>`).join('') : '<p class="section-sub">Yorum bulunamadı.</p>'}
        </section>
        ${analysis ? renderAnalysisBlock(product) : ''}
        ${improved.length ? renderImprovedImages(improved) : ''}
    `;
}

function renderAnalysisBlock(product) {
    const ca = product.data?.content_analysis || {};
    return `
        <section class="detail-section">
            <h3>Analiz Sonucu</h3>
            <div class="detail-analysis-card">
                <strong>Skor: ${product.score}/100</strong><br>
                ${escHtml(ca.score_summary || '')}
                <br><br><strong>Yeni Başlık:</strong><br>${escHtml(ca.new_title || '')}
                <br><br><strong>Yeni Açıklama:</strong><br>${escHtml(ca.new_description || '')}
            </div>
        </section>`;
}

function renderImprovedImages(paths) {
    return `
        <section class="detail-section">
            <h3>İyileştirilmiş Görseller</h3>
            <div class="detail-gallery">
                ${paths.map(path => `<img src="${API_BASE}/outputs/${escHtml(path)}" alt="İyileştirilmiş görsel">`).join('')}
            </div>
        </section>`;
}

async function analyzeActiveProduct() {
    const product = _activeDetailProduct;
    if (!product) return;
    if (product.data && product.score !== null && product.score !== undefined) {
        renderProductDetail(product);
        return;
    }
    const body = document.getElementById('productDetailBody');
    body.innerHTML = `<div class="product-loading"><i class="fa-solid fa-circle-notch"></i><span>Ürün analiz ediliyor...</span></div>`;
    const res = await apiFetch(`/api/products/${encodeURIComponent(product.id)}/analyze`, {});
    _activeDetailProduct = (await apiFetch(`/api/products/${encodeURIComponent(product.id)}`, undefined, 'GET')).data;
    renderProductDetail(_activeDetailProduct);
    await loadProducts();
    loadDashboardStats();
    return res;
}

async function improveActiveProduct() {
    const product = _activeDetailProduct;
    if (!product) return;
    const body = document.getElementById('productDetailBody');
    body.innerHTML = `<div class="product-loading"><i class="fa-solid fa-circle-notch"></i><span>Ürün iyileştiriliyor...</span></div>`;

    const token = await _getToken();
    const res = await fetch(`${API_BASE}/api/products/${encodeURIComponent(product.id)}/improve`, {
        headers: { 'Authorization': `Bearer ${token}` },
    });
    if (!res.ok) throw new Error('İyileştirme başlatılamadı.');

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let statusText = 'Ürün iyileştiriliyor...';
    body.innerHTML = `<div class="product-loading"><i class="fa-solid fa-circle-notch"></i><span id="productImproveStatus">${statusText}</span></div>`;

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();
        for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            const event = JSON.parse(line.slice(6));
            if (event.type === 'error') throw new Error(event.message);
            if (event.message) statusText = event.message;
            if (event.type === 'start') statusText = `${event.total || 0} görsel iyileştiriliyor...`;
            if (event.type === 'image') statusText = `${event.data?.idx || ''}. görsel hazırlandı...`;
            const el = document.getElementById('productImproveStatus');
            if (el) el.textContent = statusText;
        }
    }

    _activeDetailProduct = (await apiFetch(`/api/products/${encodeURIComponent(product.id)}`, undefined, 'GET')).data;
    renderProductDetail(_activeDetailProduct);
    await loadProducts();
    loadDashboardStats();
}

async function loadDashboardStats() {
    try {
        const res = await apiFetch('/api/user/stats', undefined, 'GET');
        const s = res.data || {};
        document.getElementById('statTotalAnalyses').textContent = s.total_analyses ?? 0;
        document.getElementById('statThisMonth').textContent = s.this_month ?? 0;
        document.getElementById('statAvgScore').textContent = s.avg_score ?? '—';
        document.getElementById('statImages').textContent = s.images_this_month ?? 0;
    } catch (_) {}
}

// ── API Anahtarları ───────────────────────────────────────────────────────────
async function loadApiKeys() {
    const list = document.getElementById('apiKeysList');
    if (!list) return;
    list.innerHTML = '<p style="font-size:0.82rem;color:var(--text-muted);padding:0.5rem 0;">Yükleniyor...</p>';
    try {
        const data = await apiFetch('/api/user/api-keys', undefined, 'GET');
        const keys = data.data || [];
        if (!keys.length) {
            list.innerHTML = '<p style="font-size:0.82rem;color:var(--text-muted);padding:0.5rem 0;">Henüz API anahtarı eklenmemiş.</p>';
            return;
        }
        list.innerHTML = keys.map(k => `
            <div class="api-key-item">
                <div class="api-key-platform"><i class="fa-solid fa-key"></i> ${escHtml(k.platform)}</div>
                <div class="api-key-masked">${escHtml(k.masked)}</div>
                <button class="btn-delete-key" onclick="deleteApiKey('${escHtml(k.platform)}')">
                    <i class="fa-solid fa-trash"></i> Sil
                </button>
            </div>`).join('');
    } catch (err) {
        list.innerHTML = `<p style="font-size:0.82rem;color:#f87171;padding:0.5rem 0;">Yüklenemedi: ${escHtml(err.message)}</p>`;
    }
}

async function saveApiKey() {
    const platform = document.getElementById('apiKeyPlatform').value;
    const apiKey   = document.getElementById('apiKeyValue').value.trim();
    if (!platform) { alert('Platform seçin.'); return; }
    if (!apiKey)   { alert('API anahtarı girin.'); return; }
    try {
        await apiFetch('/api/user/api-keys', { platform, api_key: apiKey });
        document.getElementById('apiKeyPlatform').value = '';
        document.getElementById('apiKeyValue').value    = '';
        await loadApiKeys();
    } catch (err) {
        alert(`Hata: ${err.message}`);
    }
}

async function deleteApiKey(platform) {
    if (!confirm(`"${platform}" API anahtarı silinsin mi?`)) return;
    try {
        await apiFetch(`/api/user/api-keys/${encodeURIComponent(platform)}`, undefined, 'DELETE');
        await loadApiKeys();
    } catch (err) {
        alert(`Hata: ${err.message}`);
    }
}

// ── Bağlı Mağazalar ───────────────────────────────────────────────────────────
let _connectedStores = [];
let _importStoreId   = null;
let _importProducts  = [];

function onStorePlatformChange() {
    const sel = document.getElementById('storePlatformSelect');
    const urlInput  = document.getElementById('storeUrlInput');
    const nameInput = document.getElementById('storeNameInput');
    if (sel.value === 'test-commerce') {
        urlInput.value  = window.location.origin + '/api/test-commerce';
        nameInput.value = nameInput.value || 'Test Mağaza';
    }
}

async function loadConnectedStores() {
    const list = document.getElementById('connectedStoresList');
    if (!list) return;
    try {
        const res = await apiFetch('/api/user/stores', undefined, 'GET');
        _connectedStores = res.data || [];
        if (!_connectedStores.length) {
            list.innerHTML = '<p style="font-size:0.82rem;color:var(--text-muted);padding:0.5rem 0;">Henüz bağlı mağaza yok.</p>';
            return;
        }
        list.innerHTML = _connectedStores.map(s => `
            <div class="api-key-item">
                <div class="api-key-platform"><i class="fa-solid fa-store"></i> ${escHtml(s.name || s.platform)}</div>
                <div class="api-key-masked" style="font-size:0.78rem;color:var(--text-muted);">${escHtml(s.api_url)}</div>
                <button class="btn-delete-key" onclick="disconnectStore('${escHtml(s.id)}')">
                    <i class="fa-solid fa-trash"></i> Sil
                </button>
            </div>`).join('');
    } catch (err) {
        if (list) list.innerHTML = `<p style="font-size:0.82rem;color:#f87171;padding:0.5rem 0;">Yüklenemedi: ${escHtml(err.message)}</p>`;
    }
}

async function connectStore() {
    const platform = document.getElementById('storePlatformSelect').value;
    const name     = document.getElementById('storeNameInput').value.trim();
    const apiUrl   = document.getElementById('storeUrlInput').value.trim();
    if (!platform) { alert('Platform seçin.'); return; }
    if (!apiUrl)   { alert('API URL girin.'); return; }
    try {
        await apiFetch('/api/user/stores', { name: name || platform, platform, api_url: apiUrl });
        document.getElementById('storePlatformSelect').value = '';
        document.getElementById('storeNameInput').value = '';
        document.getElementById('storeUrlInput').value  = '';
        await loadConnectedStores();
    } catch (err) {
        alert('Hata: ' + err.message);
    }
}

async function disconnectStore(storeId) {
    if (!confirm('Mağaza bağlantısı kaldırılsın mı?')) return;
    try {
        await apiFetch(`/api/user/stores/${encodeURIComponent(storeId)}`, undefined, 'DELETE');
        await loadConnectedStores();
    } catch (err) {
        alert('Hata: ' + err.message);
    }
}

async function openImportModal() {
    const modal = document.getElementById('importStoreModal');
    const list  = document.getElementById('importProductsList');
    modal.style.display = 'flex';
    list.innerHTML = `<div class="empty-state" style="padding:2rem;"><i class="fa-solid fa-spinner fa-spin"></i><p>Mağazalar kontrol ediliyor...</p></div>`;
    document.getElementById('importConfirmBtn').disabled = true;

    try {
        const res = await apiFetch('/api/user/stores', undefined, 'GET');
        _connectedStores = res.data || [];
        if (!_connectedStores.length) {
            list.innerHTML = `<div class="empty-state" style="padding:2rem;">
                <i class="fa-solid fa-store"></i>
                <p>Önce Ayarlar'dan bir mağaza bağlayın.</p>
                <button class="btn-primary" style="padding:0.6rem 1.2rem;font-size:0.85rem;margin-top:0.5rem;" onclick="closeImportModal();navigateTo('ayarlar');">
                    <i class="fa-solid fa-gear"></i> Ayarlara Git
                </button>
            </div>`;
            return;
        }
        _importStoreId = _connectedStores[0].id;
        document.getElementById('importStoreNameLabel').textContent =
            `"${_connectedStores[0].name || _connectedStores[0].platform}" mağazasından ürün seçin.`;

        const prodRes = await apiFetch(`/api/stores/${encodeURIComponent(_importStoreId)}/products`, undefined, 'GET');
        _importProducts = prodRes.data || [];

        if (!_importProducts.length) {
            list.innerHTML = '<p style="text-align:center;color:var(--text-muted);padding:2rem;">Mağazada ürün bulunamadı.</p>';
            return;
        }

        list.innerHTML = _importProducts.map(p => `
            <label class="import-product-row" style="display:flex;align-items:center;gap:0.8rem;padding:0.75rem 0.5rem;border-bottom:1px solid rgba(255,255,255,0.06);cursor:pointer;">
                <input type="checkbox" class="import-chk" value="${escHtml(p.id)}" onchange="_updateImportBtn()">
                <img src="${escHtml((p.images||[])[0] || 'https://placehold.co/48x48/1a1a2e/6c63ff?text=?')}"
                     style="width:48px;height:48px;object-fit:cover;border-radius:8px;flex-shrink:0;"
                     onerror="this.src='https://placehold.co/48x48/1a1a2e/6c63ff?text=?'">
                <div style="flex:1;min-width:0;">
                    <div style="font-size:0.88rem;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${escHtml(p.title)}</div>
                    <div style="font-size:0.75rem;color:var(--text-muted);">
                        ${escHtml(p.brand || '')} · ${p.price ? p.price.toLocaleString('tr-TR', {style:'currency',currency:'TRY'}) : ''} · ⭐ ${p.rating || '?'} (${p.review_count || 0} yorum)
                    </div>
                </div>
            </label>`).join('');
    } catch (err) {
        list.innerHTML = `<div class="empty-state" style="padding:2rem;"><i class="fa-solid fa-triangle-exclamation"></i><p>Hata: ${escHtml(err.message)}</p></div>`;
    }
}

function _updateImportBtn() {
    const checked = document.querySelectorAll('.import-chk:checked').length;
    const btn = document.getElementById('importConfirmBtn');
    btn.disabled = checked === 0;
    btn.querySelector('span').textContent = checked > 0 ? `${checked} Ürünü İçe Al` : 'Seçilenleri İçe Al';
}

function closeImportModal() {
    document.getElementById('importStoreModal').style.display = 'none';
    _importStoreId = null;
    _importProducts = [];
}

async function confirmImportProducts() {
    const selectedIds = Array.from(document.querySelectorAll('.import-chk:checked')).map(c => c.value);
    if (!selectedIds.length || !_importStoreId) return;

    const status = document.getElementById('importStatus');
    const btn    = document.getElementById('importConfirmBtn');
    status.style.display = 'flex';
    btn.disabled = true;

    try {
        const res = await apiFetch(`/api/stores/${encodeURIComponent(_importStoreId)}/import`, { product_ids: selectedIds });
        closeImportModal();
        await loadProducts();
        navigateTo('urunlerim');
        alert(`${(res.imported || []).length} ürün başarıyla içe aktarıldı!`);
    } catch (err) {
        alert('Hata: ' + err.message);
    } finally {
        status.style.display = 'none';
        btn.disabled = false;
    }
}

async function deployActiveProduct() {
    const product = _activeDetailProduct;
    if (!product) return;
    if (!product.source_store_id) {
        alert('Bu ürün bir mağazadan içe aktarılmamış, deploy edilecek hedef mağaza bilinmiyor.');
        return;
    }
    const btn = document.getElementById('deployBtn');
    btn.disabled = true;
    btn.querySelector('span').textContent = 'Gönderiliyor...';
    try {
        await apiFetch(`/api/products/${encodeURIComponent(product.id)}/deploy`, { store_id: product.source_store_id });
        btn.querySelector('span').textContent = '✓ Mağazaya Gönderildi';
        btn.style.background = 'rgba(74,222,128,0.2)';
        btn.style.borderColor = '#4ade80';
        setTimeout(() => {
            btn.querySelector('span').textContent = 'Mağazaya Gönder';
            btn.style.background = '';
            btn.style.borderColor = '';
            btn.disabled = false;
        }, 3000);
    } catch (err) {
        alert('Deploy hatası: ' + err.message);
        btn.disabled = false;
        btn.querySelector('span').textContent = 'Mağazaya Gönder';
    }
}

// ── Kullanıcı Planı ───────────────────────────────────────────────────────────
const _tierLabels  = { free: 'Ücretsiz', pro: 'Pro', admin: 'Admin' };
const _tierClasses = {
    free:  'plan-badge',
    pro:   'plan-badge plan-badge-pro',
    admin: 'plan-badge plan-badge-admin',
};

async function fetchUserPlan() {
    const badge = document.getElementById('planBadge');
    if (!badge) return;
    try {
        const data = await apiFetch('/api/user/me', undefined, 'GET');
        const tier = data.data?.tier || 'free';
        badge.textContent = _tierLabels[tier] || tier;
        badge.className   = _tierClasses[tier] || 'plan-badge';
    } catch (_) {
        badge.textContent = 'Ücretsiz';
    }
}
