"""Tautology tool: how far the graph is from the proof level, and what already follows. Standard library only.

The core counts the rungs (``ladder``) and walks one judgement back (``why``). This file asks the questions the
name stands for: which level does a node stand on, which edges are still below proof, and which proof edges
follow from the stated ones whatever the data.

It also judges definitions, the way TalkCompress judges a round trip: a rule decides first, and what a rule cannot
decide goes to a judgment model (an LLM there). A rule is a feature name or ``[OP, rule, ...]`` with OP one of
AND OR NOT NAND NOR — JSON, so it travels unchanged through py_launch.cjs. ``judge`` runs a rule over every
concept of a corpus (the core's ``define_concepts`` input) and counts FN / FP; ``rules`` builds the candidates
from set operations on the common part (genus) and what tells the neighbours apart; ``equivalent`` checks two
rules on every truth assignment, so a rewritten rule can be restored without loss (reversible).

Ladder: a rule with no FN and no FP over every observed concept is ``derived`` (it holds for what was
collected, one more concept can refute it); an equivalence over every assignment is ``proof``.

CLI: python -S tools/tautology.py rules | judge | equivalent ... (through the core's command line, so the core
commands and exit codes come along).

Dependency goes one way: tools/ import the core, the core never imports tools/.
Every function is callable by name from Python, and from Node through vendor/py_launch.cjs (--call).
"""
import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ontautology as ot  # noqa: E402

__all__ = ["standing", "gaps", "entailed", "holds", "atoms", "judge", "rules", "equivalent", "main"]
OPS = {"AND": all, "OR": any, "NAND": lambda v: not all(v), "NOR": lambda v: not any(v), "NOT": lambda v: not v[0]}


def holds(rule, elements):
    """Does ``rule`` hold for a set of elements. An empty AND is true, an empty OR is false; NOT takes one rule."""
    if isinstance(rule, str):
        return rule in elements
    if not isinstance(rule, (list, tuple)) or not rule or rule[0] not in OPS or (rule[0] == "NOT" and len(rule) != 2):
        raise ValueError(f"a rule is a feature name or [AND|OR|NOT|NAND|NOR, rule, ...]: {rule!r}")
    return OPS[rule[0]]([holds(part, elements) for part in rule[1:]])


def atoms(rule):
    """The feature names a rule mentions, sorted."""
    return sorted({rule} if isinstance(rule, str) else {name for part in rule[1:] for name in atoms(part)})


def judge(corpus, concept, rule):
    """Run ``rule`` as the judge of "x is ``concept``" over every concept of the corpus.

    fp: the rule says yes, it is another concept — a counterexample to the proposition (rule → concept) and
        its contrapositive (not concept → not rule).
    fn: it is the concept, the rule says no — a counterexample to the converse (concept → rule) and the
        inverse (not rule → not concept).
    to_model: concepts whose elements were not observed; the rule cannot decide them, a judgment model may.
    verdict: reversible (no fn, no fp, nothing left undecided) · refuted (a counterexample) · undecided.
    """
    defined = ot.define_concepts(corpus)["concepts"]
    if concept not in defined:
        raise ValueError(f"unknown concept: {concept!r}")
    matched, fp, fn, to_model, tn = [], [], [], [], 0
    for name, info in sorted(defined.items()):
        if info["elements"] is None:
            to_model.append(name)
            continue
        said = holds(rule, set(info["elements"]))
        matched += [name] if said else []
        fp += [name] if said and name != concept else []
        fn += [name] if not said and name == concept else []
        tn += not said and name != concept
    tp = len(matched) - len(fp)
    seen = tp + len(fp) + len(fn) + tn
    verdict = "refuted" if fp or fn else "undecided" if to_model else "reversible"
    return {"concept": concept, "rule": rule, "matched": matched, "fp": fp, "fn": fn, "to_model": to_model,
            "tp": tp, "tn": tn, "accuracy": round((tp + tn) / seen, 4) if seen else None,
            "precision": round(tp / len(matched), 4) if matched else None,
            "recall": round(tp / (tp + len(fn)), 4) if tp + len(fn) else None,
            "propositions": {"proposition": not fp, "contrapositive": not fp, "converse": not fn, "inverse": not fn},
            "verdict": verdict, "basis": "derived" if verdict == "reversible" else "hypothesis"}


def rules(corpus, concept):
    """Candidate rules for ``concept`` from set operations, each judged; reversible first, then fewer features,
    then the order below.

    genus                  AND of the common part with the similar concepts (the control: it also lets them in)
    genus-nor-neighbours   genus AND NOR(what only the similar concepts have)
    genus-nand-neighbours  genus AND NAND(what only the similar concepts have) — weaker: not all of it
    genus-or-differentia   genus AND OR(each minimal distinguishing key)
    all-elements           AND of every observed element
    ``definition`` is the first reversible rule, or None while every candidate is refuted or undecided.
    """
    info = ot.define_concepts(corpus, [concept])["concepts"].get(concept)
    if info is None or info["elements"] is None:
        return {"concept": concept, "candidates": [], "definition": None, "to_model": [concept]}
    genus = info["definition"]["genus"]
    neighbours = sorted({el for side in info["differentia"]["vs_similar"].values() for el in side["only_similar"]})
    keys = [["AND", *key] for key in info["differentia"]["minimal_keys"] if key]
    shapes = [("genus", ["AND", *genus], genus),
              ("genus-nor-neighbours", ["AND", *genus, ["NOR", *neighbours]], genus and neighbours),
              ("genus-nand-neighbours", ["AND", *genus, ["NAND", *neighbours]], genus and neighbours),
              ("genus-or-differentia", ["AND", *genus, ["OR", *keys]], keys),
              ("all-elements", ["AND", *info["elements"]], True)]
    found = [{"shape": shape, "atoms": len(atoms(rule)), **judge(corpus, concept, rule)} for shape, rule, usable in shapes if usable]
    rank = [shape for shape, _, _ in shapes]  # on a tie, the genus-built shapes come before listing every element
    found.sort(key=lambda row: (row["verdict"] != "reversible", -(row["accuracy"] or 0), row["atoms"], rank.index(row["shape"])))
    definition = next((row["rule"] for row in found if row["verdict"] == "reversible"), None)
    return {"concept": concept, "candidates": found, "definition": definition, "to_model": found[0]["to_model"] if found else []}


