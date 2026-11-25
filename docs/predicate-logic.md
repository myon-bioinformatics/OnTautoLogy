# 有限一階述語論理

Python 3.11+、実行時外部依存なし。既存の命題論理とは独立した構文表現を用いる。

```python
from ontautology_shared.predicate_logic import FiniteModel, pred, var

model = FiniteModel(("cat", "rock"), predicates={"Animal": lambda x: x == "cat"})
formula = pred("Animal", var("x"))
assert model.counterexample(formula) == {"x": "rock"}
assert not model.evaluate(("forall", "x", formula))
```

公開API: var, const, func, pred, free_variables, substitute, universal_closure,
FiniteModel.evaluate, FiniteModel.counterexample。

式はタプルで表現する。論理演算は true, false, eq, not, and, or, implies, iff、
量化は ("forall", name, body), ("exists", name, body)。
substitute の入力は正しい構文木と項を前提とする。
モデルの定数・関数・述語は明示的な解釈を与える。
解釈のない記号は KeyError、領域外の値は ValueError。
関数・述語の全域性は事前検証しない。呼び出された解釈を検査する。
量化の探索は有限領域の大きさに依存する。
反例なしは指定モデル内のみの結果で、一般妥当性や証明済みを意味しない。
証明列検査、公理体系、既存グラフとの接続は今回の範囲外。

参考（独立実装）:
- https://qiita.com/skrtk98/items/7a4ed9c3e902a897e6bf
- https://qiita.com/skrtk98/items/295c2d41a693ab669714

テスト: `python -S -m unittest discover -s tests -p test_predicate_logic.py`
