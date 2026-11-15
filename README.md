# OnTautoLogy

オントロジーをトートロジーの水準まで持っていく。小さなナレッジグラフに共通するロジックだけを置く場所です。Python 3.11 以降の標準ライブラリだけで動き、取得処理もリポジトリ固有の読み取りも含みません。

```sh
python -S ontautology.py graph.json reach tool:tool.py     # 💥 変更の影響先
python -S ontautology.py graph.json why   app:report.md    # 🔎 判断の根拠
python -S ontautology.py graph.json order depends_on       # 🪜 順序（graphlib）
python -S ontautology.py graph.json check                  # 🧪 形・参照・重複
python -S -m unittest discover -s tests
```

終了コード: `0` 答えた / `1` 入力エラー / `2` 答えたが要確認（所見・循環・未知のノード・鍵にならない）。

## 🪜 根拠の段

| basis | 意味 |
| --- | --- |
| `hypothesis` | 誰も確かめていない候補。`reach` は候補として示すだけで、その先へ進まない |
| `derived` | 記録に対する決まった規則（名前の一致、ハッシュの照合など） |
| `observed` | 記録から読んだ、または与えた行で見えた。見ていない行については何も言わない（省略時の既定） |
| `proof` | 見ていない場合も含めて常に成り立つ。ここがトートロジーの段 |

`why` は辿った道の中で一番弱い段（`weakest`）を返すので、途中に候補が1つあれば証明済みとは読めません。`ladder` は段ごとの本数を数えます。

## 🔗 辺

`{"kind", "source", "target"}` に、呼び出し側が持っているもの（`basis`、主張している記録 `lock`、記録自身の時刻 `observed_at` など）を足した dict です。向きは **source = 依存される側 → target = source が変わったら見直す側** に固定します。前向きに辿れば影響先、後ろ向きに辿れば根拠です。

| 関数 | 答えること |
| --- | --- |
| `check(edges, nodes=None)` | 形の崩れ、未知の basis、存在しない参照、同じ主張で中身が違うもの。直さず報告する |
| `reach(edges, start)` | 変更が届く先。深さ・経路・その辺。DAG を仮定しない |
| `why(edges, node)` | 判断が拠っているもの。`cut` は深さ制限で読み残したこと |
| `cycles(edges)` | 循環の代表例。報告するだけで止めない |
| `order(edges, nodes=())` | 「先に必要」の辺だけを渡すと、並行できる組を順に返す。循環はそのまま返す |
| `ladder(edges)` | 段ごと・種類ごとの本数 |
| `key_report(items, candidates)` | 属性の組が鍵になるか: `key` / `repeat` / `collides` / `incomplete` |

同じ主張でも記録や時刻が違えば別の観測として並べます（再実行の成功は最初の失敗を消しません）。

## 🔑 取っ手から鍵へ

同一性は最後に決まります。まず意味を持たない取っ手を振り、観測を足し、区別できないものをまとめ、新しい観測で割れることを許し、欠けがなく一意な属性の組だけを鍵に昇格させ、衝突したら上書きせず報告します。`key_report` はその最後の2段です。

## 🧭 置くもの・置かないもの

- 置く: リポジトリに依らないグラフのロジック。入出力は dict / list（JSON）のまま。
- 置かない: GitHub や Git の読み取り、各リポジトリの記録形式の解釈、画面。それらは記録を書くリポジトリと親（myon-bioinformatics）の役目で、ここを呼ぶ側です。
- OWL / RDF 準拠は主張しません。SPARQL や GraphQL の代わりに、関数を名前で呼びます（Node からは Python ランチャー経由）。
