"""Reproducible opening moves and contrasting judgments."""
import unittest
from examples.reversi import OPENING, SQUARES, flips, opening_cases


class ReversiOpening(unittest.TestCase):
    def test_rules_and_all_opening_positions(self):
        positions = list(opening_cases())
        self.assertEqual(len({(p["board"], p["side"]) for p in positions}), 17)
        first = positions[0]["candidates"]
        self.assertEqual({r["square"]: r["flipped"] for r in first if r["verdict"] == "legal"},
                         {"d3": ["d4"], "c4": ["d4"], "f5": ["e5"], "e6": ["e5"]})
        self.assertEqual(first[0]["verdict"], "no-capture")
        self.assertEqual(first[SQUARES.index("d4")]["verdict"], "occupied")
        self.assertEqual(positions[0]["board"], OPENING)
        self.assertEqual([sum(r["verdict"] == "legal" for p in positions if len(p["history"]) == depth
                              for r in p["candidates"]) for depth in range(3)], [4, 12, 56])
        board = list("." * 64)
        for s in ["b2", "c3", "e4", "d5"]:
            board[SQUARES.index(s)] = "W"
        for s in ["a1", "f4"]:
            board[SQUARES.index(s)] = "B"
        self.assertEqual([SQUARES[i] for i in flips(board, "B", SQUARES.index("d4"))], ["b2", "c3", "e4"])

    def test_policy_disagreement_after_d3(self):
        position = next(p for p in opening_cases() if p["history"] == ("d3",))
        moves = {row["square"]: row for row in position["candidates"] if row["verdict"] == "legal"}
        self.assertEqual({key: row["replies"] for key, row in moves.items()}, {"c3": 4, "e3": 5, "c5": 5})
        self.assertEqual(moves["e3"]["judgments"], {"mostFlips": True, "fewestReplies": False})
