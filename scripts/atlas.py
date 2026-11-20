"""Build the public wave catalog and bounded Mermaid views from the same RDF triples."""
import argparse
from collections import defaultdict
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import subprocess
import sys
from urllib.parse import quote, unquote

from rdflib import Graph, Literal, Namespace, RDF, RDFS, URIRef
from rdflib.namespace import DCTERMS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gh_audit.gh_audit import audit, plan, transfer_report, turtle
from ontautology import concept_edges, define_concepts
from ontautology_shared._onto.knowledgegraph import graph_mermaid, mermaid_renderer_js
from ontautology_shared.truth import judgment_graph
from tools import tautology
from examples.relation_holdout import replay
from examples import detail_propositions, reversi

OT = Namespace("urn:otl:")
TITLES = ("第一弾　GitHub監査と移管", "第二弾　概念・語彙と論理検証", "第三弾　事例・判断と比較評価")
CORPUS = "examples/concepts-20261115.json"


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def key(value):
    return quote(str(value), safe=":-")


def resource(value):
    return OT[key(value)]


def record(graph, subject, data):
    """Expose nested records as resources; preserve nulls, list order and scalar types."""
    for field, value in data.items():
        predicate = OT["field:" + key(field)]
        if isinstance(value, dict):
            obj = URIRef(str(subject) + "/" + key(field))
            record(graph, obj, value)
        elif isinstance(value, list) and any(isinstance(v, (dict, list)) for v in value):
            obj = URIRef(str(subject) + "/" + key(field))
            record(graph, obj, dict(enumerate(value)))
        elif value is None or isinstance(value, list):
            obj = Literal(json.dumps(value, ensure_ascii=False), datatype=RDF.JSON)
        else:
            obj = Literal(value)
        graph.add((subject, predicate, obj))


def domain_graph(data):
    graph = Graph()
    for node in data["nodes"]:
        if isinstance(node, str):
            node = {"id": node}
        term = resource(node["id"])
        graph.add((term, RDFS.label, Literal(node.get("name", node["id"]))))
        if "type" in node:
            graph.add((term, RDF.type, resource(node["type"])))
        record(graph, term, {k: v for k, v in node.items() if k not in ("id", "name", "type")})
    for edge in data["edges"]:
        triple = resource(edge["source"]), resource(edge["kind"]), resource(edge["target"])
        attrs = {k: v for k, v in edge.items() if k not in ("source", "kind", "target")}
        if not attrs:
            graph.add(triple)
            continue
        digest = sha256(json.dumps(edge, sort_keys=True).encode()).hexdigest()
        claim = OT["claim:" + digest]
        graph.add((claim, RDF.type, RDF.Statement))
        for prop, value in zip((RDF.subject, RDF.predicate, RDF.object), triple):
            graph.add((claim, prop, value))
        lock = attrs.pop("lock", None)
        if lock:
            target = URIRef(lock) if lock.startswith(("https://", "http://")) else resource(lock)
            graph.add((claim, OT["field:lock"], target))
        record(graph, claim, attrs)
    return graph


