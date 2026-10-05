import unittest
import json
from unittest.mock import MagicMock, patch

from app import app, definition_cache


class WordFinderRegressionTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, SECRET_KEY='word-finder-test-key')
        self.client = app.test_client()
        definition_cache.clear()

    def test_find_smallest_returns_json_for_dense_reverse_search(self):
        response = self.client.post('/word-extensions', json={
            'letters': 'ANCCILAHJK',
            'minAdded': 1,
            'maxAdded': 7,
            'chainMode': True,
            'chainStep': 1,
            'reverseMode': True,
            'forcedLetters': {},
            'forcedWords': [],
            'biggestOnly': True,
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.is_json)
        self.assertIn('groups', response.get_json())

    @patch('app.urllib.request.urlopen')
    def test_definition_includes_ipa_pronunciation(self, mock_urlopen):
        upstream_response = MagicMock()
        upstream_response.read.return_value = json.dumps([{
            'word': 'anagram',
            'defs': ['n\ta word formed by rearranging another word'],
            'tags': ['n', 'pron:AE1 N AH0 G R AE0 M', 'ipa_pron:\u02c8\u00e6n\u0259\u0261r\u00e6m'],
        }]).encode('utf-8')
        mock_urlopen.return_value.__enter__.return_value = upstream_response

        response = self.client.get('/definition/anagram')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['pronunciation'], '\u02c8\u00e6n\u0259\u0261r\u00e6m')
        self.assertEqual(response.get_json()['pronunciationType'], 'IPA')
        requested_url = mock_urlopen.call_args.args[0].full_url
        self.assertIn('md=dr', requested_url)
        self.assertIn('ipa=1', requested_url)


if __name__ == '__main__':
    unittest.main()
