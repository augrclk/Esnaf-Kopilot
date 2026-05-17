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

// ── Ana Akış: Aşamalı Analiz (Phase 2 & 3 paralel) ──────────────────────────
async function startProgressiveAnalysis() {
    const url = document.getElementById('urlInput').value.trim();
    if (!url) { alert('Lütfen bir Trendyol linki girin!'); return; }

    resetUI();
    analysisContext = null;
    currentOutputDir = '';

    const analyzeBtn = document.getElementById('analyzeBtn');
    analyzeBtn.disabled = true;
    analyzeBtn.style.opacity = '0.5';

    try {
        // ─── FAZ 1: Scraping ─────────────────────────────────────────────────
        setStatus('🔍 Ürün sayfası çekiliyor...', [1]);
        const scrapeRes = await apiFetch('/api/phase/scrape', { url, max_review_pages: 5 });
        renderScrapePhase(scrapeRes.data);

        // ─── FAZ 2 + FAZ 3: PARALEL başlat ──────────────────────────────────
        // İkisi de sadece scrape cache'ine ihtiyaç duyuyor → aynı anda çalışabilir
        setStatus('🤖 İçerik analizi + 🎨 Görsel üretim — paralel çalışıyor...', [2, 3]);

        const analyzePromise = apiFetch('/api/phase/analyze', { url, max_review_pages: 5 })
            .then(res => {
                currentOutputDir = res.output_dir || '';
                analysisContext = res.data;
                renderAnalyzePhase(res.data);
                setStepDone(2);
            });

        const imagesPromise = streamImages(url);

        // İkisi de bitince status temizle
        await Promise.allSettled([analyzePromise, imagesPromise]);
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

function setStatus(msg, activePhases) {
    const bar  = document.getElementById('statusBar');
    const text = document.getElementById('statusText');
    bar.style.display = 'flex';
    text.textContent  = msg;

    // activePhases: number veya number[] — her ikisini de kabul et
    const active = Array.isArray(activePhases) ? activePhases : [activePhases];

    document.querySelectorAll('.phase-step').forEach((s, i) => {
        const phaseNum = i + 1;
        const isDone   = !active.includes(phaseNum) && Math.min(...active) > phaseNum;
        const isActive = active.includes(phaseNum);
        s.classList.toggle('active', isActive);
        s.classList.toggle('done',   isDone);
    });
}

function setStepDone(phaseNum) {
    const steps = document.querySelectorAll('.phase-step');
    const step  = steps[phaseNum - 1];
    if (step) {
        step.classList.remove('active');
        step.classList.add('done');
    }
}

function clearStatus() {
    document.getElementById('statusBar').style.display = 'none';
    document.querySelectorAll('.phase-step').forEach(s => {
        s.classList.remove('active');
        s.classList.add('done');
    });
}

async function apiFetch(path, body) {
    const res = await fetch('http://localhost:8000' + path, {
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
    renderGiftSuggestions(data.gift_suggestions);
    document.getElementById('phaseAnalysis').scrollIntoView({ behavior: 'smooth', block: 'start' });

    // Chat bölümünü de göster
    document.getElementById('phaseChatSection').style.display = 'block';
}


// ── FAZ 3: SSE stream ile anlık görsel ekleme ────────────────────────────────

async function streamImages(url) {
    const res = await fetch('http://localhost:8000/api/phase/images', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ url, output_dir: '', max_review_pages: 5 })
    });
    if (!res.ok) { console.error('Images stream error:', res.status); return; }

    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    let   buffer  = '';

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();
        for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            try { handleImageEvent(JSON.parse(line.slice(6))); } catch (_) {}
        }
    }
}

function handleImageEvent(event) {
    switch (event.type) {
        case 'start':  _initImagesSection(event.strategy_note, event.total); break;
        case 'image':  _appendImageCard(event.data);                         break;
        case 'retry': {
            const b = document.getElementById('imagesRetryBadge');
            if (b) b.style.display = 'flex';
            break;
        }
        case 'done':
            setStepDone(3);
            _finalizeImagesSection(event.count);
            break;
        case 'error':
            console.error('[Images]', event.message);
            break;
    }
}

