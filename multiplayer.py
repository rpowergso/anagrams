import math
import threading
import time
import uuid
from collections import Counter, defaultdict, deque

from flask import request
from flask_socketio import emit, join_room

from app import socketio
from game import generate_tiles, check_dictionary, same_root, choose_bot_move

rooms = {}
SILENCE_DURATION_SECONDS = 7
GHOST_GRACE_SECONDS = 300
MAX_PLAYERS_PER_ROOM = 8
MAX_USERNAME_LENGTH = 24
MAX_WORD_LENGTH = 30
BOT_DIFFICULTIES = {'easy', 'medium', 'hard'}
reconnect_tokens = {}
sid_tokens = {}
room_bans = defaultdict(set)
event_buckets = defaultdict(deque)
event_buckets_lock = threading.Lock()


def valid_room_id(room):
    return (isinstance(room, str) and 1 <= len(room) <= 16
            and room.isascii() and room.isalnum())


def bot_sid():
    return f"bot:{uuid.uuid4().hex[:10]}"


def make_bot(difficulty='medium'):
    difficulty = difficulty if difficulty in BOT_DIFFICULTIES else 'medium'
    return {
        'username': 'Bot',
        'words': [],
        'score': 0,
        'ready': True,
        'incorrect_attempts': 0,
        'silenced_until': 0,
        'connected': True,
        'disconnected_at': None,
        'is_host': False,
        'is_bot': True,
        'difficulty': difficulty,
    }


def is_bot_player(game, sid):
    return bool(game['players'].get(sid, {}).get('is_bot'))


def all_board_words(game):
    return [
        word
        for player in game['players'].values()
        for word in player['words']
    ]


def remove_pool_letters(game, letters):
    needed = Counter(''.join(letters).upper())
    available = Counter(''.join(game['active_pool']).upper())
    if not needed <= available:
        return False
    for letter in letters:
        target = letter.upper()
        index = next((
            index for index, tile in enumerate(game['active_pool'])
            if tile.upper() == target
        ), None)
        game['active_pool'].pop(index)
    return True


def apply_bot_move(game, sid, move):
    source_word = move.get('source_word')
    stolen_from = None
    stolen_word = None
    if source_word:
        source_form = source_word.upper()
        for player in game['players'].values():
            stolen_word = next((
                word for word in player['words']
                if word.upper() == source_form
            ), None)
            if stolen_word:
                stolen_from = player
                break
        if not stolen_word:
            return False
    if not remove_pool_letters(game, move.get('pool_letters', [])):
        return False
    if stolen_from and stolen_word:
        stolen_from['words'].remove(stolen_word)
        stolen_from['score'] -= max(0, len(stolen_word) - 2)
    word = move['word']
    game['players'][sid]['words'].append(word)
    game['players'][sid]['score'] += max(0, len(word) - 2)
    give_word_winner_next_draw(game, sid)
    return True


def schedule_bot_turn(room):
    game = rooms.get(room)
    if (not game or game.get('status') != 'playing'
            or game.get('bot_turn_pending') or not game.get('player_order')):
        return
    game['turn_index'] %= len(game['player_order'])
    sid = game['player_order'][game['turn_index']]
    if not is_bot_player(game, sid):
        return
    game['bot_turn_pending'] = True
    socketio.start_background_task(run_bot_turn, room, sid)


