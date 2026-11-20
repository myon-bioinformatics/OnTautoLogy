"""Regression checks for the dated examples used by the cross-repository CI."""
import json
import sys
from pathlib import Path

report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
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
