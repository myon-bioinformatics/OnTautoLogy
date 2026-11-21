"""OTL のグラフを TaxOntOy の分類表と TopOntoLogy の集計へ渡す境界。

想定する版は、調査時点で開いている PR が無かった両リポジトリの main です。

- TOO ``78ed91aee522e9a7305e2bf964dab9be2bd3fff0`` の ``otl-relations.json``。
  トップレベルはプロファイル名（``audit`` / ``concepts`` / ``cases``）から
  「OTL の関係名 → 分類名」へのオブジェクト。名前はどちらも空でない文字列。
  表に無い関係はグラフに残り、TOL が ``unclassified_edges`` として数える。
- TOL ``7bd70a45585e94522a1e87c362ee35b1316118d9`` の ``topology.summarize(graph, classes)``。
  ``graph["edges"]`` の各要素は ``source`` と ``target`` を持つ。
  関係名は ``kind`` があればそれ、無ければ ``relation``。
  戻り値は ``classes``（分類名 → ``edges`` / ``incident_nodes`` /
  ``multiple_sources`` / ``sample_cycles``）と ``unclassified_edges``。
  ``nodes`` は読まない。閉路は ONTO の ``relation_cycles``（最大 5 件）。

書き出す ``otl-tol-graph/1`` は ``nodes``（``id`` と、あれば ``type``・``name``）と
``edges``（``source`` / ``target`` / ``kind``）だけを持つ。監査グラフの ``relation`` は
``kind`` に写す。向きと ID は保存されたグラフのままで、芯の ``edges_of`` が行う反転はかけない。
閉路検出と端点の集計は TOL に残し、こちらは同じ規則で辺の本数だけを数える。
"""
from __future__ import annotations

import argparse
import json
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SCHEMA = "otl-tol-graph/1"
PROFILES = ("audit", "concepts", "cases")
TOO_COMMIT = "78ed91aee522e9a7305e2bf964dab9be2bd3fff0"
TOL_COMMIT = "7bd70a45585e94522a1e87c362ee35b1316118d9"
WAVE_TITLES = {
    "audit": "第一弾　監査の依存と重複",
    "concepts": "第二弾　階層と類似",
    "cases": "第三弾　候補・判断・未登録要素",
}
CASE_STATUS = {
    "confirmed": "確定",
    "disputed": "食い違い",
    "pending": "未判断",
    "judged": "人が決めた",
}


def _text(value, where):
    if not isinstance(value, str) or not value:
        raise ValueError(f"{where} must be a non-empty string")
    return value


def classification(document):
    """TOO の分類表。プロファイル名から関係名、関係名から分類名。"""
    if not isinstance(document, dict) or not document:
        raise ValueError("classification must be a non-empty object of profiles")
    table = {}
    for profile, classes in document.items():
        name = _text(profile, "profile name")
        if not isinstance(classes, dict) or not classes:
            raise ValueError(f"{name}: profile needs a non-empty relation map")
        mapped = {}
        for relation, category in classes.items():
            mapped[_text(relation, f"{name} relation")] = _text(category, f"{name} class")
        table[name] = mapped
    return table


