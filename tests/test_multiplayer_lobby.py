import unittest

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
        })
        settings = rooms['TEST']['settings']
        self.assertFalse(settings['autodraw_enabled'])
        self.assertEqual(settings['draw_time'], 45)
        self.assertTrue(settings['word_winner_draws_next'])


if __name__ == '__main__':
    unittest.main()