def run_bot_turn(room, sid):
    game = rooms.get(room)
    if not game:
        return
    difficulty = game['players'].get(sid, {}).get('difficulty', 'medium')
    move = choose_bot_move(game['active_pool'][:], all_board_words(game), difficulty)
    delay = move.get('delay', 0.8) if move.get('found') else 0.8
    socketio.sleep(max(0.35, min(float(delay), game['settings'].get('draw_time', 20))))

    game = rooms.get(room)
    if (not game or game.get('status') != 'playing' or not game.get('player_order')
            or game['player_order'][game['turn_index']] != sid):
        if game:
            game['bot_turn_pending'] = False
        return

    if move.get('found') and apply_bot_move(game, sid, move):
        source = move.get('source_word')
        action = (f'Bot stole "{source}" to make "{move["word"]}"'
                  if source else f'Bot played "{move["word"]}"')
        socketio.emit('player_action', {'message': action}, room=room)
        socketio.emit('update_board', game, room=room)
        socketio.sleep(0.45)

    game = rooms.get(room)
    if (not game or game.get('status') != 'playing' or not game.get('player_order')
            or game['player_order'][game['turn_index']] != sid):
        if game:
            game['bot_turn_pending'] = False
        return

    if not game['tiles'] and game.get('zen_mode'):
        game['tiles'] = generate_tiles(
            game['settings']['max_tiles'],
            preset=game['settings'].get('tile_preset', 'standard')
        )
    if game['tiles']:
        game['active_pool'].append(game['tiles'].pop(0))
        game['turn_index'] = (game['turn_index'] + 1) % len(game['player_order'])
    game['bot_turn_pending'] = False
    socketio.emit('update_board', game, room=room)
    schedule_bot_turn(room)


def clean_username(value):
    if not isinstance(value, str):
        return None
    username = ' '.join(value.split())
    if not username or len(username) > MAX_USERNAME_LENGTH:
        return None
    allowed_punctuation = set(" _-'.")
    if any(not (char.isalnum() or char in allowed_punctuation) for char in username):
        return None
    return username


def event_limited(event, maximum=90, window_seconds=60):
    now = time.monotonic()
    key = (request.remote_addr or request.sid, event)
    with event_buckets_lock:
        bucket = event_buckets[key]
        cutoff = now - window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= maximum:
            return True
        bucket.append(now)
    return False


def event_room(data, require_player=True):
    if not isinstance(data, dict):
        return None, None
    room = data.get('room')
    if not valid_room_id(room):
        return None, None
    game = rooms.get(room)
    if require_player and (not game or request.sid not in game['players']):
        return room, None
    return room, game


def emit_room_state(game, room):
    event = 'lobby_update' if game['status'] == 'lobby' else 'update_board'
    socketio.emit(event, game, room=room)


def incorrect_attempt_limit(game):
    """Allow more misses as more tiles are revealed, without enabling spam."""
    revealed_tiles = len(game['active_pool']) + sum(
        len(word)
        for player in game['players'].values()
        for word in player['words']
    )
    return max(7, min(12, 6 + math.ceil(revealed_tiles / 12)))


def reject_word(game, sid, message):
    if not game['settings'].get('incorrect_word_penalty', True):
        emit('error_message', {'msg': message}, room=sid)
        return

    player = game['players'][sid]
    player['incorrect_attempts'] = player.get('incorrect_attempts', 0) + 1
    limit = incorrect_attempt_limit(game)

    if player['incorrect_attempts'] >= limit:
        player['incorrect_attempts'] = 0
        player['silenced_until'] = time.time() + SILENCE_DURATION_SECONDS
        emit('silenced', {
            'seconds': SILENCE_DURATION_SECONDS,
            'msg': f'Too many incorrect attempts. Silenced for {SILENCE_DURATION_SECONDS} seconds.'
        }, room=sid)
        return

    attempts_left = limit - player['incorrect_attempts']
    attempt_suffix = '' if attempts_left == 1 else 's'
    emit('error_message', {
        'msg': f'{message} ({attempts_left} incorrect attempt{attempt_suffix} left)'
    }, room=sid)


def give_word_winner_next_draw(game, sid):
    if game['settings'].get('word_winner_draws_next') and sid in game['player_order']:
        game['turn_index'] = game['player_order'].index(sid)

def can_make_word(target_word, source_letters):
    target_count = Counter(target_word.upper())
    source_text = ''.join(source_letters) if not isinstance(source_letters, str) else source_letters
    source_count = Counter(source_text.upper())
    for char, count in target_count.items():
        if source_count[char] < count:
            return False
    return True

