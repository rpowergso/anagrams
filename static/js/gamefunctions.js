function getWordScore(word) {
    if (!word || word.length < 3) return 0;
    return word.length - 2; 
}

function updateTileCount() {
    const el = document.getElementById('tileCount');
    if (el) el.innerText = TILE_COUNT - tilesDrawn;
}

async function fetchTile() {
    const response = await fetch('/get-tile');
    const data = await response.json();
    if (!data.done) {
        tilesDrawn++;
        updateTileCount();
    }
    return data;
}

function renderTiles() {
    const container = document.getElementById('tilePool');
    if (!container) return;
    container.innerHTML = '';
    activeTiles.forEach(letter => {
        const div = document.createElement('div');
        div.className = 'tile pool-tile'; 
        div.innerText = letter;
        container.appendChild(div);
    });
}

function renderWordsTo(elementId, words, scoreElementId) {
    const container = document.getElementById(elementId);
    const scoreDisplay = document.getElementById(scoreElementId);
    if (!container) return;
    container.innerHTML = ''; // Clear container
    
    let totalScore = 0;
    words.forEach(word => {
        const score = getWordScore(word);
        totalScore += score;
        
        const block = document.createElement('div');
        block.className = 'word-block';
        
        word.split('').forEach(char => {
            const t = document.createElement('div');
            t.className = 'tile small';
            t.innerText = char;
            block.appendChild(t);
        });

        const tag = document.createElement('span');
        tag.className = 'word-score-tag';
        tag.innerText = score;
        block.appendChild(tag);

        container.appendChild(block);
    });
    if (scoreDisplay) scoreDisplay.innerText = totalScore;
}

function renderPlayerWords() { renderWordsTo('playerWords', playerWords, 'playerTotalScore'); }
function renderBotWords() { renderWordsTo('botWords', botWords, 'botTotalScore'); }
function renderSoloWords() { renderWordsTo('myWords', myWords, 'playerTotalScore'); }

function removeWordFromTiles(word, tiles) {
    const remaining = [...tiles];
    for (const letter of word.split('')) {
        const index = remaining.indexOf(letter);
        if (index !== -1) remaining.splice(index, 1);
    }
    return remaining;
}

function canMakeWord(word, tiles) {
    const available = [...tiles];
    for (const letter of word.split('')) {
        const index = available.indexOf(letter);
        if (index === -1) return false;
        available.splice(index, 1);
    }
    return true;
}

async function canStealWord(word, boardWords, activeTiles) {
    for (const existingWord of boardWords) {
        const combined = [...existingWord.split(''), ...activeTiles];
        if (!canMakeWord(word, combined)) continue;
        if (word.length === existingWord.length + 1 && word.endsWith('S') && word.slice(0, -1) === existingWord) continue;

        const stemResponse = await fetch('/check-stem', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ word1: word, word2: existingWord })
        });
        const stemData = await stemResponse.json();
        if (stemData.same_root) continue;

        const existingLetters = existingWord.split('');
        const available = [...activeTiles];
        for (const letter of word.split('')) {
            const fromExisting = existingLetters.indexOf(letter);
            if (fromExisting !== -1) {
                existingLetters.splice(fromExisting, 1);
            } else {
                const fromPool = available.indexOf(letter);
                if (fromPool === -1) { existingLetters.length = 1; break; }
                available.splice(fromPool, 1);
            }
        }
        if (existingLetters.length > 0) continue;
        if ((activeTiles.length - available.length) < 1) continue;
        return { stolenWord: existingWord, newActiveTiles: available };
    }
    return null;
}