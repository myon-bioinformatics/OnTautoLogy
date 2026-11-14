# 継続監査サイトのJSONを使う

サイトの「統合証跡JSON」または「観測JSON」を保存し、次を実行します。

```sh
python -S audit_adapter.py integration-audit.json -o graph.json
python -S -m unittest -v
```

既存の `ontautology.py` のグラフを再利用します。PRのhead・main SHA、観測時刻、監査状態、変更ファイル、記録された依存、対象headに一致する実行を取り込みます。ファイル未取得は空リストと区別します。

依存先が入力にない場合は `coverage.unobserved_dependencies` に記録します。実行SHAがない、またはPRのheadと異なる実行は `coverage.omitted_runs` に残し、現在headの結果として扱いません。出力の `integration_batches` は入力にある全PR（マージ済みを含む）と記録済みの依存だけに基づきます。未観測の依存やCI、レビュー、競合を自動推測するものではありません。

入力は取得時点のスナップショットです。GitHubからの最新取得、リポジトリ更新、CI再実行、マージは行いません。入力・出力を公開前に確認し、認証情報を含めないでください。