@socketio.on('join')
def on_join(data):
    if event_limited('join', 20):
        emit('error_message', {'msg': 'Too many join attempts. Please wait.'}, room=request.sid)
        return
    if not isinstance(data, dict):
        emit('error_message', {'msg': 'Invalid join request.'}, room=request.sid)
        return
    room = data.get('room')
    username = clean_username(data.get('username'))
    reconnect_value = data.get('reconnect_token', '')
    reconnect_token = reconnect_value.strip() if isinstance(reconnect_value, str) else ''
    if (not valid_room_id(room) or username is None or len(reconnect_token) > 128):
        emit('error_message', {
            'msg': 'Use a 1–24 character name with letters, numbers, spaces, apostrophes, periods, hyphens, or underscores.'
        }, room=request.sid)
        return
    
    if room not in rooms:
        initial_bot_difficulty = data.get('initial_bot_difficulty', '')
        if initial_bot_difficulty not in BOT_DIFFICULTIES:
            initial_bot_difficulty = ''
        rooms[room] = {
            'status': 'lobby',
            'host_sid': request.sid,
            'zen_mode': False,
            'settings': {
                'tile_preset': 'standard',
                'max_tiles': 60,
                'draw_time': 20,
                'autodraw_enabled': True,
                'incorrect_word_penalty': True,
                'word_winner_draws_next': False,
                'prefire_enabled': False,
                'paste_allowed': True,
            },
            'tiles': [],
            'active_pool': [],
            'turn_index': 0,
            'player_order': [],
            'players': {},
            'bot_turn_pending': False,
            'pending_initial_bot': initial_bot_difficulty,
        }
    
    game = rooms[room]
    if reconnect_token and reconnect_token in room_bans[room]:
        emit('kicked', {'msg': 'The host removed you from this lobby.'}, room=request.sid)
        return
    previous_connection = reconnect_tokens.get(reconnect_token) if reconnect_token else None
    if previous_connection and previous_connection['room'] == room:
        previous_sid = previous_connection['sid']
        if previous_sid in game['players']:
            join_room(room)
            player = game['players'].pop(previous_sid)
            player['connected'] = True
            player['disconnected_at'] = None
            game['players'][request.sid] = player
            game['player_order'] = [
                request.sid if sid == previous_sid else sid
                for sid in game['player_order']
            ]
            if game['host_sid'] == previous_sid:
                game['host_sid'] = request.sid
            if previous_sid in game.get('end_game_votes', {}):
                game['end_game_votes'][request.sid] = game['end_game_votes'].pop(previous_sid)
            sid_tokens.pop(previous_sid, None)
            sid_tokens[request.sid] = reconnect_token
            reconnect_tokens[reconnect_token] = {'room': room, 'sid': request.sid}
            emit_room_state(game, room)
            return

    if game['status'] == 'playing':
        emit('error_message', {'msg': 'Game already in progress'}, room=request.sid)
        return
    if len(game['players']) >= MAX_PLAYERS_PER_ROOM:
        emit('error_message', {'msg': 'This room is full.'}, room=request.sid)
        return

    join_room(room)

    game['players'][request.sid] = {
        'username': username,
        'words': [],
        'score': 0,
        'ready': False,
        'incorrect_attempts': 0,
        'silenced_until': 0,
        'connected': True,
        'disconnected_at': None,
        'is_host': (request.sid == game['host_sid']),
        'is_bot': False,
    }
    if reconnect_token:
        sid_tokens[request.sid] = reconnect_token
        reconnect_tokens[reconnect_token] = {'room': room, 'sid': request.sid}
    if request.sid not in game['player_order']:
        game['player_order'].append(request.sid)
    initial_bot_difficulty = game.pop('pending_initial_bot', '')
    if initial_bot_difficulty:
        new_bot_sid = bot_sid()
        game['players'][new_bot_sid] = make_bot(initial_bot_difficulty)
        game['player_order'].append(new_bot_sid)
    
    emit('lobby_update', game, room=room)

