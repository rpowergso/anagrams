const finderForm = document.getElementById('finderForm');
const finderInput = document.getElementById('finderInput');
const finderResults = document.getElementById('finderResults');
const finderStatus = document.getElementById('finderStatus');
const finderMore = document.getElementById('finderMore');
const chainMode = document.getElementById('chainMode');
const chainStep = document.getElementById('chainStep');
const chainPath = document.getElementById('chainPath');
const reverseMode = document.getElementById('reverseMode');
const forcedLetterRows = document.getElementById('forcedLetterRows');
const addForcedLetter = document.getElementById('addForcedLetter');
const forcedWordRows = document.getElementById('forcedWordRows');
const addForcedWord = document.getElementById('addForcedWord');
const toggleConstraints = document.getElementById('toggleConstraints');
const chainConstraints = document.getElementById('chainConstraints');
const findBiggest = document.getElementById('findBiggest');
let sourceLetters = '';
let shownThrough = 5;
let keepChainOnNextSearch = false;

function buildChainRow(path, number, total) {
    const chainTiles = document.createElement('div');
    chainTiles.className = 'chain-tiles';
    if (total > 1) {
        const numberLabel = document.createElement('span');
        numberLabel.className = 'chain-path-number';
        numberLabel.textContent = `${number}.`;
        chainTiles.appendChild(numberLabel);
    }
    path.forEach((word, index) => {
        if (index) {
            const arrow = document.createElement('span');
            arrow.className = 'chain-arrow';
            arrow.textContent = '→';
            chainTiles.appendChild(arrow);
        }
        const comparisonCounts = {};
        const comparisonWord = reverseMode.checked && index < path.length - 1
            ? path[index + 1]
            : (index ? path[index - 1] : '');
        for (const char of comparisonWord) comparisonCounts[char] = (comparisonCounts[char] || 0) + 1;
        const wordTiles = document.createElement('button');
        wordTiles.type = 'button';
        wordTiles.title = `Definition of ${word}`;
        wordTiles.setAttribute('aria-label', `Definition of ${word}`);
        wordTiles.addEventListener('click', () => selectWord(word));
        wordTiles.className = 'chain-word-tiles';
        for (const char of word) {
            const tile = document.createElement('span');
            tile.className = 'tile small';
            if (comparisonCounts[char] > 0) comparisonCounts[char]--;
            else if (reverseMode.checked && index < path.length - 1) tile.classList.add('removed');
            else if (!reverseMode.checked && index) tile.classList.add('added');
            tile.textContent = char;
            wordTiles.appendChild(tile);
        }
        chainTiles.appendChild(wordTiles);
    });
    return chainTiles;
}

let visibleChainPaths = [];
let visibleChainIndex = 0;

function renderVisibleChain() {
    chainPath.innerHTML = '';
    const paths = visibleChainPaths;
    const path = paths[visibleChainIndex];
    const title = document.createElement('div');
    title.className = 'chain-title';
    title.textContent = `CHAIN ${visibleChainIndex + 1} OF ${paths.length} FROM ${path[0]}`;
    chainPath.appendChild(title);
    chainPath.appendChild(buildChainRow(path, 1, 1));
    if (paths.length > 1) {
        const controls = document.createElement('div');
        controls.id = 'chainPathControls';
        const previous = document.createElement('button');
        previous.className = 'btn btn-blue';
        previous.textContent = 'PREVIOUS';
        previous.disabled = visibleChainIndex === 0;
        previous.onclick = () => { visibleChainIndex--; renderVisibleChain(); };
        const next = document.createElement('button');
        next.className = 'btn btn-blue';
        next.textContent = 'NEXT';
        next.disabled = visibleChainIndex === paths.length - 1;
        next.onclick = () => { visibleChainIndex++; renderVisibleChain(); };
        controls.append(previous, next);
        chainPath.appendChild(controls);
    }
    chainPath.hidden = false;
    chainPath.scrollIntoView({behavior: 'smooth', block: 'nearest'});
}

function showChain(paths) {
    visibleChainPaths = paths;
    visibleChainIndex = 0;
    renderVisibleChain();
}

function getForcedLetters() {
    const constraints = {};
    forcedLetterRows.querySelectorAll('.forced-letter-row').forEach(row => {
        const step = Number.parseInt(row.querySelector('.forced-step').value, 10);
        const letters = row.querySelector('.forced-letters').value.trim().toUpperCase();
        if (step > 0 && letters) constraints[step] = (constraints[step] || '') + letters;
    });
    return constraints;
}

function getForcedWords() {
    return [...forcedWordRows.querySelectorAll('.forced-word')]
        .map(input => input.value.trim().toUpperCase())
        .filter(Boolean);
}

