"""Replay the bot relation holdout with only the clues disclosed at each stage."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import ontautology as ot
from tools import tautology


def infer_relations(reference, word, clues):
    """Two explicit rules for this exercise. A shared purpose is symmetric."""
    elements, meta, _, _ = ot._normalize_corpus(reference)
    relations = []
    purposes = {clue for clue in clues if clue.startswith("用途:")}
    for name, facts in elements.items():
        facts = set(facts or ())
        shared = sorted(purposes & facts)
        target = meta[name].get("id", name)
        if shared:
            relations.append({"source": word, "kind": "sharesPurposeWith", "target": target,
                              "basis": "hypothesis", "evidence": shared})
        inference = "入力から出力を推論"
        if purposes and inference in clues and {inference, "対象:システム一般"} <= facts:
            relations.append({"source": word, "kind": "applicationOf", "target": target,
                              "basis": "hypothesis", "evidence": sorted(purposes | {inference})})
    return relations


def replay(corpus, word, clues):
    if word not in ot._normalize_corpus(corpus)[0]:
        raise ValueError(f"unknown holdout: {word}")
    reference = tautology._without(corpus, word)
    hits = tautology.wobble(reference, [word])["words"][word]
    stages = []
    for count in range(len(clues) + 1):
        observed = clues[:count]
        stages.append({"clues": observed, "relations": infer_relations(reference, word, observed),
                       "equivalence": "undetermined"})
    return {"held_out": word, "name_hits": hits, "stages": stages}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("word")
    parser.add_argument("clues", nargs="*")
    args = parser.parse_args()
    result = replay(json.loads(args.corpus.read_text(encoding="utf-8")), args.word, args.clues)
    print(json.dumps(result, ensure_ascii=False, indent=2))
