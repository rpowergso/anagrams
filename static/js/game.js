    function toggleAutoDraw() {
        if (autoDrawInterval) {
            clearInterval(autoDrawInterval);
            autoDrawInterval = null;
            document.getElementById('autoDrawButton').innerText = 'Autodraw: Off';
        } else {
            autoDrawInterval = setInterval(drawTile, AUTODRAW_INTERVAL_MS);
            document.getElementById('autoDrawButton').innerText = 'Autodraw: On';
        }
    }

    function renderTilesTo(elementId, tiles) {
        const element = document.getElementById(elementId);
        if (element) {
            element.innerText = tiles.join(' ');
        }
    }

    function renderWordsTo(elementId, words) {
        const element = document.getElementById(elementId);
        if (element) {
            element.innerText = words.length > 0 ? words.join(', ') : 'No words yet';
        }
    }

    function removeWordFromTiles(word, tiles) {
        const remaining = [...tiles];
        for (const letter of word.split('')) {
            const index = remaining.indexOf(letter);
            if (index !== -1) {
                remaining.splice(index, 1);
            }
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
                    if (fromPool === -1) {
                        existingLetters.length = 1; // ensure failure
                        break;
                    }
                    available.splice(fromPool, 1);
                }
            }
            if (existingLetters.length > 0) continue;
            const usedFromPool = activeTiles.length - available.length;
            if (usedFromPool < 1) continue;

            return { stolenWord: existingWord, newActiveTiles: available };
        }
        return null;
    }

    function renderTiles() {
        document.getElementById('tilePool').innerText = activeTiles.join(' ');
    }

    function renderWords() {
        document.getElementById('myWords').innerText = myWords.join(', ');
    }

    async function drawTile() {
        const response = await fetch('/get-tile');
        const data = await response.json();
        if (data.done) {
            document.getElementById('noMoreTiles').style.display = 'block';
            document.getElementById('drawButton').disabled = true;
            if (autoDrawInterval) {
                clearInterval(autoDrawInterval);
                autoDrawInterval = null;
                document.getElementById('autoDrawButton').innerText = 'Autodraw: Off';
                document.getElementById('autoDrawButton').disabled = true;
            }
            return;
        }
        tilesDrawn++;
        document.getElementById('tileCount').innerText = TILE_COUNT - tilesDrawn;
        activeTiles.push(data.tile);
        renderTiles();
    }

    async function checkWord() {
        const word = document.getElementById('wordInput').value.toUpperCase().trim();

        if (word.length < 3) {
            document.getElementById('result').innerText = 'Word must be at least 3 letters';
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
                const available = [...activeTiles];
                for (const letter of word.split('')) {
                    const index = available.indexOf(letter);
                    available.splice(index, 1);
                }
                activeTiles = available;
                myWords.push(word);
                renderTiles();
                renderWords();
                document.getElementById('wordInput').value = '';
                document.getElementById('result').innerText = 'Valid!';
            } else {
                document.getElementById('result').innerText = 'Not a word';
            }
            return;
        }

        const steal = await canStealWord(word, myWords, activeTiles);
        if (steal) {
            const response = await fetch('/check-word', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ word: word })
            });
            const data = await response.json();
            if (data.valid) {
                myWords = myWords.filter(w => w !== steal.stolenWord);
                activeTiles = steal.newActiveTiles;
                myWords.push(word);
                renderTiles();
                renderWords();
                document.getElementById('wordInput').value = '';
                document.getElementById('result').innerText = `Stole ${steal.stolenWord}!`;
            } else {
                document.getElementById('result').innerText = 'Not a word';
            }
            return;
        }

        document.getElementById('result').innerText = 'Tiles are not there';
    }