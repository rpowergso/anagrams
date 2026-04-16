const socket = io();
let myUsername = "";
let mySid = "";
let isMyTurn = false;
let drawTimerInterval = null;

document.addEventListener('DOMContentLoaded', () => {
    // 1. Join logic
    myUsername = prompt("Enter your username:") || "Player_" + Math.floor(Math.random() * 1000);
    socket.emit('join', { room: ROOM_ID, username: myUsername });

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

/* --- ACTIONS --- */

function toggleReady() {
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
    
    if (turnIndicator) {
        const currentName = data.players[currentTurnSid].username;
        turnIndicator.innerText = isMyTurn ? "IT IS YOUR TURN!" : `${currentName.toUpperCase()} IS DRAWING...`;
        turnIndicator.style.color = isMyTurn ? "#2ecc71" : "#f1c40f";
    }

    if (drawBtn) {
        drawBtn.disabled = !isMyTurn;
        // Visual "Lock" Feedback
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