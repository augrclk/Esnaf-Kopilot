// Global state: analiz sonucu chat'te context olarak kullanılır
let analysisContext = null;

document.addEventListener('DOMContentLoaded', () => {
    const analyzeBtn = document.getElementById('analyzeBtn');
    const urlInput = document.getElementById('urlInput');
    const statusBar = document.getElementById('statusBar');
    const resultsSection = document.getElementById('resultsSection');
    
    const origTitle = document.getElementById('origTitle');
    const seoScore = document.getElementById('seoScore');
    const newTitle = document.getElementById('newTitle');
    const newDescription = document.getElementById('newDescription');
    const keywordList = document.getElementById('keywordList');
    const strategyNote = document.getElementById('strategyNote');
    const imageGallery = document.getElementById('imageGallery');

    // Enter tuşuyla analiz başlat
    urlInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') analyzeBtn.click();
    });

    analyzeBtn.addEventListener('click', async () => {
        const url = urlInput.value.trim();
        if (!url) {
            alert('Lütfen bir Trendyol linki girin!');
            return;
        }

        // Reset
        resultsSection.style.display = 'none';
        statusBar.style.display = 'flex';
        analyzeBtn.disabled = true;
        analyzeBtn.style.opacity = '0.5';
        document.getElementById('chatMessages').innerHTML = '';
        analysisContext = null;

        try {
            const response = await fetch('http://localhost:8000/api/analyze', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: url, max_review_pages: 1 })
            });

            if (!response.ok) {
                const errData = await response.json().catch(() => ({}));
                throw new Error('API Hatası: ' + response.status + ' — ' + (errData.detail || ''));
            }

            const resData = await response.json();
            const data = resData.data;

            // Context'i sakla (chat için)
            analysisContext = data;

            // ── Önce / Sonra Karşılaştırma ──────────────────────────────
            const currentScore = data.content_analysis.score;
            const projectedScore = Math.min(100, currentScore + Math.round((100 - currentScore) * 0.72));

            document.getElementById('origTitle').textContent = data.product.original_title;
            document.getElementById('newTitle').textContent = data.content_analysis.new_title;
            document.getElementById('origDescription').textContent =
                data.product.original_description || '(Açıklama bulunamadı)';
            document.getElementById('newDescription').textContent =
                data.content_analysis.new_description;

            // Animasyonlu skor halkaları
            animateScoreRing('scoreBefore', 'ringFillBefore', currentScore, false);
            animateScoreRing('scoreAfter', 'ringFillAfter', projectedScore, true);

            // ── Anahtar Kelimeler ──────────────────────────────────────
            keywordList.innerHTML = '';
            (data.content_analysis.keywords || []).forEach(kw => {
                const span = document.createElement('span');
                span.className = 'keyword-tag';
                span.textContent = kw;
                keywordList.appendChild(span);
            });

            // ── Yorum Analizi ───────────────────────────────────────
            renderReviewAnalysis(data.review_analysis);

            // ── Görsel Strateji ─────────────────────────────────────
            const imgData = data.images && data.images.length > 0 ? data.images[0] : null;
            strategyNote.textContent = imgData ? (imgData.strategy_note || 'Strateji notu yok.') : 'Görsel üretilemedi.';

            // ── Görseller ───────────────────────────────────────────
            imageGallery.innerHTML = '';
            if (imgData && imgData.enhanced) {
                imgData.enhanced.forEach((img, index) => {
                    const imgUrl = 'http://localhost:8000/' + img.path;
                    const card = document.createElement('div');
                    card.className = 'concept-card';
                    card.innerHTML = `
                        <div class="concept-img-wrapper">
                            <img src="${imgUrl}" alt="Konsept ${index + 1}" 
                                 onerror="this.src='https://placehold.co/400x400/1a1a2e/6c63ff?text=Üretiliyor...'">
                        </div>
                        <div class="concept-info">
                            <span class="concept-tag">Konsept ${index + 1}</span>
                            <h4 class="concept-name">${img.concept}</h4>
                        </div>
                    `;
                    imageGallery.appendChild(card);
                });
            }

            resultsSection.style.display = 'block';
            resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });

        } catch (error) {
            console.error(error);
            alert('Analiz sırasında bir hata oluştu. Lütfen konsolu kontrol edin.\n\n' + error.message);
        } finally {
            statusBar.style.display = 'none';
            analyzeBtn.disabled = false;
            analyzeBtn.style.opacity = '1';
        }
    });
});

// ── Animasyonlu Skor Halkası ──────────────────────────────────────────────

