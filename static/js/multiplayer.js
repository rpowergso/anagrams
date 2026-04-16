const socket = io();
let myUsername = "";
let mySid = "";
let isMyTurn = false;
let drawTimerInterval = null;
let endGameVotes = {}; // Track who voted to end the game
let hasVotedToEnd = false; // Did I vote to end?
let playerReadyState = false; // Track my ready state

document.addEventListener('DOMContentLoaded', () => {
    // 1. Show custom username popup
    showUsernamePopup();

    // 2. Input Listeners
    const wordInput = document.getElementById('wordInput');
    if (wordInput) {
        wordInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') submitWord();
        });
    }

    // Capture my Socket ID when connected
    socket.on('connect', () => {
        mySid = socket.id;
    });
});

/* --- END GAME EVENTS --- */

socket.on('end_game_vote', (data) => {
    endGameVotes = data.votes;
    const votesNeeded = Math.ceil(Object.keys(data.players).length * 2 / 3);
    const votesReceived = Object.values(endGameVotes).filter(v => v).length;
    updateEndGameUI(votesReceived, votesNeeded);
    
    if (votesReceived >= votesNeeded) {
        // Start countdown to game end
        showSmallCountdown();
        lockTextInput();
    }
});

socket.on('game_ended', (data) => {
    showGameOverScreen(data);
});

/* --- LOBBY EVENTS --- */

socket.on('lobby_update', (data) => {
    const lobbyContainer = document.getElementById('lobby-container');
    const gameContainer = document.getElementById('game-container');
    
    // Switch visibility if still in lobby
    if (data.status === 'lobby') {
        if (lobbyContainer) lobbyContainer.style.display = 'block';
        if (gameContainer) gameContainer.style.display = 'none';
        renderLobby(data);
    }
});

socket.on('game_start', (data) => {
    const lobbyContainer = document.getElementById('lobby-container');
    const gameContainer = document.getElementById('game-container');
    
    if (lobbyContainer) lobbyContainer.style.display = 'none';
    if (gameContainer) gameContainer.style.display = 'block';
    
    updateUI(data);
});

/* --- GAMEPLAY EVENTS --- */

socket.on('update_board', (data) => {
    updateUI(data);
});

socket.on('game_state', (data) => {
    updateUI(data);
});