def datasets():
    profiles = read("examples/wave-profiles.json")["waves"]
    for path, title in [("audit-20261114", "PR監査"), ("flutter-absorption", "Flutter移管台帳")]:
        source = f"examples/{path}.json"
        data = read(source)
        graph = audit([data])
        rdf = Graph().parse(data=turtle(graph), format="turtle")
        yield 1, path, title, source, rdf
        result = plan(graph) if path.startswith("audit") else transfer_report(data)
        yield 1, path+"-result", title+"の判定", source, result

    for path in sorted((ROOT / "examples").glob("concepts-*.json")):
        source = path.relative_to(ROOT).as_posix()
        data = read(source)
        title = "概念・名前・階層" if source == CORPUS else "ポリゴン2・人間・AI"
        graph = domain_graph(concept_edges(data))
        # Keep attributes outside the graph projection, including citation URLs.
        record(graph, resource(path.stem), {k: v for k, v in data.items() if k not in ("cases", "judgments")})
        yield 2, path.stem, title, source, graph
        results = {"definitions": define_concepts(data), "rules": {n: tautology.rules(data,n) for n in data["seeds"]},
                   "holdout": tautology.holdout(data), "guess": tautology.guess_report(data),
                   "wobble": tautology.wobble(data)}
        yield 2, path.stem+"-results", title+"の検証結果", source, results
        if data.get("cases"):
            rows = tautology.cases(data)
            output = subprocess.run([sys.executable, "tools/tautology.py", "cases", source, "--graph"],
                                    cwd=ROOT, capture_output=True, text=True)
            if output.returncode != (2 if rows["summary"]["disputed"] else 0):
                raise RuntimeError(output.stderr or "case graph failed")
            projection = json.loads(output.stdout)
            for node in projection["nodes"]:
                node.pop("markers", None)  # judgment_graph emits the queryable slots once.
            graph = domain_graph(projection)
            graph += judgment_graph(data, rows["cases"])
            for case in data["cases"]:
                term = resource("case:"+case["id"])
                details = dict(rows["cases"][case["id"]])
                details.pop("markers")
                record(graph, term, {"input": case, **details})
            yield 3, "cases-"+path.stem, "事例・候補・人の判断", source, graph
    source = "examples/concepts-20261120.json"
    yield 2, "bot-replay", "未登録語と手掛かりごとの判定", source, replay(
        read(source), "AI搭載bot", ["用途:自動応答", "入力から出力を推論"])
    source = "examples/detail-propositions.json"
    yield 2, "detail-propositions", "同じ命題を異なる条件で検証", source, detail_propositions.run(ROOT / source)
    source = "examples/lexical-gender.json"
    data = read(source)
    graph = domain_graph(data)
    record(graph, resource("lexical-gender"), {k:v for k,v in data.items() if k not in ("nodes","edges")})
    yield 2, "lexical-gender", "文法性と人間概念", source, graph
    for wave, slug, title, source in (
        (2, "bot", "AI搭載botの仮説", "site/concepts/bot.ttl"),
        (3, "K001", "夜間DB対応のRDF交換例", "examples/K001-night-db.ttl"),
    ):
        yield wave, slug, title, source, Graph().parse(ROOT/source, format="turtle")
    yield 3, "reversi", "リバーシの合法手と二つの評価", "examples/reversi.py", reversi.graph(reversi.opening_cases(), preview=True)
    source = "site/third-design/baseline-evidence.json"
    yield 3, "baseline", "固定版の評価値・測定条件", source, read(source)
    board = subprocess.check_output(["node", "scripts/board_export.cjs"], cwd=ROOT)
    yield 3, "board", "設計案・評価順序・比較記録", "site/third-design/review-records.js", json.loads(board)
    for wave, name in enumerate(("audit", "concepts", "cases"), 1):
        yield wave, name+"-profile", "TOO分類・TOL構造集計", "examples/wave-profiles.json", profiles[name]


def short(term):
    if isinstance(term, Literal):
        return str(term)
    text = unquote(str(term))
    for prefix in (str(OT)+"field:", str(OT), "urn:ontautology:", str(RDF), str(RDFS)):
        if text.startswith(prefix):
            return text[len(prefix):]
    return text.rsplit("#", 1)[-1]


def views(graph, entry):
    """Every incident triple is reachable, in pages small enough for Mermaid."""
    adjacent = defaultdict(list)
    for triple in sorted(graph, key=lambda t: tuple(v.n3() for v in t)):
        s, p, o = triple
        adjacent[s].append(triple)
        if isinstance(o, URIRef) and o != s:
            adjacent[o].append(triple)
    terms = sorted(adjacent, key=str)
    ids = {t: i for i, t in enumerate(terms)}
    def label(term):
        value = graph.value(term, RDFS.label) if isinstance(term, URIRef) else None
        return str(value or short(term))
    rows = []
    for term in terms:
        pages = []
        triples = adjacent[term]
        for i in range(0, len(triples), 8):
            batch = triples[i:i+8]
            nodes = {v for s, _, o in batch for v in (s,o)}
            diagram = graph_mermaid({
                "nodes": [{"id": t.n3(), "name": label(t)[:52]} for t in nodes],
                "edges": [{"source": s.n3(), "kind": short(p), "target": o.n3()} for s,p,o in batch]})
            pages.append({"diagram": diagram.split("\n",1)[1].removesuffix("```\n"),
                          "edges": [[short(p), label(o if s==term else s), ids.get(o if s==term else s),
                                     s==term] for s,p,o in batch]})
        rows.append({"label": label(term), "uri": str(term), "pages": pages})
    return {"start": ids[entry], "nodes": rows}


