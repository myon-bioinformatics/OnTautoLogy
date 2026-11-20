"""Replay wave-two propositions under the observations disclosed by each source."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import ontautology as ot
from tools.tautology import evaluate_nodes


def replay(groups, concepts, editions):
    """concepts maps each registered word to its corpus path, concept ID and elements."""
    results = {}
    totals = Counter()
    mismatches = []
    for topic, group in groups.items():
        nodes = []
        references = {}
        for label, observation in group["observations"].items():
            word = observation["concept"]
            corpus, concept_id, elements = concepts[word]
            if "edition" in observation:
                edition = observation["edition"]
                entry = editions[concept_id]["editions"][edition]
                facts = dict.fromkeys(entry["claims"], True)
                source = entry["source"]
            elif "source" in observation:
                facts = observation["facts"]
                source = observation["source"]
            else:
                if elements is None:
                    raise ValueError(f"{word}: no observed elements")
                facts = dict.fromkeys(elements, True)
                source = corpus
            if "id" in facts or not all(isinstance(v, bool) for v in facts.values()):
                raise ValueError(f"{label}: expected boolean facts")
            nodes.append({**facts, "id": label})
            references[label] = {"concept": word, "source": source, "facts": facts}
        for question in group["questions"]:
            key = question["id"]
            if key in results or not nodes or question["expect"].keys() != references.keys():
                raise ValueError(f"{key}: duplicate ID or incomplete expectation matrix")
            rule = question["rule"]
            classification = ot.classify(rule)
            evaluation = evaluate_nodes({"nodes": nodes}, rule, partial=True)
            for row in evaluation["nodes"]:
                label = row["id"]
                row["expected"] = question["expect"][label]
                row["source"] = references[label]["source"]
                row["concept"] = references[label]["concept"]
                row["observed"] = {k: v for k, v in references[label]["facts"].items() if k in classification["atoms"]}
                if row["expected"] != row["verdict"]:
                    mismatches.append([key, label])
            totals.update(evaluation["counts"])
            results[key] = {"topic": topic, "question": question["text"], "rule": rule,
                            "logical_form": classification["verdict"], "observations": evaluation["nodes"]}
    return {"questions": results, "counts": dict(totals), "mismatches": mismatches}


def run(path):
    concepts = {}
    for corpus in sorted((ROOT / "examples").glob("concepts-*.json")):
        elements, meta, _, _ = ot._normalize_corpus(ot._read_json(corpus))
        for name in elements:
            if name in concepts:
                raise ValueError(f"ambiguous concept: {name}")
            concepts[name] = (corpus.relative_to(ROOT).as_posix(), meta[name].get("id", name), elements[name])
    return replay(ot._read_json(path), concepts, ot._read_json(ROOT / "examples/pokedex-editions.json"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", type=Path, default=Path(__file__).with_name("detail-propositions.json"))
    report = run(parser.parse_args().input)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(2 if report["mismatches"] else 0)
