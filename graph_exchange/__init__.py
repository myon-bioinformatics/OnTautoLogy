"""Exchange named RDF statements through a scoped property graph."""

import argparse
import base64
import json
import os
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


def statements(graph):
    """Encode terms with their RDF datatype or language intact."""
    rows = []
    for subject, predicate, obj in graph:
        if not isinstance(subject, URIRef) or isinstance(obj, BNode):
            raise ValueError("Use stable IRIs for unnamed resources before exchange")
        rows.append(dict(subject=subject.n3(), predicate=predicate.n3(), object=obj.n3()))
    return sorted(rows, key=lambda r: (r["subject"], r["predicate"], r["object"]))


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


def main(argv):
    parser = argparse.ArgumentParser(prog="ontautology exchange")
    subs = parser.add_subparsers(dest="action", required=True)
    for action in ("import", "export"):
        sub = subs.add_parser(action)
        sub.add_argument("backend", choices=("neo4j", "arcade"))
        sub.add_argument("scope")
        sub.add_argument("turtle", type=Path)
    query = subs.add_parser("query")
    query.add_argument("turtle", type=Path)
    query.add_argument("select", help="SPARQL SELECT")
    args = parser.parse_args(argv)
    if args.action == "export":
        transfer(args.backend, args.scope).serialize(destination=args.turtle, format="turtle")
    else:
        graph = Graph().parse(args.turtle, format="turtle")
        if args.action == "import":
            transfer(args.backend, args.scope, graph)
        else:
            print(graph.query(args.select).serialize(format="json").decode())
    return 0
