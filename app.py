import eventlet
eventlet.monkey_patch()

import os
import uuid
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from flask_session import Session
from flask_socketio import SocketIO

# FIXED: Import correctly from respective files
from game import check_dictionary, choose_bot_move, generate_tiles, same_root
from constants import TILE_COUNT, AUTODRAW_INTERVAL_MS

app = Flask(__name__)
app.secret_key = 'anagrams_secret'
app.config['SESSION_TYPE'] = 'filesystem'
Session(app)

# FIXED: Use async_mode='threading' to avoid Python 3.13 eventlet crashes
socketio = SocketIO(app, manage_session=True, cors_allowed_origins="*", async_mode='threading')

@app.route('/')
def home():
    return redirect(url_for('index'))

@app.route('/homepage')
def index():
    return render_template('homepage.html')

# --- MULTIPLAYER ROOM LOBBY ---

@app.route('/create-room')
def create_room():
    room_id = str(uuid.uuid4())[:4].upper()
    return redirect(url_for('multiplayer_game', room_id=room_id))

@app.route('/join-room', methods=['POST'])
def join_room_post():
    room_id = request.form.get('room_id', '').upper().strip()
    if room_id:
        return redirect(url_for('multiplayer_game', room_id=room_id))
    return redirect(url_for('index'))

@app.route('/multiplayer/<room_id>')
def multiplayer_game(room_id):
    return render_template('multiplayergamescreen.html', 
                           room_id=room_id,
                           tile_count=TILE_COUNT, 
                           autodraw_interval=AUTODRAW_INTERVAL_MS)

# --- SOLO AND BOT ROUTES ---

@app.route('/sologamescreen')
def solo_game():
    session['tiles'] = generate_tiles()
    session['zen_mode'] = False
    session.modified = True
    return render_template('sologamescreen.html', tile_count=TILE_COUNT, autodraw_interval=AUTODRAW_INTERVAL_MS)

@app.route('/zengamescreen')
def zen_game():
    session['tiles'] = generate_tiles()
    session['zen_mode'] = True
    session.modified = True
    return render_template('zengamescreen.html', tile_count=TILE_COUNT, autodraw_interval=AUTODRAW_INTERVAL_MS)

@app.route('/botgamescreen', methods=['POST'])
def bot_game():
    difficulty = request.form.get('difficulty', 'medium')
    autodraw_mode = request.form.get('autodraw', 'off')
    session['tiles'] = generate_tiles()
    session.modified = True
    return render_template('botgamescreen.html', 
                           difficulty=difficulty, 
                           autodraw_mode=autodraw_mode,
                           tile_count=TILE_COUNT, 
                           autodraw_interval=AUTODRAW_INTERVAL_MS)

# --- API HELPERS ---

@app.route('/get-tile')
def get_tile():
    tiles = session.get('tiles', [])
    if not tiles:
        # In zen mode, regenerate tiles instead of ending
        if session.get('zen_mode', False):
            tiles = generate_tiles()
            session['tiles'] = tiles
            session.modified = True
        else:
            return jsonify({'tile': None, 'done': True})
    
    tile = tiles.pop(0)
    session['tiles'] = tiles
    session.modified = True
    return jsonify({'tile': tile, 'done': False})

@app.route('/bot-move', methods=['POST'])
def bot_move():
    data = request.get_json() or {}
    active_tiles = data.get('activeTiles', [])
    board_words = data.get('boardWords', [])
    difficulty = data.get('difficulty', 'medium')
    move = choose_bot_move(active_tiles, board_words, difficulty)
    return jsonify(move)

@app.route('/check-word', methods=['POST'])
def check_word():
    word = request.json.get('word', '').lower().strip()
    return jsonify({'valid': check_dictionary(word)})

@app.route('/check-stem', methods=['POST'])
def check_stem():
    w1 = request.json.get('word1', '').lower()
    w2 = request.json.get('word2', '').lower()
    return jsonify({'same_root': same_root(w1, w2)})

# Import multiplayer logic at the end
import multiplayer

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)