import os
import json
import uuid
import time
import urllib.error
import urllib.parse
import urllib.request
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, make_response
from flask_session import Session
from flask_socketio import SocketIO

# FIXED: Import correctly from respective files
from game import (check_dictionary, choose_bot_move, generate_tiles, same_root, get_hints,
                  find_word_extensions, generate_ranked_puzzle, calculate_ranked_delta)
from constants import TILE_COUNT, AUTODRAW_INTERVAL_MS, MIN_WORD_LENGTH

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'anagrams_secret')
app.config['SESSION_TYPE'] = 'filesystem'
Session(app)
ranked_puzzles = {}
RANKED_MAX_STRIKES = 3
definition_cache = {}

# FIXED: Use async_mode='threading' to avoid Python 3.13 eventlet crashes
socketio = SocketIO(app, manage_session=True, cors_allowed_origins="*", async_mode='threading')

@app.route('/')
def home():
    return redirect(url_for('index'))

@app.route('/homepage')
def index():
    return render_template('homepage.html')

@app.route('/word-finder')
@app.route('/word-finder/<word>')
def word_finder(word=''):
    initial_word = word.upper().strip()
    if initial_word and (not initial_word.isalpha() or len(initial_word) > 15):
        return redirect(url_for('word_finder'))
    return render_template('wordfinder.html', initial_word=initial_word)

@app.route('/ranked')
def ranked():
    return redirect(url_for('ranked_puzzles_page'))

@app.route('/rankedpuzzles')
def ranked_puzzles_page():
    response = make_response(render_template('ranked.html'))
    response.headers['Cache-Control'] = 'no-store'
    return response

@app.route('/ranked-puzzle', methods=['POST'])
def ranked_puzzle():
    data = request.get_json() or {}
    try:
        elo = max(0, min(4000, int(data.get('elo', 1000))))
        puzzle = generate_ranked_puzzle(elo)
    except (TypeError, ValueError, RuntimeError) as error:
        return jsonify({'error': str(error)}), 400
    cutoff = time.time() - 3600
    for expired_id in [key for key, value in ranked_puzzles.items() if value['created'] < cutoff]:
        ranked_puzzles.pop(expired_id, None)
    puzzle_id = uuid.uuid4().hex
    ranked_puzzles[puzzle_id] = {**puzzle, 'created': time.time(), 'attempts': 0}
    return jsonify({
        'id': puzzle_id, 'boardWords': puzzle['board_words'], 'pool': puzzle['pool'],
        'flipped': puzzle['flipped'], 'rating': puzzle['rating'],
        'stealableCount': puzzle['stealable_count'], 'legalMoveCount': len(puzzle['solutions']),
    })

@app.route('/ranked-submit', methods=['POST'])
def ranked_submit():
    data = request.get_json() or {}
    puzzle = ranked_puzzles.get(data.get('id'))
    if not puzzle:
        return jsonify({'correct': False, 'failed': True,
                        'message': 'This puzzle is already over. Load the next puzzle.',
                        'error': 'This puzzle is already over. Load the next puzzle.'}), 404
    word = str(data.get('word', '')).upper().strip()
    try:
        elo = max(0, min(4000, int(data.get('elo', 1000))))
    except (TypeError, ValueError):
        elo = 1000
    if not word.isalpha() or len(word) < 3:
        return jsonify({'correct': False, 'message': 'Enter a valid word.'})
    puzzle['attempts'] += 1
    source = puzzle['solutions'].get(word)
    if not source:
        penalty = -min(8, 2 + puzzle['attempts'])
        new_elo = max(0, elo + penalty)
        if puzzle['attempts'] >= RANKED_MAX_STRIKES:
            answers = [{'word': answer, 'source': answer_source}
                       for answer, answer_source in puzzle['solutions'].items()]
            ranked_puzzles.pop(data.get('id'), None)
            return jsonify({
                'correct': False, 'failed': True,
                'message': 'Three strikes — puzzle over.',
                'attempts': puzzle['attempts'], 'delta': penalty,
                'newElo': new_elo, 'answers': answers,
            })
        return jsonify({'correct': False, 'message': 'That is not a legal play.',
                        'attempts': puzzle['attempts'], 'delta': penalty,
                        'strikesLeft': RANKED_MAX_STRIKES - puzzle['attempts'],
                        'newElo': new_elo})
    elapsed = time.time() - puzzle['created']
    delta = calculate_ranked_delta(elo, puzzle['rating'], True, elapsed, puzzle['attempts'] - 1)
    answers = [{'word': answer, 'source': answer_source}
               for answer, answer_source in puzzle['solutions'].items()]
    ranked_puzzles.pop(data.get('id'), None)
    return jsonify({'correct': True, 'word': word, 'source': source, 'delta': delta,
                    'elapsed': round(elapsed, 1), 'newElo': min(4000, elo + delta),
                    'answers': answers})

@app.route('/ranked-give-up', methods=['POST'])
def ranked_give_up():
    data = request.get_json() or {}
    puzzle = ranked_puzzles.pop(data.get('id'), None)
    if not puzzle:
        return jsonify({'message': 'This puzzle is already over. Load the next puzzle.',
                        'error': 'This puzzle is already over. Load the next puzzle.'}), 404
    try:
        elo = max(0, min(4000, int(data.get('elo', 1000))))
    except (TypeError, ValueError):
        elo = 1000
    delta = calculate_ranked_delta(elo, puzzle['rating'], False,
                                   time.time() - puzzle['created'], puzzle['attempts'])
    answers = [{'word': word, 'source': source} for word, source in puzzle['solutions'].items()]
    return jsonify({'delta': delta, 'newElo': max(0, elo + delta), 'answers': answers})

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

