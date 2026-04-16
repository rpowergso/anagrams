let botIsThinking = false;
let countdownInterval = null;
let autoDrawMode = false; 

function setCountdown(ms) {
    const display = document.getElementById('countdown-display');
    if (!display) return;
    clearInterval(countdownInterval);
    if (ms <= 0) { display.innerText = "READY"; return; }
    let remaining = ms;
    countdownInterval = setInterval(() => {
        remaining -= 100;
        display.innerText = `NEXT DRAW: ${(remaining / 1000).toFixed(1)}s`;
        if (remaining <= 0) { clearInterval(countdownInterval); display.innerText = "DRAWING..."; }
    }, 100);
}

function toggleAutoDraw() {
    autoDrawMode = !autoDrawMode;
    const btn = document.getElementById('autoDrawBtn');
    if (btn) btn.innerText = `AUTODRAW: ${autoDrawMode ? 'ON' : 'OFF'}`;
    
    if (autoDrawMode) {
        botInterval = setInterval(botDrawTile, AUTODRAW_INTERVAL_MS);
        setCountdown(AUTODRAW_INTERVAL_MS);
    } else {
        clearInterval(botInterval);
        botInterval = null;
        setCountdown(0);
    }
}

async function startBot() {
    botRunning = true;
    if (typeof START_AUTODRAW_INITIALLY !== 'undefined' && START_AUTODRAW_INITIALLY === "on") {
        toggleAutoDraw(); 
    }
}

async function botDrawTile() {
    if (!botRunning) return;
    const data = await fetchTile();
    if (data.done) { 
        // No more tiles - bot tries to find one more word
        if (!botIsThinking) {
            requestBotMove(true); // Final attempt
        }
        return; 
    }
    activeTiles.push(data.tile);
    renderTiles();
    
    // Bot scans immediately when tile hits pool
    requestBotMove();
    
    if (autoDrawMode) {
        setCountdown(AUTODRAW_INTERVAL_MS);
    } else {
        clearInterval(botInterval);
        botInterval = null;
        setCountdown(0);
        const drawBtn = document.getElementById('playerDrawButton');
        if (drawBtn) drawBtn.disabled = false;
    }
}

async function drawTileForPlayer() {
    const data = await fetchTile();
    if (data.done) {
        // No more tiles - player tries to find one more word, then bot final attempt
        if (!botIsThinking && botRunning) {
            setTimeout(() => requestBotMove(true), 500); // Bot final attempt
        }
        return;
    }
    activeTiles.push(data.tile);
    renderTiles();
    botCancelId++; 

    if (!autoDrawMode) {
        const drawBtn = document.getElementById('playerDrawButton');
        if (drawBtn) drawBtn.disabled = true;
        setCountdown(AUTODRAW_INTERVAL_MS);
        setTimeout(botDrawTile, AUTODRAW_INTERVAL_MS);
    }
    
    // Keep focus on input
    const input = document.getElementById('playerWordInput');
    if (input) input.focus();
}

async function requestBotMove(isFinalAttempt = false) {
    if (botIsThinking || !botRunning) return;
    botIsThinking = true;
    const currentCancelId = botCancelId;
    
    const response = await fetchBotMove();
    
    // Safety check if state changed while waiting for fetch
    if (currentCancelId !== botCancelId || !botRunning) {
        botIsThinking = false;
        return;
    }

    if (response.found) {
        // --- DEBUG INFO ---
        console.group(`%cBot Move: ${response.word}`, "color: #e67e22; font-weight: bold;");
        console.log(`Delay: ${response.delay}s`);
        console.log(`Zipf Frequency: ${response.debug.chosen_freq}`);
        console.log(`Candidates considered: ${response.debug.considered_count}`);
        console.log("Top 15 words found by bot brain:");
        console.table(response.debug.top_candidates);
        console.groupEnd();
        // ------------------

        setTimeout(() => {
            if (currentCancelId === botCancelId && botRunning) {
                applyBotMove(response);
            }
            botIsThinking = false;
        }, response.delay * 1000);
    } else {
        // No move found
        if (isFinalAttempt) {
            endGameWithWinner();
        }
        botIsThinking = false;
    }
}