def project(graph):
    """TOL が読む部分だけを残した ``otl-tol-graph/1``。同じ形をもう一度渡しても変わらない。"""
    if not isinstance(graph, dict) or not isinstance(graph.get("edges"), list):
        raise ValueError("a graph needs an edges array")
    raw_nodes = graph.get("nodes", [])
    if not isinstance(raw_nodes, list):
        raise ValueError("nodes must be an array")
    nodes = {}
    for index, node in enumerate(raw_nodes):
        if isinstance(node, str):
            node = {"id": node}
        if not isinstance(node, dict):
            raise ValueError(f"node {index} must be an object or id")
        ident = _text(node.get("id"), f"node {index} id")
        if ident in nodes:
            raise ValueError(f"duplicate node {ident}")
        kept = {"id": ident}
        for field in ("type", "name"):
            if node.get(field) is not None:
                kept[field] = _text(node[field], f"node {ident} {field}")
        nodes[ident] = kept
    edges = []
    for index, edge in enumerate(graph["edges"]):
        if not isinstance(edge, dict):
            raise ValueError(f"edge {index} must be an object")
        source = _text(edge.get("source"), f"edge {index} source")
        target = _text(edge.get("target"), f"edge {index} target")
        has_kind, has_relation = "kind" in edge, "relation" in edge
        if has_kind and has_relation and edge["kind"] != edge["relation"]:
            raise ValueError(f"edge {index}: kind and relation disagree")
        if not has_kind and not has_relation:
            raise ValueError(f"edge {index} needs kind or relation")
        kind = _text(edge["kind"] if has_kind else edge["relation"], f"edge {index} relation")
        edges.append({"source": source, "target": target, "kind": kind})
        nodes.setdefault(source, {"id": source})
        nodes.setdefault(target, {"id": target})
    edges.sort(key=lambda item: (item["kind"], item["source"], item["target"]))
    return {"schema": SCHEMA, "nodes": [nodes[key] for key in sorted(nodes)], "edges": edges}


def source_graph(profile, document):
    """固定の3プロファイルを、それぞれの OTL 入力からグラフにする。"""
    if not isinstance(document, dict):
        raise ValueError("input must be a JSON object")
    if profile == "audit":
        if document.get("schema") in ("ontautology/1", SCHEMA):
            return document
        from gh_audit.gh_audit import audit
        return audit([document])
    if profile == "concepts":
        if document.get("schema") in ("ontautology-concept-graph/1", SCHEMA):
            return document
        from ontautology import concept_edges
        return concept_edges(document)
    if profile == "cases":
        if document.get("schema") == SCHEMA:
            return document
        from tools.tautology import case_graph, cases
        return case_graph(document, cases(document))
    raise ValueError(f"unknown profile {profile!r}")


def export_graph(profile, document):
    return project(source_graph(profile, document))


def relation_groups(graph, classes):
    """TOL と同じ規則で、分類ごとの辺数と分類表に無い辺数だけを数える。"""
    counts = {category: 0 for category in sorted(set(classes.values()))}
    unclassified = 0
    for edge in graph["edges"]:
        relation = edge["kind"] if "kind" in edge else edge["relation"]
        if relation in classes:
            counts[classes[relation]] += 1
        else:
            unclassified += 1
    return {"classes": counts, "unclassified": unclassified}


def counts_agree(groups, summary):
    """投影の辺数が TOL の ``edges`` と ``unclassified_edges`` に一致するか。閉路は比べない。"""
    found = summary.get("classes", {})
    if set(groups["classes"]) != set(found) or groups["unclassified"] != summary.get("unclassified_edges"):
        return False
    return all(groups["classes"][name] == found[name]["edges"] for name in groups["classes"])


def _items(values, cycle):
    if not values:
        return "なし"
    if cycle:
        lines = (" → ".join(str(part) for part in path) for path in values)
    else:
        lines = (str(item) for item in values)
    return "<br>".join(escape(line) for line in lines)


