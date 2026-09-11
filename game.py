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
    RANDOM_JITTER_MAX,
    HINT_FREQUENCY_THRESHOLD
)

stemmer = PorterStemmer()
_ranked_words = None

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

def is_legal_steal_extension(word, source_word):
    """Return whether word is a legal direct steal of source_word."""
    word = word.upper()
    source_word = source_word.upper()
    if len(word) <= len(source_word) or not uses_full_source_word(word, source_word):
        return False
    if word == source_word + 'S':
        return False
    return not same_root(word, source_word)

def find_word_extensions(letters, min_added=1, max_added=5, limit_per_length=150,
                         chain_step=None, reverse=False, forced_letters=None,
                         forced_words=None):
    """Find legal words reached by adding or removing letters."""
    letters = letters.lower().strip()
    required = Counter(letters)
    grouped = {added: [] for added in range(min_added, max_added + 1)}

    for candidate in twl.iterator():
        difference = len(letters) - len(candidate) if reverse else len(candidate) - len(letters)
        if difference not in grouped or len(candidate) < MIN_WORD_LENGTH:
            continue
        candidate_counts = Counter(candidate)
        contains_letters = all(candidate_counts[char] >= count for char, count in required.items())
        contained_by_letters = all(required[char] >= count for char, count in candidate_counts.items())
        if (contained_by_letters if reverse else contains_letters):
            candidate = candidate.upper()
            legal_direct = (is_legal_steal_extension(letters, candidate) if reverse
                            else is_legal_steal_extension(candidate, letters))
            if chain_step or legal_direct:
                grouped[difference].append(candidate)

    chain_paths = {}
    forced_letters = forced_letters or {}
    forced_words = {word.upper() for word in (forced_words or [])}
    effective_chain_step = chain_step or 1
    if effective_chain_step:
        reachable = {0: [letters.upper()]}
        chain_paths[letters.upper()] = [[letters.upper()]]
        for added in range(1, max_added + 1):
            if added % effective_chain_step:
                if chain_step:
                    grouped[added] = []
                continue
            predecessors = reachable.get(added - effective_chain_step, [])
            chain_words = []
            candidates = sorted(
                grouped[added],
                key=lambda word: (-zipf_frequency(word, 'en'), word),
            )
            for word in candidates:
                word_counts = Counter(word)
                word_paths = []
                for predecessor in predecessors:
                    predecessor_counts = Counter(predecessor)
                    contains_step = (all(predecessor_counts[char] >= count
                                         for char, count in word_counts.items()) if reverse
                                     else all(word_counts[char] >= count
                                              for char, count in predecessor_counts.items()))
                    legal_step = (is_legal_steal_extension(predecessor, word) if reverse
                                  else is_legal_steal_extension(word, predecessor))
                    step_number = added // effective_chain_step
                    required_at_step = Counter(forced_letters.get(step_number, '').upper())
                    changed_letters = ((predecessor_counts - word_counts) if reverse
                                       else (word_counts - predecessor_counts))
                    forced_letters_match = all(
                        changed_letters[char] >= count
                        for char, count in required_at_step.items()
                    )
                    forced_here = {
                        forced for forced in forced_words
                        if abs(len(forced) - len(letters)) == added
                    }
                    forced_word_match = not forced_here or (
                        len(forced_here) == 1 and word in forced_here
                    )
                    if contains_step and legal_step and forced_letters_match and forced_word_match:
                        word_paths.extend(path + [word] for path in chain_paths[predecessor])
                if word_paths:
                    chain_words.append(word)
                    chain_paths[word] = word_paths
            if chain_step:
                grouped[added] = chain_words
            reachable[added] = chain_words

        # A mandatory word constrains the whole route, including steps before it.
        # Keep only prefixes that can actually reach the furthest waypoint.
        if forced_words:
            waypoint_differences = {
                abs(len(word) - len(letters)): word for word in forced_words
            }
            furthest_difference = max(waypoint_differences)
            furthest_word = waypoint_differences[furthest_difference]
            complete_prefix_paths = chain_paths.get(furthest_word, [])

            if furthest_difference > max_added or not complete_prefix_paths:
                if chain_step:
                    for added in grouped:
                        grouped[added] = []
                chain_paths = {}
            else:
                valid_prefixes = {}
                for path in complete_prefix_paths:
                    for index, word in enumerate(path):
                        valid_prefixes.setdefault(word, set()).add(tuple(path[:index + 1]))

                for added in range(1, furthest_difference + 1):
                    if added not in grouped:
                        continue
                    allowed_words = set(valid_prefixes)
                    if chain_step:
                        grouped[added] = [word for word in grouped[added] if word in allowed_words]
                    for word in list(chain_paths):
                        if abs(len(word) - len(letters)) != added:
                            continue
                        allowed_paths = valid_prefixes.get(word, set())
                        chain_paths[word] = [
                            path for path in chain_paths[word] if tuple(path) in allowed_paths
                        ]

    results = []
    for added, words in grouped.items():
        words.sort(key=lambda word: (-zipf_frequency(word, 'en'), word))
        displayed_words = words[:limit_per_length]
        results.append({
            'added': added,
            'words': displayed_words,
            'total': len(words),
            'chains': {word: chain_paths[word] for word in displayed_words if word in chain_paths},
        })
    return results

