# constants.py

TILE_COUNT = 60
AUTODRAW_INTERVAL_MS = 3500 
MIN_WORD_LENGTH = 3

# Zipf frequency > 4.0 is generally considered a "common" word
COMMON_WORD_THRESHOLD = 4.0 

# Max randomness added/subtracted to the delay (seconds)
RANDOM_JITTER_MAX = 0.5

# Hint system frequency threshold (minimum frequency for "big hint" suggestions)
HINT_FREQUENCY_THRESHOLD = 3.2

BOT_DIFFICULTIES = {
    'easy': {
        'weights': {0: 50, 3: 20, 4: 12, 5: 10, 6: 4, 7: 1},
        'steal_weight': 0.4,
        'frequency_threshold': 4.0,
        'base_delays': {3: 4.0, 4: 5.0, 5: 6.0, 6: 7.0},
        'common_word_bonus': 1.0,
        'min_delay': 2.0
    },
    'medium': {
        'weights': {0: 33, 3: 20, 4: 15, 5: 20, 6: 5, 7: 3},
        'steal_weight': 0.6,
        'frequency_threshold': 3.2,
        'base_delays': {3: 2.5, 4: 3.0, 5: 3.5, 6: 4.0},
        'common_word_bonus': 0.7,
        'min_delay': 0.8
    },
    'hard': {
        'weights': {0: 2, 3: 1, 4: 4, 5: 10, 6: 18, 7: 25},
        'steal_weight': 1.0,
        'frequency_threshold': 1.0,
        'base_delays': {3: 1.5, 4: 2.0, 5: 2.5, 6: 3.0},
        'common_word_bonus': 0.5,
        'min_delay': 0.3
    }
}

LETTER_WEIGHTS = {
    'A': 9, 'B': 2, 'C': 2, 'D': 4, 'E': 12, 'F': 2, 'G': 3, 'H': 2, 'I': 9, 'J': 1,
    'K': 1, 'L': 4, 'M': 2, 'N': 6, 'O': 8, 'P': 2, 'Q': 1, 'R': 6, 'S': 4, 'T': 6,
    'U': 4, 'V': 2, 'W': 2, 'X': 1, 'Y': 2, 'Z': 1
}