@app.route('/word-extensions', methods=['POST'])
def word_extensions():
    data = request.get_json() or {}
    letters = data.get('letters', '').lower().strip()
    reverse = bool(data.get('reverseMode'))
    biggest_only = bool(data.get('biggestOnly'))
    forced_words = [word.strip() for word in data.get('forcedWords', []) if word.strip()]
    raw_forced_letters = data.get('forcedLetters', {})
    try:
        forced_letters = {
            int(step): str(value).strip()
            for step, value in raw_forced_letters.items()
            if str(value).strip()
        }
    except (AttributeError, TypeError, ValueError):
        return jsonify({'error': 'Invalid forced-letter constraints.'}), 400
    if any(not value.isalpha() for value in forced_letters.values()):
        return jsonify({'error': 'Forced letters must contain A–Z only.'}), 400
    if any(not word.isalpha() for word in forced_words):
        return jsonify({'error': 'Forced words must contain A–Z only.'}), 400
    if not letters.isalpha() or len(letters) > 15:
        return jsonify({'error': 'Enter 1–15 letters (A–Z only).'}), 400

    try:
        min_added = int(data.get('minAdded', 1))
        max_added = int(data.get('maxAdded', 5))
        chain_step = int(data.get('chainStep', 1)) if data.get('chainMode') else None
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid addition range.'}), 400

    max_possible = len(letters) - MIN_WORD_LENGTH if reverse else 15 - len(letters)
    if max_possible < 1:
        return jsonify({'groups': []})
    if min_added < 1 or max_added < min_added or max_added > max_possible:
        return jsonify({'error': f'Choose additions between 1 and {max_possible}.'}), 400
    if chain_step is not None and (chain_step < 1 or chain_step > max_possible):
        return jsonify({'error': f'Chain steps must be between 1 and {max_possible}.'}), 400

    search_min = 1 if chain_step else min_added
    groups = find_word_extensions(
        letters, search_min, max_added, chain_step=chain_step, reverse=reverse,
        forced_letters=forced_letters, forced_words=forced_words
    )
    groups = [group for group in groups if group['added'] >= min_added]
    if biggest_only:
        largest_group = next((group for group in reversed(groups) if group['words']), None)
        if not largest_group:
            return jsonify({'groups': [], 'biggest': True})
        chosen_word = largest_group['words'][0]
        largest_group = {
            **largest_group,
            'words': [chosen_word],
            'total': 1,
            'chains': {chosen_word: largest_group['chains'].get(chosen_word, [])},
        }
        return jsonify({'groups': [largest_group], 'biggest': True})
    return jsonify({'groups': groups})

@app.route('/definition/<word>')
def word_definition(word):
    """Return a small definition payload and cache lookups for one day."""
    normalized = word.lower().strip()
    if not normalized.isalpha() or len(normalized) > 30:
        return jsonify({'error': 'Invalid word.'}), 400

    cached = definition_cache.get(normalized)
    if cached and time.time() - cached['stored_at'] < 86400:
        return jsonify(cached['payload'])

    query = urllib.parse.urlencode({'sp': normalized, 'qe': 'sp', 'md': 'd', 'max': 1})
    upstream_request = urllib.request.Request(
        f'https://api.datamuse.com/words?{query}',
        headers={'User-Agent': 'AnagramsWordFinder/1.0'},
    )
    try:
        with urllib.request.urlopen(upstream_request, timeout=2.0) as response:
            results = json.loads(response.read().decode('utf-8'))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return jsonify({'error': 'Definition unavailable.'}), 503

    definitions = []
    if results and results[0].get('word', '').lower() == normalized:
        part_names = {'n': 'noun', 'v': 'verb', 'adj': 'adjective', 'adv': 'adverb', 'u': ''}
        for raw_definition in results[0].get('defs', [])[:6]:
            part, separator, definition = raw_definition.partition('\t')
            definitions.append({
                'partOfSpeech': part_names.get(part, part) if separator else '',
                'definition': definition.strip() if separator else raw_definition.strip(),
            })

    payload = {
        'word': normalized.upper(),
        'isWord': bool(definitions),
        'definitions': definitions,
    }
    if len(definition_cache) >= 500:
        definition_cache.pop(next(iter(definition_cache)))
    definition_cache[normalized] = {'stored_at': time.time(), 'payload': payload}
    return jsonify(payload)

@app.route('/check-stem', methods=['POST'])
def check_stem():
    w1 = request.json.get('word1', '').lower()
    w2 = request.json.get('word2', '').lower()
    return jsonify({'same_root': same_root(w1, w2)})

@app.route('/get-hint', methods=['POST'])
def get_hint():
    data = request.get_json() or {}
    active_tiles = data.get('activeTiles', [])
    board_words = data.get('boardWords', [])
    hints = get_hints(active_tiles, board_words)
    return jsonify(hints)

# Import multiplayer logic at the end
import multiplayer

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