def render_relations_page(report):
    """``wave-profiles.json`` と同じ形の集計を、Pages に置く HTML にする。"""
    sections = []
    for name, wave in report["waves"].items():
        rows = []
        for category, row in wave["classes"].items():
            rows.append(
                "<tr><th scope=\"row\">"
                + escape(category)
                + f"</th><td>{row['edges']:,}</td><td>{row['incident_nodes']:,}</td><td>"
                + _items(row.get("multiple_sources") or [], False)
                + "</td><td>"
                + _items(row.get("sample_cycles") or [], True)
                + "</td></tr>"
            )
        sections.append(
            f"<section id=\"{escape(name)}\"><h2>{escape(WAVE_TITLES.get(name, name))}</h2>"
            f"<p>分類表に無い辺は {wave['unclassified_edges']:,} 本です。</p>"
            "<table><caption>TOL が返した分類ごとの構造</caption><thead><tr>"
            "<th scope=\"col\">分類</th><th scope=\"col\">辺</th><th scope=\"col\">端点</th>"
            "<th scope=\"col\">複数の始点を持つ終点</th><th scope=\"col\">代表閉路</th>"
            "</tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table></section>"
        )
    statuses = []
    for case_id, status in report.get("case_status", {}).items():
        label = CASE_STATUS.get(status, status)
        statuses.append(
            f"<tr><th scope=\"row\">{escape(case_id)}</th><td>{escape(label)}</td>"
            f"<td><code>{escape(status)}</code></td></tr>"
        )
    status_section = ""
    if statuses:
        status_section = (
            "<section id=\"cases-status\"><h2>第三弾の判定</h2>"
            "<p>事例が成り立つかは OTL の cases が決めます。TOL は上の辺を数えます。</p>"
            "<table><caption>事例ごとの状態</caption><thead><tr>"
            "<th scope=\"col\">事例</th><th scope=\"col\">状態</th><th scope=\"col\">記録</th>"
            "</tr></thead><tbody>"
            + "".join(statuses)
            + "</tbody></table></section>"
        )
    too = f"https://github.com/myon-bioinformatics/TaxOntOy/commit/{TOO_COMMIT}"
    tol = f"https://github.com/myon-bioinformatics/TopOntoLogy/commit/{TOL_COMMIT}"
    body = "\n".join(sections)
    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TOO の分類で見た構造集計 | OnTautoLogy</title>
<link rel="stylesheet" href="../atlas/atlas.css">
<style>
table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
th, td {{ border: 1px solid #c3d5ce; padding: .4rem .6rem; vertical-align: top; text-align: left; }}
caption {{ text-align: left; font-weight: 600; margin-bottom: .4rem; }}
</style>
</head>
<body>
<main>
<nav><a href="../">OnTautoLogy</a> · <a href="../atlas/">知識グラフ</a></nav>
<h1>TOO の分類で見た構造集計</h1>
<p>第一弾から第三弾の固定例を <code>otl-tol-graph/1</code> に写し、
<a href="{too}">TOO {TOO_COMMIT[:12]}</a> の分類表で関係を選び、
<a href="{tol}">TOL {TOL_COMMIT[:12]}</a> の <code>topology.summarize</code> が数えた結果です。
数値の正本は <a href="profiles.json">profiles.json</a>（リポジトリの <code>examples/wave-profiles.json</code>）です。</p>
{body}
{status_section}
</main>
</body>
</html>
"""


def write_relations_site(report_path, output_dir):
    text = Path(report_path).read_text(encoding="utf-8")
    report = json.loads(text)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "profiles.json").write_text(text, encoding="utf-8")
    (output / "index.html").write_text(render_relations_page(report), encoding="utf-8")


def _load(path):
    if str(path) == "-":
        return json.loads(sys.stdin.read())
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="write an otl-tol-graph/1 document")
    export.add_argument("profile", choices=PROFILES)
    export.add_argument("source")
    export.add_argument("-o", type=Path, help="output path; standard output when omitted")
    check = commands.add_parser("check", help="count edges with a TOO classification table")
    check.add_argument("graph")
    check.add_argument("table")
    check.add_argument("profile")
    page = commands.add_parser("page", help="write the Pages article from wave-profiles.json")
    page.add_argument("report", type=Path)
    page.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "page":
            write_relations_site(args.report, args.output)
            return 0
        if args.command == "export":
            document = json.dumps(export_graph(args.profile, _load(args.source)), ensure_ascii=False, indent=2) + "\n"
            if args.o is None:
                sys.stdout.write(document)
            else:
                args.o.write_text(document, encoding="utf-8")
            return 0
        table = classification(_load(args.table))
        if args.profile not in table:
            raise ValueError(f"classification has no {args.profile!r} profile")
        found = relation_groups(project(_load(args.graph)), table[args.profile])
    except (OSError, ValueError, json.JSONDecodeError, KeyError) as error:
        print(error, file=sys.stderr)
        return 1
    print(json.dumps(found, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