function buildWord(word, paths) {
    const available = {};
    for (const char of sourceLetters) available[char] = (available[char] || 0) + 1;
    const block = document.createElement('button');
    block.type = 'button';
    block.className = 'finder-word';
    if (paths && paths.length) block.classList.add('has-chain');
    block.title = `Find words from ${word} and show its definition`;
    block.setAttribute('aria-label', `Find words from ${word} and show its definition`);
    block.addEventListener('click', () => selectWord(word, paths));
    for (const char of word) {
        const tile = document.createElement('span');
        tile.className = 'tile small';
        if (available[char] > 0) available[char]--;
        else tile.classList.add('added');
        tile.textContent = char;
        block.appendChild(tile);
    }
    if (reverseMode.checked) {
        const tag = document.createElement('span');
        tag.className = 'removed-tag';
        tag.textContent = `−${sourceLetters.length - word.length}`;
        block.appendChild(tag);
    }
    return block;
}

function appendGroups(groups) {
    for (const group of groups) {
        const section = document.createElement('section');
        section.className = 'result-group';
        const heading = document.createElement('h2');
        const direction = reverseMode.checked ? '−' : '+';
        heading.textContent = `${direction}${group.added} LETTER${group.added === 1 ? '' : 'S'} — ${group.total} WORD${group.total === 1 ? '' : 'S'}`;
        section.appendChild(heading);
        const words = document.createElement('div');
        words.className = 'finder-words';
        group.words.forEach(word => words.appendChild(buildWord(word, group.chains[word])));
        if (!group.words.length) words.textContent = 'No matches.';
        section.appendChild(words);
        if (group.total > group.words.length) {
            const note = document.createElement('p');
            note.textContent = `Showing the ${group.words.length} most common results.`;
            note.style.opacity = '.65';
            section.appendChild(note);
        }
        finderResults.appendChild(section);
    }
}

async function loadRange(minAdded, maxAdded, biggestOnly = false) {
    finderStatus.textContent = 'Searching…';
    finderMore.disabled = true;
    try {
        const response = await fetch('/word-extensions', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                letters: sourceLetters,
                minAdded,
                maxAdded,
                chainMode: chainMode.checked,
                chainStep: Number(chainStep.value),
                reverseMode: reverseMode.checked,
                forcedLetters: getForcedLetters(),
                forcedWords: getForcedWords(),
                biggestOnly
            })
        });
        const responseText = await response.text();
        let data;
        try {
            data = JSON.parse(responseText);
        } catch (_error) {
            throw new Error(response.ok
                ? 'The search returned an invalid response. Please try again.'
                : `The search service is temporarily unavailable (${response.status}). Please try again.`);
        }
        if (!response.ok) throw new Error(data.error || 'Search failed.');
        appendGroups(data.groups);
        if (biggestOnly && !data.groups.length) {
            finderStatus.textContent = 'No chain satisfies those constraints.';
        } else {
            finderStatus.textContent = '';
        }
        if (biggestOnly && data.groups.length) {
            const word = data.groups[0].words[0];
            const paths = data.groups[0].chains[word];
            if (paths && paths.length) showChain(paths);
        }
        shownThrough = maxAdded;
        const maximum = reverseMode.checked ? sourceLetters.length - 3 : 15 - sourceLetters.length;
        finderMore.hidden = shownThrough >= maximum;
        finderMore.textContent = `SHOW ${reverseMode.checked ? '−' : '+'}${shownThrough + 1} LETTER WORDS`;
    } catch (error) {
        finderStatus.textContent = error.message;
    } finally {
        finderMore.disabled = false;
    }
}

finderForm.addEventListener('submit', async event => {
    event.preventDefault();
    sourceLetters = finderInput.value.trim().toUpperCase();
    finderResults.innerHTML = '';
    if (keepChainOnNextSearch) keepChainOnNextSearch = false;
    else chainPath.hidden = true;
    const maximum = reverseMode.checked ? sourceLetters.length - 3 : 15 - sourceLetters.length;
    shownThrough = Math.min(5, maximum);
    if (!/^[A-Z]+$/.test(sourceLetters) || sourceLetters.length > 15) {
        finderStatus.textContent = 'Enter 1–15 letters (A–Z only).';
        finderMore.hidden = true;
        return;
    }
    const wordPath = `/word-finder/${encodeURIComponent(sourceLetters.toLowerCase())}`;
    if (window.location.pathname !== wordPath) history.pushState({word: sourceLetters}, '', wordPath);
    showDefinition(sourceLetters);
    if (shownThrough < 1) {
        finderStatus.textContent = reverseMode.checked
            ? 'No shorter legal game words are possible.'
            : 'This word is already at the maximum game-word length.';
        finderMore.hidden = true;
        return;
    }
    await loadRange(1, shownThrough);
});

finderMore.addEventListener('click', () => loadRange(shownThrough + 1, shownThrough + 1));

chainMode.addEventListener('change', () => {
    finderResults.classList.toggle('chain-mode', chainMode.checked);
    updateChainAction();
    if (sourceLetters) finderForm.requestSubmit();
});

