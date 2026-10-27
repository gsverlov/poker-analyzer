import random
from itertools import combinations

import numpy as np
import pytest
from phevaluator import evaluate_cards

from poker_analyzer.equity import RANKS, SUITS, cards, equity, evaluate

DECK = [r + s for r in RANKS for s in SUITS]


def score(text: str) -> int:
    return int(evaluate(np.array([cards(text)]))[0])


def reference_equity(holes: list[str], board: str) -> list[float]:
    """Brute force with phevaluator (lower rank = better hand), as an independent check."""
    used = set(" ".join(holes + [board]).split())
    deck = [c for c in DECK if c not in used]
    known = board.split()
    shares = [0.0] * len(holes)
    runouts = list(combinations(deck, 5 - len(known)))
    for runout in runouts:
        ranks = [evaluate_cards(*h.split(), *known, *runout) for h in holes]
        best = min(ranks)
        winners = [i for i, r in enumerate(ranks) if r == best]
        for i in winners:
            shares[i] += 1 / len(winners)
    return [s / len(runouts) for s in shares]


def test_evaluator_orders_random_hands_like_phevaluator():
    rng = random.Random(1)
    hands = [rng.sample(DECK, 7) for _ in range(20000)]
    ours = evaluate(np.array([cards(" ".join(h)) for h in hands]))
    theirs = np.array([evaluate_cards(*h) for h in hands])
    i, j = np.array([rng.randrange(len(hands)) for _ in range(50000)]), np.array([rng.randrange(len(hands)) for _ in range(50000)])
    # phevaluator ranks lower-is-better, ours higher-is-better.
    assert (np.sign(ours[i] - ours[j]) == -np.sign(theirs[i] - theirs[j])).all()


@pytest.mark.parametrize(
    "better, worse",
    [
        ("As Ks Qs Js Ts 2c 3d", "9s 8s 7s 6s 5s Ac Ad"),  # royal flush beats a lower straight flush
        ("5h 4h 3h 2h Ah Kd Kc", "Ac Ad Ah As Kc 2d 3d"),  # steel wheel beats quads
        ("Ac Ad Ah As 3c 2d 2h", "Kc Kd Kh Ks Qc Jd Th"),  # quad aces beat quad kings
        ("Kc Kd Kh Ks Qc 2d 2h", "Kc Kd Kh Ks Jc Td 9h"),  # quads: kicker counts
        ("9c 9d 9h 5s 5c 2d 3h", "9c 9d 9h 4s 4c Ad Kh"),  # full house: the pair counts
        ("7c 7d 7h 5s 5c 5d 2h", "7c 7d 7h 4s 4c 4d Ah"),  # two sets make a full house with the higher pair
        ("Ac 9c 7c 5c 3c Kd Kh", "Kc Qc Jc Tc 8c 2d 2h"),  # flush: highest card first
        ("6c 5d 4h 3s 2c Ad Kh", "5c 4d 3h 2s Ac Kd Qh"),  # six-high straight beats the wheel
        ("Ac Ad Kc Kd Qc Qd 2h", "Ac Ad Kc Kd Jc Jd Th"),  # three pairs: best two plus kicker
        ("Ac Ad 5c 5d Kc 2s 3h", "Ac Ad 5c 5d Qc Js Th"),  # two pair kicker
        ("Ac Ad Kc 9d 7c 4s 2h", "Ac Ad Kc 9d 6c 4s 2h"),  # pair: third kicker decides
    ],
)
def test_evaluator_edge_cases(better, worse):
    assert score(better) > score(worse)


def test_ties_split():
    assert score("Ac Kd 2h 2s 7c 7d Qh") == score("As Ks 2c 2d 7h 7s Qd")
    assert equity([cards("Ah Ad"), cards("Ac As")]) == pytest.approx([0.5, 0.5])


def test_aa_vs_kk_preflop_matches_published_equity():
    # AhAd against each of the six kings combos: one shares no suit, four share one, one shares both.
    no_shared = equity([cards("Ah Ad"), cards("Ks Kc")])[0]
    one_shared = equity([cards("Ah Ad"), cards("Kh Kc")])[0]
    both_shared = equity([cards("Ah Ad"), cards("Kh Kd")])[0]
    average = (no_shared + 4 * one_shared + both_shared) / 6
    assert average == pytest.approx(0.8195, abs=0.0005)  # published: AA 81.95% vs KK
    assert no_shared < one_shared < both_shared  # sharing suits takes flush outs away from the kings


@pytest.mark.parametrize(
    "holes, board",
    [
        (["As Kd", "Qh Qc"], "Ts 9s 2d"),
        (["Jh Th", "Ac Kc", "8d 8s"], "9h 8h 2c"),
        (["7c 6c", "Ad Ah"], "5c 4d Kh Qc"),
    ],
)
def test_equity_matches_brute_force(holes, board):
    assert equity([cards(h) for h in holes], cards(board)) == pytest.approx(reference_equity(holes, board), abs=1e-12)
