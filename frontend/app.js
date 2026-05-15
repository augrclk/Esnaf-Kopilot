// ── Global State ─────────────────────────────────────────────────────────────
let analysisContext = null;  // Chat için
let currentOutputDir = '';   // Phase 2'den Phase 3'e aktarılır

// ── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    const analyzeBtn = document.getElementById('analyzeBtn');
    const urlInput   = document.getElementById('urlInput');

    urlInput.addEventListener('keydown', e => { if (e.key === 'Enter') analyzeBtn.click(); });
    analyzeBtn.addEventListener('click', () => startProgressiveAnalysis());

    // Chat input Enter
    const chatInput = document.getElementById('chatInput');
    if (chatInput) {
        chatInput.addEventListener('keydown', e => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
        });
    }
});

// ── Ana Akış: Aşamalı Analiz ─────────────────────────────────────────────────
async function startProgressiveAnalysis() {
    const url = document.getElementById('urlInput').value.trim();
    if (!url) { alert('Lütfen bir Trendyol linki girin!'); return; }

    // Temizle
    resetUI();
    analysisContext = null;
    currentOutputDir = '';

    const analyzeBtn = document.getElementById('analyzeBtn');
    analyzeBtn.disabled = true;
    analyzeBtn.style.opacity = '0.5';

    try {
        // ─── FAZ 1: Scraping ─────────────────────────────────────────────────
        setStatus('🔍 Ürün sayfası çekiliyor...', 1);
        const scrapeRes = await apiFetch('/api/phase/scrape', { url, max_review_pages: 5 });
        renderScrapePhase(scrapeRes.data);

        // ─── FAZ 2: İçerik + Yorum Analizi ──────────────────────────────────
        setStatus('🤖 İçerik analiz ediliyor, yeni başlık ve açıklama oluşturuluyor...', 2);
        const analyzeRes = await apiFetch('/api/phase/analyze', { url, max_review_pages: 5 });
        currentOutputDir = analyzeRes.output_dir || '';
        renderAnalyzePhase(analyzeRes.data);

        // Analiz bitti → chat için context güncelle
        analysisContext = analyzeRes.data;

        // ─── FAZ 3: Görsel Üretim ────────────────────────────────────────────
        setStatus('🎨 Görseller analiz ediliyor ve yeni versiyonları oluşturuluyor...', 3);
        const imagesRes = await apiFetch('/api/phase/images', {
            url,
            output_dir: currentOutputDir,
            max_review_pages: 5
        });
        renderImagesPhase(imagesRes.data);

        clearStatus();

    } catch (err) {
        console.error(err);
        clearStatus();
        alert('Bir hata oluştu:\n\n' + err.message);
    } finally {
        analyzeBtn.disabled = false;
        analyzeBtn.style.opacity = '1';
    }
}

// ── UI Yardımcıları ──────────────────────────────────────────────────────────

function resetUI() {
    // Tüm section'ları gizle
    document.getElementById('resultsSection').style.display = 'none';
    document.getElementById('phaseContent').style.display = 'none';
    document.getElementById('phaseAnalysis').style.display = 'none';
    document.getElementById('phaseImages').style.display = 'none';
    document.getElementById('phaseChatSection').style.display = 'none';
    document.getElementById('chatMessages').innerHTML = '';
}

function setStatus(msg, phase) {
    const bar = document.getElementById('statusBar');
    const text = document.getElementById('statusText');
    const steps = document.querySelectorAll('.phase-step');
    bar.style.display = 'flex';
    text.textContent = msg;
    steps.forEach((s, i) => {
        s.classList.toggle('active', i + 1 === phase);
        s.classList.toggle('done', i + 1 < phase);
    });
}

function clearStatus() {
    document.getElementById('statusBar').style.display = 'none';
    document.querySelectorAll('.phase-step').forEach(s => s.classList.add('done'));
}

async function apiFetch(path, body) {
    const res = await fetch('http://localhost:8000/api' + path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(`API Hatası (${res.status}): ${err.detail || 'Bilinmeyen hata'}`);
    }
    return res.json();
}

// ── FAZ 1 RENDER: Scrape Sonuçları ───────────────────────────────────────────
function renderScrapePhase(data) {
    document.getElementById('resultsSection').style.display = 'block';
    document.getElementById('phaseContent').style.display = 'block';

    // Başlık & Açıklama (orijinal)
    document.getElementById('origTitle').textContent     = data.product.title;
    document.getElementById('origDescription').textContent = data.product.description || '(Açıklama bulunamadı)';
    document.getElementById('newTitle').textContent      = '— analiz ediliyor...';
    document.getElementById('newDescription').textContent = '— analiz ediliyor...';

    // Skor halkalarını placeholder göster
    document.getElementById('scoreBefore').textContent = '—';
    document.getElementById('scoreAfter').textContent  = '—';

    // Yorum örnekleri
    const sampleEl = document.getElementById('reviewSampleList');
    sampleEl.innerHTML = '';
    (data.review_sample || []).forEach(r => {
        const li = document.createElement('li');
        li.className = 'review-sample-item';
        const stars = r.rating ? '⭐'.repeat(Math.round(r.rating)) : '?';
        li.innerHTML = `<span class="sample-stars">${stars}</span> ${escHtml(r.text)}`;
        sampleEl.appendChild(li);
    });

    // Yorum sayısı badge
    const badge = document.getElementById('reviewCountBadge');
    if (badge) badge.textContent = `${data.review_count} yorum`;

    document.getElementById('reviewSampleCard').style.display = 'block';
    document.getElementById('resultsSection').scrollIntoView({ behavior: 'smooth' });
}

