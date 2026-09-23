const socket = io();
let myUsername = localStorage.getItem('anagramsMultiplayerUsername') ||
    sessionStorage.getItem('anagramsMultiplayerUsername') || "";
const safeUsernamePattern = /^[\p{L}\p{N} _.'-]+$/u;
if (myUsername.length > 24 || !safeUsernamePattern.test(myUsername)) {
    sessionStorage.removeItem('anagramsMultiplayerUsername');
    localStorage.removeItem('anagramsMultiplayerUsername');
    myUsername = "";
}
let mySid = "";
let joinedSocketId = "";
const reconnectStorageKey = `anagramsReconnectToken:${ROOM_ID}`;
const reconnectToken = localStorage.getItem(reconnectStorageKey) ||
    (window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`);
localStorage.setItem(reconnectStorageKey, reconnectToken);
let isMyTurn = false;
let drawTimerInterval = null;
let endGameVotes = {}; // Track who voted to end the game
let hasVotedToEnd = false; // Did I vote to end?
let playerReadyState = false; // Track my ready state
let countdownActive = false; // Track if final countdown is active
let playerLockedOut = false; // Track if player is locked out during countdown
let silencedUntil = 0;
let silenceTimerInterval = null;
let lastSubmittedWord = null;
const boardDefinitionCache = new Map();
const boardStealCache = new Map();
let wordDetailsRequest = 0;
let gameHasEnded = false;
let gameInProgress = false;
let prefireEnabled = false;
let pasteAllowed = true;
let standbyWord = '';

function escapeHtml(value) {
    const node = document.createElement('span');
    node.textContent = String(value ?? '');
    return node.innerHTML;
}

document.addEventListener('DOMContentLoaded', () => {
    // 1. Show custom username popup
    if (myUsername) {
        joinCurrentSocket();
    } else {
        showUsernamePopup();
    }

    // 2. Input Listeners
    const wordInput = document.getElementById('wordInput');
    if (wordInput) {
        wordInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                // If it's my turn and input is empty, draw tile instead of submitting
                if (isMyTurn && wordInput.value.trim().length === 0) {
                    drawTile();
                } else {
                    submitWord();
                }
            } else if (e.key === 'Tab' && prefireEnabled) {
                e.preventDefault();
                handleStandbyWord();
            } else if (e.key === ' ') {
                // Space key submits the word instead of typing a space
                e.preventDefault();
                submitWord();
            }
        });
        ['paste', 'copy', 'cut', 'drop'].forEach(eventName => {
            wordInput.addEventListener(eventName, event => {
                if (pasteAllowed) return;
                event.preventDefault();
                showInputMessage('Copy and paste are disabled for this game.', '#f1c40f');
            });
        });
    }

    document.addEventListener('pointerup', () => {
        window.setTimeout(focusWordInput, 0);
    });

    // Capture my Socket ID when connected
    socket.on('connect', () => {
        mySid = socket.id;
        joinCurrentSocket();
    });

    socket.on('disconnect', () => showReconnectNotice());
    socket.on('connect_error', () => {
        showReconnectNotice();
        const status = document.getElementById('rejoin-status');
        if (status) status.textContent = 'Could not connect yet. Try again.';
    });
});

function joinCurrentSocket() {
    if (!myUsername || !socket.connected || joinedSocketId === socket.id) return;
    joinedSocketId = socket.id;
    socket.emit('join', {
        room: ROOM_ID,
        username: myUsername,
        reconnect_token: reconnectToken,
        initial_bot_difficulty: INITIAL_BOT_DIFFICULTY
    });
}

socket.on('kicked', (data) => {
    localStorage.removeItem(reconnectStorageKey);
    alert(data.msg || 'The host removed you from this lobby.');
    window.location.href = '/homepage';
});

/* --- END GAME EVENTS --- */

socket.on('end_game_vote', (data) => {
    endGameVotes = data.votes;
    const votesNeeded = data.votes_needed || Math.ceil(Object.keys(data.players).length * 2 / 3);
    const votesReceived = Object.values(endGameVotes).filter(v => v).length;
    updateEndGameUI(votesReceived, votesNeeded);
    
    if (votesReceived >= votesNeeded && !data.immediate) {
        // Start countdown to game end
        showSmallCountdown();
        lockTextInput();
    }
});

socket.on('game_ended', (data) => {
    gameHasEnded = true;
    gameInProgress = false;
    showGameOverScreen(data);
});

/* --- LOBBY EVENTS --- */

socket.on('lobby_update', (data) => {
    hideReconnectNotice();
    const lobbyContainer = document.getElementById('lobby-container');
    const gameContainer = document.getElementById('game-container');
    
    // Switch visibility if still in lobby
    if (data.status === 'lobby') {
        const gameOverModal = document.getElementById('game-over-modal');
        if (gameOverModal) gameOverModal.remove();
        setTopReplayVisible(false);
        playerReadyState = false;
        playerLockedOut = false;
        countdownActive = false;
        gameHasEnded = false;
        gameInProgress = false;
        clearStandbyWord();
        silencedUntil = 0;
        hasVotedToEnd = false;
        lastSubmittedWord = null;
        clearInterval(silenceTimerInterval);
        closeBoardWordDefinition();
        unlockTextInput();
        const readyBtn = document.getElementById('ready-btn');
        if (readyBtn) {
            readyBtn.innerText = 'READY UP';
            readyBtn.style.background = '';
        }
        if (lobbyContainer) lobbyContainer.style.display = 'block';
        if (gameContainer) gameContainer.style.display = 'none';
        renderLobby(data);
    }
});

socket.on('game_start', (data) => {
    hideReconnectNotice();
    setTopReplayVisible(false);
    gameHasEnded = false;
    gameInProgress = true;
    const lobbyContainer = document.getElementById('lobby-container');
    const gameContainer = document.getElementById('game-container');
    
    if (lobbyContainer) lobbyContainer.style.display = 'none';
    if (gameContainer) gameContainer.style.display = 'block';
    
    updateUI(data);
});

/* --- GAMEPLAY EVENTS --- */

socket.on('update_board', (data) => {
    hideReconnectNotice();
    lastSubmittedWord = null;
    updateUI(data);
});

socket.on('game_state', (data) => {
    hideReconnectNotice();
    updateUI(data);
});

socket.on('error_message', (data) => {
    lastSubmittedWord = null;
    const msgDiv = document.getElementById('statusMessage');
    if (msgDiv) {
        msgDiv.innerText = data.msg;
        msgDiv.style.color = "#e74c3c";
        setTimeout(() => msgDiv.innerText = "", 3000);
    }
});

socket.on('silenced', (data) => {
    lastSubmittedWord = null;
    startSilenceTimer(data.seconds, data.msg);
});

socket.on('player_action', (data) => {
    showActionMessage(data.message);
});

/* --- ACTIONS --- */

function toggleReady() {
    playerReadyState = !playerReadyState;
    const readyBtn = document.getElementById('ready-btn');
    if (readyBtn) {
        readyBtn.innerText = playerReadyState ? 'NOT READY' : 'READY UP';
        readyBtn.style.background = playerReadyState ? '#e74c3c' : '';
    }
    socket.emit('toggle_ready', { room: ROOM_ID });
}

function updateSettings() {
    const maxTiles = document.getElementById('setting-tiles').value;
    const drawTime = document.getElementById('setting-timer').value;
    const autodrawEnabled = document.getElementById('setting-autodraw').value;
    const tilePreset = document.getElementById('setting-preset').value;
    const incorrectWordPenalty = document.getElementById('setting-penalty').value;
    const wordWinnerDrawsNext = document.getElementById('setting-winner-draws').value;
    const prefire = document.getElementById('setting-prefire').value;
    const paste = document.getElementById('setting-paste').value;
    socket.emit('update_settings', {
        room: ROOM_ID,
        tile_preset: tilePreset,
        max_tiles: maxTiles,
        draw_time: drawTime,
        autodraw_enabled: autodrawEnabled,
        incorrect_word_penalty: incorrectWordPenalty,
        word_winner_draws_next: wordWinnerDrawsNext,
        prefire_enabled: prefire,
        paste_allowed: paste
    });
}

function addBot() {
    socket.emit('add_bot', { room: ROOM_ID, difficulty: 'medium' });
}

function removeBot(sid) {
    socket.emit('remove_bot', { room: ROOM_ID, sid });
}

function updateBotDifficulty(sid, difficulty) {
    socket.emit('update_bot_difficulty', { room: ROOM_ID, sid, difficulty });
}

function kickPlayer(sid, username) {
    if (!window.confirm(`Remove ${username} from this lobby?`)) return;
    socket.emit('kick_player', { room: ROOM_ID, sid });
}

function applyTilePreset() {
    const preset = document.getElementById('setting-preset').value;
    const tileInput = document.getElementById('setting-tiles');
    const presetCounts = { standard: 60, bananagrams: 144 };
    if (presetCounts[preset]) tileInput.value = presetCounts[preset];
    tileInput.disabled = preset !== 'custom';
    updateSettings();
}

function useCustomTileCount() {
    document.getElementById('setting-preset').value = 'custom';
    updateSettings();
}

function startGame() {
    socket.emit('start_game', { room: ROOM_ID });
}

function drawTile() {
    // The server will validate if it's actually our turn
    socket.emit('draw_tile', { room: ROOM_ID });
    
    // Keep focus on the word input
    const input = document.getElementById('wordInput');
    if (input) input.focus();
}

function submitWord(wordOverride = null) {
    // If locked out during countdown, don't allow submission
    if (playerLockedOut) {
        return;
    }
    
    const input = document.getElementById('wordInput');
    const word = (wordOverride ?? input.value).trim().toUpperCase();
    if (word.length < 3) return;
    if (lastSubmittedWord === word) return;
    lastSubmittedWord = word;

    socket.emit('claim_word', { 
        room: ROOM_ID, 
        word: word 
    });
    if (wordOverride === null) input.value = "";
    focusWordInput();
}

function handleStandbyWord() {
    if (!standbyWord) {
        const input = document.getElementById('wordInput');
        const candidate = input.value.trim().toUpperCase();
        if (candidate.length < 3) {
            showInputMessage('Type a word first, then press Tab to hold it.', '#f1c40f');
            return;
        }
        standbyWord = candidate;
        input.value = '';
        updateStandbyWordDisplay();
        showInputMessage(`${standbyWord} is standing by. Press Tab again to play it.`, '#f1c40f');
        return;
    }

    const wordToPlay = standbyWord;
    clearStandbyWord();
    submitWord(wordToPlay);
}

function clearStandbyWord() {
    standbyWord = '';
    updateStandbyWordDisplay();
}

function updateStandbyWordDisplay() {
    const display = document.getElementById('standbyWordDisplay');
    if (!display) return;
    display.hidden = !standbyWord;
    display.textContent = standbyWord ? `STANDBY: ${standbyWord} · TAB TO PLAY` : '';
}

function showInputMessage(message, color) {
    const status = document.getElementById('statusMessage');
    if (!status) return;
    status.textContent = message;
    status.style.color = color;
    window.setTimeout(() => {
        if (status.textContent === message) status.textContent = '';
    }, 2500);
}

/* --- UI RENDERING --- */

function renderLobby(data) {
    const playerList = document.getElementById('player-list');
    if (!playerList) return;

    playerList.innerHTML = '';
    
    // Check if I am host
    const amIHost = data.host_sid === socket.id;
    const hostControls = document.getElementById('host-controls');
    const startBtn = document.getElementById('start-btn');
    const addBotBtn = document.getElementById('add-bot-btn');
    const humanCount = Object.values(data.players).filter(player => !player.is_bot).length;
    const botCount = Object.values(data.players).filter(player => player.is_bot).length;
    
    // Everyone can see the room settings; only the host can change them.
    if (hostControls) hostControls.style.display = 'block';
    if (startBtn) startBtn.style.display = amIHost ? 'inline-block' : 'none';
    if (startBtn) startBtn.textContent = humanCount === 1 && botCount === 0 ? 'START ZEN' : 'START GAME';
    if (addBotBtn) addBotBtn.style.display = amIHost ? 'inline-block' : 'none';
    const modeLabel = document.getElementById('lobby-mode-label');
    if (modeLabel) modeLabel.textContent = humanCount === 1 && botCount === 0 ? 'START ALONE FOR ZEN' : 'MULTIPLAYER / BOT';

    const presetInput = document.getElementById('setting-preset');
    const tileInput = document.getElementById('setting-tiles');
    const timerInput = document.getElementById('setting-timer');
    const autodrawInput = document.getElementById('setting-autodraw');
    const penaltyInput = document.getElementById('setting-penalty');
    const winnerDrawsInput = document.getElementById('setting-winner-draws');
    const prefireInput = document.getElementById('setting-prefire');
    const pasteInput = document.getElementById('setting-paste');
    if (presetInput && tileInput && timerInput && autodrawInput && penaltyInput && winnerDrawsInput && prefireInput && pasteInput && data.settings) {
        presetInput.value = data.settings.tile_preset || 'custom';
        tileInput.value = data.settings.max_tiles;
        timerInput.value = data.settings.draw_time;
        autodrawInput.value = data.settings.autodraw_enabled === false ? 'false' : 'true';
        penaltyInput.value = data.settings.incorrect_word_penalty === false ? 'false' : 'true';
        winnerDrawsInput.value = data.settings.word_winner_draws_next === true ? 'true' : 'false';
        prefireInput.value = data.settings.prefire_enabled === true ? 'true' : 'false';
        pasteInput.value = data.settings.paste_allowed === false ? 'false' : 'true';
        prefireEnabled = data.settings.prefire_enabled === true;
        pasteAllowed = data.settings.paste_allowed !== false;
        if (!prefireEnabled) clearStandbyWord();
        presetInput.disabled = !amIHost;
        tileInput.disabled = !amIHost || presetInput.value !== 'custom';
        timerInput.disabled = !amIHost;
        autodrawInput.disabled = !amIHost;
        penaltyInput.disabled = !amIHost;
        winnerDrawsInput.disabled = !amIHost;
        prefireInput.disabled = !amIHost;
        pasteInput.disabled = !amIHost;
    }

    // List players
    const orderedPlayers = data.player_order
        .filter(sid => data.players[sid])
        .map(sid => [sid, data.players[sid]]);
    orderedPlayers.forEach(([sid, player]) => {
        const item = document.createElement('div');
        item.className = 'lobby-player-item';
        item.style.padding = '10px';
        item.style.margin = '5px 0';
        item.style.background = 'rgba(255,255,255,0.1)';
        item.style.borderRadius = '8px';
        item.style.display = 'flex';
        item.style.justifyContent = 'space-between';
        item.style.opacity = player.connected === false ? '0.55' : '1';
        
        const readyText = player.connected === false
            ? '<span style="color: #95a5a6;">GHOST — RECONNECTING</span>'
            : player.ready ?
            '<span style="color: #2ecc71;">READY</span>' : 
            '<span style="color: #e74c3c;">WAITING</span>';

        let controls = `<b>${readyText}</b>`;
        if (player.is_bot) {
            const difficulty = player.difficulty || 'medium';
            controls = amIHost ? `
                <span class="lobby-row-controls">
                    <select data-bot-difficulty="${escapeHtml(sid)}" aria-label="Bot difficulty">
                        ${['easy', 'medium', 'hard'].map(level => `<option value="${level}" ${level === difficulty ? 'selected' : ''}>${level.toUpperCase()}</option>`).join('')}
                    </select>
                    <button type="button" class="lobby-remove" data-remove-bot="${escapeHtml(sid)}" aria-label="Remove bot">×</button>
                </span>` : `<b style="color:#e67e22">${escapeHtml(difficulty.toUpperCase())}</b>`;
        } else if (amIHost && sid !== socket.id) {
            controls = `<span class="lobby-row-controls">${controls}<button type="button" class="lobby-remove" data-kick-player="${escapeHtml(sid)}" aria-label="Kick player">KICK</button></span>`;
        }
        item.innerHTML = `
            <span>${escapeHtml(player.username)} ${player.is_host ? '👑' : ''} ${player.is_bot ? '<small>BOT</small>' : ''}</span>
            ${controls}
        `;
        item.querySelector('[data-bot-difficulty]')?.addEventListener('change', event => updateBotDifficulty(sid, event.target.value));
        item.querySelector('[data-remove-bot]')?.addEventListener('click', () => removeBot(sid));
        item.querySelector('[data-kick-player]')?.addEventListener('click', () => kickPlayer(sid, player.username));
        playerList.appendChild(item);
    });
}

function updateUI(data) {
    const countEl = document.getElementById('tileCount');
    if (countEl) countEl.innerText = data.tiles.length;

    gameHasEnded = data.status === 'ended' || gameHasEnded;
    gameInProgress = data.status === 'playing' && !gameHasEnded;
    prefireEnabled = data.settings.prefire_enabled === true;
    pasteAllowed = data.settings.paste_allowed !== false;
    if (!prefireEnabled) clearStandbyWord();
    renderPool(data.active_pool);
    renderPlayers(data.players, data.player_order);

    // Turn Handling
    const currentTurnSid = data.player_order[data.turn_index];
    isMyTurn = (currentTurnSid === socket.id);
    
    const turnIndicator = document.getElementById('turn-indicator');
    const drawBtn = document.getElementById('drawButton');
    const endGameBtn = document.getElementById('endGameButton');
    
    if (turnIndicator) {
        const currentName = data.players[currentTurnSid].username;
        turnIndicator.innerText = isMyTurn ? "IT IS YOUR TURN!" : `${currentName.toUpperCase()} IS DRAWING...`;
        turnIndicator.style.color = isMyTurn ? "#2ecc71" : "#f1c40f";
    }

    // Show end game button when no tiles left
    if (data.tiles.length === 0) {
        if (drawBtn) {
            drawBtn.disabled = true;
            drawBtn.innerText = "NO TILES LEFT";
            drawBtn.style.opacity = "0.5";
        }
        if (endGameBtn) {
            endGameBtn.style.display = 'inline-block';
            endGameBtn.innerText = hasVotedToEnd ? "END GAME ✓" : "END GAME?";
        }
    } else {
        if (drawBtn) {
            drawBtn.disabled = !isMyTurn;
            if (isMyTurn) {
                drawBtn.innerText = "DRAW TILE";
                drawBtn.style.opacity = "1";
                drawBtn.style.cursor = "pointer";
            } else {
                drawBtn.innerText = "LOCKED";
                drawBtn.style.opacity = "0.5";
                drawBtn.style.cursor = "not-allowed";
            }
        }
        if (endGameBtn) {
            endGameBtn.style.display = 'none';
        }
        hasVotedToEnd = false;
    }

    resetTurnTimer(data.settings.draw_time, data.settings.autodraw_enabled !== false);
    window.setTimeout(focusWordInput, 0);
}

function resetTurnTimer(duration, enabled = true) {
    clearInterval(drawTimerInterval);
    let secondsLeft = duration;
    const timerDisplay = document.getElementById('draw-timer');
    const timerWrap = document.getElementById('draw-timer-wrap');
    
    if (!timerDisplay) return;
    if (timerWrap) timerWrap.style.display = enabled ? 'block' : 'none';
    if (!enabled) {
        timerDisplay.innerText = '-';
        return;
    }
    timerDisplay.innerText = secondsLeft;

    drawTimerInterval = setInterval(() => {
        secondsLeft--;
        timerDisplay.innerText = secondsLeft;

        if (secondsLeft <= 0) {
            clearInterval(drawTimerInterval);
            // If it's my turn and time ran out, tell server to auto-draw
            if (isMyTurn) {
                socket.emit('draw_tile', { room: ROOM_ID, auto: true });
            }
        }
    }, 1000);
}

function renderPool(pool) {
    const poolDiv = document.getElementById('tilePool');
    if (!poolDiv) return;
    poolDiv.innerHTML = '';
    pool.forEach(letter => {
        const tile = document.createElement('div');
        tile.className = 'tile pool-tile';
        tile.innerText = letter;
        poolDiv.appendChild(tile);
    });
}

function renderPlayers(players, playerOrder) {
    const board = document.getElementById('playersBoard');
    if (!board) return;
    board.innerHTML = '';

    const orderedPlayers = playerOrder
        .filter(sid => players[sid])
        .map(sid => [sid, players[sid]]);
    for (const [sid, player] of orderedPlayers) {
        const isMe = sid === socket.id;
        const section = document.createElement('section');
        section.style.background = isMe ? 'rgba(52, 152, 219, 0.1)' : 'rgba(0,0,0,0.2)';
        section.style.padding = '20px';
        section.style.borderRadius = '15px';
        section.style.border = isMe ? '2px solid #3498db' : '1px solid rgba(255,255,255,0.1)';
        section.style.opacity = player.connected === false ? '0.55' : '1';

        const wordsHtml = player.words.map(w => {
            const contents = `
                ${w.split('').map(char => `<div class="tile small">${char}</div>`).join('')}
                <span class="word-score-tag">${w.length - 2}</span>`;
            const detail = gameHasEnded ? 'definition and direct steals' : 'definition';
            return `<button type="button" class="word-block board-word-button" data-board-word="${escapeHtml(w)}" title="Show ${detail} for ${escapeHtml(w)}">${contents}</button>`;
        }).join('');

        section.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                <h3 style="margin: 0; color: ${isMe ? '#3498db' : 'white'}">${escapeHtml(player.username)}${player.connected === false ? ' · GHOST' : ''}</h3>
                <div class="score-badge" style="font-size: 1.8rem;">${player.score || 0}</div>
            </div>
            <div class="words-container" style="display: flex; flex-wrap: wrap; gap: 10px;">
                ${wordsHtml}
            </div>
        `;
        section.querySelectorAll('[data-board-word]').forEach(button => {
            button.addEventListener('click', () => showBoardWordDefinition(button.dataset.boardWord));
        });
        board.appendChild(section);
    }
}

