"""固定の3例を otl-tol-graph/1 に写し、TOO と TOL の CLI で比べる。

投影を ``examples/tol-export/`` に書き、``too/taxontoy.py coverage`` と
``tol/topontology.py`` をサブプロセスで呼ぶ。版と入力の sha256 はその文書のまま残す。
``taxonomy.py`` は無く、``from topology import summarize`` も使わない。
投影の辺数は、TOL が増やしたキーを除いた ``edges`` と ``unclassified_edges`` に一致させ、
TOO の被覆が閉じていなければ失敗する。
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import onto_path  # noqa: E402
from examples.sibling_format import PROFILES, classification, counts_agree, export_graph, relation_groups
from tools.tautology import cases

EXPORTS = Path("examples/tol-export")
ONTO = Path("ontautology_shared/_onto")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def as_relative(path):
    candidate = Path(path)
    if candidate.is_absolute():
        try:
            return candidate.resolve().relative_to(ROOT)
        except ValueError:
            return candidate
    return candidate


def write_graph(graph, profile):
    relative = EXPORTS / f"{profile}.json"
    destination = ROOT / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(graph, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return relative


def run_cli(argv):
    result = subprocess.run(
        [sys.executable, "-S", *argv], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        detail = "\n".join(part.strip() for part in (result.stderr, result.stdout) if part.strip())
        raise RuntimeError(detail or f"exited {result.returncode}")
    return json.loads(result.stdout)


def checkout_script(short, root_name, script, *, base=None):
    """短いディレクトリ名がファイルならそれを使い、無ければ隣の checkout を探す。"""
    base = ROOT if base is None else base
    bundled = base / short / script
    if bundled.is_file():
        return bundled
    return onto_path.resolve_root(root_name, anchor=base) / script


def coverage_cli(classification_path):
    argv = [
        str(checkout_script("too", "TaxOntOy", "taxontoy.py")), "coverage",
        Path(classification_path).as_posix(),
        "--onto", ONTO.as_posix(), "--strict", "--format", "json",
    ]
    for profile in PROFILES:
        argv.extend(["--graph", f"{profile}={(EXPORTS / (profile + '.json')).as_posix()}"])
    return run_cli(argv)


def summarize_cli(classification_path, profile):
    return run_cli([
        str(checkout_script("tol", "TopOntoLogy", "topontology.py")),
        (EXPORTS / f"{profile}.json").as_posix(),
        Path(classification_path).as_posix(),
        profile,
    ])


def report(classification_path):
    classification_path = as_relative(classification_path)
    table = classification(read(ROOT / classification_path if not Path(classification_path).is_absolute() else classification_path))
    examples = ROOT / "examples"
    corpus = read(examples / "concepts-20261115.json")
    graphs = {
        "audit": export_graph("audit", read(examples / "audit-20261114.json")),
        "concepts": export_graph("concepts", corpus),
        "cases": export_graph("cases", corpus),
    }
    judgments = cases(corpus)
    for wave, graph in graphs.items():
        if wave not in table:
            raise RuntimeError(f"分類表に {wave} がありません")
        write_graph(graph, wave)
    covered = coverage_cli(classification_path)
    metrics = {}
    for wave, graph in graphs.items():
        groups = relation_groups(graph, table[wave])
        summary = summarize_cli(classification_path, wave)
        if not counts_agree(groups, summary):
            raise RuntimeError(f"{wave}: 投影の辺数 {groups} が TOL の集計 {summary} と一致しません")
        metrics[wave] = summary
    return {"taxontoy": covered, "waves": metrics, "case_status": {
        key: row["status"] for key, row in judgments["cases"].items()
    }}


def default_classification(anchor=None):
    """TaxOntOy のマーカー。無ければ CI が使う短いディレクトリ名に戻す。"""
    anchor = ROOT if anchor is None else anchor
    try:
        return onto_path.marker_file("TaxOntOy", anchor=anchor)
    except onto_path.RootError:
        return Path("too") / onto_path.TAXONTOY_MARKER


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("target", nargs="?", help="classification to read (default: the bundled one)")
    args = parser.parse_args(argv)
    try:
        target = args.target or default_classification()
        print(json.dumps(report(target), indent=2, ensure_ascii=False))
    except Exception as error:
        print(f"wave_relations: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
