import requests
import random
from nltk.stem import PorterStemmer
import nltk
nltk.download('punkt', quiet=True)

stemmer = PorterStemmer()

LETTER_WEIGHTS = {
    'A': 9, 'B': 2, 'C': 2, 'D': 4, 'E': 12,
    'F': 2, 'G': 3, 'H': 2, 'I': 9, 'J': 1,
    'K': 1, 'L': 4, 'M': 2, 'N': 6, 'O': 8,
    'P': 2, 'Q': 1, 'R': 6, 'S': 4, 'T': 6,
    'U': 4, 'V': 2, 'W': 2, 'X': 1, 'Y': 2,
    'Z': 1
}

def generate_tiles():
    pool = []
    for letter, count in LETTER_WEIGHTS.items():
        pool.extend([letter] * count)
    random.shuffle(pool)
    return pool[:60]

def check_dictionary(word):
    if len(word) < 3:
        return False
    response = requests.get(f'https://api.dictionaryapi.dev/api/v2/entries/en/{word.lower()}')
    return response.status_code == 200

def same_root(word1, word2):
    return stemmer.stem(word1.lower()) == stemmer.stem(word2.lower())