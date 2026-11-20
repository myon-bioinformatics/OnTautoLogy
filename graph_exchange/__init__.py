"""Exchange named RDF statements through a scoped property graph."""

import argparse
import base64
import json
import os
import sys
from pathlib import Path
from urllib.request import Request, urlopen

from rdflib import BNode, Graph, URIRef
from rdflib.util import from_n3


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
    formats = {".ttl": "turtle", ".nt": "nt", ".rdf": "xml"}
    path = Path(path)
    suffix = path.suffix.lower() or ".ttl"
    if suffix not in formats:
        raise ValueError("Supported RDF input extensions: " + ", ".join(formats))
    return Graph().parse(path, format=formats[suffix])


def statements(graph):
    """Encode terms with their RDF datatype or language intact."""
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
        sub.add_argument("backend", choices=("neo4j", "arcade"))
        sub.add_argument("scope")
        if action == "export":
            sub.add_argument("file", nargs="?", type=Path, help="output file (default: stdout)")
            sub.add_argument("--format", choices=("ttl", "json"), help="stdout format (default: ttl)")
        else:
            sub.add_argument("file", type=Path, help=".ttl, .nt, .rdf")
    query = subs.add_parser("query")
    query.add_argument("file", type=Path, help=".ttl, .nt, .rdf")
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
            graph = read_graph(args.file)
        except ValueError as exc:
            parser.error(str(exc))
        if args.action == "import":
            transfer(args.backend, args.scope, graph)
        else:
            print(graph.query(args.select).serialize(format="json").decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(prog="python -m onto_exchange"))
