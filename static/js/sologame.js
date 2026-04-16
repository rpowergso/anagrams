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
        if (countdown) countdown.innerText = "NO TILES LEFT";
        showSoloGameOver();
        return; 
    }
    activeTiles.push(data.tile);
    renderTiles();
    if (soloAutoDraw) setSoloCountdown(AUTODRAW_INTERVAL_MS);
}

function showSoloGameOver() {
    const score = parseInt(document.getElementById('playerTotalScore')?.innerText || 0);
    
    const modal = document.createElement('div');
    modal.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: rgba(0,0,0,0.8);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 9999;
    `;
    
    modal.innerHTML = `
        <div style="background: #1a252f; padding: 50px; border-radius: 20px; text-align: center; border: 3px solid #3498db;">
            <h1 style="font-size: 3rem; margin-bottom: 20px; letter-spacing: 2px;">GAME OVER</h1>
            <div style="font-size: 2rem; margin-bottom: 40px; color: #2ecc71; font-weight: bold;">
                FINAL SCORE: ${score}
            </div>
            <div style="font-size: 1.1rem; margin-bottom: 40px; opacity: 0.8;">
                Words Found: ${myWords.length}
            </div>
            <a href="/homepage" style="text-decoration: none;">
                <button class="btn btn-green" style="padding: 15px 40px; font-size: 1.2rem;">BACK TO HOME</button>
            </a>
        </div>
    `;
    
    document.body.appendChild(modal);
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

function confirmLeaveGame() {
    const modal = document.createElement('div');
    modal.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: rgba(0,0,0,0.8);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 10000;
    `;
    
    modal.innerHTML = `
        <div style="background: #1a252f; padding: 40px; border-radius: 20px; text-align: center; border: 3px solid #e74c3c; max-width: 400px;">
            <h1 style="font-size: 1.8rem; margin-bottom: 25px; letter-spacing: 2px;">LEAVE GAME?</h1>
            <p style="font-size: 1rem; opacity: 0.8; margin-bottom: 30px;">Are you sure you want to leave this game?</p>
            <div style="display: flex; gap: 15px; justify-content: center;">
                <button class="btn btn-leave" onclick="document.querySelector('div[style*=\\'z-index: 10000\\']').remove()" style="padding: 12px 30px;">CANCEL</button>
                <a href="/homepage" style="text-decoration: none;">
                    <button class="btn btn-green" style="padding: 12px 30px; background: #e74c3c;">LEAVE</button>
                </a>
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
}