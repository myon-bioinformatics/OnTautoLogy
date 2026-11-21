"""固定の3例を otl-tol-graph/1 に写し、TOO の分類表と TOL の集計で比べる。

TOL に渡すのは内部グラフではなく投影です。投影の辺数は TOL の edges と一致させます。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from examples.sibling_format import classification, counts_agree, export_graph, relation_groups
from tools.tautology import cases
from topology import summarize


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def report(classification_path):
    table = classification(read(classification_path))
    examples = ROOT / "examples"
    corpus = read(examples / "concepts-20261115.json")
    graphs = {
        "audit": export_graph("audit", read(examples / "audit-20261114.json")),
        "concepts": export_graph("concepts", corpus),
        "cases": export_graph("cases", corpus),
    }
    judgments = cases(corpus)
    metrics = {}
    for wave, graph in graphs.items():
        if wave not in table:
            raise RuntimeError(f"分類表に {wave} がありません")
        groups = relation_groups(graph, table[wave])
        summary = summarize(graph, table[wave])
        if not counts_agree(groups, summary):
            raise RuntimeError(f"{wave}: 投影の辺数 {groups} が TOL の集計 {summary} と一致しません")
        metrics[wave] = summary
    return {"waves": metrics, "case_status": {
        key: row["status"] for key, row in judgments["cases"].items()
    }}


if __name__ == "__main__":
    print(json.dumps(report(sys.argv[1]), indent=2, ensure_ascii=False))
