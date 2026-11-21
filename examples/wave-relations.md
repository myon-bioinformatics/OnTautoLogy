# 第一弾から第三弾の関係を比較する

OTL の固定事例を `examples/sibling_format.py` で `otl-tol-graph/1` に写し、TOO の分類表で関係を選び、TOL の CLI で分類ごとの構造を調べる。循環検出は TOL が ONTO の `knowledgegraph.py` を呼ぶ。OTL は辺の本数だけを同じ規則で数え、TOL の `edges` と `unclassified_edges` に一致することを確かめる。CLI の文書にはツールの版、入力の sha256、次数、弱連結成分、独立閉路、深さが入る。それらのキーが増えても辺数の照合は壊さず、無いときは Pages の表で「—」にする。

想定する版は TOO main `8621f2261d694af0de35e103ad2387872ca10b99`（親は `30c5ed689cb931bce3787e37056082ce8cb52b3d` と `8cfb0cab3a917ffe9b945fc0c6d4ee0e8edc7f04`、版 0.2.0）の `taxontoy.py` と、TOL main `d8880c9e55a0ce502dbf54a128bcaf471f0efc0e`（親は `7bd70a45` と `3184b725`）の `topontology.py` です。表は `taxontoy-relations/2` で、`properties` に `transitive`・`symmetric`・`inverse_of`・`acyclic`・`disjoint_with` を宣言します。`taxontoy-relations/1` も読めます。`taxonomy.py` は無く、`topology.py` は `from topology import summarize` の互換用で、コマンドとしては使いません。形式が変わったらこの手順と `sibling_format.py` だけを直します。

OTL のルートから実行する。`too` と `tol` は CI の `wave-relations.yml` に記載したコミットを checkout したディレクトリです。

```sh
python3 -S examples/sibling_format.py export audit examples/audit-20261114.json -o audit.json
python3 -S examples/sibling_format.py export concepts examples/concepts-20261115.json -o concepts.json
python3 -S examples/sibling_format.py export cases examples/concepts-20261115.json -o cases.json
PYTHONPATH=tol:ontautology_shared/_onto python3 -S examples/wave_relations.py too/otl-relations.json > report.json
python3 -S examples/check_wave_report.py report.json
```

`export` は監査グラフの `relation` を `kind` にそろえ、`source`・`target`・`kind` 以外の属性を落とします。向きは保存されたグラフのままで、`edges_of` の反転はかけません。`wave_relations.py` は投影を `examples/tol-export/` に書き、`too/taxontoy.py coverage --strict` と `tol/topontology.py` に渡します。`check_wave_report.py` は、両方の CLI 文書に版と sha256 があること、被覆が閉じていること、TOL の新しい構造キーがあること、そして得られた集計が `examples/wave-profiles.json` およびそこに固定した辺数と一致することを見ます。Pages の構造集計はこの JSON を表にしたものです。

第一弾は 2026-11-14 の監査記録の dependsOn を集計する。第二弾は上位から下位への narrower と双方向の similarTo を別々に調べる。第三弾の判定は OTL の cases が計算し、TOL は候補、判断、肯定・否定、未登録要素それぞれの辺を集計する。分類対象外の辺数は unclassified_edges で確認できる。
