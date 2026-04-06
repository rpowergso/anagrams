import requests
import random
from functools import lru_cache
from nltk.stem import PorterStemmer
import nltk
from constants import BOT_DIFFICULTIES, LETTER_WEIGHTS, MIN_WORD_LENGTH, TILE_COUNT, FILTER_KEYWORDS
nltk.download('punkt', quiet=True)

stemmer = PorterStemmer()

def generate_tiles():
    pool = []
    for letter, count in LETTER_WEIGHTS.items():
        pool.extend([letter] * count)
    random.shuffle(pool)
    return pool[:TILE_COUNT]


@lru_cache(maxsize=1000)
def check_word_dictionary(word):
    try:
        response = requests.get(f'https://api.dictionaryapi.dev/api/v2/entries/en/{word.lower()}', timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data and isinstance(data, list) and len(data) > 0:
                # Check all meanings and definitions for filter keywords
                for entry in data:
                    meanings = entry.get('meanings', [])
                    for meaning in meanings:
                        definitions = meaning.get('definitions', [])
                        for def_item in definitions:
                            definition = def_item.get('definition', '').lower()
                            if any(keyword in definition for keyword in FILTER_KEYWORDS):
                                return False
                        # Also check synonyms/antonyms if present
                        for syn_list in [meaning.get('synonyms', []), meaning.get('antonyms', [])]:
                            for syn in syn_list:
                                if any(keyword in syn.lower() for keyword in FILTER_KEYWORDS):
                                    return False
                # Check for abbreviation
                meanings = data[0].get('meanings', [])
                if meanings:
                    defs = meanings[0].get('definitions', [])
                    if defs:
                        definition = defs[0]['definition']
                        words_in_def = definition.split()
                        if len(words_in_def) == 1:
                            def_word = words_in_def[0].lower()
                            if len(def_word) > len(word) and word in def_word:
                                return False  # abbreviation
                return True
        return False
    except:
        return True  # fallback to allow if API fails


def get_words_from_letters(letters):
    if not letters:
        return []
    normalized = ''.join(sorted(letters.lower()))
    return _get_words_from_letters_cached(normalized)


@lru_cache(maxsize=256)
def _get_words_from_letters_cached(normalized_letters):
    response = requests.get(f'https://api.poocoo.app/api/v1/words-from-letters?letters={normalized_letters}', timeout=10)
    if response.status_code != 200:
        return []
    data = response.json()
    all_words = []
    for group in data.get('data', {}).get('wordGroups', []):
        all_words.extend(group.get('words', []))
    # Filter to only words that have definitions in free dictionary API
    filtered_words = [word.lower() for word in all_words if len(word) >= MIN_WORD_LENGTH and check_word_dictionary(word)]
    return list(set(filtered_words))  # dedupe


def can_make_word(word, available_letters):
    available = [letter.upper() for letter in available_letters]
    for letter in word.upper():
        if letter in available:
            available.remove(letter)
        else:
            return False
    return True


def count_used_pool_letters(word, source_word, active_tiles):
    available = [letter.upper() for letter in active_tiles]
    source_letters = list(source_word.upper()) if source_word else []
    for letter in word.upper():
        if letter in source_letters:
            source_letters.remove(letter)
        elif letter in available:
            available.remove(letter)
        else:
            return 0
    return len(active_tiles) - len(available)


def uses_full_source_word(word, source_word):
    if not source_word:
        return True
    required = list(source_word.upper())
    for letter in word.upper():
        if letter in required:
            required.remove(letter)
    return len(required) == 0


def get_bot_weight_config(difficulty):
    return BOT_DIFFICULTIES.get(difficulty, BOT_DIFFICULTIES['medium'])


def get_length_weight(difficulty, length):
    return get_bot_weight_config(difficulty)['length_weights'].get(length, 1)


def get_steal_weight(difficulty, is_steal):
    if not is_steal:
        return 1
    return get_bot_weight_config(difficulty).get('steal_weight', 1)


def get_no_move_weight(difficulty):
    return get_bot_weight_config(difficulty).get('no_move_weight', 0)


def get_delay_for_length(difficulty, length):
    config = get_bot_weight_config(difficulty)['delay_by_length']
    return config.get(length, max(config.values()))


def choose_weighted_move(moves, difficulty):
    weighted = []
    for move in moves:
        weight = get_length_weight(difficulty, len(move['word']))
        weight *= get_steal_weight(difficulty, move.get('source_word') is not None)
        if weight > 0:
            weighted.append((move, weight))
    no_move_weight = get_no_move_weight(difficulty)
    if no_move_weight > 0:
        weighted.append(('no_move', no_move_weight))
    if not weighted:
        return None
    total = sum(weight for _, weight in weighted)
    choice = random.uniform(0, total)
    current = 0
    for item, weight in weighted:
        current += weight
        if choice <= current:
            return None if item == 'no_move' else item
    last_item = weighted[-1][0]
    return None if last_item == 'no_move' else last_item


def choose_bot_move(active_tiles, board_words, difficulty='medium'):
    active_tiles_upper = [letter.upper() for letter in active_tiles]
    candidates_by_word = {}

    def add_candidates_from_source(source_word):
        combined_letters = [*list(source_word.upper()), *active_tiles_upper] if source_word else active_tiles_upper
        for word in get_words_from_letters(''.join(combined_letters)):
            if len(word) < MIN_WORD_LENGTH:
                continue
            if source_word and word.lower() == source_word.lower():
                continue
            if source_word and word.endswith('s') and word[:-1].lower() == source_word.lower():
                continue
            if source_word and same_root(word, source_word):
                continue
            if not can_make_word(word, combined_letters):
                continue
            if word.lower() in [w.lower() for w in board_words]:
                continue
            if source_word and not uses_full_source_word(word, source_word):
                continue
            used_from_pool = count_used_pool_letters(word, source_word, active_tiles_upper)
            if used_from_pool < 1:
                continue
            word_key = word.lower()
            candidate = {
                'word': word.upper(),
                'source_word': source_word
            }
            existing = candidates_by_word.get(word_key)
            if existing and existing['source_word'] is None:
                continue
            candidates_by_word[word_key] = candidate

    for source_word in board_words:
        add_candidates_from_source(source_word)

    add_candidates_from_source(None)

    candidates = list(candidates_by_word.values())
    selected = choose_weighted_move(candidates, difficulty)
    if not selected:
        return {'found': False}

    return {
        'found': True,
        'word': selected['word'],
        'source_word': selected['source_word'],
        'length': len(selected['word']),
        'delay': get_delay_for_length(difficulty, len(selected['word']))
    }


def check_dictionary(word):
    if len(word) < 3:
        return False
    return check_word_dictionary(word)

def same_root(word1, word2):
    return stemmer.stem(word1.lower()) == stemmer.stem(word2.lower())