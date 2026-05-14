document.addEventListener('DOMContentLoaded', () => {
    const analyzeBtn = document.getElementById('analyzeBtn');
    const urlInput = document.getElementById('urlInput');
    const statusBar = document.getElementById('statusBar');
    const resultsSection = document.getElementById('resultsSection');
    
    // UI Elements
    const origTitle = document.getElementById('origTitle');
    const seoScore = document.getElementById('seoScore');
    const newTitle = document.getElementById('newTitle');
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
            origTitle.textContent = data.scraped.product.title;
            seoScore.textContent = data.score.total_score;
            newTitle.textContent = data.content.new_title;

            // Keywords
            keywordList.innerHTML = '';
            data.content.suggested_keywords.forEach(kw => {
                const span = document.createElement('span');
                span.className = 'keyword-tag';
                span.textContent = kw;
                keywordList.appendChild(span);
            });

            // Strategy
            strategyNote.textContent = data.image_analyses[0].issues.analysis_note || "Strateji notu bulunamadı.";

            // Images
            imageGallery.innerHTML = '';
            data.generated_images.forEach((img, index) => {
                // img.local_path = "outputs_api_XXX/image_name.jpg"
                // Sunucudan (localhost:8000/outputs/...) çekeceğiz.
                // Klasör adını api.py "outputs_api_..." yapıyor. Fakat main.py sadece "outputs" u mount ediyor.
                // Buna dikkat! Eğer path "outputs_api..." ise bunu düzeltmemiz lazım veya backend'de mount yolunu düzeltmemiz lazım.
                // Şu an path'i backend'den gelen haliyle sunucu url'sine ekleyeceğiz.
                
                // NOT: Backend'de klasörü "/outputs" a mount ettik ama klasör adı dinamik ("outputs_test_...").
                // Bu yüzden basitçe resmi çekerken lokal yolunu frontendde dinamik ayarlayacağız.
                // Şimdilik demo olduğu için /outputs_api_XXX altındaki dosyayı okuyacak şekilde yapılandırdık.
                const imgUrl = 'http://localhost:8000/' + img.local_path; 

                const card = document.createElement('div');
                card.className = 'concept-card';
                card.innerHTML = `
                    <div class="concept-img-wrapper">
                        <img src="${imgUrl}" alt="Concept ${index + 1}" onerror="this.src='https://via.placeholder.com/400x400?text=Uretiliyor...'">
                    </div>
                    <div class="concept-info">
                        <span class="concept-tag">Konsept ${index + 1}</span>
                        <h4 class="concept-name">${img.concept_name}</h4>
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