@socketio.on('claim_word')
def on_claim_word(data):
    sid = request.sid
    if event_limited('claim_word', 90):
        emit('error_message', {'msg': 'Too many submissions. Please slow down.'}, room=sid)
        return
    room, game = event_room(data)
    submitted_word = data.get('word') if isinstance(data, dict) else None

    # Better error handling with feedback
    if not game:
        emit('error_message', {'msg': 'Game room not found!'}, room=sid)
        return
    if not isinstance(submitted_word, str) or len(submitted_word) > MAX_WORD_LENGTH:
        reject_word(game, sid, 'Invalid word!')
        return
    word = submitted_word.upper().strip()
    if not word.isascii() or not word.isalpha():
        reject_word(game, sid, 'Words may contain letters A-Z only!')
        return
    
    if game['status'] != 'playing':
        emit('error_message', {'msg': 'Game is not in progress!'}, room=sid)
        return

    if sid not in game['players']:
        emit('error_message', {'msg': 'Player not found in game!'}, room=sid)
        return

    silence_remaining = math.ceil(game['players'][sid].get('silenced_until', 0) - time.time())
    if silence_remaining > 0:
        emit('silenced', {
            'seconds': silence_remaining,
            'msg': f'You are silenced for {silence_remaining} more seconds.'
        }, room=sid)
        return
    
    if len(word) < 3:
        reject_word(game, sid, 'Word must be at least 3 letters!')
        return

    if not check_dictionary(word):
        reject_word(game, sid, 'Not a valid dictionary word!')
        return

    if any(
        existing.upper() == word
        for player in game['players'].values()
        for existing in player['words']
    ):
        # Losing a race to a word is not an incorrect guess.
        emit('error_message', {'msg': 'That word is already on the board!'}, room=sid)
        return

    # 1. Try to take from pool only
    if can_make_word(word, game['active_pool']):
        # Remove letters from pool
        remove_pool_letters(game, word)
        game['players'][sid]['words'].append(word)
        game['players'][sid]['score'] += (len(word) - 2)
        game['players'][sid]['incorrect_attempts'] = 0
        give_word_winner_next_draw(game, sid)
        
        # Broadcast action
        player_name = game['players'][sid]['username']
        emit('player_action', {
            'message': f"✓ {player_name} played \"{word}\""
        }, room=room)
        
        emit('update_board', game, room=room)
        return

    # 2. Try to steal from any player
    for target_sid, player in game['players'].items():
        for existing_word in player['words']:
            # A steal must use letters from the existing word + at least 1 from the pool
            combined_letters = list(existing_word.upper()) + game['active_pool']
            
            if can_make_word(word, combined_letters):
                # A steal must retain every letter from the word being stolen.
                if not can_make_word(existing_word, word): continue

                # Rules: must be longer, and not same root
                if len(word) <= len(existing_word): continue
                if same_root(word, existing_word): continue
                
                # Check if it actually uses at least one pool tile
                needed_from_pool = Counter(word) - Counter(existing_word.upper())
                if not needed_from_pool: continue 

                # Success! Remove pool tiles
                remove_pool_letters(game, list(needed_from_pool.elements()))
                
                # Remove word from victim, add to stealer
                player['words'].remove(existing_word)
                player['score'] -= (len(existing_word) - 2)
                
                game['players'][sid]['words'].append(word)
                game['players'][sid]['score'] += (len(word) - 2)
                game['players'][sid]['incorrect_attempts'] = 0
                give_word_winner_next_draw(game, sid)
                
                # Broadcast action
                stealer_name = game['players'][sid]['username']
                victim_name = player['username']
                emit('player_action', {
                    'message': f"🔥 {stealer_name} STOLE \"{existing_word}\" from {victim_name} to make \"{word}\""
                }, room=room)
                
                emit('update_board', game, room=room)
                return

    reject_word(game, sid, 'Cannot form word with available tiles')