def equivalent(left, right, *, limit=16):
    """Do two rules agree on every truth assignment of their features (at most ``limit`` of them).

    ``counterexample`` is the set of present features on which they first differ. Equivalence to ``["AND"]``
    (always true) means the rule is a tautology.
    """
    names = sorted(set(atoms(left)) | set(atoms(right)))
    if len(names) > limit:
        raise ValueError(f"{len(names)} features exceed the truth-table limit {limit}")
    for bits in itertools.product((False, True), repeat=len(names)):
        present = {name for name, bit in zip(names, bits) if bit}
        if holds(left, present) != holds(right, present):
            return {"equivalent": False, "counterexample": sorted(present), "atoms": names, "basis": "hypothesis"}
    return {"equivalent": True, "counterexample": None, "atoms": names, "basis": "proof"}


# ---------------------------------------------------------------- command line

def _rule(text):
    """A rule on the command line: JSON (["AND", "a", ["NOR", "b"]]) or a bare feature name."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _corpus(parser):
    parser.add_argument("graph", type=Path, help="a concept corpus (ontautology-concepts/1) or - for stdin")


def _rules_arguments(parser):
    _corpus(parser)
    parser.add_argument("terms", nargs="*", help="concepts (default: the corpus seeds, else every concept)")


def _judge_arguments(parser):
    _corpus(parser)
    parser.add_argument("concept")
    parser.add_argument("rule", type=_rule, help='JSON such as \'["AND", "弦楽器", ["NOR", "4弦標準"]]\'')


def _equivalent_arguments(parser):
    parser.add_argument("left", type=_rule)
    parser.add_argument("right", type=_rule)


def _rules(args):
    corpus = ot._read_json(args.graph)
    names = args.terms or corpus.get("seeds") or sorted(ot.define_concepts(corpus)["concepts"])
    found = {name: rules(corpus, name) for name in names}
    return found, any(row["definition"] is None for row in found.values())


def _judge(args):
    found = judge(ot._read_json(args.graph), args.concept, args.rule)
    return found, found["verdict"] != "reversible"


def _equivalent(args):
    found = equivalent(args.left, args.right)
    return found, not found["equivalent"]


def main(argv=None):
    """Exit codes as the core: 0 answered, 1 input error, 2 answered and something needs a look."""
    return ot.main(argv, commands=(
        ("rules", "🧩 第二弾 · ⚖️ candidate rules per concept, judged; the first reversible one is the definition", _rules_arguments, _rules),
        ("judge", "🧩 第二弾 · 🧮 one rule as the judge of a concept: FN / FP / accuracy / propositions", _judge_arguments, _judge),
        ("equivalent", "🧩 第二弾 · ✅ two rules on every truth assignment (proof) or a counterexample", _equivalent_arguments, _equivalent)))


if __name__ == "__main__":
    raise SystemExit(main())


def standing(edges, node):
    """The level a node stands on: the weakest basis among everything it rests on, however deep.

    ``level`` is None when nothing is stated for the node to rest on — a given, which is not a proof.
    ``tautology`` is true only when every edge underneath is at the proof level.
    """
    edges = list(edges)
    rows = ot.why(edges, node, depth=len(edges) + 1, limit=len(edges) + 1)["rows"]
    level = min((row["weakest"] for row in rows), key=ot.BASIS.index, default=None)
    return {"node": node, "level": level, "edges": len(rows), "tautology": level == "proof"}


def gaps(edges):
    """What is left before the graph is at the tautology level: the edges below proof, weakest first."""
    edges = list(edges)
    below = [edge for edge in edges if ot._basis(edge) != "proof"]
    below.sort(key=lambda edge: (ot.BASIS.index(ot._basis(edge)), edge["kind"], edge["source"], edge["target"]))
    return {"edges": len(edges), "proof": len(edges) - len(below), "gaps": below}


def entailed(edges, kinds):
    """Proof edges that follow by transitivity and are not stated at the proof level yet.

    ``kinds`` are the edge kinds the caller declares transitive (an implication between rules, "must come
    before"). From a → b and b → c, both proof, a → c holds for every case too; ``via`` keeps the chain.
    Edges below proof entail nothing here, and an edge stated only below proof is returned so it can be raised.
    """
    found = []
    for kind in dict.fromkeys(kinds):
        proven = [edge for edge in edges if edge["kind"] == kind and ot._basis(edge) == "proof"]
        stated = {(edge["source"], edge["target"]) for edge in proven}
        for source in sorted({edge["source"] for edge in proven}):
            for row in ot.reach(proven, [source], limit=len(proven) + 1)["rows"]:
                if (source, row["node"]) not in stated:
                    found.append({"kind": kind, "source": source, "target": row["node"], "basis": "proof", "via": row["via"]})
    return found
