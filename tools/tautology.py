"""Tautology tool: how far the graph is from the proof level, and what already follows. Standard library only.

The core counts the rungs (``ladder``) and walks one judgement back (``why``). This file asks the questions the
name stands for: which level does a node stand on, which edges are still below proof, and which proof edges
follow from the stated ones whatever the data.

It also judges definitions, the way TalkCompress judges a round trip: a rule decides first, and what a rule cannot
decide goes to a judgment model (an LLM there). A rule is a feature name or ``[OP, rule, ...]`` with OP one of
AND OR NOT NAND NOR — JSON, so it travels unchanged through py_launch.cjs. ``judge`` runs a rule over every
concept of a corpus (the core's ``define_concepts`` input) and counts FN / FP; ``rules`` builds the candidates
from set operations on the common part (genus) and what tells the neighbours apart; ``equivalent`` checks two
rules on every truth assignment, so a rewritten rule can be restored without loss (reversible). ``holdout`` and
``guess`` measure the definitions on what they were not built from; ``wobble`` shakes the names (the corpus's name
side) on TalkCompress's tiers: exact, notation folded, one character apart.

Ladder: a rule with no FN and no FP over every observed concept is ``derived`` (it holds for what was
collected, one more concept can refute it); an equivalence over every assignment is ``proof``.

CLI: python -S tools/tautology.py rules | judge | equivalent | holdout | guess | wobble ... (through the core's command line, so the core
commands and exit codes come along).

Dependency goes one way: tools/ import the core, the core never imports tools/.
Every function is callable by name from Python, and from Node through vendor/py_launch.cjs (--call).
"""
import collections
import itertools
import json
import math
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ontautology as ot  # noqa: E402

__all__ = ["standing", "gaps", "entailed", "holds", "atoms", "judge", "rules", "holdout", "guess", "guess_report", "wobble", "cases", "equivalent", "main"]
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
    observed = ot._normalize_corpus(corpus)[0]  # the elements are all a judge needs; no definitions
    if concept not in observed:
        raise ValueError(f"unknown concept: {concept!r}")
    matched, fp, fn, to_model, tn = [], [], [], [], 0
    for name, elements in sorted(observed.items()):
        if elements is None:
            to_model.append(name)
            continue
        said = holds(rule, set(elements))
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
    """Candidate rules for ``concept`` from set operations, each judged; reversible first, then accuracy, then
    what the concept has before what it lacks, then fewer features, then the order below.

    genus                   AND of the common part with the similar concepts (the control: it also lets them in)
    genus-most-differentia  genus AND all but one of the shortest distinguishing keys (one may be missing);
                            the values of one attribute are one clue (any of them)
    genus-nor-neighbours    genus AND NOR(what only the similar concepts have) — knows only the neighbours it saw
    genus-nand-neighbours   genus AND NAND(what only the similar concepts have) — weaker: not all of it
    all-elements            AND of every observed element
    What the concept has comes before what it lacks (the -neighbours shapes): an unseen neighbour lacks the seen
    neighbours' features too, so a NOR of them lets it in. Those two are the fallback.
    ``definition`` is the first reversible rule, or None while every candidate is refuted or undecided.
    """
    info = ot.define_concepts(corpus, [concept])["concepts"].get(concept)
    if info is None or info["elements"] is None:
        return {"concept": concept, "candidates": [], "definition": None, "to_model": [concept]}
    genus = info["definition"]["genus"]
    neighbours = sorted({el for side in info["differentia"]["vs_similar"].values() for el in side["only_similar"]})
    # Only the shortest keys: a longer key is a combination of features others share, and it lets unseen neighbours in.
    shortest = min((len(key) for key in info["differentia"]["minimal_keys"] if key), default=0)
    keys = [key for key in info["differentia"]["minimal_keys"] if key and len(key) == shortest]
    # One attribute is one clue, as it is one question in guess: 別名:アキアジ or 別名:トキシラズ counts once.
    clues = {}
    for key in keys:
        clues.setdefault(key[0].split(":", 1)[0] if len(key) == 1 and ":" in key[0] else tuple(key), []).append(key)
    clues = [key[0] if len(key) == 1 else ["AND", *key] for key, *more in clues.values() if not more] + \
            [["OR", *(key[0] for key in group)] for group in clues.values() if len(group) > 1]
    # All but one: a masked observation may take one clue away, but one clue an unseen neighbour shares is not enough.
    flat = lambda group: [*sorted({el for clue in group if not isinstance(clue, list) or clue[0] == "AND" for el in ([clue] if isinstance(clue, str) else clue[1:])}),
                          *(clue for clue in group if isinstance(clue, list) and clue[0] == "OR")]
    most = ["OR", *(["AND", *flat(group)] for group in itertools.combinations(clues, max(1, len(clues) - 1)))]
    shapes = [("genus", ["AND", *genus], genus),
              ("genus-most-differentia", ["AND", *genus, most], keys),
              ("genus-nor-neighbours", ["AND", *genus, ["NOR", *neighbours]], genus and neighbours),
              ("genus-nand-neighbours", ["AND", *genus, ["NAND", *neighbours]], genus and neighbours),
              ("all-elements", ["AND", *info["elements"]], True)]
    found = [{"shape": shape, "atoms": len(atoms(rule)), **judge(corpus, concept, rule)} for shape, rule, usable in shapes if usable]
    rank = [shape for shape, _, _ in shapes]  # on a tie, the genus-built shapes come before listing every element
    found.sort(key=lambda row: (row["verdict"] != "reversible", -(row["accuracy"] or 0), row["shape"].endswith("-neighbours"),
                                row["atoms"], rank.index(row["shape"])))
    definition = next((row["rule"] for row in found if row["verdict"] == "reversible"), None)
    return {"concept": concept, "candidates": found, "definition": definition, "to_model": found[0]["to_model"] if found else []}


