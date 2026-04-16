# game.py (Top of file)
import random
import time
from collections import Counter
from nltk.stem import PorterStemmer
import nltk
import twl 
from wordfreq import zipf_frequency

from constants import (
    BOT_DIFFICULTIES, 
    LETTER_WEIGHTS, 
    MIN_WORD_LENGTH, 
    TILE_COUNT, 
    COMMON_WORD_THRESHOLD, 
    RANDOM_JITTER_MAX
)

# ... rest of your code ...

nltk.download('punkt', quiet=True)
stemmer = PorterStemmer()

def same_root(word1, word2):
    return stemmer.stem(word1.lower()) == stemmer.stem(word2.lower())

def uses_full_source_word(word, source_word):
    if not source_word: return True
    s_count = Counter(source_word.upper())
    w_count = Counter(word.upper())
    for letter, count in s_count.items():
        if w_count[letter] < count: return False
    return True

def get_used_pool_letters(word, source_word, active_tiles):
    word_letters = list(word.upper())
    if source_word:
        for char in source_word.upper():
            if char in word_letters: word_letters.remove(char)
    return word_letters

def get_delay_for_length(difficulty, length):
    config = BOT_DIFFICULTIES.get(difficulty, BOT_DIFFICULTIES['medium'])
    delays = config['delay_by_length']
    lookup_len = length if length < 10 else 10
    return delays.get(lookup_len, 5.0)

def get_calculated_delay(difficulty, length, frequency):
    config = BOT_DIFFICULTIES.get(difficulty, BOT_DIFFICULTIES['medium'])
    base_map = config.get('base_delays', {})
    
    # Get base time for length (cap at longest defined length)
    lookup_len = length if length in base_map else max(base_map.keys())
    delay = base_map.get(lookup_len, 2.0)
    
    # Apply bonus for common words
    if frequency > COMMON_WORD_THRESHOLD:
        delay -= config.get('common_word_bonus', 0)
    
    # Apply randomness (+- 0.5s)
    delay += random.uniform(-RANDOM_JITTER_MAX, RANDOM_JITTER_MAX)
    
    # Ensure it doesn't go below the floor
    return max(config.get('min_delay', 0.5), round(delay, 2))

def choose_bot_move(active_tiles, board_words, difficulty='medium'):
    config = BOT_DIFFICULTIES.get(difficulty, BOT_DIFFICULTIES['medium'])
    min_freq = config.get('frequency_threshold', 0.0)
    steal_chance = config.get('steal_weight', 0.5)

    roll_options = list(config['weights'].keys())
    roll_weights = list(config['weights'].values())
    target_roll = random.choices(roll_options, weights=roll_weights, k=1)[0]

    if target_roll == 0: return {'found': False}

    candidates_by_len = {}
    all_possible_debug = [] # To store every word found for debugging
    
    active_tiles_str = "".join(active_tiles).lower()
    board_words_upper = list(dict.fromkeys(w.upper() for w in board_words))

    sources = [(None, active_tiles_str)]
    for bw in board_words_upper:
        sources.append((bw, (bw + active_tiles_str).lower()))

    for source_word, letters in sources:
        possible_words = twl.anagram(letters)
        is_steal = source_word is not None

        for word in possible_words:
            word = word.upper()
            if len(word) < MIN_WORD_LENGTH: continue
            
            # Logic filters
            if is_steal:
                if len(word) <= len(source_word): continue
                if not uses_full_source_word(word, source_word): continue
                if same_root(word, source_word): continue
                if random.random() > steal_chance: continue
            
            word_score = zipf_frequency(word, 'en')
            
            # Record for debug (limited to top 50 to keep JSON small)
            all_possible_debug.append({'w': word, 'f': round(word_score, 2)})

            if word_score < min_freq: continue
            if word in board_words_upper: continue
            if any(same_root(word, existing) for existing in board_words_upper): continue

            bin_idx = len(word) if len(word) < 10 else 10
            if bin_idx not in candidates_by_len: candidates_by_len[bin_idx] = []
            
            candidates_by_len[bin_idx].append({
                'word': word, 
                'source_word': source_word, 
                'freq': word_score
            })

    # Pick moves from target length downwards
    for current_len in range(target_roll, MIN_WORD_LENGTH - 1, -1):
        moves = candidates_by_len.get(current_len, [])
        if not moves: continue
        
        moves.sort(key=lambda x: x['freq'], reverse=True)
        move = moves[0]
        
        final_delay = get_calculated_delay(difficulty, len(move['word']), move['freq'])
        
        return {
            'found': True,
            'word': move['word'],
            'source_word': move['source_word'],
            'pool_letters': get_used_pool_letters(move['word'], move['source_word'], active_tiles),
            'delay': final_delay,
            'debug': {
                'considered_count': len(all_possible_debug),
                'top_candidates': sorted(all_possible_debug, key=lambda x: x['f'], reverse=True)[:15],
                'chosen_freq': round(move['freq'], 2)
            }
        }
    return {'found': False}

def check_dictionary(word):
    if not word or len(word) < MIN_WORD_LENGTH: return False
    return twl.check(word.lower())

def generate_tiles():
    pool = []
    for letter, count in LETTER_WEIGHTS.items():
        pool.extend([letter] * count)
    random.shuffle(pool)
    return pool[:TILE_COUNT]