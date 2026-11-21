"""回帰確認。CI が TOO/TOL から得た集計は、Pages が読む wave-profiles.json と一致する。"""
import json
import sys
from pathlib import Path

here = Path(__file__).parent
report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
published = json.loads((here / "wave-profiles.json").read_text(encoding="utf-8"))
if report != published:
    raise SystemExit("集計が examples/wave-profiles.json と一致しません")
waves = report["waves"]
assert waves["audit"]["classes"]["dependency"]["edges"] == 13
concepts = waves["concepts"]["classes"]
assert concepts["hierarchy"]["edges"] == 29 and not concepts["hierarchy"]["sample_cycles"]
assert concepts["similarity"]["edges"] == 62 and concepts["similarity"]["sample_cycles"]
assert {key: row["edges"] for key, row in waves["cases"]["classes"].items()} == {
    "affirmation": 3, "hypothesis": 3, "judgment-record": 3, "negation": 0, "unknown-element": 1,
}
assert waves["cases"]["unclassified_edges"] == 0
assert report["case_status"] == {
    "K001-night-db": "confirmed", "K002-share-only": "disputed",
    "K003-shift-change": "pending", "K004-first-word": "judged",
}