def _without(corpus, name):
    """The corpus with one concept masked out: its elements, its maybe and names, and every similar pair that names it."""
    concepts = corpus.get("concepts", {})
    concepts = ({k: v for k, v in concepts.items() if k != name} if isinstance(concepts, dict)
                else [entry for entry in concepts if entry.get("id") != name])
    ends = lambda e: e if isinstance(e, (list, tuple)) else (e.get("left", e.get("source")), e.get("right", e.get("target")))
    beside = {key: {k: v for k, v in corpus[key].items() if k != name} for key in ("maybe", "names") if isinstance(corpus.get(key), dict)}
    return {**corpus, **beside, "concepts": concepts, "similar": [e for e in corpus.get("similar", []) if name not in ends(e)]}


def holdout(corpus, names=None):
    """How each definition behaves on what it was not built from: 🙈 unseen concepts and 🎭 masked elements.

    unseen  for every other observed concept x: mask x out of the corpus, build the definition again, then judge x
            with it. A pass is an FP on unseen data — the collection looked enough only because x was missing.
    masked  for every element e of the concept: judge the concept itself with e hidden. A miss means the
            definition needs e and breaks when that observation is missing (an AND keeps every element it names).
    Defaults to the corpus seeds. ``summary`` adds the counts up; ``rate`` is misses per test.
    """
    defined = ot.define_concepts(corpus)["concepts"]
    names = names or corpus.get("seeds") or sorted(defined)
    observed = [name for name, info in sorted(defined.items()) if info["elements"] is not None]
    found = {}
    for name in names:
        info = defined.get(name)
        if info is None or info["elements"] is None:
            found[name] = {"concept": name, "definition": None, "to_model": [name]}
            continue
        elements, definition = set(info["elements"]), rules(corpus, name)["definition"]
        fp, undefined = [], []
        for other in (x for x in observed if x != name):
            rule = rules(_without(corpus, other), name)["definition"]
            if rule is None:
                undefined.append(other)
            elif holds(rule, set(defined[other]["elements"])):
                fp.append(other)
        fn = [] if definition is None else [e for e in sorted(elements) if not holds(definition, elements - {e})]
        found[name] = {"concept": name, "definition": definition,
                       "unseen": {"tested": len(observed) - 1 - len(undefined), "fp": fp, "undefined": undefined},
                       "masked": {"tested": len(elements) if definition else 0, "fn": fn}}
    rows = [row for row in found.values() if row["definition"] is not None]
    count = lambda part, key: sum(len(row[part][key]) for row in rows)
    tested = lambda part: sum(row[part]["tested"] for row in rows)
    rate = lambda part, key: round(count(part, key) / tested(part), 4) if tested(part) else None
    return {"concepts": found, "summary": {
        "seeds": len(names), "defined": len(rows),
        "unseen": {"tested": tested("unseen"), "fp": count("unseen", "fp"), "rate": rate("unseen", "fp")},
        "masked": {"tested": tested("masked"), "fn": count("masked", "fn"), "rate": rate("masked", "fn")}}}


