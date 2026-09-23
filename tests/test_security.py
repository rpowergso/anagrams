import unittest

from app import app, socketio
from multiplayer import rooms


class HttpSecurityTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, SECRET_KEY='security-test-key')
        self.client = app.test_client()

    def test_security_headers_are_present(self):
        response = self.client.get('/homepage')
        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(response.headers['X-Frame-Options'], 'DENY')
        self.assertEqual(response.headers['Referrer-Policy'], 'same-origin')

    def test_hebrew_version_is_not_in_the_release(self):
        self.assertEqual(self.client.get('/hebrew').status_code, 404)

    def test_multiplayer_page_has_post_game_and_word_detail_controls(self):
        response = self.client.get('/multiplayer/TEST')
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn('id="topReplayButton"', page)
        self.assertIn('id="board-steals-body"', page)
        self.assertIn('WAYS TO STEAL IT', page)
        self.assertIn('id="setting-prefire"', page)
        self.assertIn('id="setting-paste"', page)
        self.assertIn('id="standbyWordDisplay"', page)

    def test_custom_room_code_routes_to_a_new_lobby(self):
        response = self.client.post('/join-room', data={'room_id': 'friends2026'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers['Location'].endswith('/multiplayer/FRIENDS2026'))
        lobby = self.client.get(response.headers['Location'])
        self.assertEqual(lobby.status_code, 200)

    def test_custom_room_code_rejects_unsafe_characters(self):
        response = self.client.post('/join-room', data={'room_id': '../oops'})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(response.headers['Location'].endswith('/multiplayer/../OOPS'))

    def test_large_request_is_rejected(self):
        response = self.client.post(
            '/check-word', data='{"word":"' + ('A' * 70000) + '"}',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 413)

    def test_word_routes_reject_wrong_types_and_long_words(self):
        wrong_type = self.client.post('/check-word', json={'word': ['CAT']})
        self.assertEqual(wrong_type.status_code, 400)
        too_long = self.client.post('/check-stem', json={
            'word1': 'A' * 31, 'word2': 'CAT'
        })
        self.assertEqual(too_long.status_code, 400)
        bad_state = self.client.post('/bot-move', json={
            'activeTiles': 'ABC', 'boardWords': [],
            'difficulty': 'easy',
        })
        self.assertEqual(bad_state.status_code, 400)

class MultiplayerSecurityTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, SECRET_KEY='security-test-key')
        rooms.clear()
        self.http_client = app.test_client()
        self.client = socketio.test_client(app, flask_test_client=self.http_client)

    def tearDown(self):
        if self.client.is_connected():
            self.client.disconnect()
        rooms.clear()

    def test_html_username_is_rejected(self):
        self.client.emit('join', {
            'room': 'SAFE',
            'username': '<img src=x onerror=alert(1)>',
            'reconnect_token': 'test-token',
        })
        messages = self.client.get_received()
        self.assertTrue(any(message['name'] == 'error_message' for message in messages))
        self.assertNotIn('SAFE', rooms)

    def test_normal_unicode_username_is_allowed(self):
        self.client.emit('join', {
            'room': 'SAFE',
            'username': "D'Artagnan",
            'reconnect_token': 'test-token',
        })
        self.assertIn('SAFE', rooms)
        player = next(iter(rooms['SAFE']['players'].values()))
        self.assertEqual(player['username'], "D'Artagnan")


if __name__ == '__main__':
    unittest.main()
