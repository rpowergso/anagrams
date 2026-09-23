import unittest

from app import app


class WordFinderRegressionTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, SECRET_KEY='word-finder-test-key')
        self.client = app.test_client()

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


if __name__ == '__main__':
    unittest.main()