def _attribute(elements, name):
    """The values an element set gives for one attribute (``属性:値``), as a sorted tuple; () when it has none."""
    return tuple(sorted(e.split(":", 1)[1] for e in elements if e.startswith(name + ":")))


def guess(corpus, target, *, lies=0, forget=(), known=True, sure=1):
    """🎯 A guessing game over the corpus: ask until one candidate is left, like twenty questions or Numeron.

    Two kinds of question: "does it have e?" (yes / no) and, for ``属性:値`` elements, "what is its 属性?" (the
    values, as Numeron answers more than yes or no). The upper layer (``broader``: 楽器 → 区分:道具 → 上位:もの) is asked about
    too, so one question can split groups that share nothing else. Each turn takes the question whose worst answer leaves the
    fewest candidates. A candidate dies after more than ``lies`` answers against it; its ``maybe`` elements
    (links allowed to be wrong) never count against it. The answerer answers from the target's elements but
    says no to the ones in ``forget`` (a person who forgot). With ``known=False`` the target is not among the
    candidates: the honest end is no guess. ``estimate`` is ceil(log2 candidates), the yes / no ideal.

    ✅ One candidate left is not the answer yet. The answers that isolated it may be shared with someone the game
    does not know, so they count for nothing; the game asks what only the candidate has — its rarest answers not
    asked yet. Each answer weighs log2(candidates / sharers) over log2(candidates), so an answer no one else
    gives is one whole identification; ``confidence`` gains the weight when the answer fits and loses it when it
    does not, and starts below zero by the answers the candidate already failed. It answers once ``confidence``
    reaches ``sure`` (0: confirm only to make up for answers it failed), or when nothing is left to ask and nothing
    stands against it; it guesses nothing if the candidate fails more than ``lies`` answers or falls short.
    """
    concepts, _, _, _ = ot._normalize_corpus(corpus)
    if concepts.get(target) is None:
        raise ValueError(f"unknown or unobserved concept: {target!r}")
    maybe, broader = ot._beside(corpus, concepts, "maybe"), ot._broader(corpus)
    up = lambda elements: set(elements) | ot._above(broader, elements)  # 🪜 what is above them is theirs too
    truth = up(concepts[target]) - set(forget)  # one forgotten element is one wrong answer, not its upper layer too
    book = {name: (up(found), up(maybe.get(name, ())) - up(found)) for name, found in concepts.items()
            if found is not None and (known or name != target)}
    strikes, asked, log, missed = dict.fromkeys(book, 0), set(), [], {name: [] for name in book}
    by_attribute = lambda elements: {a: _attribute(elements, a) for a in {e.split(":", 1)[0] for e in elements if ":" in e}}
    table = {name: (by_attribute(found), by_attribute(may)) for name, (found, may) in book.items()}  # read once, asked often
    value = lambda name, side, attribute: table[name][side].get(attribute, ())
    holders = {}  # element -> (who has it, who may have it)
    for name, sides in book.items():
        for side, elements in enumerate(sides):
            for element in elements:
                holders.setdefault(element, (set(), set()))[side].add(name)
    alive = lambda: [name for name in sorted(book) if strikes[name] <= lies]

    def ask(kind, question, confirm=False):
        """kind 1: does it have the element (yes / no); kind 0: what is its attribute (the values)."""
        asked.add(question)
        if kind:
            answer = question in truth
            against = [n for n in book if question not in book[n][1] and (question in book[n][0]) != answer]
            log.append({"ask": question, "answer": answer})
        else:
            answer = _attribute(truth, question)
            against = [n for n in book if not value(n, 1, question) and value(n, 0, question) != answer]
            log.append({"ask": question + ":?", "answer": list(answer)})
        for name in against:
            strikes[name] += 1
            missed[name].append((kind, question))
        log[-1].update({"left": len(alive())}, **({"confirm": True} if confirm else {}))
    while len(alive()) > 1:
        live, options = alive(), []
        living = set(live)
        for element in sorted({e for name in live for e in book[name][0] | book[name][1]} - asked):
            has, may = holders[element]
            yes, no = len(living & (has | may)), len(live) - len(living & (has - may))  # a maybe answers either way
            if yes < len(live) and no < len(live):
                options.append((max(yes, no), 1, element))
        for name in sorted({e.split(":", 1)[0] for n in live for e in book[n][0] if ":" in e} - asked):
            groups = {}
            for n in live:
                groups.setdefault(value(n, 0, name), []).append(n)
            if len(groups) > 1:
                options.append((max(map(len, groups.values())), 0, name))
        if not options:
            break
        ask(*min(options)[1:])
    live = alive()
    fewest = min((strikes[n] for n in live), default=None)
    best = [n for n in live if strikes[n] == fewest]
    picked = best[0] if len(best) == 1 else None
    confidence = 0.0
    if picked is not None:  # ✅ confirm with the rarest answers of the one left (in the whole corpus), not asked yet
        found = book[picked][0]
        same = lambda kind, q: sum((q in book[n][0]) == (q in found) if kind else value(n, 0, q) == value(picked, 0, q) for n in book)
        weight = lambda kind, q: math.log2(len(book) / same(kind, q)) / math.log2(len(book)) if len(book) > 1 else 1.0
        confidence -= sum(weight(*miss) for miss in missed[picked])  # answers it already failed count against it
        rare = sorted((same(kind, q), kind, q) for kind, q in [*((1, e) for e in found - asked if ":" not in e),
                                                                 *((0, a) for a in {e.split(":", 1)[0] for e in found if ":" in e} - asked)])
        left = len(rare)
        for _, kind, question in rare:
            if confidence >= sure or strikes[picked] > lies:
                break
            before, left = strikes[picked], left - 1
            ask(kind, question, confirm=True)
            confidence += weight(kind, question) if strikes[picked] == before else -weight(kind, question)
        # nothing left to ask and nothing against it: the best answer there is, with the confidence it has
        enough = confidence >= sure or (not left and confidence >= 0)
        picked = picked if strikes[picked] <= lies and enough else None
    return {"target": target, "known": known, "lies": lies, "forget": sorted(forget), "questions": log,
            "count": len(log), "estimate": math.ceil(math.log2(len(book))) if len(book) > 1 else 0,
            "guess": picked, "confidence": round(confidence, 2), "reached": picked == target if known else picked is None}


