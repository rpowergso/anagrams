from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from flask_session import Session
from game import check_dictionary, choose_bot_move, generate_tiles, same_root
from constants import TILE_COUNT, AUTODRAW_INTERVAL_MS

app = Flask(__name__)
app.secret_key = 'anagrams_secret'
app.config['SESSION_TYPE'] = 'filesystem'
Session(app)

@app.route('/')
def home():
    return redirect(url_for('index'))

@app.route('/homepage')
def index():
    return render_template('homepage.html')

@app.route('/sologamescreen')
def solo_game():
    session['tiles'] = generate_tiles()
    session.modified = True
    return render_template('sologamescreen.html', tile_count=TILE_COUNT, autodraw_interval=AUTODRAW_INTERVAL_MS)

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

@app.route('/get-tile')
def get_tile():
    tiles = session.get('tiles', [])
    if not tiles:
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

@app.route('/voicetest')
def voicetest():
    return render_template('voicetest.html')

if __name__ == '__main__':
    app.run(debug=True)