@socketio.on('update_settings')
def on_update_settings(data):
    room, game = event_room(data)
    if game and request.sid == game['host_sid']:
        preset = data.get('tile_preset', 'custom')
        if preset not in ('standard', 'bananagrams', 'custom'):
            preset = 'custom'
        preset_counts = {'standard': 60, 'bananagrams': 144}
        try:
            custom_count = int(data.get('max_tiles', 60))
            draw_time = int(data.get('draw_time', 20))
        except (TypeError, ValueError):
            emit('error_message', {'msg': 'Invalid game settings.'}, room=request.sid)
            return
        game['settings']['tile_preset'] = preset
        game['settings']['max_tiles'] = preset_counts.get(preset, max(20, min(144, custom_count)))
        game['settings']['draw_time'] = max(3, min(60, draw_time))
        autodraw_value = data.get(
            'autodraw_enabled',
            game['settings'].get('autodraw_enabled', True)
        )
        game['settings']['autodraw_enabled'] = (
            autodraw_value is True or str(autodraw_value).lower() == 'true'
        )
        penalty_value = data.get(
            'incorrect_word_penalty',
            game['settings'].get('incorrect_word_penalty', True)
        )
        game['settings']['incorrect_word_penalty'] = (
            penalty_value is True or str(penalty_value).lower() == 'true'
        )
        winner_draw_value = data.get(
            'word_winner_draws_next',
            game['settings'].get('word_winner_draws_next', False)
        )
        game['settings']['word_winner_draws_next'] = (
            winner_draw_value is True or str(winner_draw_value).lower() == 'true'
        )
        prefire_value = data.get(
            'prefire_enabled',
            game['settings'].get('prefire_enabled', False)
        )
        game['settings']['prefire_enabled'] = (
            prefire_value is True or str(prefire_value).lower() == 'true'
        )
        paste_value = data.get(
            'paste_allowed',
            game['settings'].get('paste_allowed', True)
        )
        game['settings']['paste_allowed'] = (
            paste_value is True or str(paste_value).lower() == 'true'
        )
        emit('lobby_update', game, room=room)


@socketio.on('add_bot')
def on_add_bot(data):
    room, game = event_room(data)
    if (not game or request.sid != game['host_sid']
            or game['status'] != 'lobby'):
        return
    if len(game['players']) >= MAX_PLAYERS_PER_ROOM:
        emit('error_message', {'msg': 'This lobby is full.'}, room=request.sid)
        return
    difficulty = data.get('difficulty', 'medium')
    new_bot_sid = bot_sid()
    game['players'][new_bot_sid] = make_bot(difficulty)
    game['player_order'].append(new_bot_sid)
    emit('lobby_update', game, room=room)


@socketio.on('remove_bot')
def on_remove_bot(data):
    room, game = event_room(data)
    target_sid = data.get('sid') if isinstance(data, dict) else None
    if (not game or request.sid != game['host_sid']
            or game['status'] != 'lobby' or not is_bot_player(game, target_sid)):
        return
    game['players'].pop(target_sid, None)
    game['player_order'] = [sid for sid in game['player_order'] if sid != target_sid]
    emit('lobby_update', game, room=room)


@socketio.on('update_bot_difficulty')
def on_update_bot_difficulty(data):
    room, game = event_room(data)
    target_sid = data.get('sid') if isinstance(data, dict) else None
    difficulty = data.get('difficulty') if isinstance(data, dict) else None
    if (not game or request.sid != game['host_sid']
            or game['status'] != 'lobby' or not is_bot_player(game, target_sid)
            or difficulty not in BOT_DIFFICULTIES):
        return
    game['players'][target_sid]['difficulty'] = difficulty
    emit('lobby_update', game, room=room)


