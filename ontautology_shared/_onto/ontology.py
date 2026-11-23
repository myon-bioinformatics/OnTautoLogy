"""Validate vocabularies and identities, and exchange named RDF statements."""
import argparse
import base64
import json
import os
import sys
from pathlib import Path
from urllib.request import Request, urlopen

__all__ = ["classes", "violations", "identity", "read_graph", "statements", "graph_json", "transfer"]


def classes(relations):
    """The classes a vocabulary names, sorted."""
    return sorted({kind for domains, range_type in relations.values() for kind in (*domains, range_type)})


def violations(graph, relations):
    """Every place ``graph`` ({"nodes": [{"id", "type"}], "edges": [{"source", "relation", "target"}]}) leaves
    the vocabulary: a node id used twice, an unknown class, an edge to a node that is not there, an unknown
    relation, a relation between the wrong classes. An empty list means the vocabulary holds for these
    nodes and edges — nothing more."""
    known, findings, nodes = set(classes(relations)), [], {}
    for index, node in enumerate(graph["nodes"]):
        if node["id"] in nodes:
            findings.append({"kind": "duplicate-node", "node": index, "detail": f"{node['id']} is listed twice"})
        nodes[node["id"]] = node
        if node["type"] not in known:
            findings.append({"kind": "unknown-class", "node": index, "detail": f"{node['id']} has class {node['type']!r}"})
    for index, edge in enumerate(graph["edges"]):
        missing = [end for end in ("source", "target") if edge[end] not in nodes]
        for end in missing:
            findings.append({"kind": "missing-reference", "edge": index, "detail": f"{end} {edge[end]} is not a known node"})
        if edge["relation"] not in relations:
            findings.append({"kind": "unknown-relation", "edge": index, "detail": f"unknown relation {edge['relation']!r}"})
        elif not missing:
            domains, range_type = relations[edge["relation"]]
            source, target = nodes[edge["source"]]["type"], nodes[edge["target"]]["type"]
            if source not in domains or target != range_type:
                findings.append({"kind": "domain-range", "edge": index,
                                 "detail": f"{edge['relation']} joins {source} → {target}, expected {' | '.join(domains)} → {range_type}"})
    return findings


def key_report(items, candidates):
    """Can an attribute set be the key of these entries? Identity is settled last: a handle first, a key only
    when the observations support it, and a key that collides is reported, not overwritten.

    key        complete and unique — may be promoted from handle to identity
    repeat     unique except for entries equal in every field (the same entry listed twice)
    collides   one value names entries that differ — not an identity
    incomplete some entry lacks a field, so nothing is claimed
    The verdict is about these entries only; one more entry can turn ``key`` into ``collides``.
    """
    report = {}
    for fields in candidates:
        groups, missing = {}, 0
        for item in items:
            if any(item.get(field) in (None, "") for field in fields):
                missing += 1
                continue
            groups.setdefault(tuple(str(item[field]) for field in fields), []).append(json.dumps(item, sort_keys=True, ensure_ascii=False))
        repeats = sorted(key for key, texts in groups.items() if len(texts) > 1 and len(set(texts)) == 1)
        conflicts = sorted(key for key, texts in groups.items() if len(set(texts)) > 1)
        verdict = "incomplete" if missing else "collides" if conflicts else "repeat" if repeats else "key"
        report["+".join(fields)] = {"verdict": verdict, "distinct": len(groups), "repeats": len(repeats), "collisions": len(conflicts),
                                    "missing": missing, "examples": ["+".join(key) for key in (conflicts or repeats)[:5]]}
    return report


def identity(items, candidates):
    """Which attribute set may be promoted from handle to key: the first candidate, in the caller's order of
    preference, that is complete and unique over these entries (core ``key_report`` verdict ``key``).

    ``key`` is None while no candidate qualifies — the entries keep their handles and the report says why
    (collides, repeat, incomplete). One more entry can take a key away again; identity is settled last.
    """
    candidates = [tuple(fields) for fields in candidates]
    report = key_report(items, candidates)
    key = next((fields for fields in candidates if report["+".join(fields)]["verdict"] == "key"), None)
    return {"key": list(key) if key else None, "report": report}


WRITE = """
UNWIND $rows AS row
MERGE (s:OtlTerm {scope: $scope, term: row.subject})
MERGE (o:OtlTerm {scope: $scope, term: row.object})
MERGE (s)-[:OtlStatement {predicate: row.predicate}]->(o)
"""
READ = """
MATCH (s:OtlTerm)-[r:OtlStatement]->(o:OtlTerm)
WHERE s.scope = $scope AND o.scope = $scope
RETURN s.term AS subject, r.predicate AS predicate, o.term AS object
"""


def read_graph(path):
    """Read one local RDF graph using its filename to select the syntax."""
    from rdflib import Graph

    formats = {".ttl": "turtle", ".nt": "nt", ".rdf": "xml"}
    path = Path(path)
    suffix = path.suffix.lower() or ".ttl"
    if suffix not in formats:
        raise ValueError("Supported RDF input extensions: " + ", ".join(formats))
    return Graph().parse(path, format=formats[suffix])


