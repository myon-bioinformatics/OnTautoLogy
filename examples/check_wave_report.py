"""回帰確認。CI が TOO/TOL から得た集計は、Pages が読む wave-profiles.json と一致する。"""
import json
import sys
from pathlib import Path

here = Path(__file__).parent
report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
published = json.loads((here / "wave-profiles.json").read_text(encoding="utf-8"))
CLASS_KEYS = {
    "edges", "incident_nodes", "multiple_sources", "sample_cycles",
    "degree", "weakly_connected_components", "independent_cycles", "depth", "order_cycle",
}
DEGREE_KEYS = {"max_in", "max_out", "max_total", "sources", "sinks"}


def require_tol_document(name, wave):
    tool = wave.get("tool") or {}
    if tool.get("name") != "topontology" or not tool.get("version"):
        raise SystemExit(f"{name}: TOL の CLI 文書ではありません")
    provenance = wave.get("provenance") or {}
    for side in ("graph", "classification"):
        digest = (provenance.get(side) or {}).get("sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            raise SystemExit(f"{name}: {side} の sha256 がありません")
    if provenance.get("profile") != name:
        raise SystemExit(f"{name}: provenance の profile が違います")
    for category, row in wave["classes"].items():
        missing = CLASS_KEYS - set(row)
        if missing:
            raise SystemExit(f"{name}/{category}: 足りないキー {sorted(missing)}")
        if DEGREE_KEYS - set(row["degree"]):
            raise SystemExit(f"{name}/{category}: degree のキーが足りません")
        components = row["weakly_connected_components"]
        if "count" not in components or "sizes" not in components:
            raise SystemExit(f"{name}/{category}: 弱連結成分のキーが足りません")


def require_taxontoy(document):
    if document.get("tool") != "taxontoy" or not document.get("version"):
        raise SystemExit("TOO の CLI 文書ではありません")
    if document.get("command") != "coverage" or document.get("ok") is not True or document.get("errors"):
        raise SystemExit("TOO の被覆が閉じていません")
    for item in document.get("inputs") or []:
        if not isinstance(item.get("sha256"), str) or len(item["sha256"]) != 64:
            raise SystemExit("TOO の入力 sha256 がありません")
    onto = document.get("onto") or {}
    if not isinstance(onto.get("sha256"), str) or len(onto["sha256"]) != 64:
        raise SystemExit("ONTO の sha256 がありません")
    for name in ("audit", "concepts", "cases"):
        part = document["waves"][name]["partition"]
        if not part["holds"] or part["unclassified"] or part["stale"]:
            raise SystemExit(f"{name}: 被覆が閉じていません")


require_taxontoy(report["taxontoy"])
waves = report["waves"]
for wave_name, wave in waves.items():
    require_tol_document(wave_name, wave)
if report != published:
    raise SystemExit("集計が examples/wave-profiles.json と一致しません")
assert waves["audit"]["classes"]["dependency"]["edges"] == 13
concepts = waves["concepts"]["classes"]
assert concepts["hierarchy"]["edges"] == 29 and not concepts["hierarchy"]["sample_cycles"]
assert concepts["similarity"]["edges"] == 62 and concepts["similarity"]["sample_cycles"]
assert {key: row["edges"] for key, row in waves["cases"]["classes"].items()} == {
    "affirmation": 3, "hypothesis": 3, "judgment-record": 3, "unknown-element": 1,
}
assert "negation" not in waves["cases"]["classes"]
assert waves["cases"]["unclassified_edges"] == 0
assert report["case_status"] == {
    "K001-night-db": "confirmed", "K002-share-only": "disputed",
    "K003-shift-change": "pending", "K004-first-word": "judged",
}
