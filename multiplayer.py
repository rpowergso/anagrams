# multiplayer.py
from flask import request
from flask_socketio import emit, join_room
from __main__ import socketio
from game import generate_tiles, check_dictionary, same_root
from collections import Counter

rooms = {}

@socketio.on('join')
def on_join(data):
    room = data['room']
    username = data.get('username', 'Anonymous')
    join_room(room)
    
    if room not in rooms:
        rooms[room] = {
            'status': 'lobby', # lobby, playing
            'host_sid': request.sid,
            'settings': {'max_tiles': 60, 'draw_time': 7},
            'tiles': [],
            'active_pool': [],
            'turn_index': 0,
            'player_order': [],
            'players': {} 
        }
    
    game = rooms[room]
    
    # Don't let people join if game already started (optional)
    if game['status'] == 'playing':
        emit('error_message', {'msg': 'Game already in progress'}, room=request.sid)
        return

    game['players'][request.sid] = {
        'username': username,
        'words': [],
        'score': 0,
        'ready': False,
        'is_host': (request.sid == game['host_sid'])
    }
    game['player_order'].append(request.sid)
    
    emit('lobby_update', game, room=room)

@socketio.on('update_settings')
def on_update_settings(data):
    room = data['room']
    game = rooms.get(room)
    if game and request.sid == game['host_sid']:
        game['settings']['max_tiles'] = int(data['max_tiles'])
        game['settings']['draw_time'] = int(data['draw_time'])
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
    if game and request.sid == game['host_sid']:
        # Check if everyone (except host maybe) is ready
        all_ready = all(p['ready'] for sid, p in game['players'].items() if sid != game['host_sid'])
        if not all_ready:
            emit('error_message', {'msg': 'Not everyone is ready!'}, room=request.sid)
            return
        
        game['status'] = 'playing'
        game['tiles'] = generate_tiles(game['settings']['max_tiles'])
        emit('game_start', game, room=room)

@socketio.on('draw_tile')
def on_draw(data):
    room = data['room']
    game = rooms.get(room)
    if not game or game['status'] != 'playing': return
    
    # Turn validation
    current_player_sid = game['player_order'][game['turn_index']]
    if request.sid != current_player_sid and data.get('auto') != True:
        return # Not your turn

    if game['tiles']:
        tile = game['tiles'].pop(0)
        game['active_pool'].append(tile)
        # Advance turn
        game['turn_index'] = (game['turn_index'] + 1) % len(game['player_order'])
        emit('update_board', game, room=room)