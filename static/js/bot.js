function setBotStatus(message) {
    const status = document.getElementById('botStatus');
    if (status) {
        status.innerText = message;
    }
}

function renderPlayerWords() {
    renderWordsTo('playerWords', playerWords);
}

function renderBotWords() {
    renderWordsTo('botWords', botWords);
}

function updateTileCount() {
    const count = document.getElementById('tileCount');
    if (count) {
        count.innerText = TILE_COUNT - tilesDrawn;
    }
}

function setPlayerResult(message) {
    const result = document.getElementById('playerResult');
    if (result) {
        result.innerText = message;
    }
}

function disableDrawButtons() {
    const playerButton = document.getElementById('playerDrawButton');
    if (playerButton) playerButton.disabled = true;
    const botButton = document.getElementById('startBotButton');
    if (botButton) botButton.disabled = true;
}

function clearBotTimers() {
    if (botInterval) {
        clearInterval(botInterval);
        botInterval = null;
    }
}

function stopBot(message) {
    botRunning = false;
    clearBotTimers();
    setBotStatus(message);
}

async function fetchTile() {
    const response = await fetch('/get-tile');
    const data = await response.json();
    if (data.done) {
        disableDrawButtons();
        setBotStatus('No more tiles to draw.');
        return { done: true };
    }

    tilesDrawn++;
    updateTileCount();
    return { done: false, tile: data.tile };
}

async function drawTileForPlayer() {
    const data = await fetchTile();
    if (data.done) {
        setPlayerResult('No more tiles to draw.');
        return;
    }
    activeTiles.push(data.tile);
    renderTiles();
    botCancelId++;
}

function cancelBotPendingActions() {
    botCancelId++;
}

    let isChecking = false;

async function checkPlayerWord() {
    if (isChecking) return;
    isChecking = true;

    const input = document.getElementById('playerWordInput');
    const word = input.value.toUpperCase().trim();

    if (word.length < 3) {
        setPlayerResult('Word must be at least 3 letters');
        isChecking = false;
        return;
    }

    if (canMakeWord(word, activeTiles)) {
        const response = await fetch('/check-word', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ word: word })
        });
        const data = await response.json();
        if (data.valid) {
            activeTiles = removeWordFromTiles(word, activeTiles);
            playerWords.push(word);
            renderTiles();
            renderPlayerWords();
            input.value = '';
            setPlayerResult('Valid!');
            cancelBotPendingActions();
        } else {
            setPlayerResult('Not a word');
        }
        isChecking = false;
        return;
    }

    const steal = await canStealWord(word, [...botWords, ...playerWords], activeTiles);
    if (steal) {
        const response = await fetch('/check-word', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ word: word })
        });
        const data = await response.json();
        if (data.valid) {
            const stolenUpper = steal.stolenWord.toUpperCase();
            if (botWords.map(w => w.toUpperCase()).includes(stolenUpper)) {
                botWords = botWords.filter(w => w.toUpperCase() !== stolenUpper);
            } else {
                playerWords = playerWords.filter(w => w.toUpperCase() !== stolenUpper);
            }
            activeTiles = steal.newActiveTiles;
            playerWords.push(word);
            renderTiles();
            renderPlayerWords();
            renderBotWords();
            input.value = '';
            setPlayerResult(`Stole ${steal.stolenWord}!`);
            cancelBotPendingActions();
        } else {
            setPlayerResult('Not a word');
        }
        isChecking = false;
        return;
    }

    setPlayerResult('Tiles are not there');
    isChecking = false;
}

async function startBot() {
    if (botRunning) return;
    botRunning = true;
    const button = document.getElementById('startBotButton');
    if (button) button.disabled = true;
    setBotStatus('Bot starting...');
    botInterval = setInterval(botCycle, AUTODRAW_INTERVAL_MS);
    await botCycle();
}

async function botCycle() {
    if (!botRunning || botBusy) return;
    botBusy = true;
    const cycleId = botCancelId;

    const data = await fetchTile();
    if (data.done) {
        stopBot('Bot finished: no more tiles.');
        botBusy = false;
        return;
    }

    activeTiles.push(data.tile);
    renderTiles();

    if (cycleId !== botCancelId) {
        botBusy = false;
        return;
    }

    const move = await fetchBotMove();
    if (cycleId !== botCancelId) {
        botBusy = false;
        return;
    }

    if (move.found) {
        setTimeout(() => {
            if (cycleId === botCancelId) {
                applyBotMove(move);
                renderTiles();
                renderBotWords();
                renderPlayerWords();
            }
        }, move.delay * 1000);
    }

    botBusy = false;
}

async function fetchBotMove() {
    const response = await fetch('/bot-move', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            activeTiles: activeTiles,
            boardWords: [...playerWords, ...botWords],
            difficulty: BOT_DIFFICULTY
        })
    });
    return await response.json();
}

function applyBotMove(move) {
    const word = move.word.toUpperCase();
    activeTiles = removeWordFromTiles(word, activeTiles);

    if (move.source_word) {
        const source = move.source_word.toUpperCase();
        if (playerWords.map(w => w.toUpperCase()).includes(source)) {
            playerWords = playerWords.filter(w => w.toUpperCase() !== source);
        } else {
            botWords = botWords.filter(w => w.toUpperCase() !== source);
        }
    }

    botWords.push(word);
}

document.addEventListener('DOMContentLoaded', () => {
    renderPlayerWords();
    renderBotWords();
    renderTiles();
    const input = document.getElementById('playerWordInput');
    if (input) {
        input.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                checkPlayerWord();
            }
        });
    }
});