def build(out):
    out.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(["git","rev-parse","HEAD"], cwd=ROOT,text=True).strip()
    groups = {i: Graph() for i in range(1,4)}
    cards = {i: [] for i in groups}
    for wave, slug, title, source, data in datasets():
        entry = resource("dataset:"+slug)
        graph = data if isinstance(data,Graph) else Graph()
        if not isinstance(data,Graph):
            record(graph, entry, data)
        else:
            # Link the document to meaningful entry points; all subjects remain selectable.
            candidates = sorted(set(graph.subjects()), key=str)
            for term in candidates:
                if (term,RDF.type,RDF.Statement) in graph or str(term).startswith("urn:otl:claim:"):
                    continue
                if (term,RDFS.label,None) in graph or (term,RDF.type,None) in graph or term==candidates[0]:
                    graph.add((entry,DCTERMS.hasPart,term))
        for claim in set(graph.subjects(RDF.predicate, None)):
            subject, relation, obj = [graph.value(claim, prop) for prop in (RDF.subject, RDF.predicate, RDF.object)]
            if subject is not None and obj is not None:
                terms = [str(graph.value(t, RDFS.label) or short(t)) for t in (subject, relation, obj)]
                graph.add((claim, RDFS.label, Literal(" → ".join(terms))))
        graph.add((entry,RDFS.label,Literal(title,lang="ja")))
        url=f"https://github.com/myon-bioinformatics/OnTautoLogy/blob/{revision}/{source}"
        graph.add((entry,DCTERMS.source,URIRef(url)))
        graph.bind("otl",OT)
        graph.serialize(out/(slug+".ttl"), format="turtle")
        view = views(graph,entry)
        nodes = view["nodes"]
        folder = out/slug
        folder.mkdir(exist_ok=True)
        for i in range(0, len(nodes), 32):
            block = [node["pages"] for node in nodes[i:i+32]]
            (folder/f"{i//32}.json").write_text(json.dumps(block, ensure_ascii=False, separators=(",", ":")))
        index = {"title": title, "start": view["start"], "nodes": [[n["label"], n["uri"]] for n in nodes]}
        (out/(slug+".json")).write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")))
        groups[wave] += graph
        cards[wave].append(f'<li><a href="view.html?set={slug}">{escape(title)}</a>　'
                           f'<small>{len(graph):,} triples · <a href="{slug}.ttl" download>TTL</a> · '
                           f'<a href="{escape(url)}">出典</a></small></li>')
    sections = []
    for wave, graph in groups.items():
        graph.bind("otl",OT)
        graph.serialize(out/f"wave-{wave}.ttl",format="turtle")
        sections.append(f'<section id="wave-{wave}"><h2>{TITLES[wave-1]}</h2>'
                        f'<p><a href="wave-{wave}.ttl" download>この弾のTTLを一括取得</a>（{len(graph):,} triples）</p>'
                        f'<ul>{"".join(cards[wave])}</ul></section>')
    template=(ROOT/"scripts/atlas-index.html").read_text()
    (out/"index.html").write_text(template.replace("<!-- waves -->","\n".join(sections)))


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output",type=Path)
    parser.add_argument("--renderer-output", type=Path, help="also write the shared ES module for the atlas and concepts pages")
    args = parser.parse_args()
    build(args.output)
    if args.renderer_output:
        args.renderer_output.parent.mkdir(parents=True, exist_ok=True)
        args.renderer_output.write_text(mermaid_renderer_js(), encoding="utf-8")