function endGameWithWinner() {
    stopBot('');
    
    const playerScore = parseInt(document.getElementById('playerTotalScore')?.innerText || 0);
    const botScore = parseInt(document.getElementById('botTotalScore')?.innerText || 0);
    
    let resultText = '';
    if (playerScore > botScore) {
        resultText = `🎉 YOU WIN! ${playerScore} - ${botScore}`;
    } else if (botScore > playerScore) {
        resultText = `🤖 BOT WINS! ${botScore} - ${playerScore}`;
    } else {
        resultText = `🤝 TIE GAME! ${playerScore} - ${botScore}`;
    }
    
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
        <div style="background: #1a252f; padding: 50px; border-radius: 20px; text-align: center; border: 3px solid #2ecc71;">
            <h1 style="font-size: 3rem; margin-bottom: 20px; letter-spacing: 2px;">${resultText}</h1>
            <div style="font-size: 1.3rem; margin-bottom: 40px; opacity: 0.8;">
                <div style="margin: 10px;">YOUR WORDS: ${playerWords.length}</div>
                <div style="margin: 10px;">BOT WORDS: ${botWords.length}</div>
            </div>
            <a href="/homepage" style="text-decoration: none;">
                <button class="btn btn-green" style="padding: 15px 40px; font-size: 1.2rem;">BACK TO HOME</button>
            </a>
        </div>
    `;
    
    document.body.appendChild(modal);
}

async function fetchBotMove() {
    const response = await fetch('/bot-move', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            activeTiles,
            boardWords: [...playerWords, ...botWords],
            difficulty: BOT_DIFFICULTY
        })
    });
    return await response.json();
}

function applyBotMove(move) {
    if (move.source_word) {
        const src = move.source_word.toUpperCase();
        // Remove from whichever list it was in
        playerWords = playerWords.filter(w => w.toUpperCase() !== src);
        botWords = botWords.filter(w => w.toUpperCase() !== src);
        setBotStatus(`Bot STOLE "${src}" to make "${move.word}"!`);
    } else {
        setBotStatus(`Bot played "${move.word}"`);
    }

    if (move.pool_letters) {
        move.pool_letters.forEach(l => {
            const i = activeTiles.findIndex(t => t.toUpperCase() === l.toUpperCase());
            if (i !== -1) activeTiles.splice(i, 1);
        });
    }
    botWords.push(move.word.toUpperCase());
    renderTiles(); 
    renderBotWords(); 
    renderPlayerWords(); 
    
    // Check for a combo play immediately
    setTimeout(requestBotMove, 500); 
}

function stopBot(msg) {
    botRunning = false;
    clearInterval(botInterval);
    clearInterval(countdownInterval);
    setBotStatus(msg);
}

function setBotStatus(msg) {
    const el = document.getElementById('botStatus');
    if (el) {
        el.innerText = msg;
        setTimeout(() => { if(el.innerText === msg) el.innerText = ''; }, 3500);
    }
}

async function checkPlayerWord() {
    const input = document.getElementById('playerWordInput');
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
            playerWords.push(word);
            renderTiles();
            renderPlayerWords();
            input.value = '';
            botCancelId++; 
            requestBotMove();
        }
    } else {
        const steal = await canStealWord(word, [...botWords, ...playerWords], activeTiles);
        if (steal) {
            const response = await fetch('/check-word', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ word })
            });
            const data = await response.json();
            if (data.valid) {
                const stolenUpper = steal.stolenWord.toUpperCase();
                playerWords = playerWords.filter(w => w.toUpperCase() !== stolenUpper);
                botWords = botWords.filter(w => w.toUpperCase() !== stolenUpper);
                
                activeTiles = steal.newActiveTiles;
                playerWords.push(word);
                renderTiles();
                renderPlayerWords();
                renderBotWords();
                input.value = '';
                botCancelId++;
                requestBotMove();
            }
        }
    }
}