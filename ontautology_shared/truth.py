"""RDF projections of a truth-table classification and of attributed case judgments."""
import json
from urllib.parse import quote

try:
    from rdflib import Graph, Literal, Namespace, RDF, RDFS
except ModuleNotFoundError as exc:
    if exc.name != "rdflib":
        raise
    raise ValueError("Install ontautology[exchange] to generate Turtle") from exc

import ontautology as ot

OT = Namespace("urn:otl:")


def formula_graph(rule, result):
    """Project classify(rule). isTrue is defined only for a constant truth table."""
    graph = Graph()
    graph.bind("ot", OT)
    term = OT["formula:" + ot.digest(rule)]
    graph.add((term, RDF.type, OT.Proposition))
    graph.add((term, OT.rule, Literal(json.dumps(rule, ensure_ascii=False), datatype=RDF.JSON)))
    verdict = result["verdict"]
    graph.add((term, OT.classification, OT[verdict]))
    if verdict in ("tautology", "contradiction"):
        graph.add((term, OT.isTrue, Literal(verdict == "tautology")))
    return graph


def entailment_graph(premises, conclusion, result):
    """Keep the outcome on the inference check, scoped to its premises."""
    graph = Graph()
    graph.bind("ot", OT)
    check = OT["inference:" + ot.digest([premises, conclusion])]
    graph.add((check, RDF.type, OT.InferenceCheck))
    graph.add((check, OT.verdict, OT[result["verdict"]]))
    for predicate, rules in ((OT.premise, premises), (OT.conclusion, [conclusion])):
        for rule in rules:
            term = OT["formula:" + ot.digest(rule)]
            graph.add((check, predicate, term))
            graph.add((term, RDF.type, OT.Proposition))
            graph.add((term, OT.rule, Literal(json.dumps(rule, ensure_ascii=False), datatype=RDF.JSON)))
    if result["counterexample"] is not None:
        present = set(result["counterexample"])
        assignment = {name: name in present for name in result["atoms"]}
        graph.add((check, OT.counterexample, Literal(json.dumps(assignment, ensure_ascii=False), datatype=RDF.JSON)))
    return graph


def judgment_graph(corpus, cases):
    """Project the validated rows from cases(). Each judgment speaks for its own record."""
    graph = Graph()
    graph.bind("ot", OT)
    _, concepts, _, _ = ot._normalize_corpus(corpus)
    for case_id, row in cases.items():
        case_key = quote(case_id, safe=":-")
        case = OT["case:" + case_key]
        graph.add((case, RDF.type, OT.Case))
        for field in ("statement", "context", "evidence", "actor", "role"):
            if field in row:
                graph.add((case, OT[field], Literal(row[field])))
        for index, judgment in enumerate(row["judgments"]):
            node = OT[f"judgment:{case_key}:{index}"]
            concept = judgment["concept"]
            concept_id = concepts[concept].get("id", concept)
            concept_term = OT["concept:" + quote(concept_id, safe=":-")]
            prop = OT[f"proposition:{case_key}/{quote(concept_id, safe='')}"]
            graph.add((prop, RDF.type, OT.Proposition))
            graph.add((prop, OT.aboutCase, case))
            graph.add((prop, OT.concept, concept_term))
            graph.add((concept_term, RDFS.label, Literal(concept)))
            graph.add((case, OT.judgment, node))
            graph.add((node, RDF.type, OT.Judgment))
            relation = OT.regardsAsTrue if judgment["holds"] else OT.regardsAsFalse
            graph.add((node, relation, prop))
            for field in ("actor", "role", "note", "evidence"):
                if field in judgment:
                    graph.add((node, OT[field], Literal(judgment[field])))
    return graph
