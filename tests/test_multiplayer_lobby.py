import unittest
from unittest.mock import patch

from app import app, socketio
from multiplayer import reconnect_tokens, room_bans, rooms, sid_tokens


class MultiplayerLobbyTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, SECRET_KEY='lobby-test-key')
        rooms.clear()
        reconnect_tokens.clear()
        sid_tokens.clear()
        room_bans.clear()
        self.http_client = app.test_client()
        self.host = socketio.test_client(app, flask_test_client=self.http_client)
        self.host.emit('join', {
            'room': 'TEST', 'username': 'Host',
            'reconnect_token': 'host-token',
        })
        self.host.get_received()

    def tearDown(self):
        if self.host.is_connected():
            self.host.disconnect()
        rooms.clear()
        reconnect_tokens.clear()
        sid_tokens.clear()
        room_bans.clear()

    def test_default_room_settings(self):
        self.assertEqual(rooms['TEST']['settings'], {
            'tile_preset': 'bananagrams',
            'max_tiles': 144,
            'draw_time': 20,
            'autodraw_enabled': True,
            'incorrect_word_penalty': False,
            'word_winner_draws_next': True,
            'prefire_enabled': True,
            'paste_allowed': False,
            'word_delay': 'balanced',
        })

    def test_room_word_delay_applies_to_submissions(self):
        for mode, delay in [('snappy', 0), ('balanced', 0.25), ('classic', 0.75)]:
            with self.subTest(mode=mode):
                self.host.emit('update_settings', {'room': 'TEST', 'word_delay': mode})
                self.host.emit('update_settings', {'room': 'TEST', 'word_delay': []})
                self.host.emit('start_game', {'room': 'TEST'})
                game = rooms['TEST']
                self.assertEqual(game['settings']['word_delay'], mode)
                game['active_pool'] = list('CAT')
                with patch.object(socketio, 'sleep') as sleep:
                    self.host.emit('claim_word', {'room': 'TEST', 'word': 'CAT'})
                if delay:
                    sleep.assert_called_once_with(delay)
                else:
                    sleep.assert_not_called()
                self.assertEqual(game['players'][game['host_sid']]['words'], ['CAT'])
                self.host.emit('vote_end_game', {'room': 'TEST'})
                self.host.emit('replay_game', {'room': 'TEST'})

    def test_late_joiner_can_watch_and_cannot_play(self):
        self.host.emit('start_game', {'room': 'TEST'})
        game = rooms['TEST']
        guest = socketio.test_client(app)
        try:
            guest.emit('join', {
                'room': 'TEST', 'username': 'Observer', 'reconnect_token': 'observer-token',
            })
            [snapshot] = [message['args'][0] for message in guest.get_received()
                          if message['name'] == 'update_board']
            self.assertEqual(snapshot['tiles_remaining'], 144)
            self.assertNotIn('tiles', snapshot)
            self.assertEqual(game['player_order'], [game['host_sid']])

            game['active_pool'] = list('CAT')
            guest.emit('claim_word', {'room': 'TEST', 'word': 'CAT'})
            guest.emit('draw_tile', {'room': 'TEST'})
            guest.emit('vote_end_game', {'room': 'TEST'})
            self.assertEqual(game['active_pool'], list('CAT'))
            self.assertEqual(len(game['tiles']), 144)
            self.assertFalse(game['end_game_votes'])
            guest.get_received()

            self.host.emit('draw_tile', {'room': 'TEST'})
            [snapshot] = [message['args'][0] for message in guest.get_received()
                          if message['name'] == 'update_board']
            self.assertEqual(snapshot['tiles_remaining'], 143)
            self.assertEqual(len(snapshot['active_pool']), 4)

            self.host.emit('vote_end_game', {'room': 'TEST'})
            guest.emit('replay_game', {'room': 'TEST'})
            self.assertEqual(game['status'], 'ended')
            self.assertTrue(any(message['name'] == 'game_ended' for message in guest.get_received()))
        finally:
            guest.disconnect()

    def test_host_can_add_and_configure_bot(self):
        self.host.emit('add_bot', {'room': 'TEST', 'difficulty': 'easy'})
        bot_sid = next(
            sid for sid, player in rooms['TEST']['players'].items()
            if player.get('is_bot')
        )
        self.assertEqual(rooms['TEST']['players'][bot_sid]['difficulty'], 'easy')

        self.host.emit('update_bot_difficulty', {
            'room': 'TEST', 'sid': bot_sid, 'difficulty': 'hard',
        })
        self.assertEqual(rooms['TEST']['players'][bot_sid]['difficulty'], 'hard')

        self.host.emit('remove_bot', {'room': 'TEST', 'sid': bot_sid})
        self.assertNotIn(bot_sid, rooms['TEST']['players'])

    def test_starting_alone_enters_zen_mode(self):
        self.host.emit('start_game', {'room': 'TEST'})
        self.assertEqual(rooms['TEST']['status'], 'playing')
        self.assertTrue(rooms['TEST']['zen_mode'])
        self.assertTrue(rooms['TEST']['tiles'])

    def test_solo_zen_end_game_skips_countdown(self):
        self.host.emit('start_game', {'room': 'TEST'})
        self.host.get_received()

        self.host.emit('vote_end_game', {'room': 'TEST'})

        messages = self.host.get_received()
        vote = next(message for message in messages if message['name'] == 'end_game_vote')
        self.assertTrue(vote['args'][0]['immediate'])
        self.assertTrue(any(message['name'] == 'game_ended' for message in messages))
        self.assertEqual(rooms['TEST']['status'], 'ended')

    def test_bot_game_keeps_ten_second_end_countdown(self):
        self.host.emit('add_bot', {'room': 'TEST', 'difficulty': 'easy'})
        self.host.emit('start_game', {'room': 'TEST'})
        self.host.get_received()

        with patch.object(socketio, 'start_background_task') as start_task:
            self.host.emit('vote_end_game', {'room': 'TEST'})

        messages = self.host.get_received()
        vote = next(message for message in messages if message['name'] == 'end_game_vote')
        self.assertFalse(vote['args'][0]['immediate'])
        start_task.assert_called_once()
        self.assertEqual(rooms['TEST']['status'], 'playing')

    def test_host_can_kick_another_player(self):
        guest_http = app.test_client()
        guest = socketio.test_client(app, flask_test_client=guest_http)
        try:
            guest.emit('join', {
                'room': 'TEST', 'username': 'Guest',
                'reconnect_token': 'guest-token',
            })
            guest_sid = next(
                sid for sid, player in rooms['TEST']['players'].items()
                if player['username'] == 'Guest'
            )
            self.host.emit('kick_player', {'room': 'TEST', 'sid': guest_sid})
            self.assertNotIn(guest_sid, rooms['TEST']['players'])
            self.assertIn('guest-token', room_bans['TEST'])
            self.assertTrue(any(
                message['name'] == 'kicked' for message in guest.get_received()
            ))
        finally:
            if guest.is_connected():
                guest.disconnect()

    def test_autodraw_can_be_disabled_and_interval_changed(self):
        self.host.emit('update_settings', {
            'room': 'TEST', 'tile_preset': 'standard', 'max_tiles': 60,
            'draw_time': 45, 'autodraw_enabled': False,
            'incorrect_word_penalty': True,
            'word_winner_draws_next': True,
            'prefire_enabled': True,
            'paste_allowed': False,
        })
        settings = rooms['TEST']['settings']
        self.assertFalse(settings['autodraw_enabled'])
        self.assertEqual(settings['draw_time'], 45)
        self.assertTrue(settings['word_winner_draws_next'])
        self.assertTrue(settings['prefire_enabled'])
        self.assertFalse(settings['paste_allowed'])


if __name__ == '__main__':
    unittest.main()