@socketio.on('kick_player')
def on_kick_player(data):
    room, game = event_room(data)
    target_sid = data.get('sid') if isinstance(data, dict) else None
    if (not game or request.sid != game['host_sid']
            or game['status'] != 'lobby' or target_sid == game['host_sid']
            or target_sid not in game['players'] or is_bot_player(game, target_sid)):
        return
    token = sid_tokens.pop(target_sid, None)
    if token:
        room_bans[room].add(token)
        reconnect_tokens.pop(token, None)
    game['players'].pop(target_sid, None)
    game['player_order'] = [sid for sid in game['player_order'] if sid != target_sid]
    socketio.emit('kicked', {'msg': 'The host removed you from this lobby.'}, room=target_sid)
    emit('lobby_update', game, room=room)

@socketio.on('toggle_ready')
def on_toggle_ready(data):
    room, game = event_room(data)
    if game:
        game['players'][request.sid]['ready'] = not game['players'][request.sid]['ready']
        emit('lobby_update', game, room=room)

@socketio.on('start_game')
def on_start(data):
    room, game = event_room(data)
    
    if not game:
        emit('error_message', {'msg': 'Room not found!'}, room=request.sid)
        return
    
    if request.sid != game['host_sid']:
        emit('error_message', {'msg': 'Only the host can start the game!'}, room=request.sid)
        return
    
    human_players = [
        player for player in game['players'].values()
        if not player.get('is_bot')
    ]
    all_ready = len(human_players) == 1 or all(
        player['ready'] and player.get('connected', True)
        for player in human_players
    )
    if not all_ready:
        emit('error_message', {'msg': 'Not everyone is ready!'}, room=request.sid)
        return
    
    game['status'] = 'playing'
    game['zen_mode'] = (
        len(human_players) == 1
        and not any(player.get('is_bot') for player in game['players'].values())
    )
    game['tiles'] = generate_tiles(
        game['settings']['max_tiles'],
        preset=game['settings'].get('tile_preset', 'standard')
    )
    game['end_game_votes'] = {}  # Initialize end game votes
    emit('game_start', game, room=room)
    schedule_bot_turn(room)

@socketio.on('draw_tile')
def on_draw(data):
    room, game = event_room(data)
    
    if not game:
        emit('error_message', {'msg': 'Game room not found!'}, room=request.sid)
        return
    
    if game['status'] != 'playing':
        emit('error_message', {'msg': 'Game is not in progress!'}, room=request.sid)
        return
    if data.get('auto') and not game['settings'].get('autodraw_enabled', True):
        return
    
    # Turn validation
    if not game['player_order'] or game['turn_index'] >= len(game['player_order']):
        emit('error_message', {'msg': 'Invalid game state!'}, room=request.sid)
        return
    
    current_player_sid = game['player_order'][game['turn_index']]
    if request.sid != current_player_sid:
        emit('error_message', {'msg': 'It is not your turn!'}, room=request.sid)
        return

    if not game['tiles'] and game.get('zen_mode'):
        game['tiles'] = generate_tiles(
            game['settings']['max_tiles'],
            preset=game['settings'].get('tile_preset', 'standard')
        )
    if game['tiles']:
        tile = game['tiles'].pop(0)
        game['active_pool'].append(tile)
        # Advance turn
        game['turn_index'] = (game['turn_index'] + 1) % len(game['player_order'])
        emit('update_board', game, room=room)
        schedule_bot_turn(room)
    else:
        emit('error_message', {'msg': 'No tiles left to draw!'}, room=room)

@socketio.on('vote_end_game')
def on_vote_end_game(data):
    room, game = event_room(data)
    
    if not game or game.get('status') != 'playing':
        return
    
    # Initialize end game votes if not present
    if 'end_game_votes' not in game:
        game['end_game_votes'] = {}
    
    # Mark this player as voting to end
    game['end_game_votes'][request.sid] = True
    
    # Check if 2/3 majority reached
    human_sids = {
        sid for sid, player in game['players'].items()
        if not player.get('is_bot')
    }
    total_players = len(human_sids)
    votes_for_end = len(set(game['end_game_votes']) & human_sids)
    votes_needed = (total_players * 2) // 3 + (1 if (total_players * 2) % 3 > 0 else 0)
    immediate_end = bool(game.get('zen_mode') and total_players == 1)
    
    # Send vote update to all players
    emit('end_game_vote', {
        'votes': game['end_game_votes'],
        'players': game['players'],
        'votes_needed': votes_needed,
        'immediate': immediate_end,
    }, room=room)
    
    # If 2/3 majority reached, start final countdown
    if votes_for_end >= votes_needed and not game.get('end_countdown_started'):
        game['end_countdown_started'] = True
        if immediate_end:
            finish_game(room, game)
        else:
            # Give multiplayer and bot games a final 10-second window.
            socketio.start_background_task(end_game_countdown, room, game)