def get_hints(active_tiles, board_words):
    """Returns two hints: (small_hint, big_hint).
    - small_hint: most frequent word from active tiles
    - big_hint: longest word above HINT_FREQUENCY_THRESHOLD
    """
    active_tiles_str = "".join(active_tiles).lower()
    board_words_upper = list(dict.fromkeys(w.upper() for w in board_words))
    
    small_hint = None
    small_hint_freq = -1
    big_hint = None
    big_hint_len = 0
    
    # Find all possible words from active tiles
    possible_words = twl.anagram(active_tiles_str)
    
    for word in possible_words:
        word = word.upper()
        if len(word) < MIN_WORD_LENGTH: continue
        if word in board_words_upper: continue
        if any(same_root(word, existing) for existing in board_words_upper): continue
        
        freq = zipf_frequency(word, 'en')
        
        # Small hint: most frequent word
        if freq > small_hint_freq:
            small_hint_freq = freq
            small_hint = word
        
        # Big hint: longest word above threshold
        if freq >= HINT_FREQUENCY_THRESHOLD and len(word) > big_hint_len:
            big_hint_len = len(word)
            big_hint = word
    
    return {
        'small_hint': small_hint,
        'big_hint': big_hint
    }

def generate_tiles(count=TILE_COUNT):
    pool = []
    for letter, c in LETTER_WEIGHTS.items():
        pool.extend([letter] * c)
    random.shuffle(pool)
    return pool[:count]

def _get_ranked_words():
    global _ranked_words
    if _ranked_words is None:
        _ranked_words = [
            word.upper() for word in twl.iterator()
            if 3 <= len(word) <= 8 and zipf_frequency(word, 'en') >= 2.3
        ]
    return _ranked_words

def _ranked_settings(elo):
    if elo < 800: return (3, 1, False, 4, 1, 4.2)
    if elo < 1400: return (3, 2, False, 4, 1, 4.0)
    if elo < 1600: return (4, 2, False, 4, 1, 3.9)
    if elo < 1800: return (5, 2, False, 4, 1, 3.75)
    if elo < 2000: return (6, 2, False, 4, 2, 3.6)
    if elo < 2600: return (9, 2, True, 6, 2, 3.2)
    if elo < 3200: return (12, random.choice([1, 2]), True, 7, 3, 2.8)
    if elo < 3700: return (16, 1, True, 8, 4, 2.4)
    return (random.choice([14, 16, 18]), 1, True, 9, 6, 0.0)

def _ranked_source_limits(elo):
    if elo < 800: return (4, 4.6)
    if elo < 1400: return (5, 4.2)
    if elo < 1600: return (5, 4.1)
    if elo < 1800: return (6, 4.0)
    if elo < 2000: return (6, 3.8)
    if elo < 2600: return (7, 3.3)
    if elo < 3200: return (8, 2.8)
    if elo < 3700: return (8, 2.3)
    return (8, 0.0)

def _ranked_solution_cap(elo):
    if elo < 800: return 4
    if elo < 1400: return 6
    if elo < 1600: return 7
    if elo < 1800: return 8
    if elo < 2000: return 10
    if elo < 2600: return 14
    if elo < 3200: return 20
    return 30

def _legal_steals(source, pool, max_added=15, min_frequency=0):
    letters = (source + ''.join(pool)).lower()
    steals = []
    for answer in twl.anagram(letters):
        answer = answer.upper()
        if (len(answer) <= len(source) or len(answer) - len(source) > max_added
                or zipf_frequency(answer, 'en') < min_frequency
                or not is_legal_steal_extension(answer, source)):
            continue
        steals.append(answer)
    return sorted(set(steals), key=lambda word: (-len(word), -zipf_frequency(word, 'en'), word))

