# 第一弾から第三弾の関係を比較する

OTL の固定事例を元の API と CLI でグラフに変換し、TOO の分類表で関係を選び、TOL で分類ごとの構造を調べる。循環検出には OTL が ONTO から固定版で取り込んだ knowledgegraph.py を使う。

OTL のルートから実行する。too と tol は CI の wave-relations.yml に記載したコミットを checkout したディレクトリ。

```sh
PYTHONPATH=tol:ontautology_shared/_onto python3 -S examples/wave_relations.py too/otl-relations.json > report.json
python3 -S examples/check_wave_report.py report.json
```

第一弾は 2026-11-14 の監査記録の dependsOn を集計する。第二弾は上位から下位への narrower と双方向の similarTo を別々に調べる。第三弾の判定は OTL の cases が計算し、TOL は候補、判断、肯定・否定、未登録要素それぞれの辺を集計する。分類対象外の辺数は unclassified_edges で確認できる。