def _read_stdin_turtle():
    from rdflib import Graph

    stream = getattr(sys.stdin, "buffer", None)
    if stream is None:
        raise ValueError("Turtle stdin is unavailable")
    try:
        data = stream.read()
    except (OSError, ValueError) as exc:
        raise ValueError("Could not read Turtle from stdin") from exc
    try:
        return Graph().parse(data=data, format="turtle")
    except UnicodeDecodeError as exc:
        raise ValueError("Turtle on stdin must be valid UTF-8") from exc
    except SyntaxError as exc:
        raise ValueError("Invalid Turtle on stdin") from exc


def statements(graph):
    """Encode terms with their RDF datatype or language intact."""
    from rdflib import BNode, URIRef

    rows = []
    for subject, predicate, obj in graph:
        if not isinstance(subject, URIRef) or isinstance(obj, BNode):
            raise ValueError("Use stable IRIs for unnamed resources before exchange")
        rows.append(dict(subject=subject.n3(), predicate=predicate.n3(), object=obj.n3()))
    return sorted(rows, key=lambda r: (r["subject"], r["predicate"], r["object"]))


def graph_json(graph):
    """Build a portable node/relationship view of the scoped RDF statements."""
    rows = statements(graph)
    terms = sorted({row[key] for row in rows for key in ("subject", "object")})
    nodes = [{"id": term, "labels": ["OtlTerm"], "properties": {"term": term}} for term in terms]
    rels = [
        {"label": "OtlStatement", "start": {"id": row["subject"]},
         "end": {"id": row["object"]}, "properties": {"predicate": row["predicate"]}}
        for row in rows
    ]
    return {"nodes": nodes, "rels": rels}


def arcade(language, command, params):
    endpoint = os.environ["ARCADE_COMMAND_URL"]
    auth = base64.b64encode(os.environ["ARCADE_CREDENTIALS"].encode()).decode()
    body = json.dumps(dict(language=language, command=command, params=params)).encode()
    req = Request(endpoint, data=body, headers={"Authorization": "Basic " + auth,
                                                "Content-Type": "application/json"})
    with urlopen(req, timeout=30) as response:
        return json.load(response)["result"]


def transfer(backend, scope, graph=None):
    """Append idempotently to a scope, or export it when graph is omitted."""
    from rdflib import Graph
    from rdflib.util import from_n3

    rows = statements(graph) if graph is not None else None
    if backend == "neo4j":
        from neo4j import GraphDatabase
        auth = (os.environ.get("NEO4J_USER", "neo4j"), os.environ["NEO4J_PASSWORD"])
        with GraphDatabase.driver(os.environ["NEO4J_URI"], auth=auth) as driver:
            with driver.session(database=os.environ.get("NEO4J_DATABASE", "neo4j")) as session:
                if rows is not None:
                    session.execute_write(lambda tx: tx.run(WRITE, scope=scope, rows=rows).consume())
                    return
                result = session.run(READ, scope=scope).data()
    elif backend == "arcade":
        if rows is not None:
            arcade("opencypher", WRITE, dict(scope=scope, rows=rows))
            return
        result = arcade("opencypher", READ, dict(scope=scope))
    else:
        raise ValueError(f"Unknown backend {backend}")
    output = Graph()
    for row in result:
        triple = tuple(from_n3(row[key]) for key in ("subject", "predicate", "object"))
        if triple in output:
            raise ValueError("Duplicate database relationship for RDF triple")
        output.add(triple)
    return output


def main(argv=None, *, prog="ontautology exchange"):
    parser = argparse.ArgumentParser(prog=prog)
    subs = parser.add_subparsers(dest="action", required=True)
    for action in ("import", "export"):
        sub = subs.add_parser(action)
        sub.add_argument("backend", choices=("neo4j", "arcade"),help="graph database")
        sub.add_argument("scope",help="scope name that keeps these statements apart from others")
        if action == "export":
            sub.add_argument("file", nargs="?", type=Path, help="output file (default: stdout)")
            sub.add_argument("--format", choices=("ttl", "json"), help="stdout format (default: ttl)")
        else:
            sub.add_argument("file", type=Path, help=".ttl, .nt, .rdf file or - for Turtle on stdin")
    query = subs.add_parser("query")
    query.add_argument("file", type=Path, help=".ttl, .nt, .rdf file or - for Turtle on stdin")
    query.add_argument("select", help="SPARQL SELECT")
    args = parser.parse_args(argv)
    if args.action == "export":
        stdout = args.file is None or args.file == Path("-")
        if not stdout and args.format:
            parser.error("--format is for stdout; the filename selects the file format")
        fmt = (args.format or "ttl") if stdout else (args.file.suffix.lower()[1:] or "ttl")
        if fmt not in ("ttl", "json"):
            parser.error("Supported export extensions: .ttl, .json")
        graph = transfer(args.backend, args.scope)
        if fmt == "json":
            output = json.dumps(graph_json(graph), ensure_ascii=False, indent=2) + "\n"
        elif stdout:
            output = graph.serialize(format="turtle")
        else:
            graph.serialize(destination=args.file, format="turtle")
            return 0
        if stdout:
            sys.stdout.write(output)
        else:
            args.file.write_text(output, encoding="utf-8")
    else:
        try:
            if args.file == Path("-"):
                graph = _read_stdin_turtle()
            else:
                graph = read_graph(args.file)
        except ValueError as exc:
            parser.error(str(exc))
        if args.action == "import":
            transfer(args.backend, args.scope, graph)
        else:
            print(graph.query(args.select).serialize(format="json").decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(prog="python -m ontology"))
