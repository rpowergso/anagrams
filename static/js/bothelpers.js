function setBotStatus(message) {
    const status = document.getElementById('botStatus');
    if (status) status.innerText = message;
}

function setPlayerResult(message) {
    const result = document.getElementById('playerResult');
    if (result) result.innerText = message;
}

function renderTiles() {
    document.getElementById('tilePool').innerText = activeTiles.join(' ');
}

function renderPlayerWords() {
    renderWordsTo('playerWords', playerWords);
}

function renderBotWords() {
    renderWordsTo('botWords', botWords);
}

function updateTileCount() {
    const count = document.getElementById('tileCount');
    if (count) count.innerText = TILE_COUNT - tilesDrawn;
}

function disableDrawButtons() {
    const playerButton = document.getElementById('playerDrawButton');
    if (playerButton) playerButton.disabled = true;
    const botButton = document.getElementById('startBotButton');
    if (botButton) botButton.disabled = true;
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
    cancelBotPendingActions();
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
            body: JSON.stringify({ word })
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
            body: JSON.stringify({ word })
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