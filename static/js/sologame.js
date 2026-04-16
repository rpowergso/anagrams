let soloInterval = null;
let soloAutoDraw = false;
let countdownInterval = null;

function setSoloCountdown(ms) {
    const display = document.getElementById('solo-countdown');
    if (!display) return;
    clearInterval(countdownInterval);
    if (ms <= 0) { display.innerText = "READY"; return; }
    let remaining = ms;
    countdownInterval = setInterval(() => {
        remaining -= 100;
        display.innerText = `NEXT: ${(remaining / 1000).toFixed(1)}s`;
        if (remaining <= 0) clearInterval(countdownInterval);
    }, 100);
}

function toggleSoloAuto() {
    soloAutoDraw = !soloAutoDraw;
    const btn = document.getElementById('soloAutoBtn');
    if (btn) btn.innerText = `AUTODRAW: ${soloAutoDraw ? 'ON' : 'OFF'}`;
    if (soloAutoDraw) {
        soloInterval = setInterval(drawTile, AUTODRAW_INTERVAL_MS);
        setSoloCountdown(AUTODRAW_INTERVAL_MS);
    } else {
        clearInterval(soloInterval);
        setSoloCountdown(0);
    }
}

async function drawTile() {
    const data = await fetchTile();
    if (data.done) { 
        clearInterval(soloInterval); 
        const countdown = document.getElementById('solo-countdown');
        if (countdown) countdown.innerText = "DONE";
        return; 
    }
    activeTiles.push(data.tile);
    renderTiles();
    if (soloAutoDraw) setSoloCountdown(AUTODRAW_INTERVAL_MS);
}

async function checkWord() {
    const input = document.getElementById('wordInput');
    const resultEl = document.getElementById('result');
    const word = input.value.toUpperCase().trim();
    if (word.length < 3) return;

    if (canMakeWord(word, activeTiles)) {
        const response = await fetch('/check-word', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ word })
        });
        const data = await response.json();
        if (data.valid) {
            activeTiles = removeWordFromTiles(word, activeTiles);
            myWords.push(word);
            renderTiles();
            renderSoloWords(); // Uses function in gamefunctions.js
            input.value = '';
            if (resultEl) resultEl.innerText = "Valid!";
        }
    } else {
        const steal = await canStealWord(word, myWords, activeTiles);
        if (steal) {
            const response = await fetch('/check-word', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ word })
            });
            const data = await response.json();
            if (data.valid) {
                myWords = myWords.filter(w => w.toUpperCase() !== steal.stolenWord.toUpperCase());
                activeTiles = steal.newActiveTiles;
                myWords.push(word);
                renderTiles();
                renderSoloWords();
                input.value = '';
            }
        }
    }
}