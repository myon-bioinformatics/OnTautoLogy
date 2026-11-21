# 第一弾から第三弾の関係を比較する

OTL の固定事例を `examples/sibling_format.py` で `otl-tol-graph/1` に写し、TOO の分類表で関係を選び、TOL で分類ごとの構造を調べる。循環検出は TOL が ONTO の `knowledgegraph.py` を呼ぶ。OTL は辺の本数だけを同じ規則で数え、TOL の `edges` と `unclassified_edges` に一致することを確かめる。

想定する版は TOO main `78ed91aee522e9a7305e2bf964dab9be2bd3fff0` の `otl-relations.json` と、TOL main `7bd70a45585e94522a1e87c362ee35b1316118d9` の `topology.py` です。形式が変わったらこの手順と `sibling_format.py` だけを直します。

OTL のルートから実行する。`too` と `tol` は CI の `wave-relations.yml` に記載したコミットを checkout したディレクトリです。

```sh
python3 -S examples/sibling_format.py export audit examples/audit-20261114.json -o audit.json
python3 -S examples/sibling_format.py export concepts examples/concepts-20261115.json -o concepts.json
python3 -S examples/sibling_format.py export cases examples/concepts-20261115.json -o cases.json
PYTHONPATH=tol:ontautology_shared/_onto python3 -S examples/wave_relations.py too/otl-relations.json > report.json
python3 -S examples/check_wave_report.py report.json
```

`export` は監査グラフの `relation` を `kind` にそろえ、`source`・`target`・`kind` 以外の属性を落とします。向きは保存されたグラフのままで、`edges_of` の反転はかけません。`check_wave_report.py` は得られた集計が `examples/wave-profiles.json` と、そこに固定した辺数と一致することを見ます。Pages の構造集計はこの JSON を表にしたものです。

第一弾は 2026-11-14 の監査記録の dependsOn を集計する。第二弾は上位から下位への narrower と双方向の similarTo を別々に調べる。第三弾の判定は OTL の cases が計算し、TOL は候補、判断、肯定・否定、未登録要素それぞれの辺を集計する。分類対象外の辺数は unclassified_edges で確認できる。
