import os
import json
import secrets
import sys
import threading
import uuid
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict, deque
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, make_response
from flask_session import Session
from flask_socketio import SocketIO

# FIXED: Import correctly from respective files
from game import (check_dictionary, choose_bot_move, generate_tiles, same_root, get_hints,
                  find_word_extensions, generate_ranked_puzzle, calculate_ranked_delta)
from constants import TILE_COUNT, AUTODRAW_INTERVAL_MS, MIN_WORD_LENGTH

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
app.config['SESSION_TYPE'] = 'filesystem'
app.config['MAX_CONTENT_LENGTH'] = 64 * 1024
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('COOKIE_SECURE', '').lower() == 'true'
Session(app)
ranked_puzzles = {}
RANKED_MAX_STRIKES = 3
definition_cache = {}

MAX_WORD_LENGTH = 30
MAX_BOARD_WORDS = 100
MAX_GAME_TILES = 200
_rate_limit_buckets = defaultdict(deque)
_rate_limit_lock = threading.Lock()


def _configured_origins():
    """Use same-origin Socket.IO by default; allow explicit deployment origins."""
    raw_origins = os.environ.get('ALLOWED_ORIGINS', '')
    origins = [origin.strip() for origin in raw_origins.split(',') if origin.strip()]
    return origins or None


def _json_object():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def _limited(key, maximum, window_seconds):
    """Small in-process limiter for endpoints that do dictionary or network work."""
    now = time.monotonic()
    client = request.remote_addr or 'unknown'
    bucket_key = (client, key)
    with _rate_limit_lock:
        bucket = _rate_limit_buckets[bucket_key]
        cutoff = now - window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= maximum:
            return True
        bucket.append(now)
    return False


def _valid_string_list(value, maximum_items, maximum_length, alphabet=None):
    if not isinstance(value, list) or len(value) > maximum_items:
        return False
    for item in value:
        if not isinstance(item, str) or len(item) > maximum_length:
            return False
        if alphabet == 'en' and (not item or not item.isascii() or not item.isalpha()):
            return False
    return True

# Socket.IO enforces same-origin unless ALLOWED_ORIGINS explicitly names trusted sites.
socketio = SocketIO(
    app,
    manage_session=True,
    cors_allowed_origins=_configured_origins(),
    max_http_buffer_size=64 * 1024,
    async_mode='threading',
)


@app.after_request
def add_security_headers(response):
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'DENY')
    response.headers.setdefault('Referrer-Policy', 'same-origin')
    response.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
    return response


@app.errorhandler(413)
def request_too_large(_error):
    return jsonify({'error': 'Request is too large.'}), 413

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
    if _limited('ranked-puzzle', 20, 60):
        return jsonify({'error': 'Too many requests. Please slow down.'}), 429
    data = _json_object()
    if data is None:
        return jsonify({'error': 'Expected a JSON object.'}), 400
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
    data = _json_object()
    if data is None:
        return jsonify({'error': 'Expected a JSON object.'}), 400
    puzzle = ranked_puzzles.get(data.get('id'))
    if not puzzle:
        return jsonify({'correct': False, 'failed': True,
                        'message': 'This puzzle is already over. Load the next puzzle.',
                        'error': 'This puzzle is already over. Load the next puzzle.'}), 404
    submitted_word = data.get('word', '')
    if not isinstance(submitted_word, str) or len(submitted_word) > MAX_WORD_LENGTH:
        return jsonify({'correct': False, 'message': 'Enter a valid word.'}), 400
    word = submitted_word.upper().strip()
    try:
        elo = max(0, min(4000, int(data.get('elo', 1000))))
    except (TypeError, ValueError):
        elo = 1000
    if not word.isascii() or not word.isalpha() or len(word) < 3:
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
    data = _json_object()
    if data is None:
        return jsonify({'error': 'Expected a JSON object.'}), 400
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
    bot = request.args.get('bot', '')
    if bot not in {'easy', 'medium', 'hard'}:
        bot = ''
    return redirect(url_for('multiplayer_game', room_id=room_id, bot=bot))

@app.route('/join-room', methods=['POST'])
def join_room_post():
    room_id = request.form.get('room_id', '').upper().strip()
    if len(room_id) == 4 and room_id.isascii() and room_id.isalnum():
        return redirect(url_for('multiplayer_game', room_id=room_id))
    return redirect(url_for('index'))

