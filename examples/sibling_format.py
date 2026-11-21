"""OTL のグラフを TaxOntOy の分類表と TopOntoLogy の集計へ渡す境界。

想定する版は両リポジトリの main のマージコミットです。

- TOO ``8621f2261d694af0de35e103ad2387872ca10b99``（親は ``30c5ed689cb931bce3787e37056082ce8cb52b3d``
  と ``8cfb0cab3a917ffe9b945fc0c6d4ee0e8edc7f04``、版 0.2.0）の ``taxontoy.py``。
  ``taxonomy.py`` は無い。表は ``taxontoy-relations/2`` で、``taxontoy-relations/1`` も読む。
  どちらも ``audit`` / ``concepts`` / ``cases`` が「関係名 → 分類名」、``direction`` が向き、
  ``excluded`` がその弾では数えない関係名です。``/2`` はそれに ``properties`` を足す。
  ``properties.classes`` は ``transitive`` / ``symmetric`` / ``acyclic``、
  ``properties.relations`` はそれらに ``inverse_of`` と ``disjoint_with`` を足した宣言です。
  各宣言は ``since``（ASCII の YYYY-MM-DD）と ``reason`` を持ち、相手を指す宣言は ``relation`` も持つ。
  版ごとのトップレベルキーは過不足なく一致しなければならない。未知の schema は一行で失敗する。
  ``holds false`` は固定例に辺が無いので表に無く、現れたら被覆の未分類になります。
  ``taxontoy coverage`` は分類済み・除外・未分類・表にあってグラフに無い名前が
  重ならず全体を覆うことを見ます。``taxontoy candidates`` は畳まずに候補を出します。
  CLI の JSON には版と入力の sha256 が入ります。
- TOL ``d8880c9e55a0ce502dbf54a128bcaf471f0efc0e``（親は ``7bd70a45`` と ``3184b725``）の
  ``topontology.py``。``from topology import summarize`` は互換のために残っている。
  ``graph["edges"]`` の各要素は ``source`` と ``target`` を持つ。
  関係名は ``kind`` があればそれ、無ければ ``relation``。
  分類ごとの値は従来の ``edges`` / ``incident_nodes`` / ``multiple_sources`` /
  ``sample_cycles`` に加え、``degree`` / ``weakly_connected_components`` /
  ``independent_cycles`` / ``depth`` / ``order_cycle`` を持つ。
  CLI の JSON はそれらに ``tool``（名前と版）と ``provenance``（入力パスと sha256）を足す。
  ``nodes`` は集計には使わない。閉路は ONTO の ``relation_cycles``（既定は最大 5 件）。

書き出す ``otl-tol-graph/1`` は ``nodes``（``id`` と、あれば ``type``・``name``）と
``edges``（``source`` / ``target`` / ``kind``）だけを持つ。監査グラフの ``relation`` は
``kind`` に写す。向きと ID は保存されたグラフのままで、芯の ``edges_of`` が行う反転はかけない。
閉路検出と端点の集計は TOL に残し、こちらは同じ規則で辺の本数だけを数える。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SCHEMA = "otl-tol-graph/1"
PROFILES = ("audit", "concepts", "cases")
TOO_COMMIT = "8621f2261d694af0de35e103ad2387872ca10b99"
SCHEMA_V1 = "taxontoy-relations/1"
SCHEMA_V2 = "taxontoy-relations/2"
TOL_COMMIT = "d8880c9e55a0ce502dbf54a128bcaf471f0efc0e"
_VERSION_KEYS = {
    SCHEMA_V1: frozenset({"schema", *PROFILES, "direction", "excluded"}),
    SCHEMA_V2: frozenset({"schema", *PROFILES, "direction", "excluded", "properties"}),
}
_CLASS_NAMES = frozenset({
    "affirmation", "dependency", "hierarchy", "hypothesis", "judgment-record",
    "negation", "overlap", "similarity", "unknown-element",
})
_CLASS_FLAGS = frozenset({"acyclic", "symmetric", "transitive"})
_RELATION_FLAGS = frozenset({"acyclic", "disjoint_with", "inverse_of", "symmetric", "transitive"})
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
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


def _profile_map(profile, classes):
    if not isinstance(classes, dict) or not classes:
        raise ValueError(f"{profile}: profile needs a non-empty relation map")
    mapped = {}
    for relation, category in classes.items():
        mapped[_text(relation, f"{profile} relation")] = _text(category, f"{profile} class")
    return mapped


def _unsupported(schema):
    if isinstance(schema, str):
        shown = " ".join(schema.split())
    else:
        shown = type(schema).__name__
    if not shown:
        shown = "empty"
    raise ValueError(f"unsupported table schema: {shown}")


def _since_ok(value):
    if not isinstance(value, str) or _DATE.fullmatch(value) is None:
        return False
    year_text, month_text, day_text = value.split("-")
    year, month, day = int(year_text), int(month_text), int(day_text)
    if month < 1 or month > 12 or day < 1:
        return False
    if month == 2:
        leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
        last = 29 if leap else 28
    elif month in (4, 6, 9, 11):
        last = 30
    else:
        last = 31
    return day <= last


def _declaration(body, where, partner):
    """``since`` と ``reason``、相手を指すときは ``relation`` を読む。"""
    if not isinstance(body, dict):
        raise ValueError(f"{where} must be an object")
    allowed = {"reason", "relation", "since"} if partner else {"reason", "since"}
    unexpected = sorted(set(body) - allowed)
    if unexpected:
        raise ValueError(f"{where} has unexpected field {unexpected[0]}")
    if "since" not in body:
        raise ValueError(f"{where} missing since")
    if not _since_ok(body["since"]):
        raise ValueError(f"{where} invalid since")
    reason = body.get("reason")
    if not isinstance(reason, str) or reason == "" or reason != reason.strip():
        raise ValueError(f"{where} missing reason")
    if not partner:
        return ""
    relation = body.get("relation")
    if not isinstance(relation, str) or relation == "" or relation != relation.strip():
        raise ValueError(f"{where} missing relation")
    return relation


def _properties(document, table):
    props = document["properties"]
    if not isinstance(props, dict):
        raise ValueError("properties must be an object")
    if set(props) != {"classes", "relations"}:
        raise ValueError("properties has unexpected keys")
    classes = props["classes"]
    relations = props["relations"]
    if not isinstance(classes, dict):
        raise ValueError("properties.classes must be an object")
    if not isinstance(relations, dict):
        raise ValueError("properties.relations must be an object")
    known = set()
    for profile in PROFILES:
        known.update(table[profile])
        known.update(document["excluded"][profile])
    class_flags = {}
    for name in sorted(classes):
        body = classes[name]
        where = f"properties.classes.{name}"
        if name not in _CLASS_NAMES:
            raise ValueError(f"{where} unknown class")
        if not isinstance(body, dict):
            raise ValueError(f"{where} must be an object")
        flags = set()
        for key in sorted(body):
            if key not in _CLASS_FLAGS:
                raise ValueError(f"{where} unknown property {key}")
            _declaration(body[key], f"{where}.{key}", False)
            flags.add(key)
        if "symmetric" in flags and "acyclic" in flags:
            raise ValueError(f"class {name} symmetric and acyclic contradict")
        class_flags[name] = flags
    relation_flags = {}
    inverses = {}
    for name in sorted(relations):
        body = relations[name]
        where = f"properties.relations.{name}"
        if name not in known:
            raise ValueError(f"{where} unknown relation")
        if not isinstance(body, dict):
            raise ValueError(f"{where} must be an object")
        flags = set()
        for key in sorted(body):
            if key not in _RELATION_FLAGS:
                raise ValueError(f"{where} unknown property {key}")
            if key == "inverse_of":
                partner = _declaration(body[key], f"{where}.inverse_of", True)
                if partner not in known:
                    raise ValueError(f"{where}.inverse_of unknown relation")
                inverses[name] = partner
            elif key == "disjoint_with":
                items = body[key]
                if not isinstance(items, list) or not items:
                    raise ValueError(f"{where}.disjoint_with must be a non-empty array")
                partners = []
                for index, item in enumerate(items):
                    partner = _declaration(item, f"{where}.disjoint_with[{index}]", True)
                    if partner == name:
                        raise ValueError(f"{where}.disjoint_with disjoint with itself")
                    if partner not in known:
                        raise ValueError(f"{where}.disjoint_with unknown relation")
                    partners.append(partner)
                if partners != sorted(set(partners)):
                    raise ValueError(f"{where}.disjoint_with must be sorted and unique")
            else:
                _declaration(body[key], f"{where}.{key}", False)
            flags.add(key)
        if "symmetric" in flags and "acyclic" in flags:
            raise ValueError(f"relation {name} symmetric and acyclic contradict")
        relation_flags[name] = flags
    for name, partner in sorted(inverses.items()):
        if inverses.get(partner) != name:
            pair = " ".join(sorted((name, partner)))
            raise ValueError(f"inverse pairs not mutually declared: {pair}")
    for profile in PROFILES:
        for relation, category in table[profile].items():
            combined = class_flags.get(category, set()) | relation_flags.get(relation, set())
            if "symmetric" in combined and "acyclic" in combined:
                raise ValueError(f"{relation} symmetric and acyclic contradict")


def _read_version(document, schema):
    if set(document) != _VERSION_KEYS[schema]:
        raise ValueError(f"{schema} has unexpected keys")
    direction = document["direction"]
    excluded = document["excluded"]
    if not isinstance(direction, dict) or not isinstance(excluded, dict):
        raise ValueError(f"{schema} needs direction and excluded")
    table = {}
    for profile in PROFILES:
        mapped = _profile_map(profile, document.get(profile))
        names = excluded.get(profile)
        if not isinstance(names, list):
            raise ValueError(f"excluded.{profile} must be an array")
        for name in names:
            _text(name, f"excluded.{profile}")
            if name in mapped:
                raise ValueError(f"{profile}: {name} is both classified and excluded")
        missing = [relation for relation in mapped if relation not in direction]
        if missing:
            raise ValueError("direction: missing " + ", ".join(missing))
        table[profile] = mapped
    if schema == SCHEMA_V2:
        _properties(document, table)
    return table


def _schemaless(document):
    table = {}
    for profile, classes in document.items():
        table[_text(profile, "profile name")] = _profile_map(profile, classes)
    return table


def classification(document):
    """TOO の分類表から、弾ごとの「関係名 → 分類名」だけを取り出す。

    ``direction``、``excluded``、``/2`` の ``properties`` はプロファイルにしない。
    性質の宣言はここで読み、被覆が閉じているかは ``taxontoy coverage`` が見る。
    スキーマの無いオブジェクトは、テストが渡す弾だけの表として読む。
    """
    if not isinstance(document, dict) or not document:
        raise ValueError("classification must be a non-empty object of profiles")
    if "schema" not in document:
        return _schemaless(document)
    schema = document["schema"]
    if not isinstance(schema, str) or schema not in _VERSION_KEYS:
        _unsupported(schema)
    return _read_version(document, schema)


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
    for name in groups["classes"]:
        if groups["classes"][name] != found[name]["edges"]:
            return False
    return True


def _items(values, cycle):
    if not values:
        return "なし"
    if cycle:
        lines = (" → ".join(str(part) for part in path) for path in values)
    else:
        lines = (str(item) for item in values)
    return "<br>".join(escape(line) for line in lines)


def _degree(degree):
    if not isinstance(degree, dict):
        return "—"
    return (
        f"入 {degree.get('max_in', '—')}・出 {degree.get('max_out', '—')}"
        f"・合計 {degree.get('max_total', '—')}・始点 {degree.get('sources', '—')}"
        f"・終点 {degree.get('sinks', '—')}"
    )


def _components(components):
    if not isinstance(components, dict) or "count" not in components:
        return "—"
    sizes = ", ".join(str(size) for size in components.get("sizes") or [])
    return f"{components['count']}（{sizes or 'なし'}）"


def _depth(row):
    if "depth" not in row:
        return "—"
    if row["depth"] is None:
        cycle = " → ".join(str(part) for part in row.get("order_cycle") or [])
        return "不定" + (f"（{cycle}）" if cycle else "")
    return str(row["depth"])


def _provenance(wave):
    tool = wave.get("tool") or {}
    provenance = wave.get("provenance") or {}
    if not tool and not provenance:
        return ""
    graph = provenance.get("graph") or {}
    table = provenance.get("classification") or {}
    name = escape(str(tool.get("name", "")))
    version = escape(str(tool.get("version", "")))
    return (
        f"<p><code>{name} {version}</code>。"
        f"グラフ sha256 <code>{escape(str(graph.get('sha256', '')))}</code>、"
        f"分類表 sha256 <code>{escape(str(table.get('sha256', '')))}</code>。</p>"
    )


def _coverage_section(report):
    document = report.get("taxontoy")
    if not isinstance(document, dict) or "waves" not in document:
        return ""
    rows = []
    for name, wave in document["waves"].items():
        part = wave.get("partition") or {}
        rows.append(
            "<tr><th scope=\"row\">"
            + escape(str(name))
            + f"</th><td>{part.get('total', '—')}</td><td>{part.get('classified', '—')}</td>"
            + f"<td>{part.get('excluded', '—')}</td><td>{part.get('unclassified', '—')}</td>"
            + f"<td>{part.get('stale', '—')}</td><td>"
            + ("閉じている" if part.get("holds") else "開いている")
            + "</td></tr>"
        )
    inputs = "<br>".join(
        escape(f"{item.get('path', '')} {item.get('sha256', '')}") for item in document.get("inputs") or [])
    onto = document.get("onto") or {}
    return (
        "<section id=\"coverage\"><h2>TOO の被覆</h2>"
        f"<p><code>taxontoy {escape(str(document.get('version', '')))}</code>。"
        f"ONTO sha256 <code>{escape(str(onto.get('sha256', '')))}</code>。</p>"
        f"<p>{inputs}</p>"
        "<table><caption>分類済み・除外・未分類・表にあってグラフに無い名前</caption><thead><tr>"
        "<th scope=\"col\">弾</th><th scope=\"col\">関係名</th><th scope=\"col\">分類済み</th>"
        "<th scope=\"col\">除外</th><th scope=\"col\">未分類</th><th scope=\"col\">未使用</th>"
        "<th scope=\"col\">分割</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></section>"
    )


def render_relations_page(report):
    """``wave-profiles.json`` と同じ形の集計を、Pages に置く HTML にする。

    従来の辺数・端点・閉路に加え、TOL が増やした次数・弱連結成分・独立閉路・深さを出す。
    それらのキーが無い古い文書でも、あるキーだけを表示する。
    """
    sections = [_coverage_section(report)]
    for name, wave in report["waves"].items():
        rows = []
        for category, row in wave["classes"].items():
            cycles = row.get("independent_cycles")
            rows.append(
                "<tr><th scope=\"row\">"
                + escape(category)
                + f"</th><td>{row['edges']:,}</td><td>{row['incident_nodes']:,}</td><td>"
                + _items(row.get("multiple_sources") or [], False)
                + "</td><td>"
                + _items(row.get("sample_cycles") or [], True)
                + "</td><td>"
                + escape(_degree(row.get("degree")))
                + "</td><td>"
                + escape(_components(row.get("weakly_connected_components")))
                + f"</td><td>{'—' if cycles is None else cycles}</td><td>"
                + escape(_depth(row))
                + "</td></tr>"
            )
        sections.append(
            f"<section id=\"{escape(name)}\"><h2>{escape(WAVE_TITLES.get(name, name))}</h2>"
            + _provenance(wave)
            + f"<p>分類表に無い辺は {wave['unclassified_edges']:,} 本です。</p>"
            "<table><caption>TOL が返した分類ごとの構造</caption><thead><tr>"
            "<th scope=\"col\">分類</th><th scope=\"col\">辺</th><th scope=\"col\">端点</th>"
            "<th scope=\"col\">複数の始点を持つ終点</th><th scope=\"col\">代表閉路</th>"
            "<th scope=\"col\">次数</th><th scope=\"col\">弱連結成分</th>"
            "<th scope=\"col\">独立閉路</th><th scope=\"col\">深さ</th>"
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
<a href="{too}">TOO {TOO_COMMIT[:12]}</a> の <code>taxontoy.py</code> で被覆を確かめ、
<a href="{tol}">TOL {TOL_COMMIT[:12]}</a> の <code>topontology.py</code> が数えた結果です。
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
