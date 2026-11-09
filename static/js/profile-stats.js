(() => {
    const queueKey = 'anagramsProfileProgress';
    const cosmeticKey = 'anagramsLetterCosmetics';
    const letterChoicesKey = 'anagramsLetterColorChoices';
    const signedIn = document.body.dataset.profileSignedIn === 'true';
    const ranks = [
        { name: 'Default', minimum: 0, color: '' },
        { name: 'Green', minimum: 50, color: '#66dfad' },
        { name: 'Blue', minimum: 150, color: '#75c5ff' },
        { name: 'Purple', minimum: 500, color: '#cb9cf3' },
        { name: 'Gold', minimum: 1000, color: '#ffd36a' },
        { name: 'Ruby', minimum: 2500, color: '#ff8796' }
    ];
    const emptyStats = () => ({ letters: {}, words: 0, games: 0, wins: 0, puzzles: 0, solved: 0 });
    function readPreference(storage, key, fallback) {
        try {
            return JSON.parse(storage.getItem(key)) ?? fallback;
        } catch {
            return fallback;
        }
    }

    function storePreference(storage, key, value) {
        try {
            storage.setItem(key, JSON.stringify(value));
        } catch {
            // Progress remains usable in memory when browser storage is unavailable.
        }
    }

    let pending = readPreference(sessionStorage, queueKey, []);
    let saved = emptyStats();
    let syncing = false;
    let loaded = !signedIn;
    let syncFailed = false;
    let selectedLetter = 'A';
    const letterChoices = readPreference(localStorage, letterChoicesKey, {});
    let cosmeticsEnabled = readPreference(localStorage, cosmeticKey, true);

    function totals() {
        const stats = { ...saved, letters: { ...saved.letters } };
        for (const { word, result } of pending) {
            if (word) stats.words++;
            for (const letter of word || '') stats.letters[letter] = (stats.letters[letter] || 0) + 1;
            if (result === 'game' || result === 'win') stats.games++;
            if (result === 'win') stats.wins++;
            if (result === 'puzzle' || result === 'solve') stats.puzzles++;
            if (result === 'solve') stats.solved++;
        }
        return stats;
    }

    function rankFor(count) {
        return ranks.reduce((current, rank) => count >= rank.minimum ? rank : current);
    }

    function paintTile(tile, stats) {
        const letter = tile.dataset.profileLetter;
        const count = stats.letters[letter] || 0;
        const chosen = ranks.find(rank => rank.name === letterChoices[letter] && count >= rank.minimum);
        const color = cosmeticsEnabled ? (chosen || rankFor(count)).color : '';
        tile.style.setProperty('--profile-letter-color', color);
    }

    function render() {
        const stats = totals();
        document.querySelectorAll('[data-profile-stat]').forEach(element => {
            element.textContent = loaded ? stats[element.dataset.profileStat] : '…';
        });
        document.querySelectorAll('[data-profile-letter]').forEach(tile => paintTile(tile, stats));
        document.querySelectorAll('[data-letter-detail]').forEach(button => {
            const letter = button.dataset.letterDetail;
            const count = stats.letters[letter] || 0;
            button.style.setProperty('--profile-letter-color', rankFor(count).color);
            button.setAttribute('aria-pressed', String(letter === selectedLetter));
        });
        const detail = document.getElementById('letter-rank-detail');
        if (detail) {
            const count = stats.letters[selectedLetter] || 0;
            const rank = rankFor(count);
            const next = ranks.find(item => item.minimum > count);
            detail.textContent = !loaded ? 'Loading saved progress…' : next
                ? `${selectedLetter} · ${count} uses · ${rank.name}. ${next.minimum - count} more to ${next.name}.`
                : `${selectedLetter} · ${count} uses · ${rank.name}, highest rank.`;
            const picker = document.getElementById('letter-color-choice');
            const unlocked = ranks.filter(item => count >= item.minimum);
            picker.replaceChildren(new Option('Auto (highest unlocked)', 'auto'),
                ...unlocked.map(item => new Option(item.name, item.name)));
            picker.value = unlocked.some(item => item.name === letterChoices[selectedLetter])
                ? letterChoices[selectedLetter] : 'auto';
            picker.disabled = !loaded;
        }
        document.querySelectorAll('[data-profile-sync-error]').forEach(element => {
            element.hidden = !syncFailed;
        });
    }

    async function sync() {
        if (!signedIn || syncing) return;
        syncing = true;
        try {
            do {
                const batch = pending.slice(0, 100);
                const response = await fetch('/api/profile/stats', batch.length ? {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(batch),
                    keepalive: true
                } : {});
                if (!response.ok) throw new Error('Unable to sync stats');
                saved = await response.json();
                pending.splice(0, batch.length);
                storePreference(sessionStorage, queueKey, pending);
                loaded = true;
                syncFailed = false;
                render();
            } while (pending.length);
        } catch {
            syncFailed = true;
            render();
        } finally {
            syncing = false;
        }
    }

    window.anagramsProgress = {
        record({ word, result }) {
            if (word && !/^[A-Z]{3,30}$/.test(word)) return;
            const id = Array.from(crypto.getRandomValues(new Uint8Array(16)), byte =>
                byte.toString(16).padStart(2, '0')).join('');
            pending.push({ id, word, result });
            storePreference(sessionStorage, queueKey, pending);
            void sync();
        },
        colorTiles(container) {
            const stats = totals();
            container.querySelectorAll('.tile.small').forEach(tile => {
                tile.dataset.profileLetter = tile.textContent.trim();
                paintTile(tile, stats);
            });
        }
    };

    document.addEventListener('DOMContentLoaded', () => {
        const panel = document.getElementById('home-profile');
        const open = document.getElementById('open-profile');
        const close = document.getElementById('close-profile');
        if (panel && open && close) {
            const setPanel = visible => {
                panel.hidden = !visible;
                open.setAttribute('aria-expanded', String(visible));
            };
            setPanel(readPreference(sessionStorage, 'anagramsProfilePanelOpen',
                !window.matchMedia('(max-width: 900px)').matches));
            function togglePanel(visible) {
                setPanel(visible);
                storePreference(sessionStorage, 'anagramsProfilePanelOpen', visible);
                (visible ? close : open).focus();
            }
            open.addEventListener('click', () => togglePanel(panel.hidden));
            close.addEventListener('click', () => togglePanel(false));
            panel.addEventListener('keydown', event => {
                if (event.key === 'Escape') togglePanel(false);
            });
        }
        const name = document.getElementById('profile-display-name');
        const form = document.getElementById('display-name-form');
        if (name && form) {
            const showName = () => {
                name.textContent = getDisplayName() || name.dataset.defaultName;
            };
            setupDisplayNameForm();
            showName();
            form.addEventListener('display-name-saved', showName);
        }
        const toggle = document.getElementById('letter-cosmetics');
        if (toggle) {
            toggle.checked = cosmeticsEnabled;
            toggle.addEventListener('change', () => {
                cosmeticsEnabled = toggle.checked;
                storePreference(localStorage, cosmeticKey, cosmeticsEnabled);
                render();
            });
        }
        document.querySelectorAll('[data-letter-detail]').forEach(button => {
            button.addEventListener('click', () => {
                selectedLetter = button.dataset.letterDetail;
                render();
            });
        });
        const picker = document.getElementById('letter-color-choice');
        picker?.addEventListener('change', () => {
            if (picker.value === 'auto') delete letterChoices[selectedLetter];
            else letterChoices[selectedLetter] = picker.value;
            storePreference(localStorage, letterChoicesKey, letterChoices);
            render();
        });
        document.querySelectorAll('[data-profile-sync-error] button').forEach(button => {
            button.addEventListener('click', sync);
        });
        render();
        void sync();
    });
    window.addEventListener('online', sync);
})();