@app.route('/multiplayer/<room_id>')
def multiplayer_game(room_id):
    room_id = room_id.upper().strip()
    if len(room_id) != 4 or not room_id.isascii() or not room_id.isalnum():
        return redirect(url_for('index'))
    bot = request.args.get('bot', '')
    if bot not in {'easy', 'medium', 'hard'}:
        bot = ''
    return render_template('multiplayergamescreen.html', 
                           room_id=room_id,
                           initial_bot_difficulty=bot,
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
    """Legacy entry point: bot games now live inside multiplayer lobbies."""
    difficulty = request.form.get('difficulty', 'medium')
    if difficulty not in {'easy', 'medium', 'hard'}:
        difficulty = 'medium'
    return redirect(url_for('create_room', bot=difficulty))

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
    if _limited('bot-move', 60, 60):
        return jsonify({'error': 'Too many requests. Please slow down.'}), 429
    data = _json_object()
    if data is None:
        return jsonify({'error': 'Expected a JSON object.'}), 400
    active_tiles = data.get('activeTiles', [])
    board_words = data.get('boardWords', [])
    difficulty = data.get('difficulty', 'medium')
    if difficulty not in {'easy', 'medium', 'hard'}:
        return jsonify({'error': 'Invalid game options.'}), 400
    if (not _valid_string_list(active_tiles, MAX_GAME_TILES, 1, 'en')
            or not _valid_string_list(board_words, MAX_BOARD_WORDS, MAX_WORD_LENGTH, 'en')):
        return jsonify({'error': 'Invalid game state.'}), 400
    move = choose_bot_move(active_tiles, board_words, difficulty)
    return jsonify(move)

@app.route('/check-word', methods=['POST'])
def check_word():
    if _limited('check-word', 120, 60):
        return jsonify({'error': 'Too many requests. Please slow down.'}), 429
    data = _json_object()
    if data is None:
        return jsonify({'error': 'Expected a JSON object.'}), 400
    word = data.get('word', '')
    if not isinstance(word, str) or len(word) > MAX_WORD_LENGTH:
        return jsonify({'error': 'Invalid word.'}), 400
    normalized = word.lower().strip()
    if not normalized.isascii() or not normalized.isalpha():
        return jsonify({'valid': False})
    return jsonify({'valid': check_dictionary(normalized)})

@app.route('/word-extensions', methods=['POST'])
def word_extensions():
    if _limited('word-extensions', 30, 60):
        return jsonify({'error': 'Too many requests. Please slow down.'}), 429
    data = _json_object()
    if data is None:
        return jsonify({'error': 'Expected a JSON object.'}), 400
    if not isinstance(data.get('letters', ''), str):
        return jsonify({'error': 'Invalid letters.'}), 400
    letters = data.get('letters', '').lower().strip()
    reverse = bool(data.get('reverseMode'))
    biggest_only = bool(data.get('biggestOnly'))
    submitted_forced_words = data.get('forcedWords', [])
    if (not isinstance(submitted_forced_words, list)
            or len(submitted_forced_words) > 15
            or any(not isinstance(word, str) or len(word) > 15 for word in submitted_forced_words)):
        return jsonify({'error': 'Invalid forced-word constraints.'}), 400
    forced_words = [word.strip() for word in submitted_forced_words if word.strip()]
    raw_forced_letters = data.get('forcedLetters', {})
    if not isinstance(raw_forced_letters, dict) or len(raw_forced_letters) > 15:
        return jsonify({'error': 'Invalid forced-letter constraints.'}), 400
    try:
        forced_letters = {
            int(step): str(value).strip()
            for step, value in raw_forced_letters.items()
            if str(value).strip()
        }
    except (AttributeError, TypeError, ValueError):
        return jsonify({'error': 'Invalid forced-letter constraints.'}), 400
    if any(len(value) > 14 or not value.isascii() or not value.isalpha()
           for value in forced_letters.values()):
        return jsonify({'error': 'Forced letters must contain A–Z only.'}), 400
    if any(not word.isascii() or not word.isalpha() for word in forced_words):
        return jsonify({'error': 'Forced words must contain A–Z only.'}), 400
    if not letters.isascii() or not letters.isalpha() or len(letters) > 15:
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
    if _limited('definition', 40, 60):
        return jsonify({'error': 'Too many requests. Please slow down.'}), 429
    normalized = word.lower().strip()
    if not normalized.isascii() or not normalized.isalpha() or len(normalized) > 30:
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
    if _limited('check-stem', 120, 60):
        return jsonify({'error': 'Too many requests. Please slow down.'}), 429
    data = _json_object()
    if data is None:
        return jsonify({'error': 'Expected a JSON object.'}), 400
    w1 = data.get('word1', '')
    w2 = data.get('word2', '')
    if (not isinstance(w1, str) or not isinstance(w2, str)
            or len(w1) > MAX_WORD_LENGTH or len(w2) > MAX_WORD_LENGTH):
        return jsonify({'error': 'Invalid words.'}), 400
    if (not w1.isascii() or not w1.isalpha()
            or not w2.isascii() or not w2.isalpha()):
        return jsonify({'error': 'Invalid words.'}), 400
    return jsonify({'same_root': same_root(w1.lower(), w2.lower())})

@app.route('/get-hint', methods=['POST'])
def get_hint():
    if _limited('get-hint', 30, 60):
        return jsonify({'error': 'Too many requests. Please slow down.'}), 429
    data = _json_object()
    if data is None:
        return jsonify({'error': 'Expected a JSON object.'}), 400
    active_tiles = data.get('activeTiles', [])
    board_words = data.get('boardWords', [])
    if (not _valid_string_list(active_tiles, MAX_GAME_TILES, 1, 'en')
            or not _valid_string_list(board_words, MAX_BOARD_WORDS, MAX_WORD_LENGTH, 'en')):
        return jsonify({'error': 'Invalid game state.'}), 400
    hints = get_hints(active_tiles, board_words)
    return jsonify(hints)

# When launched with ``python app.py``, make ``from app import socketio`` in
# multiplayer.py resolve to this same module instead of importing a second app
# instance with a different Socket.IO server.
if __name__ == '__main__':
    sys.modules.setdefault('app', sys.modules[__name__])

# Import multiplayer logic at the end
import multiplayer

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