// ── FAZ 2 RENDER: İçerik + Yorum Analizi ─────────────────────────────────────
function renderAnalyzePhase(data) {
    document.getElementById('phaseAnalysis').style.display = 'block';

    const ca = data.content_analysis;
    const currentScore   = ca.score;
    const projectedScore = Math.min(100, currentScore + Math.round((100 - currentScore) * 0.72));

    // Karşılaştırma
    document.getElementById('origTitle').textContent      = data.product.original_title;
    document.getElementById('newTitle').textContent       = ca.new_title;
    document.getElementById('origDescription').textContent = data.product.original_description || '(Açıklama bulunamadı)';
    document.getElementById('newDescription').textContent  = ca.new_description;

    animateScoreRing('scoreBefore', 'ringFillBefore', currentScore, false);
    animateScoreRing('scoreAfter',  'ringFillAfter',  projectedScore, true);

    // Anahtar kelimeler
    const kwList = document.getElementById('keywordList');
    kwList.innerHTML = '';
    (ca.keywords || []).forEach(kw => {
        const span = document.createElement('span');
        span.className = 'keyword-tag';
        span.textContent = kw;
        kwList.appendChild(span);
    });

    // Yorum analizi
    renderReviewAnalysis(data.review_analysis);
    document.getElementById('phaseAnalysis').scrollIntoView({ behavior: 'smooth', block: 'start' });

    // Chat bölümünü de göster
    document.getElementById('phaseChatSection').style.display = 'block';
}

// ── FAZ 3 RENDER: Görseller ───────────────────────────────────────────────────
function renderImagesPhase(data) {
    document.getElementById('phaseImages').style.display = 'block';

    const imgData = data.images && data.images.length > 0 ? data.images[0] : null;
    const strategyEl = document.getElementById('strategyNote');
    strategyEl.textContent = imgData ? (imgData.strategy_note || 'Strateji notu yok.') : 'Görsel üretilemedi.';

    const gallery = document.getElementById('imageGallery');
    gallery.innerHTML = '';
    if (imgData && imgData.enhanced) {
        imgData.enhanced.forEach((img, i) => {
            const imgUrl = 'http://localhost:8000/' + img.path;
            const card = document.createElement('div');
            card.className = 'concept-card fade-in';
            card.innerHTML = `
                <div class="concept-img-wrapper">
                    <img src="${imgUrl}" alt="Konsept ${i + 1}"
                         onerror="this.src='https://placehold.co/400x400/1a1a2e/6c63ff?text=Üretiliyor...'">
                </div>
                <div class="concept-info">
                    <span class="concept-tag">Konsept ${i + 1}</span>
                    <h4 class="concept-name">${escHtml(img.concept)}</h4>
                </div>
            `;
            gallery.appendChild(card);
        });
    } else {
        gallery.innerHTML = '<p style="color:var(--text-muted); text-align:center;">Görsel üretilemedi veya API kotası doldu.</p>';
    }

    document.getElementById('phaseImages').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ── Animasyonlu Skor Halkası ─────────────────────────────────────────────────
function animateScoreRing(numberId, ringId, targetScore, isAfter) {
    const numberEl = document.getElementById(numberId);
    const ringEl   = document.getElementById(ringId);
    if (!numberEl || !ringEl) return;

    const circumference = 2 * Math.PI * 32;
    ringEl.style.strokeDasharray  = circumference;
    ringEl.style.strokeDashoffset = circumference;

    const duration = 1200;
    const startTime = performance.now();

    function step(now) {
        const progress = Math.min((now - startTime) / duration, 1);
        const eased    = 1 - Math.pow(1 - progress, 3);
        const current  = Math.round(targetScore * eased);
        numberEl.textContent = current;
        ringEl.style.strokeDashoffset = circumference - (current / 100) * circumference;
        if (progress < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
}

// ── Yorum Analizi Render ──────────────────────────────────────────────────────
function renderReviewAnalysis(ra) {
    if (!ra) return;
    const sentimentEl = document.getElementById('reviewSentimentSummary');
    const posListEl   = document.getElementById('positivesList');
    const negListEl   = document.getElementById('negativesList');
    const unansweredSection = document.getElementById('unansweredQuestionsSection');
    const unansweredListEl  = document.getElementById('unansweredList');

    if (sentimentEl) sentimentEl.textContent = ra.sentiment_summary || '';

    posListEl.innerHTML = '';
    (ra.positives || []).forEach(p => {
        const li = document.createElement('li');
        li.className = 'review-item positive-item';
        li.innerHTML = `<strong>${escHtml(p.title)}</strong><span>${escHtml(p.detail)}</span>`;
        posListEl.appendChild(li);
    });

    negListEl.innerHTML = '';
    (ra.negatives || []).forEach(n => {
        const li = document.createElement('li');
        li.className = 'review-item negative-item';
        li.innerHTML = `<strong>${escHtml(n.title)}</strong><span>${escHtml(n.detail)}</span>`;
        negListEl.appendChild(li);
    });

    if (ra.unanswered_questions && ra.unanswered_questions.length > 0) {
        unansweredSection.style.display = 'block';
        unansweredListEl.innerHTML = '';
        ra.unanswered_questions.forEach(q => {
            const li = document.createElement('li');
            li.className = 'unanswered-item';
            li.innerHTML = `<i class="fa-solid fa-circle-question"></i> ${escHtml(q)}`;
            unansweredListEl.appendChild(li);
        });
    } else {
        if (unansweredSection) unansweredSection.style.display = 'none';
    }
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
    if (!analysisContext) { alert('Önce bir analiz yapmanız gerekiyor.'); return; }

    appendMessage(messagesEl, 'user', message);
    input.value = '';
    sendBtn.disabled = true;
    const typingId = appendTyping(messagesEl);

    try {
        const res  = await apiFetch('/chat', { message, analysis_context: analysisContext });
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
