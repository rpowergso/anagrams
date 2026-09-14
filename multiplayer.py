import math
import time
from collections import Counter

from flask import request
from flask_socketio import emit, join_room

from app import socketio
from game import generate_tiles, check_dictionary, same_root

rooms = {}
SILENCE_DURATION_SECONDS = 7
GHOST_GRACE_SECONDS = 60
reconnect_tokens = {}
sid_tokens = {}


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

def can_make_word(target_word, source_letters):
    target_count = Counter(target_word.upper())
    source_count = Counter(source_letters)
    for char, count in target_count.items():
        if source_count[char] < count:
            return False
    return True

@socketio.on('join')
def on_join(data):
    room = data['room']
    username = data.get('username', 'Anonymous')
    reconnect_token = str(data.get('reconnect_token', '')).strip()
    join_room(room)
    
    if room not in rooms:
        rooms[room] = {
            'status': 'lobby',
            'host_sid': request.sid,
            'settings': {
                'tile_preset': 'standard',
                'max_tiles': 60,
                'draw_time': 7,
                'incorrect_word_penalty': True
            },
            'tiles': [],
            'active_pool': [],
            'turn_index': 0,
            'player_order': [],
            'players': {} 
        }
    
    game = rooms[room]
    previous_connection = reconnect_tokens.get(reconnect_token) if reconnect_token else None
    if previous_connection and previous_connection['room'] == room:
        previous_sid = previous_connection['sid']
        if previous_sid in game['players']:
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

    game['players'][request.sid] = {
        'username': username,
        'words': [],
        'score': 0,
        'ready': False,
        'incorrect_attempts': 0,
        'silenced_until': 0,
        'connected': True,
        'disconnected_at': None,
        'is_host': (request.sid == game['host_sid'])
    }
    if reconnect_token:
        sid_tokens[request.sid] = reconnect_token
        reconnect_tokens[reconnect_token] = {'room': room, 'sid': request.sid}
    if request.sid not in game['player_order']:
        game['player_order'].append(request.sid)
    
    emit('lobby_update', game, room=room)

@socketio.on('claim_word')
def on_claim_word(data):
    room = data['room']
    word = data['word'].upper().strip()
    sid = request.sid
    game = rooms.get(room)

    # Better error handling with feedback
    if not game:
        emit('error_message', {'msg': 'Game room not found!'}, room=sid)
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

    if any(word in player['words'] for player in game['players'].values()):
        # Losing a race to a word is not an incorrect guess.
        emit('error_message', {'msg': 'That word is already on the board!'}, room=sid)
        return

    # 1. Try to take from pool only
    if can_make_word(word, game['active_pool']):
        # Remove letters from pool
        for char in word:
            game['active_pool'].remove(char)
        game['players'][sid]['words'].append(word)
        game['players'][sid]['score'] += (len(word) - 2)
        game['players'][sid]['incorrect_attempts'] = 0
        
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
                # Rules: must be longer, and not same root
                if len(word) <= len(existing_word): continue
                if same_root(word, existing_word): continue
                
                # Check if it actually uses at least one pool tile
                needed_from_pool = Counter(word) - Counter(existing_word)
                if not needed_from_pool: continue 

                # Success! Remove pool tiles
                for char, count in needed_from_pool.items():
                    for _ in range(count):
                        game['active_pool'].remove(char)
                
                # Remove word from victim, add to stealer
                player['words'].remove(existing_word)
                player['score'] -= (len(existing_word) - 2)
                
                game['players'][sid]['words'].append(word)
                game['players'][sid]['score'] += (len(word) - 2)
                game['players'][sid]['incorrect_attempts'] = 0
                
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
    room = data['room']
    game = rooms.get(room)
    if game and request.sid == game['host_sid']:
        preset = data.get('tile_preset', 'custom')
        if preset not in ('standard', 'bananagrams', 'custom'):
            preset = 'custom'
        preset_counts = {'standard': 60, 'bananagrams': 144}
        try:
            custom_count = int(data.get('max_tiles', 60))
            draw_time = int(data.get('draw_time', 7))
        except (TypeError, ValueError):
            emit('error_message', {'msg': 'Invalid game settings.'}, room=request.sid)
            return
        game['settings']['tile_preset'] = preset
        game['settings']['max_tiles'] = preset_counts.get(preset, max(20, min(144, custom_count)))
        game['settings']['draw_time'] = max(3, min(20, draw_time))
        penalty_value = data.get(
            'incorrect_word_penalty',
            game['settings'].get('incorrect_word_penalty', True)
        )
        game['settings']['incorrect_word_penalty'] = (
            penalty_value is True or str(penalty_value).lower() == 'true'
        )
        emit('lobby_update', game, room=room)

