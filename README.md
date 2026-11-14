# OnTautoLogy

ナレッジグラフとオントロジーの小さな実験。最初の用途は PR 監査データの関係整理です。Python 3.11 以降の標準ライブラリだけで動きます。

```sh
python -S ontautology.py snapshot.json -o graph.json
python -S -m unittest -v
```

入力は継続監査サイトの `pr-audit-snapshot.json` 形式です。取得処理は含みません。出力は `Repository`、`PullRequest`、`File`、`WorkflowRun` と、それらの `belongs_to`、`changes`、`has_run`、`shares_changed_paths_with`、`depends_on` を持つ JSON です。`observed_at` と CI の対象 head SHA を保持します。

任意の `dependencies` に `{"dependent":"Aoi#211", "prerequisite":"BlueProbe#53", "evidence":"根拠へのURLなど"}` を追加すると、明示された依存だけから並行可能な統合順を算出します。循環は `dependency_cycle` に記録し、終了コード 2 を返します。入力エラーは 1、成功は 0 です。

変更パスの一致は競合や内容の一致を意味しません。未取得の変更ファイルは空と区別します。CI は入力にある観測のみで、古い head の結果や未取得を現在の成功と推定しません。PR がマージ済みかどうかと、再検証の完了は別です。GitHub の変更、CI 起動、マージは行いません。

このモデルは OWL/RDF 準拠を主張しない軽量な語彙です。依存関係は自動推測せず、証拠付きで入力してください。