socket.on('error_message', (data) => {
    const msgDiv = document.getElementById('statusMessage');
    if (msgDiv) {
        msgDiv.innerText = data.msg;
        msgDiv.style.color = "#e74c3c";
        setTimeout(() => msgDiv.innerText = "", 3000);
    }
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
    socket.emit('update_settings', {
        room: ROOM_ID,
        max_tiles: maxTiles,
        draw_time: drawTime
    });
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

function submitWord() {
    const input = document.getElementById('wordInput');
    const word = input.value.trim().toUpperCase();
    if (word.length < 3) return;

    socket.emit('claim_word', { 
        room: ROOM_ID, 
        word: word 
    });
    input.value = "";
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
    
    if (hostControls) hostControls.style.display = amIHost ? 'block' : 'none';
    if (startBtn) startBtn.style.display = amIHost ? 'inline-block' : 'none';

    // List players
    Object.entries(data.players).forEach(([sid, player]) => {
        const item = document.createElement('div');
        item.className = 'lobby-player-item';
        item.style.padding = '10px';
        item.style.margin = '5px 0';
        item.style.background = 'rgba(255,255,255,0.1)';
        item.style.borderRadius = '8px';
        item.style.display = 'flex';
        item.style.justifyContent = 'space-between';
        
        const readyText = player.ready ? 
            '<span style="color: #2ecc71;">READY</span>' : 
            '<span style="color: #e74c3c;">WAITING</span>';
            
        item.innerHTML = `
            <span>${player.username} ${player.is_host ? '👑' : ''}</span>
            <b>${readyText}</b>
        `;
        playerList.appendChild(item);
    });
}

function updateUI(data) {
    const countEl = document.getElementById('tileCount');
    if (countEl) countEl.innerText = data.tiles.length;
    
    renderPool(data.active_pool);
    renderPlayers(data.players);

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

    resetTurnTimer(data.settings.draw_time);
}

function resetTurnTimer(duration) {
    clearInterval(drawTimerInterval);
    let secondsLeft = duration;
    const timerDisplay = document.getElementById('draw-timer');
    
    if (!timerDisplay) return;
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

function renderPlayers(players) {
    const board = document.getElementById('playersBoard');
    if (!board) return;
    board.innerHTML = '';

    for (const [sid, player] of Object.entries(players)) {
        const isMe = sid === socket.id;
        const section = document.createElement('section');
        section.style.background = isMe ? 'rgba(52, 152, 219, 0.1)' : 'rgba(0,0,0,0.2)';
        section.style.padding = '20px';
        section.style.borderRadius = '15px';
        section.style.border = isMe ? '2px solid #3498db' : '1px solid rgba(255,255,255,0.1)';

        const wordsHtml = player.words.map(w => `
            <div class="word-block">
                ${w.split('').map(char => `<div class="tile small">${char}</div>`).join('')}
                <span class="word-score-tag">${w.length - 2}</span>
            </div>
        `).join('');

        section.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                <h3 style="margin: 0; color: ${isMe ? '#3498db' : 'white'}">${player.username}</h3>
                <div class="score-badge" style="font-size: 1.8rem;">${player.score || 0}</div>
            </div>
            <div class="words-container" style="display: flex; flex-wrap: wrap; gap: 10px;">
                ${wordsHtml}
            </div>
        `;
        board.appendChild(section);
    }
}

function requestEndGame() {
    hasVotedToEnd = true;
    socket.emit('vote_end_game', { room: ROOM_ID });
}

function updateEndGameUI(votesReceived, votesNeeded) {
    const endGameBtn = document.getElementById('endGameButton');
    if (endGameBtn) {
        endGameBtn.innerText = `END GAME (${votesReceived}/${votesNeeded})`;
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
    const modal = document.createElement('div');
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
    
    const scoresHtml = scores.map(s => `
        <div style="font-size: 1.2rem; margin: 10px; padding: 10px; background: rgba(255,255,255,0.1); border-radius: 8px;">
            ${s.username}: <span style="color: #2ecc71; font-weight: bold;">${s.score} points</span>
        </div>
    `).join('');
    
    modal.innerHTML = `
        <div style="background: #1a252f; padding: 50px; border-radius: 20px; text-align: center; border: 3px solid #2ecc71; max-width: 600px;">
            <h1 style="font-size: 3rem; margin-bottom: 30px; letter-spacing: 2px;">${resultText}</h1>
            <div style="margin-bottom: 40px;">
                ${scoresHtml}
            </div>
            <a href="/homepage" style="text-decoration: none;">
                <button class="btn btn-green" style="padding: 15px 40px; font-size: 1.2rem;">BACK TO HOME</button>
            </a>
        </div>
    `;
    
    document.body.appendChild(modal);
}

/* --- CUSTOM UI FUNCTIONS --- */

function showUsernamePopup() {
    const modal = document.createElement('div');
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
            <input type="text" id="username-input" placeholder="Your name..." 
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
    myUsername = username;
    
    // Remove modal
    const modals = document.querySelectorAll('div[style*="z-index: 10000"]');
    modals.forEach(m => m.remove());
    
    // Emit join event
    socket.emit('join', { room: ROOM_ID, username: myUsername });
    
    // Continue with game
    const wordInput = document.getElementById('wordInput');
    if (wordInput) {
        wordInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') submitWord();
        });
    }
    
    socket.on('connect', () => {
        mySid = socket.id;
    });
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

function showSmallCountdown() {
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
            unlockTextInput();
        }
    }, 1000);
}

function lockTextInput() {
    const input = document.getElementById('wordInput');
    if (input) {
        input.disabled = true;
        input.style.opacity = '0.5';
        input.style.cursor = 'not-allowed';
        input.placeholder = 'Game ending...';
    }
}

function unlockTextInput() {
    const input = document.getElementById('wordInput');
    if (input) {
        input.disabled = false;
        input.style.opacity = '1';
        input.style.cursor = 'text';
        input.placeholder = 'Type word...';
    }
}

function showActionMessage(message) {
    const msgDiv = document.getElementById('statusMessage');
    if (msgDiv) {
        msgDiv.innerText = message;
        msgDiv.style.color = "#f39c12";
        setTimeout(() => msgDiv.innerText = "", 4000);
    }
}