function _initImagesSection(strategyNote, total) {
    const section = document.getElementById('phaseImages');
    section.style.display = 'block';
    const strategyEl = document.getElementById('strategyNote');
    if (strategyEl) strategyEl.textContent = strategyNote || 'Strateji oluşturuluyor...';

    // Retry badge — gizli başlar
    if (!document.getElementById('imagesRetryBadge')) {
        const badge = document.createElement('div');
        badge.id        = 'imagesRetryBadge';
        badge.className = 'analyzing-tag';
        badge.style.cssText = 'display:none; margin-top:0.5rem;';
        badge.innerHTML = `<span class="loader-pulse"></span> Bazı görseller yeniden deneniyor...`;
        strategyEl?.parentElement?.appendChild(badge);
    }
    const gallery = document.getElementById('imageGallery');
    if (gallery) gallery.innerHTML = '';
    section.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

let _imgN = 0;
function _appendImageCard(img) {
    const gallery = document.getElementById('imageGallery');
    if (!gallery) return;
    _imgN++;
    const card = document.createElement('div');
    card.className = 'concept-card fade-in';
    card.innerHTML = `
        <div class="concept-img-wrapper">
            <img src="http://localhost:8000/${img.path}" alt="${escHtml(img.concept)}"
                 onerror="this.src='https://placehold.co/400x400/1a1a2e/6c63ff?text=Y%C3%BCkleniyor...'">
        </div>
        <div class="concept-info">
            <span class="concept-tag">Konsept ${_imgN}</span>
            <h4 class="concept-name">${escHtml(img.concept)}</h4>
        </div>
    `;
    gallery.appendChild(card);
}

function _finalizeImagesSection(count) {
    const b = document.getElementById('imagesRetryBadge');
    if (b) b.style.display = 'none';
    if (count === 0) {
        const g = document.getElementById('imageGallery');
        if (g) g.innerHTML = '<p style="color:var(--text-muted);text-align:center">Görsel üretilemedi veya API kotası doldu.</p>';
    }
    _imgN = 0;
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

// ── Hediye Önerileri Render ───────────────────────────────────────────────────
function renderGiftSuggestions(gs) {
    if (!gs || !gs.suggestions || gs.suggestions.length === 0) return;

    const card = document.getElementById('giftSuggestionsCard');
    if (!card) return;
    card.style.display = 'block';

    const strategyEl = document.getElementById('giftStrategy');
    if (strategyEl) strategyEl.textContent = gs.gift_strategy || '';

    const typeLabels = { A: 'Sorun Çözücü', B: 'Kullanım Kolaylaştırıcı', C: 'Tamamlayıcı', D: 'Kişisel Dokunuş', E: 'Koruyucu' };
    const impactColors = { HIGH: '#4ade80', MEDIUM: '#facc15', LOW: '#9ca3af' };

    const listEl = document.getElementById('giftList');
    listEl.innerHTML = '';
    (gs.suggestions || []).forEach(s => {
        const color = impactColors[s.impact] || '#9ca3af';
        const item = document.createElement('div');
        item.style.cssText = 'margin-bottom:0.8rem; padding:0.9rem 1rem; border-radius:10px; background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.07);';
        item.innerHTML = `
            <div style="display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap;margin-bottom:0.4rem;">
                <strong style="font-size:0.95rem;">${escHtml(s.gift)}</strong>
                <span class="keyword-tag" style="font-size:0.7rem;padding:2px 8px;">${escHtml(typeLabels[s.type] || s.type)}</span>
                <span style="margin-left:auto;font-size:0.78rem;color:var(--text-muted);">${escHtml(s.estimated_cost)}</span>
                <span style="font-size:0.72rem;font-weight:600;color:${color};background:${color}22;padding:2px 7px;border-radius:20px;">${escHtml(s.impact)}</span>
            </div>
            <p style="font-size:0.83rem;color:var(--text-muted);margin:0 0 0.25rem;">${escHtml(s.why)}</p>
            ${s.bulk_note ? `<p style="font-size:0.78rem;color:var(--text-muted);margin:0;opacity:0.7;"><i class="fa-solid fa-boxes-stacked" style="font-size:0.7rem;margin-right:4px;"></i>${escHtml(s.bulk_note)}</p>` : ''}
        `;
        listEl.appendChild(item);
    });

    const packSection = document.getElementById('giftPackagingSection');
    const packList    = document.getElementById('giftPackagingList');
    if (gs.packaging_tips && gs.packaging_tips.length > 0) {
        packSection.style.display = 'block';
        packList.innerHTML = '';
        gs.packaging_tips.forEach(tip => {
            const li = document.createElement('li');
            li.className = 'unanswered-item';
            li.innerHTML = `<i class="fa-solid fa-box-open"></i> ${escHtml(tip)}`;
            packList.appendChild(li);
        });
    }

    const disclosureEl = document.getElementById('giftDisclosure');
    if (disclosureEl && gs.disclosure_strategy) {
        disclosureEl.textContent = '💡 ' + gs.disclosure_strategy;
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
        const res  = await apiFetch('/api/chat', { message, analysis_context: analysisContext });
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
