"""Replay wave-two propositions under the observations disclosed by each source."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import ontautology as ot
from ontautology_shared.markers import marker_slots
from tools.tautology import evaluate_nodes


def argument_variants(pattern, nodes, references):
    """Compare a baseline to every single-argument substitution within one predicate."""
    slots = pattern["slots"]
    if not slots:
        raise ValueError("an argument pattern needs at least one slot")
    markers = {}
    choices = []
    for slot in slots:
        values = slot["values"]
        if not isinstance(values, list) or not values or len(set(values)) != len(values):
            raise ValueError("a slot needs distinct candidate values, baseline first")
        for value in values:
            if value is not None:
                ot._nonempty_str(value, "candidate value")
        markers.setdefault(slot["marker"], []).append({"role": slot["role"], "value": values[0]})
        choices.append(values)
    base = tuple(values[0] for values in choices)
    variants = [(None, base)]
    for index, values in enumerate(choices):
        for value in values[1:]:
            variants.append((index, base[:index] + (value,) + base[index + 1:]))
    allowed = {values for _, values in variants}
    rules = {}
    for binding in pattern["bindings"]:
        values = tuple(binding["values"])
        if values not in allowed or values in rules or None in values:
            raise ValueError(f"invalid or duplicate binding: {values!r}")
        rules[values] = binding["rule"]
    rows = []
    for index, values in variants:
        rule = rules.get(values)
        if values in rules:
            outcomes = evaluate_nodes({"nodes": nodes}, rule, partial=True)["nodes"]
        else:
            outcomes = [{"id": node["id"], "verdict": "unknown"} for node in nodes]
        for outcome in outcomes:
            outcome["source"] = references[outcome["id"]]["source"]
        rows.append({"changed_slot": index, "values": values, "mapped": values in rules,
                     "rule": rule, "observations": outcomes})
    return {"predicate": pattern["predicate"], "slots": slots, "baseline_markers": marker_slots(markers),
            "variants": rows}


def replay(groups, concepts, editions):
    """concepts maps each registered word to its corpus path, concept ID and elements."""
    results = {}
    patterns = {}
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
        if "argument_pattern" in group:
            patterns[topic] = argument_variants(group["argument_pattern"], nodes, references)
        for question in group.get("questions", []):
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
    return {"questions": results, "counts": dict(totals), "mismatches": mismatches, "argument_patterns": patterns}


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
