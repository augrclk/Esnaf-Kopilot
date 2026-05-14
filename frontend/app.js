document.addEventListener('DOMContentLoaded', () => {
    const analyzeBtn = document.getElementById('analyzeBtn');
    const urlInput = document.getElementById('urlInput');
    const statusBar = document.getElementById('statusBar');
    const resultsSection = document.getElementById('resultsSection');
    
    // UI Elements
    const origTitle = document.getElementById('origTitle');
    const seoScore = document.getElementById('seoScore');
    const newTitle = document.getElementById('newTitle');
    const newDescription = document.getElementById('newDescription');
    const keywordList = document.getElementById('keywordList');
    const strategyNote = document.getElementById('strategyNote');
    const imageGallery = document.getElementById('imageGallery');

    analyzeBtn.addEventListener('click', async () => {
        const url = urlInput.value.trim();
        if(!url) {
            alert('Lütfen bir Trendyol linki girin!');
            return;
        }

        // Reset UI
        resultsSection.style.display = 'none';
        statusBar.style.display = 'flex';
        analyzeBtn.disabled = true;
        analyzeBtn.style.opacity = '0.5';

        try {
            const response = await fetch('http://localhost:8000/api/analyze', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: url, max_review_pages: 1 })
            });

            if (!response.ok) {
                throw new Error('API Hatası: ' + response.status);
            }

            const resData = await response.json();
            const data = resData.data;

            // Fill UI with Data
            origTitle.textContent = data.product.original_title;
            seoScore.textContent = data.content_analysis.score;
            newTitle.textContent = data.content_analysis.new_title;
            if (newDescription) {
                newDescription.textContent = data.content_analysis.new_description;
            }

            // Keywords
            keywordList.innerHTML = '';
            data.content_analysis.keywords.forEach(kw => {
                const span = document.createElement('span');
                span.className = 'keyword-tag';
                span.textContent = kw;
                keywordList.appendChild(span);
            });

            // Strategy
            strategyNote.textContent = data.images[0].strategy_note || "Strateji notu bulunamadı.";

            // Images
            imageGallery.innerHTML = '';
            data.images[0].enhanced.forEach((img, index) => {
                const imgUrl = 'http://localhost:8000/' + img.path; 

                const card = document.createElement('div');
                card.className = 'concept-card';
                card.innerHTML = `
                    <div class="concept-img-wrapper">
                        <img src="${imgUrl}" alt="Concept ${index + 1}" onerror="this.src='https://via.placeholder.com/400x400?text=Uretiliyor...'">
                    </div>
                    <div class="concept-info">
                        <span class="concept-tag">Konsept ${index + 1}</span>
                        <h4 class="concept-name">${img.concept}</h4>
                    </div>
                `;
                imageGallery.appendChild(card);
            });

            // Show Results
            resultsSection.style.display = 'block';

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
