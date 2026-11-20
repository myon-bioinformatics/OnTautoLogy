"""Compare candidate placements on every reachable 8x8 Othello opening through ply two."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OPENING = "........" * 3 + "...WB..." + "...BW..." + "........" * 3
SQUARES = [f"{file}{rank}" for rank in range(1, 9) for file in "abcdefgh"]
DIRECTIONS = [(x, y) for x in (-1, 0, 1) for y in (-1, 0, 1) if x or y]


def flips(board, side, square):
    if board[square] != ".":
        return []
    row, column = divmod(square, 8)
    other = "W" if side == "B" else "B"
    captured = []
    for dr, dc in DIRECTIONS:
        r, c = row + dr, column + dc
        line = []
        while 0 <= r < 8 and 0 <= c < 8:
            cell = r * 8 + c
            if board[cell] != other:
                if board[cell] == side:
                    captured.extend(line)
                break
            line.append(cell)
            r, c = r + dr, c + dc
    return sorted(captured)


def opening_cases():
    """Yield all 64 candidate squares per position, including occupied and non-capturing squares."""
    frontier = [(OPENING, "B", ())]
    seen = set()
    while frontier:
        following = []
        for board, side, history in frontier:
            if (board, side) in seen:
                continue
            seen.add((board, side))
            opponent = "W" if side == "B" else "B"
            rows = []
            for square, name in enumerate(SQUARES):
                captured = flips(board, side, square)
                row = {"square": name, "flipped": [SQUARES[i] for i in captured],
                       "verdict": "legal" if captured else "occupied" if board[square] != "." else "no-capture"}
                rows.append(row)
                if captured:
                    after = list(board)
                    for i in [square, *captured]:
                        after[i] = side
                    after = "".join(after)
                    row["replies"] = sum(bool(flips(after, opponent, i)) for i in range(64))
                    if len(history) < 2:
                        following.append((after, opponent, (*history, name)))
            legal = [row for row in rows if row["verdict"] == "legal"]
            most = max(len(row["flipped"]) for row in legal)
            fewest = min(row["replies"] for row in legal)
            for row in legal:
                row["judgments"] = {"mostFlips": len(row["flipped"]) == most,
                                    "fewestReplies": row["replies"] == fewest}
            yield {"id": "reversi:" + ("-".join(history) or "opening"), "history": history,
                   "board": board, "side": side, "candidates": rows}
        frontier = following


def graph(positions, *, preview=False):
    from rdflib import Graph, Literal, RDF, RDFS
    from ontautology_shared.truth import OT

    result = Graph()
    result.bind("ot", OT)
    for position in positions:
        key = position["id"]
        if preview and key not in ("reversi:opening", "reversi:d3"):
            continue
        board = OT[key]
        result.add((board, RDF.type, OT.Position))
        result.add((board, OT.board, Literal(position["board"])))
        result.add((board, OT.sideToMove, Literal(position["side"])))
        result.add((board, OT.history, Literal(" ".join(position["history"]))))
        for row in position["candidates"]:
            judgments = row.get("judgments", {})
            if preview and not (key == "reversi:opening" and row["square"] in ("d3", "a1", "d4")
                                or key == "reversi:d3" and judgments):
                continue
            move = OT[key + "/" + row["square"]]
            result.add((move, RDF.type, OT.CandidateMove))
            result.add((move, RDFS.label, Literal(f"{key} / {row['square']}")))
            result.add((move, OT.position, board))
            result.add((move, OT.square, Literal(row["square"])))
            result.add((move, OT.legality, OT[row["verdict"]]))
            for square in row["flipped"]:
                result.add((move, OT.flips, Literal(square)))
            if judgments:
                result.add((move, OT.replyCount, Literal(row["replies"])))
                prop = OT[key + "/" + row["square"] + "/preferred"]
                result.add((prop, RDF.type, OT.Proposition))
                result.add((prop, OT.aboutEvent, move))
                result.add((prop, OT.concept, OT.PreferredMove))
                for policy, preferred in judgments.items():
                    node = OT[key + "/" + row["square"] + "/" + policy]
                    result.add((node, RDF.type, OT.Judgment))
                    result.add((node, OT.actor, Literal(policy)))
                    result.add((node, OT.regardsAsTrue if preferred else OT.regardsAsFalse, prop))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("summary", "json", "ttl"), default="summary")
    args = parser.parse_args()
    positions = list(opening_cases())
    if args.format == "ttl":
        print(graph(positions).serialize(format="turtle"))
    elif args.format == "json":
        print(json.dumps(positions, ensure_ascii=False))
    else:
        rows = [r for p in positions for r in p["candidates"]]
        print(json.dumps({"positions": len(positions), "candidates": len(rows),
                          "verdicts": Counter(r["verdict"] for r in rows),
                          "disagreements": sum(len(set(r.get("judgments", {}).values())) == 2 for r in rows)}))