def guess_report(corpus, names=None, *, lies=0, sure=1):
    """🎯 The guessing game for every observed concept (or ``names``), in three scenes.

    honest  the answerer knows the target and answers truly
    forget  the answerer forgets one element of the target at a time (🎭 a mask)
    unseen  the target is not among the questioner's candidates (🙈); reached means it said "I do not know"
    """
    concepts, _, _, _ = ot._normalize_corpus(corpus)
    names = names or [name for name in sorted(concepts) if concepts[name] is not None]
    scenes = {"honest": [guess(corpus, n, lies=lies, sure=sure) for n in names],
              "forget": [guess(corpus, n, lies=lies, sure=sure, forget=[e]) for n in names for e in sorted(concepts[n] or ())],
              "unseen": [guess(corpus, n, lies=lies, sure=sure, known=False) for n in names]}
    def tally(games):
        reached = [g for g in games if g["reached"]]
        return {"games": len(games), "reached": len(reached), "rate": round(len(reached) / len(games), 4) if games else None,
                "mean_questions": round(sum(g["count"] for g in games) / len(games), 2) if games else None,
                "max_questions": max((g["count"] for g in games), default=None),
                "missed": sorted({g["target"] for g in games if not g["reached"]})}
    return {"lies": lies, "sure": sure, "estimate": scenes["honest"][0]["estimate"] if names else 0,
            "summary": {scene: tally(games) for scene, games in scenes.items()},
            "honest": {g["target"]: {"count": g["count"], "guess": g["guess"], "questions": g["questions"]} for g in scenes["honest"]}}


