"""Exact all-in equity for Texas Hold'em, by enumerating every remaining board.

The 7-card evaluator is vectorised with numpy so a heads-up preflop all-in
(1,712,304 boards) takes a couple of seconds. Hands are scored as integers:
a higher score is a better hand, equal scores split the pot.
"""

from __future__ import annotations

from functools import lru_cache
from itertools import chain, combinations

import numpy as np

RANKS = "23456789TJQKA"
SUITS = "cdhs"
_CHUNK = 250_000  # boards evaluated per numpy batch


def card(text: str) -> int:
    """'As' -> 51. Cards are rank * 4 + suit, with 2 = rank 0 and A = rank 12."""
    return RANKS.index(text[0].upper()) * 4 + SUITS.index(text[1].lower())


def cards(text: str) -> list[int]:
    return [card(c) for c in text.split()]


def _build_tables():
    masks = np.arange(1 << 13)
    high = np.zeros(1 << 13, np.int64)
    top = {k: np.zeros(1 << 13, np.int64) for k in (2, 3, 5)}
    straight = np.full(1 << 13, -1, np.int64)
    for m in range(1, 1 << 13):
        ranks = [r for r in range(12, -1, -1) if m >> r & 1]
        high[m] = ranks[0]
        for k in top:
            packed = 0
            for r in (ranks + [0] * k)[:k]:
                packed = packed << 4 | r
            top[k][m] = packed
        for h in range(12, 3, -1):
            if m >> (h - 4) & 0b11111 == 0b11111:
                straight[m] = h
                break
        else:
            if m & 0b1000000001111 == 0b1000000001111:  # A-2-3-4-5
                straight[m] = 3
    return masks, high, top, straight


_, _HIGH, _TOP, _STRAIGHT = _build_tables()
_POW2 = 1 << np.arange(13, dtype=np.int64)


def _tally(hands: np.ndarray):
    """Rank counts, suit counts and per-suit rank masks of an (N, k) array of distinct cards."""
    n = len(hands)
    rows = np.arange(n)
    counts = np.zeros((n, 13), np.int64)
    suit_counts = np.zeros((n, 4), np.int64)
    suit_masks = np.zeros((n, 4), np.int64)
    for j in range(hands.shape[1]):
        rank, suit = hands[:, j] // 4, hands[:, j] % 4
        counts[rows, rank] += 1
        suit_counts[rows, suit] += 1
        suit_masks[rows, suit] |= np.int64(1) << rank
    return counts, suit_counts, suit_masks


def _add_card(tally, c: int):
    counts, suit_counts, suit_masks = (a.copy() for a in tally)
    counts[:, c // 4] += 1
    suit_counts[:, c % 4] += 1
    suit_masks[:, c % 4] |= 1 << (c // 4)
    return counts, suit_counts, suit_masks


def evaluate(hands: np.ndarray) -> np.ndarray:
    """Score an (N, 7) array of cards. Higher is better; ties mean a split."""
    return _score(*_tally(np.asarray(hands, dtype=np.int64)))


def _score(counts: np.ndarray, suit_counts: np.ndarray, suit_masks: np.ndarray) -> np.ndarray:
    rank_mask = np.bitwise_or.reduce(suit_masks, axis=1)
    flush_suit = suit_counts.argmax(axis=1)
    has_flush = suit_counts.max(axis=1) >= 5
    flush_mask = suit_masks[np.arange(len(suit_masks)), flush_suit]
    quads = ((counts == 4) * _POW2).sum(axis=1)
    trips = ((counts >= 3) * _POW2).sum(axis=1)
    pairs = ((counts >= 2) * _POW2).sum(axis=1)  # includes trips and quads

    def without(mask, *ranks_):
        for r in ranks_:
            mask = mask & ~(np.int64(1) << r)
        return mask

    straight_flush = np.where(has_flush, _STRAIGHT[flush_mask], -1)
    straight = _STRAIGHT[rank_mask]
    q = _HIGH[quads]
    t = _HIGH[trips]
    fh_pair = without(pairs, t)  # a second set of trips also fills the house
    p1 = _HIGH[pairs]
    p2 = _HIGH[without(pairs, p1)]
    two_pair = (pairs != 0) & (without(pairs, p1) != 0)

    conditions = [
        straight_flush >= 0,
        quads != 0,
        (trips != 0) & (fh_pair != 0),
        has_flush,
        straight >= 0,
        trips != 0,
        two_pair,
        pairs != 0,
    ]
    scores = [
        8 << 20 | np.maximum(straight_flush, 0) << 16,
        7 << 20 | q << 16 | _HIGH[without(rank_mask, q)] << 12,
        6 << 20 | t << 16 | _HIGH[fh_pair] << 12,
        5 << 20 | _TOP[5][flush_mask],
        4 << 20 | np.maximum(straight, 0) << 16,
        3 << 20 | t << 16 | _TOP[2][without(rank_mask, t)] << 8,
        2 << 20 | p1 << 16 | p2 << 12 | _HIGH[without(rank_mask, p1, p2)] << 8,
        1 << 20 | p1 << 16 | _TOP[3][without(rank_mask, p1)] << 4,
    ]
    return np.select(conditions, scores, default=_TOP[5][rank_mask])


@lru_cache(maxsize=8)
def _combinations(n: int, k: int) -> np.ndarray:
    count = 1
    for i in range(k):
        count = count * (n - i) // (i + 1)
    flat = np.fromiter(chain.from_iterable(combinations(range(n), k)), dtype=np.int8, count=count * k)
    return flat.reshape(count, k)


def equity(holes: list[list[int]], board: list[int] = ()) -> list[float]:
    """Each player's share of the pot over every possible completion of the board.

    ``holes`` holds each player's two cards and ``board`` the 0, 3 or 4 cards already dealt.
    Split pots count as fractions, so the equities sum to 1.
    """
    board = list(board)
    used = [c for h in holes for c in h] + board
    if len(set(used)) != len(used):
        raise ValueError("a card appears twice")
    if len(board) > 5:
        raise ValueError("more than five board cards")
    deck = np.array([c for c in range(52) if c not in set(used)], dtype=np.int64)
    combos = _combinations(len(deck), 5 - len(board))
    totals = np.zeros(len(holes))
    for start in range(0, len(combos), _CHUNK):
        runouts = deck[combos[start : start + _CHUNK]]
        boards = np.hstack([np.tile(board, (len(runouts), 1)).astype(np.int64), runouts])
        board_tally = _tally(boards)  # shared by every player; each adds only their two cards
        scores = np.stack([_score(*_add_card(_add_card(board_tally, h[0]), h[1])) for h in holes])
        winners = scores == scores.max(axis=0)
        totals += (winners / winners.sum(axis=0)).sum(axis=1)
    return list(totals / len(combos))
