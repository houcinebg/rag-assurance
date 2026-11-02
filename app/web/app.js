function setQuestion(text) {
    document.getElementById('question').value = text;
}

async function submitQuestion() {
    const question = document.getElementById('question').value;
    if (!question) return alert("Veuillez poser une question.");

    const btn = document.getElementById('submit-btn');
    const resultSection = document.getElementById('result-section');

    btn.disabled = true;
    btn.innerText = "Analyse en cours...";

    try {
        const response = await fetch('/api/answer', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question: question, k: 6 })
        });

        const data = await response.json();

        if (data.error) {
            alert(data.error);
            return;
        }

        const badge = document.getElementById('verdict-badge');
        badge.className = 'badge ' + data.verdict;
        const labels = {
            'couvert': 'Couvert',
            'non_couvert': 'Non couvert',
            'ambigu': 'Pas de reponse ferme'
        };
        badge.innerText = labels[data.verdict] || data.verdict;

        document.getElementById('raisonnement').innerText = data.raisonnement;

        const missingContainer = document.getElementById('missing-info-container');
        const missingList = document.getElementById('infos-manquantes');
        missingList.innerHTML = '';
        if (data.infos_manquantes && data.infos_manquantes.length > 0) {
            data.infos_manquantes.forEach(info => {
                const li = document.createElement('li');
                li.innerText = info;
                missingList.appendChild(li);
            });
            missingContainer.classList.remove('hidden');
        } else {
            missingContainer.classList.add('hidden');
        }

        const citationsContainer = document.getElementById('citations');
        citationsContainer.innerHTML = '';
        if (data.citations && data.citations.length > 0) {
            data.citations.forEach(cit => {
                const div = document.createElement('div');
                div.className = 'citation';
                div.innerHTML = '<div class="article-ref"><span>' + cit.article + '</span><span class="verified-badge">&#10003; Verifie mot pour mot</span></div><div class="extrait">"' + cit.extrait + '"</div>';
                citationsContainer.appendChild(div);
            });
        } else {
            citationsContainer.innerHTML = '<p>Aucune clause citee.</p>';
        }

        document.getElementById('tech-content').innerText = JSON.stringify({
            garde_fou: data.garde_fou,
            sources: data.sources,
            requete_etendue: data.requete_etendue
        }, null, 2);

        resultSection.classList.remove('hidden');

    } catch (e) {
        alert("Erreur: " + e.message);
    } finally {
        btn.disabled = false;
        btn.innerText = "Analyser";
    }
}