chainStep.addEventListener('change', () => {
    chainStep.value = Math.max(1, Number.parseInt(chainStep.value, 10) || 1);
    if (chainMode.checked && sourceLetters) finderForm.requestSubmit();
});

reverseMode.addEventListener('change', () => {
    chainPath.hidden = true;
    updateChainAction();
    if (sourceLetters) finderForm.requestSubmit();
});

function updateChainAction() {
    findBiggest.hidden = !chainMode.checked;
    findBiggest.textContent = reverseMode.checked ? 'FIND SMALLEST WORD' : 'FIND BIGGEST WORD';
}

findBiggest.addEventListener('click', async () => {
    sourceLetters = finderInput.value.trim().toUpperCase();
    if (!/^[A-Z]+$/.test(sourceLetters) || sourceLetters.length > 15) {
        finderStatus.textContent = 'Enter 1–15 letters (A–Z only).';
        return;
    }
    finderResults.innerHTML = '';
    chainPath.hidden = true;
    finderMore.hidden = true;
    const maximum = reverseMode.checked ? sourceLetters.length - 3 : 15 - sourceLetters.length;
    if (maximum < 1) {
        finderStatus.textContent = reverseMode.checked
            ? 'This is already the smallest possible game-word length.'
            : 'This word is already at the maximum length.';
        return;
    }
    await loadRange(1, maximum, true);
    finderMore.hidden = true;
});

addForcedLetter.addEventListener('click', () => {
    const row = document.createElement('div');
    row.className = 'forced-letter-row';
    row.innerHTML = '<label>STEP <input class="forced-step" type="number" min="1" value="1"></label><label>FORCE LETTERS <input class="forced-letters" maxlength="14" placeholder="e.g. ET"></label><button class="btn btn-leave" type="button">REMOVE</button>';
    row.querySelector('button').addEventListener('click', () => row.remove());
    forcedLetterRows.appendChild(row);
});

addForcedWord.addEventListener('click', () => {
    const row = document.createElement('div');
    row.className = 'forced-word-row';
    row.innerHTML = '<input class="forced-word" maxlength="15" placeholder="e.g. NATIVE"><button class="btn btn-leave" type="button">REMOVE</button>';
    row.querySelector('button').addEventListener('click', () => row.remove());
    forcedWordRows.appendChild(row);
});

toggleConstraints.addEventListener('click', () => {
    const opening = chainConstraints.hidden;
    chainConstraints.hidden = !opening;
    toggleConstraints.setAttribute('aria-expanded', String(opening));
    toggleConstraints.textContent = opening ? 'CLOSE CONSTRAINTS' : 'CONSTRAINTS';
});

const definitionPanel = document.getElementById('definitionPanel');
const definitionTitle = document.getElementById('definitionTitle');
const definitionBody = document.getElementById('definitionBody');
const definitionCache = new Map();
let definitionRequest = 0;
let definitionController;

function selectWord(word, paths) {
    if (chainMode.checked && paths?.length) {
        showChain(paths);
        keepChainOnNextSearch = true;
    }
    finderInput.value = word;
    finderForm.requestSubmit();
    window.scrollTo({top: 0, behavior: 'smooth'});
}

async function showDefinition(word) {
    const request = ++definitionRequest;
    definitionController?.abort();
    const controller = new AbortController();
    definitionController = controller;
    definitionTitle.textContent = word;
    definitionBody.textContent = 'Loading definition...';
    definitionPanel.hidden = false;
    const timeout = setTimeout(() => controller.abort(), 3000);
    try {
        let data = definitionCache.get(word);
        if (!data) {
            const response = await fetch(`/definition/${encodeURIComponent(word.toLowerCase())}`, {signal: controller.signal});
            if (!response.ok) throw new Error('Dictionary unavailable');
            data = await response.json();
            if (definitionCache.size >= 100) definitionCache.delete(definitionCache.keys().next().value);
            definitionCache.set(word, data);
        }
        if (request !== definitionRequest) return;
        const list = document.createElement('ol');
        for (const item of data.definitions || []) {
            const row = document.createElement('li');
            const label = document.createElement('strong');
            label.textContent = item.partOfSpeech ? `${item.partOfSpeech}: ` : '';
            row.append(label, document.createTextNode(item.definition));
            list.appendChild(row);
        }
        definitionBody.replaceChildren();
        if (data.isWord && list.children.length) definitionBody.appendChild(list);
        else definitionBody.textContent = `${word} is not a word.`;
    } catch (error) {
        if (request === definitionRequest) definitionBody.textContent = 'Definition unavailable right now.';
    } finally {
        clearTimeout(timeout);
    }
}

if (finderInput.value) finderForm.requestSubmit();

window.addEventListener('popstate', () => {
    const routeWord = decodeURIComponent(window.location.pathname.split('/').pop() || '').toUpperCase();
    if (/^[A-Z]{1,15}$/.test(routeWord)) {
        finderInput.value = routeWord;
        finderForm.requestSubmit();
    }
});