@socketio.on('toggle_ready')
def on_toggle_ready(data):
    room = data['room']
    game = rooms.get(room)
    if game:
        game['players'][request.sid]['ready'] = not game['players'][request.sid]['ready']
        emit('lobby_update', game, room=room)

@socketio.on('start_game')
def on_start(data):
    room = data['room']
    game = rooms.get(room)
    
    if not game:
        emit('error_message', {'msg': 'Room not found!'}, room=request.sid)
        return
    
    if request.sid != game['host_sid']:
        emit('error_message', {'msg': 'Only the host can start the game!'}, room=request.sid)
        return
    
    # Check if EVERYONE is ready (including host)
    all_ready = all(
        p['ready'] and p.get('connected', True)
        for p in game['players'].values()
    )
    if not all_ready:
        emit('error_message', {'msg': 'Not everyone is ready!'}, room=request.sid)
        return
    
    game['status'] = 'playing'
    game['tiles'] = generate_tiles(
        game['settings']['max_tiles'],
        preset=game['settings'].get('tile_preset', 'standard')
    )
    game['end_game_votes'] = {}  # Initialize end game votes
    emit('game_start', game, room=room)

@socketio.on('draw_tile')
def on_draw(data):
    room = data['room']
    game = rooms.get(room)
    
    if not game:
        emit('error_message', {'msg': 'Game room not found!'}, room=request.sid)
        return
    
    if game['status'] != 'playing':
        emit('error_message', {'msg': 'Game is not in progress!'}, room=request.sid)
        return
    
    # Turn validation
    if not game['player_order'] or game['turn_index'] >= len(game['player_order']):
        emit('error_message', {'msg': 'Invalid game state!'}, room=request.sid)
        return
    
    current_player_sid = game['player_order'][game['turn_index']]
    if request.sid != current_player_sid and data.get('auto') != True:
        emit('error_message', {'msg': 'It is not your turn!'}, room=request.sid)
        return

    if game['tiles']:
        tile = game['tiles'].pop(0)
        game['active_pool'].append(tile)
        # Advance turn
        game['turn_index'] = (game['turn_index'] + 1) % len(game['player_order'])
        emit('update_board', game, room=room)
    else:
        emit('error_message', {'msg': 'No tiles left to draw!'}, room=room)

@socketio.on('vote_end_game')
def on_vote_end_game(data):
    room = data['room']
    game = rooms.get(room)
    
    if not game:
        return
    
    # Initialize end game votes if not present
    if 'end_game_votes' not in game:
        game['end_game_votes'] = {}
    
    # Mark this player as voting to end
    game['end_game_votes'][request.sid] = True
    
    # Check if 2/3 majority reached
    total_players = len(game['players'])
    votes_for_end = len(game['end_game_votes'])
    votes_needed = (total_players * 2) // 3 + (1 if (total_players * 2) % 3 > 0 else 0)
    
    # Send vote update to all players
    emit('end_game_vote', {
        'votes': game['end_game_votes'],
        'players': game['players'],
        'votes_needed': votes_needed
    }, room=room)
    
    # If 2/3 majority reached, start final countdown
    if votes_for_end >= votes_needed:
        # Start 10 second countdown, then end game
        socketio.start_background_task(end_game_countdown, room, game)

def end_game_countdown(room, game):
    time.sleep(10)
    
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
    room = data['room']
    game = rooms.get(room)
    if not game or request.sid not in game['players'] or game['status'] != 'ended':
        emit('error_message', {'msg': 'This game cannot be replayed yet.'}, room=request.sid)
        return

    game['status'] = 'lobby'
    game['tiles'] = []
    game['active_pool'] = []
    game['turn_index'] = 0
    game['end_game_votes'] = {}
    for player in game['players'].values():
        player['words'] = []
        player['score'] = 0
        player['ready'] = False
        player['incorrect_attempts'] = 0
        player['silenced_until'] = 0

    emit('lobby_update', game, room=room)


@socketio.on('disconnect')
def on_disconnect():
    sid = request.sid
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
        return
    game['turn_index'] %= len(game['player_order'])

    if game['host_sid'] == sid:
        game['host_sid'] = game['player_order'][0]
        game['players'][game['host_sid']]['is_host'] = True
    emit_room_state(game, room)
