"""Compare the three fixed OTL examples with TOO classifications and TOL metrics."""
import json
import subprocess
import sys
from pathlib import Path

from topology import summarize

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gh_audit.gh_audit import audit
from ontautology import concept_edges
from tools.tautology import cases


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def report(classification):
    profiles = read(classification)
    examples = ROOT / "examples"
    corpus_path = examples / "concepts-20261115.json"
    corpus = read(corpus_path)
    judgments = cases(corpus)
    result = subprocess.run(
        [sys.executable, "-S", str(ROOT / "tools/tautology.py"), "cases", str(corpus_path), "--graph"],
        stdout=subprocess.PIPE, encoding="utf-8",
    )
    expected_status = 2 if judgments["summary"]["disputed"] else 0
    if result.returncode != expected_status:
        raise RuntimeError(f"cases --graph exited with {result.returncode}, expected {expected_status}")
    graphs = {
        "audit": audit([read(examples / "audit-20261114.json")]),
        "concepts": concept_edges(corpus),
        "cases": json.loads(result.stdout),
    }
    metrics = {wave: summarize(graph, profiles[wave]) for wave, graph in graphs.items()}
    return {"waves": metrics, "case_status": {
        key: row["status"] for key, row in judgments["cases"].items()
    }}


if __name__ == "__main__":
    print(json.dumps(report(Path(sys.argv[1])), indent=2, ensure_ascii=False))
