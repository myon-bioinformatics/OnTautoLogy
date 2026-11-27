# 真理値表による比較の形式検証

`formal/TruthTableSoundness.lean` は、`tools/tautology.py` の `equivalent()` と
`ontautology.py` の `entailment()` が使う、全割当の比較と反例探索の意味を形式化します。
対象は有限個の特徴に対する命題論理です。自然言語の意味全体を証明するものではありません。

共通ラッパー `lean_verify.py` と Lean 専用 CI は
[親リポジトリ](https://github.com/myon-bioinformatics/myon-bioinformatics/blob/6c2558c4251698c50bc07bad86fb49f902b2738f/lean_verify.py)
で管理します。このリポジトリは固有の証明、Python との接続テスト、この説明を管理し、
通常実行の依存は増やしません。

## 何を保証するか

Lean の割当は `Fin n → Bool`、規則の解釈はその割当から `Bool` を返す関数です。
`assignments` は各特徴に偽・真を順に割り当てます。その列挙が **任意の n に対して
すべての割当を含む**ことを証明してから、反例なしと等価性・含意の関係を証明します。
構文木の解釈は抽象化しており、Python の JSON 構文・演算子とは別途テストで接続します。

| 定理 | 保証 | Python の対応箇所 |
| --- | --- | --- |
| `OnTautoLogy.assignments_complete` | 任意の真偽割当が列挙に含まれる | `_assignments` |
| `OnTautoLogy.difference_replays` | 等価性の反例では左右の真偽が異なる | `equivalent` の `counterexample` |
| `OnTautoLogy.equivalence_iff` | 反例なしと、すべての割当での等価が同値 | `equivalent` の肯定判定 |
| `OnTautoLogy.counterexample_replays` | 含意の反例は前提を満たし、結論を満たさない | `entailment` の `counterexample` |
| `OnTautoLogy.no_counterexample_iff` | 反例なしと、前提を満たす全割当での結論成立が同値 | `entailment` の反例探索 |
| `OnTautoLogy.consistent_iff` | 前提を満たす割当の存在と、一貫性の肯定が同値 | `entailment` の `consistent` |
| `OnTautoLogy.entailed_iff` | `entailed` は前提の充足可能性と含意成立の両方を必要とする | `entailment` の `entailed` |
| `OnTautoLogy.inconsistent_iff` | `inconsistent-premises` は前提を満たす割当がない場合に限る | `entailment` の矛盾した前提の判定 |

この区別は、`p` と `NOT p` を同時に前提にしたときに必要です。
含意の反例は存在しませんが、この実装はその状態を `entailed` として扱わず、
`inconsistent-premises` として返します。

特徴が一つもない場合にも、空の割当が一つ存在します。
したがって空のリスト `[]` は正当な反例になり、反例なしの `None` と区別する必要があります。

## Python 実装との接続

`tests/test_formal_bridge.py` は実際の `_assignments`、`holds`、`classify`、
`equivalent`、`entailment` を呼びます。期待値は、整数から生成した割当と
集合の積・和・補集合で求めます。実装の `holds` を期待値の計算に再利用しません。

- AND・OR・NOT・NAND・NOR、空の演算子、複数引数、入れ子を含む **163 規則**。
- 2 特徴で可能な **16 種類すべての真理値表**を含むことも検査。
- **26,569 組**を等価性について、同じ組数を含意について検査し、返された反例を再実行。
- 0〜6 特徴の割当列挙を比較し、空の割当も検査。
- 矛盾した前提、空の前提、観測した一行だけの一致、探索上限による拒否を検査。

これらは有限の接続テストであり、Python の全入力に対する形式証明ではありません。
`classify` の証人・分類も接続テストで確認しますが、分類の制御フロー自体の Lean 証明は追加していません。

通常のテストは Lean や追加パッケージなしで実行できます。

```sh
python -S -m unittest discover -s tests -p test_formal_bridge.py -v
```

## Lean 専用の検証

`formal/lean-toolchain` は `leanprover/lean4:v4.36.0` です。
Lean 付属の `Std` を使い、Mathlib は不要です。
親リポジトリを隣の `myon-bioinformatics` に配置した場合、次のように検証します。

```sh
python -S ../myon-bioinformatics/lean_verify.py \
  --cwd formal --required --json-output build/lean-verification.json \
  --theorem OnTautoLogy.assignments_complete \
  --theorem OnTautoLogy.difference_replays \
  --theorem OnTautoLogy.equivalence_iff \
  --theorem OnTautoLogy.counterexample_replays \
  --theorem OnTautoLogy.no_counterexample_iff \
  --theorem OnTautoLogy.consistent_iff \
  --theorem OnTautoLogy.entailed_iff \
  --theorem OnTautoLogy.inconsistent_iff \
  TruthTableSoundness.lean
```

共有ラッパーは Lean 未導入を `unverified` と記録します。`--required` を使う専用 CI では
未検証も証明失敗も失敗として扱い、通常の Python テストからは Lean を呼びません。
定理名と公理の依存も監査対象です。今回の証明は Lean の標準的な `propext`・`Quot.sound`
の範囲で、独自公理や未完了の証明を追加していません。

## 境界と前提

証明は、固定された有限個の特徴に対する **全域的な二値の解釈**を前提とします。
JSON の構文検証、特徴名の収集、Python の実行、真理値表上限の例外処理、RDF への射影は
Lean の証明範囲外です。今回のテストも全構文・全ビット幅を網羅するものではありません。

観測した概念集合だけで定義が一致したことと、命題論理の全割当で一致したことは異なります。
特徴の自然言語上の同義性、文脈依存の意味、特徴間の実データ上の制約、未知の事例への精度は保証しません。
また `ontautology_shared/predicate_logic.py` の有限一階モデルは別の機構です。
そこで反例がなかった結果を、すべてのモデルでの一般妥当性へ拡張するものではありません。