function requestEndGame() {
    hasVotedToEnd = true;
    
    // If countdown is active, lock player from typing
    if (countdownActive) {
        playerLockedOut = true;
        lockTextInput();
    }
    
    socket.emit('vote_end_game', { room: ROOM_ID });
}

function updateEndGameUI(votesReceived, votesNeeded) {
    const endGameBtn = document.getElementById('endGameButton');
    if (endGameBtn) {
        endGameBtn.innerText = `END GAME (${votesReceived}/${votesNeeded})`;
        if (hasVotedToEnd) {
            endGameBtn.innerText = `END GAME ✓ (${votesReceived}/${votesNeeded})`;
        }
    }
}

function showEndGameCountdown(players) {
    const modal = document.createElement('div');
    modal.id = 'end-game-countdown';
    modal.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: rgba(0,0,0,0.9);
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        z-index: 5000;
    `;
    
    let countdown = 10;
    modal.innerHTML = `
        <h1 style="font-size: 3rem; margin-bottom: 30px; letter-spacing: 2px;">GAME ENDING IN</h1>
        <div id="countdown-timer" style="font-size: 5rem; font-weight: bold; color: #e74c3c; margin-bottom: 50px;">${countdown}</div>
        <p style="font-size: 1.2rem; opacity: 0.8;">Calculating final scores...</p>
    `;
    
    document.body.appendChild(modal);
    
    const countdownEl = document.getElementById('countdown-timer');
    const countdownInterval = setInterval(() => {
        countdown--;
        if (countdownEl) countdownEl.innerText = countdown;
        if (countdown <= 0) {
            clearInterval(countdownInterval);
            const gameModal = document.getElementById('end-game-countdown');
            if (gameModal) gameModal.remove();
        }
    }, 1000);
}

function showGameOverScreen(data) {
    setTopReplayVisible(false);
    const existingModal = document.getElementById('game-over-modal');
    if (existingModal) existingModal.remove();
    const modal = document.createElement('div');
    modal.id = 'game-over-modal';
    modal.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: rgba(0,0,0,0.9);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 9999;
    `;
    
    // Find winner
    let winner = null;
    let maxScore = -1;
    let isTie = false;
    const scores = Object.entries(data.final_scores).map(([sid, score]) => ({
        username: data.players[sid].username,
        score: score
    }));
    
    // Sort scores from highest to lowest
    scores.sort((a, b) => b.score - a.score);
    
    for (const [sid, score] of Object.entries(data.final_scores)) {
        if (score > maxScore) {
            maxScore = score;
            winner = data.players[sid].username;
            isTie = false;
        } else if (score === maxScore) {
            isTie = true;
        }
    }
    
    const resultText = isTie 
        ? `🤝 GAME OVER - TIE!` 
        : `🏆 ${winner.toUpperCase()} WINS!`;
    
    const scoresHtml = scores.map((s, idx) => `
        <div style="font-size: 1.2rem; margin: 10px; padding: 10px; background: rgba(255,255,255,0.1); border-radius: 8px;">
            ${idx === 0 ? '🥇' : idx === 1 ? '🥈' : idx === 2 ? '🥉' : '  '} ${escapeHtml(s.username)}: <span style="color: #2ecc71; font-weight: bold;">${Number(s.score) || 0} points</span>
        </div>
    `).join('');
    
    modal.innerHTML = `
        <div style="position: relative; background: #1a252f; padding: 50px; border-radius: 20px; text-align: center; border: 3px solid #2ecc71; max-width: 600px;">
            <button type="button" onclick="closeGameOverScreen()" aria-label="Close final scores" style="position: absolute; top: 10px; right: 14px; border: 0; background: transparent; color: white; cursor: pointer; font-size: 2rem;">&times;</button>
            <h1 style="font-size: 3rem; margin-bottom: 30px; letter-spacing: 2px;">${escapeHtml(resultText)}</h1>
            <div style="margin-bottom: 40px;">
                ${scoresHtml}
            </div>
            <div style="display: flex; gap: 15px; justify-content: center; flex-wrap: wrap;">
                <button class="btn btn-green" onclick="requestReplay()" style="padding: 15px 40px; font-size: 1.2rem;">PLAY AGAIN</button>
                <a href="/homepage" style="text-decoration: none;">
                    <button class="btn btn-leave" style="padding: 15px 40px; font-size: 1.2rem;">BACK TO HOME</button>
                </a>
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
}

function setTopReplayVisible(visible) {
    const replayButton = document.getElementById('topReplayButton');
    const tileCountDisplay = document.getElementById('tileCountDisplay');
    if (replayButton) replayButton.hidden = !visible;
    if (tileCountDisplay) tileCountDisplay.hidden = visible;
}

function closeGameOverScreen() {
    const modal = document.getElementById('game-over-modal');
    if (modal) modal.remove();
    setTopReplayVisible(true);
}

async function showBoardWordDefinition(word) {
    const request = ++wordDetailsRequest;
    const modal = document.getElementById('board-definition-modal');
    const card = modal.querySelector('.definition-card');
    const title = document.getElementById('board-definition-title');
    const body = document.getElementById('board-definition-body');
    const stealsPanel = document.getElementById('board-steals-panel');
    const stealsBody = document.getElementById('board-steals-body');
    const showSteals = gameHasEnded;
    title.textContent = word;
    body.textContent = 'Loading definition...';
    card.classList.toggle('definition-only', !showSteals);
    stealsPanel.hidden = !showSteals;
    if (showSteals) stealsBody.textContent = 'Finding direct steals...';
    modal.hidden = false;

    const definitionPromise = (async () => {
        let data = boardDefinitionCache.get(word);
        if (!data) {
            const response = await fetch(`/definition/${encodeURIComponent(word.toLowerCase())}`);
            if (!response.ok) throw new Error('Definition unavailable');
            data = await response.json();
            if (boardDefinitionCache.size >= 100) {
                boardDefinitionCache.delete(boardDefinitionCache.keys().next().value);
            }
            boardDefinitionCache.set(word, data);
        }
        if (request !== wordDetailsRequest) return;
        const list = document.createElement('ol');
        for (const item of data.definitions || []) {
            const row = document.createElement('li');
            const label = document.createElement('strong');
            label.textContent = item.partOfSpeech ? `${item.partOfSpeech}: ` : '';
            row.append(label, document.createTextNode(item.definition));
            list.appendChild(row);
        }
        body.replaceChildren();
        if (data.isWord && list.children.length) body.appendChild(list);
        else body.textContent = 'No definition found.';
    })().catch(() => {
        if (request === wordDetailsRequest) body.textContent = 'Definition unavailable right now.';
    });

    if (!showSteals) {
        await definitionPromise;
        return;
    }

    const stealsPromise = (async () => {
        const maxAdded = Math.min(3, 15 - word.length);
        if (maxAdded < 1) {
            if (request === wordDetailsRequest) stealsBody.textContent = 'No larger game words are possible.';
            return;
        }

        let groups = boardStealCache.get(word);
        if (!groups) {
            const response = await fetch('/word-extensions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    letters: word,
                    minAdded: 1,
                    maxAdded,
                    chainMode: false
                })
            });
            if (!response.ok) throw new Error('Steals unavailable');
            const data = await response.json();
            groups = data.groups || [];
            if (boardStealCache.size >= 100) {
                boardStealCache.delete(boardStealCache.keys().next().value);
            }
            boardStealCache.set(word, groups);
        }
        if (request !== wordDetailsRequest) return;
        renderDirectSteals(word, groups, stealsBody);
    })().catch(() => {
        if (request === wordDetailsRequest) stealsBody.textContent = 'Ways to steal are unavailable right now.';
    });

    await Promise.allSettled([definitionPromise, stealsPromise]);
}

function renderDirectSteals(sourceWord, groups, container) {
    container.replaceChildren();
    const groupsBySize = new Map(groups.map(group => [Number(group.added), group]));

    for (let added = 1; added <= 3; added++) {
        const section = document.createElement('section');
        section.className = 'steal-group';
        const heading = document.createElement('h4');
        heading.textContent = `+${added}`;
        section.appendChild(heading);

        const group = groupsBySize.get(added);
        if (!group || !group.words.length) {
            const empty = document.createElement('p');
            empty.className = 'steal-empty';
            empty.textContent = added > 15 - sourceWord.length ? 'Not possible at this word length.' : 'No direct steals found.';
            section.appendChild(empty);
        } else {
            const words = document.createElement('div');
            words.className = 'steal-words';
            group.words.forEach(word => words.appendChild(buildStealWord(sourceWord, word)));
            section.appendChild(words);
            if (group.total > group.words.length) {
                const overflow = document.createElement('p');
                overflow.className = 'steal-overflow';
                overflow.textContent = `Showing ${group.words.length} of ${group.total}.`;
                section.appendChild(overflow);
            }
        }
        container.appendChild(section);
    }
}

function buildStealWord(sourceWord, word) {
    const available = {};
    for (const char of sourceWord) available[char] = (available[char] || 0) + 1;
    const block = document.createElement('div');
    block.className = 'steal-word';
    block.title = word;
    for (const char of word) {
        const tile = document.createElement('span');
        tile.className = 'tile small';
        if (available[char] > 0) available[char]--;
        else tile.classList.add('added');
        tile.textContent = char;
        block.appendChild(tile);
    }
    return block;
}

function closeBoardWordDefinition() {
    wordDetailsRequest++;
    document.getElementById('board-definition-modal').hidden = true;
    focusWordInput();
}

function requestReplay() {
    setTopReplayVisible(false);
    socket.emit('replay_game', { room: ROOM_ID });
}

/* --- CUSTOM UI FUNCTIONS --- */

function showUsernamePopup() {
    const modal = document.createElement('div');
    modal.className = 'blocking-modal';
    modal.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: rgba(0,0,0,0.9);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 10000;
    `;
    
    modal.innerHTML = `
        <div style="background: #1a252f; padding: 50px; border-radius: 20px; text-align: center; border: 3px solid #3498db; max-width: 400px;">
            <h1 style="font-size: 2rem; margin-bottom: 30px; letter-spacing: 2px;">ENTER USERNAME</h1>
            <input type="text" id="username-input" maxlength="24" placeholder="Your name..."
                   style="width: 100%; padding: 15px; border-radius: 8px; border: 2px solid #3498db; background: #2c3e50; color: white; font-size: 1.1rem; outline: none; margin-bottom: 25px; text-align: center;" autocomplete="off">
            <div style="display: flex; gap: 15px; justify-content: center;">
                <button class="btn btn-green" onclick="confirmUsername()" style="padding: 12px 40px; font-size: 1rem;">JOIN</button>
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
    const input = document.getElementById('username-input');
    if (input) {
        input.focus();
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') confirmUsername();
        });
    }
}

function confirmUsername() {
    const input = document.getElementById('username-input');
    const username = input.value.trim() || "Player_" + Math.floor(Math.random() * 1000);
    if (username.length > 24 || !safeUsernamePattern.test(username)) {
        input.setCustomValidity("Use 1–24 letters, numbers, spaces, apostrophes, periods, hyphens, or underscores.");
        input.reportValidity();
        return;
    }
    input.setCustomValidity('');
    myUsername = username;
    sessionStorage.setItem('anagramsMultiplayerUsername', myUsername);
    localStorage.setItem('anagramsMultiplayerUsername', myUsername);
    
    // Remove modal
    const modals = document.querySelectorAll('div[style*="z-index: 10000"]');
    modals.forEach(m => m.remove());
    
    // Join with a stable token so reconnects restore this player.
    joinCurrentSocket();
    
}

function confirmLeaveGame() {
    const modal = document.createElement('div');
    modal.className = 'blocking-modal';
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

function showSmallCountdown() {
    countdownActive = true;
    playerLockedOut = false; // Reset lock - players can still type initially
    
    const timerDiv = document.createElement('div');
    timerDiv.id = 'small-countdown-timer';
    timerDiv.style.cssText = `
        position: fixed;
        bottom: 120px;
        right: 30px;
        background: rgba(231, 76, 60, 0.95);
        border: 3px solid #e74c3c;
        padding: 20px 30px;
        border-radius: 15px;
        font-size: 2rem;
        font-weight: bold;
        color: white;
        text-align: center;
        z-index: 8000;
        min-width: 120px;
        box-shadow: 0 0 20px rgba(231, 76, 60, 0.6);
    `;
    
    let countdown = 10;
    timerDiv.innerText = countdown;
    document.body.appendChild(timerDiv);
    
    const countdownInterval = setInterval(() => {
        countdown--;
        timerDiv.innerText = countdown;
        if (countdown <= 0) {
            clearInterval(countdownInterval);
            timerDiv.remove();
            countdownActive = false;
            playerLockedOut = false;
            unlockTextInput();
        }
    }, 1000);
}

function lockTextInput(placeholder = 'Game ending...') {
    const input = document.getElementById('wordInput');
    if (input) {
        input.disabled = true;
        input.style.opacity = '0.5';
        input.style.cursor = 'not-allowed';
        input.placeholder = placeholder;
    }
}

function unlockTextInput() {
    if (countdownActive || Date.now() < silencedUntil) return;
    const input = document.getElementById('wordInput');
    if (input) {
        input.disabled = false;
        input.style.opacity = '1';
        input.style.cursor = 'text';
        input.placeholder = 'Type word...';
        window.setTimeout(focusWordInput, 0);
    }
}

function focusWordInput() {
    const input = document.getElementById('wordInput');
    const wordModal = document.getElementById('board-definition-modal');
    if (!input || input.disabled || !gameInProgress) return;
    if (wordModal && !wordModal.hidden) return;
    if (document.querySelector('.blocking-modal, #game-over-modal, #end-game-countdown')) return;
    input.focus({ preventScroll: true });
}

function startSilenceTimer(seconds, message) {
    clearInterval(silenceTimerInterval);
    silencedUntil = Date.now() + (seconds * 1000);
    playerLockedOut = true;

    const updateSilenceUI = () => {
        const secondsLeft = Math.max(0, Math.ceil((silencedUntil - Date.now()) / 1000));
        const msgDiv = document.getElementById('statusMessage');
        if (secondsLeft > 0) {
            lockTextInput(`Silenced (${secondsLeft}s)`);
            if (msgDiv) {
                msgDiv.innerText = message || `Too many incorrect attempts. Silenced for ${secondsLeft}s.`;
                msgDiv.style.color = '#e74c3c';
            }
            return;
        }

        clearInterval(silenceTimerInterval);
        silencedUntil = 0;
        playerLockedOut = countdownActive;
        unlockTextInput();
        if (msgDiv && !countdownActive) msgDiv.innerText = '';
    };

    updateSilenceUI();
    silenceTimerInterval = setInterval(updateSilenceUI, 250);
}

function showActionMessage(message) {
    const msgDiv = document.getElementById('statusMessage');
    if (msgDiv) {
        msgDiv.innerText = message;
        msgDiv.style.color = "#f39c12";
        setTimeout(() => msgDiv.innerText = "", 4000);
    }
}

function showReconnectNotice() {
    if (document.getElementById('reconnect-notice')) return;
    const notice = document.createElement('div');
    notice.id = 'reconnect-notice';
    notice.style.cssText = 'position:fixed;inset:0;z-index:12000;display:grid;place-items:center;background:rgba(8,14,20,.9);';
    notice.innerHTML = `
        <div style="max-width:420px;padding:34px;text-align:center;border:2px solid #3498db;border-radius:18px;background:#1a252f;">
            <h2>CONNECTION LOST</h2>
            <p style="opacity:.75;line-height:1.5;">Your seat is being held. Rejoin with the same name, words, score, and turn position.</p>
            <button id="rejoin-button" class="btn btn-blue" type="button">REJOIN NOW</button>
            <p id="rejoin-status" style="min-height:1.2em;font-size:.82rem;opacity:.7;">Trying automatically…</p>
        </div>`;
    document.body.appendChild(notice);
    notice.querySelector('#rejoin-button').addEventListener('click', () => {
        notice.querySelector('#rejoin-status').textContent = 'Reconnecting…';
        joinedSocketId = '';
        if (socket.connected) joinCurrentSocket();
        else socket.connect();
    });
}

function hideReconnectNotice() {
    document.getElementById('reconnect-notice')?.remove();
}