def end_game_countdown(room, game):
    socketio.sleep(10)
    finish_game(room, game)


def finish_game(room, game):
    if rooms.get(room) is not game or game.get('status') != 'playing':
        return

    # Calculate final scores and announce winner
    final_scores = {}
    for sid, player in game['players'].items():
        final_scores[sid] = player['score']
    
    game['status'] = 'ended'
    socketio.emit('game_ended', {
        'final_scores': final_scores,
        'players': game['players']
    }, room=room)


@socketio.on('replay_game')
def on_replay_game(data):
    room, game = event_room(data)
    if not game or request.sid not in game['players'] or game['status'] != 'ended':
        emit('error_message', {'msg': 'This game cannot be replayed yet.'}, room=request.sid)
        return

    game['status'] = 'lobby'
    game['tiles'] = []
    game['active_pool'] = []
    game['turn_index'] = 0
    game['end_game_votes'] = {}
    game['end_countdown_started'] = False
    for player in game['players'].values():
        player['words'] = []
        player['score'] = 0
        player['ready'] = bool(player.get('is_bot'))
        player['incorrect_attempts'] = 0
        player['silenced_until'] = 0
    game['zen_mode'] = False
    game['bot_turn_pending'] = False

    emit('lobby_update', game, room=room)


@socketio.on('disconnect')
def on_disconnect():
    sid = request.sid
    with event_buckets_lock:
        for key in [key for key in event_buckets if key[0] == sid]:
            event_buckets.pop(key, None)
    reconnect_token = sid_tokens.pop(sid, None)
    if not reconnect_token:
        return
    connection = reconnect_tokens.get(reconnect_token)
    if not connection:
        return
    room = connection['room']
    game = rooms.get(room)
    if not game or sid not in game['players']:
        return

    disconnected_at = time.time()
    game['players'][sid]['connected'] = False
    game['players'][sid]['disconnected_at'] = disconnected_at
    emit_room_state(game, room)
    socketio.start_background_task(
        remove_expired_ghost, room, sid, reconnect_token, disconnected_at
    )


def remove_expired_ghost(room, sid, reconnect_token, disconnected_at):
    socketio.sleep(GHOST_GRACE_SECONDS)
    game = rooms.get(room)
    if not game:
        return
    player = game['players'].get(sid)
    if not player or player.get('connected') or player.get('disconnected_at') != disconnected_at:
        return

    game['players'].pop(sid, None)
    connection = reconnect_tokens.get(reconnect_token)
    if connection == {'room': room, 'sid': sid}:
        reconnect_tokens.pop(reconnect_token, None)
    game.get('end_game_votes', {}).pop(sid, None)
    if sid in game['player_order']:
        removed_index = game['player_order'].index(sid)
        game['player_order'].remove(sid)
        if removed_index < game['turn_index']:
            game['turn_index'] -= 1
    if not game['player_order']:
        rooms.pop(room, None)
        room_bans.pop(room, None)
        return
    game['turn_index'] %= len(game['player_order'])

    if game['host_sid'] == sid:
        next_host = next((
            player_sid for player_sid in game['player_order']
            if not game['players'][player_sid].get('is_bot')
        ), None)
        if next_host is None:
            rooms.pop(room, None)
            room_bans.pop(room, None)
            return
        game['host_sid'] = next_host
        game['players'][next_host]['is_host'] = True
    emit_room_state(game, room)
    schedule_bot_turn(room)