def generate_ranked_puzzle(elo):
    """Generate a verified ranked board without exposing its solutions."""
    elo = max(0, min(4000, int(elo)))
    spread = 110 if elo < 800 else 220 if elo < 3200 else 140
    difficulty_elo = max(0, min(4000, elo + random.randint(-spread, spread)))
    board_count, desired_stealable, require_flip, pool_size, max_added, min_frequency = _ranked_settings(elo)
    words = _get_ranked_words()
    max_source_length, min_source_frequency = _ranked_source_limits(elo)
    solution_cap = _ranked_solution_cap(elo)
    if elo < 800:
        allow_pool_word = True
    elif elo < 1400:
        allow_pool_word = random.random() < 0.18
    elif elo < 1800:
        allow_pool_word = random.random() < 0.08
    elif elo < 2000:
        allow_pool_word = random.random() < 0.10
    else:
        allow_pool_word = True
    candidate_words = [
        word for word in words
        if len(word) <= max_source_length
        and zipf_frequency(word, 'en') >= min_source_frequency
    ]

    for _ in range(40):
        guarantee_pool_word = elo < 800
        sometimes_seed_pool_word = elo < 1400 and random.random() < 0.15
        if guarantee_pool_word or sometimes_seed_pool_word:
            easy_words = [word for word in candidate_words if len(word) <= pool_size and zipf_frequency(word, 'en') >= 4.5]
            seed = random.choice(easy_words)
            pool = list(seed) + generate_tiles(pool_size - len(seed))
            random.shuffle(pool)
        else:
            pool = generate_tiles(pool_size)
        pool_words = [word.upper() for word in twl.anagram(''.join(pool).lower())
                      if len(word) >= 3]
        if pool_words and not allow_pool_word:
            continue
        flipped = pool[-1]
        before_flip = pool[:-1]
        stealable = []
        decoys = []
        for source in random.sample(candidate_words, min(len(candidate_words), 260)):
            unrestricted_after = _legal_steals(source, pool)
            after = _legal_steals(source, pool, max_added, min_frequency)
            if require_flip:
                before = set(_legal_steals(source, before_flip, max_added, min_frequency))
                after = [answer for answer in after if answer not in before]
            if elo < 1800 and len(unrestricted_after) > 2:
                continue
            if after:
                stealable.append((source, after[:12]))
            elif not unrestricted_after:
                decoys.append(source)
            if len(stealable) >= desired_stealable * 3 and len(decoys) >= board_count * 2:
                break

        if len(stealable) < desired_stealable or len(decoys) < board_count - desired_stealable:
            continue

        chosen = random.sample(stealable, desired_stealable)
        board = [source for source, _ in chosen]
        board.extend(random.sample(decoys, board_count - desired_stealable))
        random.shuffle(board)
        # Difficulty filters choose the board, but every genuinely legal play on
        # that board must be accepted once the puzzle is shown.
        solutions = {
            answer: source
            for source in board
            for answer in _legal_steals(source, pool)
        }
        for answer in sorted(set(pool_words), key=lambda word: (-len(word), -zipf_frequency(word, 'en'), word)):
            solutions.setdefault(answer, 'POOL')
        if len(solutions) > solution_cap:
            continue
        puzzle_rating = min(4000, max(100, difficulty_elo + random.randint(-45, 45)))
        return {
            'board_words': board,
            'pool': pool,
            'flipped': flipped,
            'solutions': solutions,
            'rating': puzzle_rating,
            'stealable_count': desired_stealable,
        }
    raise RuntimeError('Could not generate a ranked puzzle. Please try again.')

def calculate_ranked_delta(player_elo, puzzle_rating, solved, elapsed_seconds, attempts):
    player_elo = max(0, min(4000, int(player_elo)))
    expected = 1 / (1 + 10 ** ((puzzle_rating - player_elo) / 600))
    if solved:
        time_factor = max(0.18, 1 / (1 + max(0, elapsed_seconds - 8) / 45))
        attempt_factor = max(0.35, 1 - attempts * 0.18)
        raw = 42 * (1 - expected) * time_factor * attempt_factor
        cap_factor = max(0.08, (4000 - player_elo) / 900)
        return max(1, round(raw * min(1, cap_factor)))
    raw = 34 * expected + attempts * 3
    return -max(3, round(raw))