function animateScoreRing(numberId, ringId, targetScore, isAfter) {
    const numberEl = document.getElementById(numberId);
    const ringEl = document.getElementById(ringId);
    if (!numberEl || !ringEl) return;

    const circumference = 2 * Math.PI * 32; // r=32
    ringEl.style.strokeDasharray = circumference;
    ringEl.style.strokeDashoffset = circumference;

    let current = 0;
    const duration = 1200;
    const startTime = performance.now();

    function step(now) {
        const elapsed = now - startTime;
        const progress = Math.min(elapsed / duration, 1);
        const eased = 1 - Math.pow(1 - progress, 3); // ease-out cubic
        current = Math.round(targetScore * eased);
        numberEl.textContent = current;
        const offset = circumference - (current / 100) * circumference;
        ringEl.style.strokeDashoffset = offset;
        if (progress < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
}

// ── Yorum Analizi Render ────────────────────────────────────────────────────

function renderReviewAnalysis(ra) {
    if (!ra) return;

    const sentimentEl = document.getElementById('reviewSentimentSummary');
    const badgeEl = document.getElementById('reviewCountBadge');
    const posListEl = document.getElementById('positivesList');
    const negListEl = document.getElementById('negativesList');
    const unansweredSection = document.getElementById('unansweredQuestionsSection');
    const unansweredListEl = document.getElementById('unansweredList');

    sentimentEl.textContent = ra.sentiment_summary || '';
    badgeEl.textContent = ra.total_reviews ? `${ra.total_reviews} yorum • Ort. ${(ra.avg_rating || 0).toFixed(1)}/5` : '';

    posListEl.innerHTML = '';
    (ra.positives || []).forEach(p => {
        const li = document.createElement('li');
        li.className = 'review-item positive-item';
        li.innerHTML = `<strong>${p.title}</strong><span>${p.detail}</span>`;
        posListEl.appendChild(li);
    });

    negListEl.innerHTML = '';
    (ra.negatives || []).forEach(n => {
        const li = document.createElement('li');
        li.className = 'review-item negative-item';
        li.innerHTML = `<strong>${n.title}</strong><span>${n.detail}</span>`;
        negListEl.appendChild(li);
    });

    if (ra.unanswered_questions && ra.unanswered_questions.length > 0) {
        unansweredSection.style.display = 'block';
        unansweredListEl.innerHTML = '';
        ra.unanswered_questions.forEach(q => {
            const li = document.createElement('li');
            li.className = 'unanswered-item';
            li.innerHTML = `<i class="fa-solid fa-circle-question"></i> ${q}`;
            unansweredListEl.appendChild(li);
        });
    } else {
        unansweredSection.style.display = 'none';
    }
}

// ── AI Chat ─────────────────────────────────────────────────────────────────

function askQuestion(question) {
    document.getElementById('chatInput').value = question;
    sendChat();
}

async function sendChat() {
    const input = document.getElementById('chatInput');
    const messagesEl = document.getElementById('chatMessages');
    const sendBtn = document.getElementById('chatSendBtn');
    const message = input.value.trim();

    if (!message) return;
    if (!analysisContext) {
        alert('Önce bir analiz yapmanız gerekiyor.');
        return;
    }

    // Kullanıcı mesajını göster
    appendMessage(messagesEl, 'user', message);
    input.value = '';
    sendBtn.disabled = true;

    // "Yazıyor..." göster
    const typingId = appendTyping(messagesEl);

    try {
        const response = await fetch('http://localhost:8000/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: message,
                analysis_context: analysisContext
            })
        });

        const data = await response.json();
        removeTyping(messagesEl, typingId);

        if (data.status === 'success') {
            appendMessage(messagesEl, 'ai', data.answer);
        } else {
            appendMessage(messagesEl, 'ai', 'Bir hata oluştu: ' + (data.detail || 'Bilinmeyen hata'));
        }
    } catch (err) {
        removeTyping(messagesEl, typingId);
        appendMessage(messagesEl, 'ai', 'Bağlantı hatası: ' + err.message);
    } finally {
        sendBtn.disabled = false;
    }
}

// Chat input — Enter ile gönder
document.addEventListener('DOMContentLoaded', () => {
    const chatInput = document.getElementById('chatInput');
    if (chatInput) {
        chatInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendChat();
            }
        });
    }
});

function appendMessage(container, role, text) {
    const div = document.createElement('div');
    div.className = `chat-msg ${role === 'user' ? 'chat-msg-user' : 'chat-msg-ai'}`;
    
    const icon = role === 'user'
        ? '<i class="fa-solid fa-user"></i>'
        : '<i class="fa-solid fa-robot"></i>';

    // Satır sonlarını koruyarak display et
    const safeText = text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    const htmlText = safeText.replace(/\n/g, '<br>');

    div.innerHTML = `
        <div class="chat-msg-icon">${icon}</div>
        <div class="chat-msg-bubble">${htmlText}</div>
    `;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
    return div;
}

function appendTyping(container) {
    const id = 'typing-' + Date.now();
    const div = document.createElement('div');
    div.className = 'chat-msg chat-msg-ai';
    div.id = id;
    div.innerHTML = `
        <div class="chat-msg-icon"><i class="fa-solid fa-robot"></i></div>
        <div class="chat-msg-bubble typing-bubble">
            <span></span><span></span><span></span>
        </div>
    `;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
    return id;
}

function removeTyping(container, id) {
    const el = document.getElementById(id);
    if (el) el.remove();
}