def _notation(text):
    """A written form with its notation folded, as TalkCompress's notation_tolerant tier: width (NFKC), case,
    separators (space - _ ・ ·), katakana as hiragana, and a long-vowel mark ー as the vowel before it."""
    out = []
    for ch in unicodedata.normalize("NFKC", text).casefold():
        if ch in " -_・·":
            continue
        if "ァ" <= ch <= "ヶ":
            ch = chr(ord(ch) - 0x60)
        if ch == "ー" and out and "ぁ" <= out[-1] <= "ゖ" and unicodedata.name(out[-1])[-1] in "AIUEO":
            ch = "あいうえお"["AIUEO".index(unicodedata.name(out[-1])[-1])]
        out.append(ch)
    return "".join(out)


def _one_apart(a, b):
    """One character inserted, deleted or replaced, or two neighbours swapped (and not equal)."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    a, b = sorted((a, b), key=len)
    i = next((k for k, (x, y) in enumerate(zip(a, b)) if x != y), len(a))
    return a[i + (len(a) == len(b)):] == b[i + 1:] or len(a) == len(b) and a[i:i + 2] == b[i + 1] + b[i] and a[i + 2:] == b[i + 2:]


def _shake(text):
    """Ways a person might write the same name, as (kind, variant), each different from ``text``.

    notation  kana (katakana and hiragana swapped), long (ー spelled out as its vowel, or a repeated vowel
              written ー), width (full-width letters and digits), case, space (separators dropped or spaced):
              these fold back to the same form, so the name should come back on the notation tier
    typo      drop (one character left out) and swap (two neighbours swapped): one slip of the hand
    """
    kana = lambda ch, off: chr(ord(ch) + off)
    vowel = lambda ch: unicodedata.name(ch, " ")[-1] if "ぁ" <= _notation(ch) <= "ゖ" else ""
    out = [("kana", "".join(kana(ch, -0x60) if "ァ" <= ch <= "ヶ" else kana(ch, 0x60) if "ぁ" <= ch <= "ゖ" else ch for ch in text))]
    spelled, marked = [], []
    for i, ch in enumerate(text):
        before = vowel(text[i - 1]) if i else ""
        spelled.append("あいうえお"["AIUEO".index(before)] if ch == "ー" and before in tuple("AIUEO") else ch)
        marked.append("ー" if i and _notation(ch) in "あいうえお" and before and vowel(ch) == before and ch != "ー" else ch)
    out += [("long", "".join(spelled)), ("long", "".join(marked))]
    out += [("width", "".join(chr(ord(ch) + 0xFEE0) if "!" <= ch <= "~" else ch for ch in text)), ("case", text.swapcase())]
    if any(ch in " -_・·" for ch in text):
        out += [("space", "".join(ch for ch in text if ch not in " -_・·")), ("space", "".join(" " if ch in "-_・·" else ch for ch in text))]
    if len(text) > 2:
        out += [("drop", text[:i] + text[i + 1:]) for i in range(len(text))]
        out += [("swap", text[:i] + text[i + 1] + text[i] + text[i + 2:]) for i in range(len(text) - 1) if text[i] != text[i + 1]]
    seen, kept = {text}, []
    for kind, variant in out:
        if variant not in seen:
            seen.add(variant)
            kept.append((kind, variant))
    return kept


def wobble(corpus, words=()):
    """🔤 Shake the names and see what comes out, on TalkCompress's tiers: exact ⊂ notation ⊂ near.

    Each concept's written forms are its own name and the values of its ``names`` (読み:さけ → さけ), folded by
    ``_notation``. A word of one character is near any other, so near compares forms of two or more.
    words     each word looked up: exact, the same once folded, or one character apart. ``via`` is the name it
              hit: 酒 hits 鮭 through 同音語:酒, a word that sounds the same, not 鮭 itself
    near      concepts whose forms are one character apart (マリオ・ワリオ), and whether they are similar too
    same      a folded form two concepts share: that name splits
    rephrase  thing-side elements that contain the concept's own name or reading: they only restate the name
              (白鮭 has 鮭 in it, サケ属 has さけ), so they belong on the name side. Anything here is worth a look.
    shaken    every written form shaken on purpose (``_shake``) and looked up again. The first tier with a hit is
              the answer: ``rate`` is how often the concept is in it, ``false_merges`` how many other concepts
              are in it too, for notation and typo kinds. A hit on another concept is only counted: no two
              concepts are ever merged.
    Each hit also carries ``id``, the concept's stable ID (its name when it has none).
    """
    concepts, meta, pairs, _ = ot._normalize_corpus(corpus)
    called = ot._beside(corpus, concepts, "names")
    forms = {name: [(name, name), *((el, el.split(":", 1)[-1]) for el in called.get(name, ()))] for name in sorted(concepts)}
    folded = {name: [(via, text, _notation(text)) for via, text in rows] for name, rows in forms.items()}
    near_enough = lambda a, b: min(len(a), len(b)) > 1 and _one_apart(a, b)

    def look(word):
        key, found, seen = _notation(word), {"exact": [], "notation": [], "near": []}, set()
        for tier, hit in (("exact", lambda text, f: text == word), ("notation", lambda text, f: f == key),
                          ("near", lambda text, f: near_enough(f, key))):
            for name, rows in folded.items():
                for via, text, f in rows:
                    if (name, via) not in seen and hit(text, f):
                        seen.add((name, via))
                        found[tier].append({"concept": name, "id": meta[name].get("id", name), "via": via})
        return found

    similar = {frozenset((p["left"], p["right"])) for p in pairs}
    near = []
    for a, b in itertools.combinations(folded, 2):
        hit = next(([va, vb] for va, _, fa in folded[a] for vb, _, fb in folded[b] if near_enough(fa, fb)), None)
        if hit:
            near.append({"pair": [a, b], "via": hit, "similar": frozenset((a, b)) in similar})
    shared = {}
    for name, rows in folded.items():
        for _, _, f in rows:
            shared.setdefault(f, set()).add(name)
    same = [{"form": f, "concepts": sorted(names)} for f, names in sorted(shared.items()) if len(names) > 1]
    rephrase = {}
    for name, elements in sorted(concepts.items()):
        keys = [folded[name][0][2], *(f for _, _, f in folded[name][1:] if len(f) > 1)]
        hits = [el for el in elements or () if any(k in _notation(el) for k in keys)]
        if hits:
            rephrase[name] = hits
    tally = lambda: {"tries": 0, "returned": 0, "false_merges": 0}
    shaken, misses, merges = {"notation": tally(), "typo": tally()}, [], []
    kinds = {}
    for name, rows in forms.items():
        for via, text in rows:
            for kind, variant in _shake(text):
                group = "typo" if kind in ("drop", "swap") else "notation"
                hits = {hit["concept"] for hit in next((tier for tier in look(variant).values() if tier), [])}
                for counts in (shaken[group], kinds.setdefault(kind, tally())):
                    counts["tries"] += 1
                    counts["returned"] += name in hits
                    counts["false_merges"] += len(hits - {name})
                if name not in hits:
                    misses.append({"concept": name, "via": via, "kind": kind, "query": variant})
                merges += [{"concept": name, "other": other, "via": via, "kind": kind, "query": variant} for other in sorted(hits - {name})]
    for counts in (*shaken.values(), *kinds.values()):
        counts["rate"] = round(counts["returned"] / counts["tries"], 4) if counts["tries"] else None
    shaken.update({"kinds": dict(sorted(kinds.items())), "misses": misses[:12], "merges": merges[:12]})
    return {"words": {word: look(word) for word in words}, "near": near, "same": same, "rephrase": rephrase, "shaken": shaken,
            "summary": {"concepts": len(forms), "named": len(called), "near": len(near), "near_similar": sum(row["similar"] for row in near),
                        "same": len(same), "rephrase": sum(map(len, rephrase.values())),
                        "shaken": {group: shaken[group]["rate"] for group in ("notation", "typo")},
                        "false_merges": shaken["notation"]["false_merges"] + shaken["typo"]["false_merges"]}}


def cases(corpus, *, sure=1):
    """📋 Observed cases (who said what, in which role) read against the concepts, apart from what people judged.

    A case is an observation: what was said (``statement``), where (``context``), on what (``evidence``), by whom
    (``actor``: kept as the record, never reasoned on) in which position (``role``), its ``6W1H`` (誰が・誰へ・何を・
    どうやって・いつまで・どう) and the thing-side ``elements`` seen in it.
    candidate  the only concept that has every known element of the case (with what is above its elements), once
               those elements weigh ``sure`` identifications, weighed as ``guess`` weighs answers. A hypothesis.
    to_model   elements no concept has: reading them is the middle layer's (a judgment model's) work
    missing    6W1H slots left empty
    judgments  what someone in a role decided (``holds``: it is / is not that concept), kept apart from the case.
               They change no definition and no candidate: one decision is not a rule.
    status     confirmed (the judgments agree with the candidate) · disputed (one does not: worth a look) ·
               judged (people decided what the concepts could not) · pending (no judgment yet)
    """
    concepts, meta, _, _ = ot._normalize_corpus(corpus)
    maybe, broader = ot._beside(corpus, concepts, "maybe"), ot._broader(corpus)
    up = lambda elements: set(elements) | ot._above(broader, elements)
    held = {name: up(found) | up(maybe.get(name, ())) for name, found in concepts.items() if found is not None}
    holders = {}
    for name, elements in held.items():
        for element in elements:
            holders.setdefault(element, set()).add(name)
    weight = lambda element: math.log2(len(held) / len(holders[element])) / math.log2(len(held)) if len(held) > 1 else 1.0
    raw_cases, raw_judgments = corpus.get("cases", []), corpus.get("judgments", [])
    if not isinstance(raw_cases, list) or not isinstance(raw_judgments, list):
        raise ValueError("cases and judgments must be lists")
    found, slots = {}, ("誰が", "誰へ", "何を", "どうやって", "いつまで", "どう")
    for case in raw_cases:
        if not isinstance(case, dict) or not isinstance(case.get("elements", []), list) or not isinstance(case.get("6W1H", {}), dict):
            raise ValueError("a case is an object with an id, a list of elements and a 6W1H object")
        cid = ot._nonempty_str(case.get("id"), "case id")
        if cid in found:
            raise ValueError(f"duplicate case id: {cid!r}")
        seen = {ot._nonempty_str(el, f"{cid} element") for el in case.get("elements", [])}
        known = sorted(seen & set(holders))
        fits = sorted(name for name in held if set(known) <= held[name]) if known else []
        confidence = round(sum(map(weight, known)), 2)
        one = fits[0] if len(fits) == 1 and confidence >= sure else None
        found[cid] = {**{k: case[k] for k in ("statement", "context", "evidence", "actor", "role") if k in case},
                      "candidate": one and {"concept": one, "id": meta[one].get("id", one), "basis": "hypothesis", "confidence": confidence},
                      "fits": fits, "to_model": sorted(seen - set(holders)),
                      "missing": [slot for slot in slots if not case.get("6W1H", {}).get(slot)], "judgments": []}
    for judgment in raw_judgments:
        cid = judgment.get("case") if isinstance(judgment, dict) else None
        if cid not in found or judgment.get("concept") not in held or not isinstance(judgment.get("holds"), bool):
            raise ValueError("a judgment names a known case, an observed concept and holds (true / false)")
        candidate = found[cid]["candidate"]
        found[cid]["judgments"].append({**{k: judgment[k] for k in ("concept", "holds", "actor", "role", "note") if k in judgment},
                                        "basis": "observed", "agrees": None if candidate is None else (judgment["concept"] == candidate["concept"]) == judgment["holds"]})
    for row in found.values():
        agrees = [j["agrees"] for j in row["judgments"]]
        row["status"] = ("pending" if not agrees else "judged" if row["candidate"] is None else
                         "disputed" if False in agrees else "confirmed")
    count = lambda key, value: sum(row[key] == value for row in found.values())
    roles = lambda rows: dict(sorted(collections.Counter(row["role"] for row in rows if "role" in row).items()))
    return {"cases": found, "summary": {
        "cases": len(found), "candidate": sum(row["candidate"] is not None for row in found.values()),
        "to_model": sum(bool(row["to_model"]) for row in found.values()),
        **{status: count("status", status) for status in ("confirmed", "disputed", "judged", "pending")},
        "roles": {"cases": roles(found.values()), "judgments": roles(j for row in found.values() for j in row["judgments"])}}}


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


def _guess_arguments(parser):
    _rules_arguments(parser)
    parser.add_argument("--lies", type=int, default=0, help="answers against a candidate it survives (default 0)")
    parser.add_argument("--sure", type=float, default=1.0,
                        help="confidence to reach before answering, in identifications (1: one answer no one else gives, the default)")


def _guess(args):
    found = guess_report(ot._read_json(args.graph), args.terms or None, lies=args.lies, sure=args.sure)
    return found, found["summary"]["honest"]["reached"] < found["summary"]["honest"]["games"]


def _holdout(args):
    found = holdout(ot._read_json(args.graph), args.terms or None)
    summary = found["summary"]
    return found, bool(summary["unseen"]["fp"]) or summary["defined"] < summary["seeds"]


def _wobble_arguments(parser):
    _corpus(parser)
    parser.add_argument("words", nargs="*", help="words to look up by their names: exact, notation folded, one character apart")


def _wobble(args):
    found = wobble(ot._read_json(args.graph), args.words)
    return found, bool(found["rephrase"])


def _cases_arguments(parser):
    _corpus(parser)
    parser.add_argument("--graph", dest="as_graph", action="store_true", help="emit case statuses, candidates and judgments as nodes and edges")
    parser.add_argument("--sure", type=float, default=1.0, help="weight the case's elements need before a concept is its candidate (default 1)")


def _cases(args):
    corpus = ot._read_json(args.graph)
    found = cases(corpus, sure=args.sure)
    disputed = bool(found["summary"]["disputed"])
    if not args.as_graph:
        return found, disputed

    _, meta, _, _ = ot._normalize_corpus(corpus)
    nodes, edges = {}, []
    for case_id, row in found["cases"].items():
        cid = "case:" + case_id
        nodes[cid] = f"{case_id} ({row['status']})"
        if candidate := row["candidate"]:
            target = "concept:" + candidate["id"]
            nodes[target] = candidate["concept"]
            edges.append(dict(source=cid, kind="candidate", basis=candidate["basis"], target=target))
        for element in row["to_model"]:
            target = "elem:" + element
            nodes[target] = element
            edges.append(dict(source=cid, kind="to_model", target=target))
        for i, judgment in enumerate(row["judgments"]):
            jid = f"judgment:{case_id}:{i}"
            nodes[jid] = judgment.get("actor") or jid
            target = "concept:" + meta[judgment["concept"]].get("id", judgment["concept"])
            nodes[target] = judgment["concept"]
            edges.append(dict(source=cid, kind="judgment", target=jid))
            edges.append(dict(source=jid, kind="holds " + str(judgment["holds"]).lower(), target=target))
    return {"nodes": [{"id": key, "name": name} for key, name in nodes.items()],
            "edges": edges}, disputed


def main(argv=None):
    """Exit codes as the core: 0 answered, 1 input error, 2 answered and something needs a look."""
    return ot.main(argv, commands=(
        ("rules", "🧩 第二弾 · ⚖️ candidate rules per concept, judged; the first reversible one is the definition", _rules_arguments, _rules),
        ("judge", "🧩 第二弾 · 🧮 one rule as the judge of a concept: FN / FP / accuracy / propositions", _judge_arguments, _judge),
        ("equivalent", "🧩 第二弾 · ✅ two rules on every truth assignment (proof) or a counterexample", _equivalent_arguments, _equivalent),
        ("holdout", "🧩 第二弾 · 🙈 unseen concepts and 🎭 masked elements: how definitions hold on what they were not built from", _rules_arguments, _holdout),
        ("guess", "🧩 第二弾 · 🎯 guessing game: questions to reach each concept, honest / forgetting / unseen", _guess_arguments, _guess),
        ("wobble", "🧩 第二弾 · 🔤 shake the names: near names, a name that splits, names inside the thing side, shaken names coming back", _wobble_arguments, _wobble),
        ("cases", "🧩 第三弾 · 📋 observed cases read against the concepts, apart from the judgments people made", _cases_arguments, _cases)))


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
