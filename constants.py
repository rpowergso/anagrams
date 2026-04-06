TILE_COUNT = 60
AUTODRAW_INTERVAL_MS = 3000

BOT_DIFFICULTIES = {
    'easy': {
        'length_weights': {
            3: 10,
            4: 8,
            5: 6,
            6: 4,
            7: 2,
            8: 1,
            9: 0.5,
            10: 0.1
        },
        'delay_by_length': {
            3: 5,
            4: 6,
            5: 7,
            6: 8,
            7: 9,
            8: 10,
            9: 11,
            10: 12
        },
        'steal_weight': 0.2,
        'no_move_weight': 1.0
    },
    'medium': {
        'length_weights': {
            3: 5,
            4: 5,
            5: 4,
            6: 3,
            7: 2,
            8: 1,
            9: 1,
            10: 1
        },
        'delay_by_length': {
            3: 3,
            4: 4,
            5: 5,
            6: 5,
            7: 4,
            8: 4,
            9: 5,
            10: 5
        },
        'steal_weight': 0.5,
        'no_move_weight': 0.5
    },
    'hard': {
        'length_weights': {
            3: 2,
            4: 3,
            5: 4,
            6: 5,
            7: 6,
            8: 7,
            9: 8,
            10: 8
        },
        'delay_by_length': {
            3: 2,
            4: 3,
            5: 3,
            6: 3,
            7: 3,
            8: 4,
            9: 4,
            10: 4
        },
        'steal_weight': 1.0,
        'no_move_weight': 0.1
    }
}

LETTER_WEIGHTS = {
    'A': 9, 'B': 2, 'C': 2, 'D': 4, 'E': 12,
    'F': 2, 'G': 3, 'H': 2, 'I': 9, 'J': 1,
    'K': 1, 'L': 4, 'M': 2, 'N': 6, 'O': 8,
    'P': 2, 'Q': 1, 'R': 6, 'S': 4, 'T': 6,
    'U': 4, 'V': 2, 'W': 2, 'X': 1, 'Y': 2,
    'Z': 1
}

MIN_WORD_LENGTH = 3

FILTER_KEYWORDS = ['archaic', 'obsolete', 'slang', 'abbreviation', 'informal', 'dated', 'old-fashioned', 'rare', 'regional']