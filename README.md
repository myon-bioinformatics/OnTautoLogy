# OnTautoLogy

<p align="center"><img src="docs/icon.png" alt="OnTautoLogy のアイコン（開いた本から伸びるナレッジグラフと王冠）" width="160"></p>

オントロジーをトートロジーの水準まで持っていく、小さなナレッジグラフです。主張は 🤔 候補 → 🧮 規則で導出 → 👀 観測 → ✅ 証明 の段を上り、最上段は「見ていない場合も含めて常に成り立つ」＝トートロジーです。Python 3.11 以降の標準ライブラリだけで動き、取得・書き込み・マージ・CI 起動・LLM 呼び出しは行いません。

## 🧭 2つの用途

| | 問い | 置き場 | 例データ |
| --- | --- | --- | --- |
| 🧩 第二弾 | 〇〇は何の要素があれば〇〇として成立するか。「〇〇は🔳🔳の類似」を集め、共通項と見分けから定義を作る | `ontautology.py`（define・roundtrip）＋ `tools/tautology.py`（rules・judge・equivalent） | `examples/concepts-20261115.json` |
| 🔭 第一弾 | 多数のリポジトリの PR を、観測の履歴ごと1つのグラフで見る（親の監査ダッシュボード向け） | `gh_audit/gh_audit.py` | `examples/audit-20261114.json`・`examples/flutter-absorption.json` |

どちらも同じ芯（辿る・循環・順序・根拠の段・鍵の昇格）の上に乗っています。Aoi の命題（逆・裏・対偶と判例）や TalkCompress の往復・判定モデルの延長線です。

## 🧭 全体図（監視・中間・管理の3層）

![OnTautoLogy の概念図: 主張がトートロジーに至るまでの段、2つの用途、監視・中間・管理の3層のナレッジグラフ](docs/concept.png)

画像は概観です。クラスと関係の正確な対応は下の Mermaid 図で、テストがコードの語彙と突き合わせています。

```mermaid
flowchart LR
  subgraph WATCH["👀 監視層 — 観測と履歴"]
    O[Observation 観測]
    N[Snapshot スナップショット]
  end
  subgraph MID["🔁 中間層 — 案件ごとに差し替え（今は2つ）"]
    subgraph GH["🔭 第一弾 GitHub（gh_audit/）"]
      P[PullRequest]
      W[ActionsRun]
      C[Commit]
      T[Task]
      R[Repository]
      F[File]
    end
    subgraph SIM["🧩 第二弾 類似語集め（examples/concepts-*.json）"]
      E[Element 要素]
      K[Concept 概念]
      S[Concept 類似概念]
    end
  end
  subgraph MGMT["🗂️ 管理層 — オントロジー（本体・tools）"]
    V["📚 語彙 · classes / violations"]
    L["🪜 根拠の段 · basis / ladder / why"]
    D["⚖️ 定義 · define / rules / judge"]
    Q["✅ 証明 · equivalent"]
  end
  O -->|derived_from| N
  O -->|observes| P
  O -->|observes| K
  O -->|hasHead / hasBase / hasMain| C
  O -->|hasRun| W
  O -->|changesFile| F
  O -->|hasTask| T
  P -->|dependsOn| P
  W -->|runsAt| C
  P -->|belongsTo| R
  C -->|belongsTo| R
  T -->|migration_source| F
  T -->|migration_target| R
  E -->|hasElement / genusElement / differentiaElement| K
  K <-->|similarTo| S
  GH ==> V
  GH ==> L
  SIM ==> L
  SIM ==> D
  D ==> Q
  P -.->|represents| K
  T -.->|represents| K
  F -.->|represents| K
  R -.->|relatedConcept| K
  O -.->|classifiedAs| K
```

| 層 | 役目 | 今あるもの |
| --- | --- | --- |
| 👀 監視層 | いつ・何を見たか（観測と履歴） | Observation・Snapshot（🔭 第一弾と 🧩 第二弾で共通。同じ関係 `observes`・`derived_from` を使い、`digest`・`timestamp` は本体にある） |
| 🔁 中間層 | 案件ごとの実体。ここだけを差し替える | 🔭 第一弾 GitHub（`gh_audit/`）・🧩 第二弾 類似語集め（`concept_edges` と `examples/concepts-*.json`） |
| 🗂️ 管理層 | どの案件にも使うオントロジー | 📚 語彙の検査・🪜 根拠の段・⚖️ 定義・✅ 証明（本体と tools） |

| 線 | 意味 |
| --- | --- |
| ── 実線 | 今のコードにある関係（🔭 は `gh_audit.RELATIONS`、🧩 は `concept_edges`） |
| ══ 太線 | 管理層の関数で扱う（実装済み。🔭 は `validate` が `violations` を使い、🧩 は `define`・`rules` で定義を出す） |
| ┄┄ 点線 | 中間層どうしをつなぐ関係の設計案（`represents`・`relatedConcept`・`classifiedAs`）。まだ実装していない |

- 🔁 **案件を足すときは中間層を1つ足します。** 🔭 第一弾のやり方にならい、案件ごとにフォルダを切って語彙（`RELATIONS`）と読み込み・コマンドを置き、本体の口 `main(commands=..., load=...)` に差し込みます。語彙を引数で受ける `tools/ontology.violations` で検査できるので、管理層（本体と tools）は変えずに済みます。
- 🧪 **図とコードがずれないようにしています。** 実線の関係はコードの語彙にあること、点線の関係はまだ無いこと、中間層の2つの枠にそれぞれの語彙のクラスだけが入っていることをテストで確かめます。点線を実装したら、図も実線に直さないとテストが落ちます。

## 📂 構成

```
ontautology.py          🧠🧩 本体（汎用だけ・標準ライブラリのみ。これ1本を vendor すれば動く）
tools/
  tautology.py          🧩⚖️ 第二弾の判定（規則・可逆な定義・真理値表）、証明の段までの距離
  ontology.py           📚 語彙の違反を全部挙げる・鍵に昇格できる属性の組
  knowledgegraph.py     🕸️ 親の fleet コードと同じ名前・形の答え
gh_audit/               🔭 第一弾だけのフォルダ（第一弾の enhancement はここへ）
  gh_audit.py           🔭 第一弾: GitHub 監査（PR 監査・plan・diff・Turtle・Flutter 移管台帳）
vendor/                 📦 親から借りるもの（vendor.lock.json で SHA 固定）: py_launch.cjs・fleet_check.py
examples/               🌱 第二弾の類似コーパス、第一弾の監査スナップショット・移管台帳
tests/                  🧪 unittest（Redis の答え合わせは任意）
docs/                   🖼️ アイコン（icon.png）・ファビコン（favicon.png）・概念図（concept.png）、📝 方針メモ（policy-rules.md）
```

| 🖼️ アイコン（512×512） | ファビコン（32×32、16×16 でも見分けられる） |
| :---: | :---: |
| <img src="docs/icon.png" alt="アイコン" width="96"> | <img src="docs/favicon.png" alt="ファビコン" width="32"> |

依存は 🔭 第一弾（gh_audit）→ 🧰 tools → 🧠 本体 の一方向です。🔭 第一弾は `gh_audit/` に閉じていて、本体と tools は gh_audit を読みません（テストで固定）。🧩 第二弾は汎用なので本体と `tools/tautology.py` にあります。

## 🚀 すぐ試す

```sh
# 🧩 第二弾
python -S tools/tautology.py rules examples/concepts-20261115.json             # ⚖️ seeds の〇〇ごとに規則を判定し、可逆な定義を出す
python -S tools/tautology.py judge examples/concepts-20261115.json ギター '["AND", "弦楽器", "撥弦", "フレット"]'   # 🧮 1本の規則の FN・FP
python -S tools/tautology.py equivalent '["NOR", "a", "b"]' '["AND", ["NOT", "a"], ["NOT", "b"]]'          # ✅ 書き換えが全通りで同じか
python -S tools/tautology.py holdout examples/concepts-20261115.json           # 🙈 初見・🎭 マスクで定義を測る
python -S tools/tautology.py guess examples/concepts-20261115.json --lies 1 --sure 1  # 🎯 当てっこ（食い違いを1回まで許し、確信度1まで確かめる）
python -S tools/tautology.py wobble examples/concepts-20261115.json シャケ るいじ  # 🔤 名前を揺らす（語も引く）
python -S ontautology.py define examples/concepts-20261115.json ギター ピカチュウ 鮭 iPhone エナジードリンク ルイージ   # 🧩 類と種差
python -S ontautology.py roundtrip examples/concepts-20261115.json カフェイン含有 飲料                     # 🔁 要素 → 語の往復

# 🔭 第一弾（gh_audit/）
python -S gh_audit/gh_audit.py audit examples/audit-20261114.json -o graph.json   # スナップショット → グラフ（複数渡すと履歴）
python -S gh_audit/gh_audit.py plan  graph.json                                  # main 未導入の PR の依存順
python -S gh_audit/gh_audit.py transfers examples/flutter-absorption.json        # Flutter の未吸収機能

python -S -m unittest discover -s tests
```

Node からは親の起動役を通します（ツールごとの `.mjs` / `.cjs` は置きません）。

```sh
node vendor/py_launch.cjs -- ontautology.py define examples/concepts-20261115.json ギター
node vendor/py_launch.cjs -- tools/tautology.py rules examples/concepts-20261115.json
node vendor/py_launch.cjs -- gh_audit/gh_audit.py audit examples/audit-20261114.json -o graph.json
node vendor/py_launch.cjs --call equivalent -- tools/tautology.py '["NOR","a","b"]' '["AND",["NOT","a"],["NOT","b"]]'   # 関数を名前で
```

`uv tool install .`（または `uv tool install git+https://github.com/myon-bioinformatics/OnTautoLogy.git`）で入るのは本体の `ontautology` コマンドです。tools と gh_audit はチェックアウトから使います。

## 🗂️ オントロジーを並べて見る

| | 🧩 第二弾（本体・`tools/tautology.py`） | 🔭 第一弾（`gh_audit/`） |
| --- | --- | --- |
| 入力 | `ontautology-concepts/1`（seeds・similar・concepts・names・maybe） | `integration-audit/3`（監査スナップショット） |
| 👀 監視層 | Observation（観測した概念ごと）・Snapshot（コーパスごと） | Observation（PR ごと）・Snapshot（スナップショットごと） |
| 語彙の置き場 | `ontautology.concept_edges` | `gh_audit.RELATIONS`（domain と range） |
| 芯の辺への写し | `concept_edges` | `edges_of` |
| 検証 | `check` | `check` ＋ `tools/ontology.violations` ＋ 監査固有の規則 |
| 手順 | ⚖️ `rules`（〇〇の定義） | 🪜 `plan`（PR の統合順序） |
| 証明の段 | ✅ `equivalent` が埋める | まだ 0 本 |

下の2つの表は、クラスと「そのクラスから出ていく関係 → 先のクラス」をすべて並べたものです。コードの語彙と1つでもずれるとテストが落ちます。

### 🧩 第二弾のクラスと関係

| クラス | 識別子 | 出ていく関係 → 先 |
| --- | --- | --- |
| `Observation` | `observation:` コーパスの digest ＋ `concept:` 語 | `observes` → Concept・`derived_from` → Snapshot |
| `Snapshot` | `snapshot:` コーパスの digest | — |
| `Concept` | `concept:` ＋ 語 | `similarTo` → Concept |
| `Element` | `elem:` ＋ 要素 | `hasElement` / `genusElement` / `differentiaElement` → Concept |
| `Name` | `name:` ＋ 名前側の値 | `hasName` → Concept |

```mermaid
flowchart LR
  O[Observation 観測] -->|observes| C[Concept 〇〇]
  O -->|derived_from| N[Snapshot コーパス]
  E[Element 要素] -->|hasElement 観測| C
  E -->|genusElement 類| C
  E -->|differentiaElement 種差| C
  M[Name 名前側] -->|hasName 読み・英名・別名…| C
  C <-->|similarTo| S[Concept 類似]
```

向きは芯と同じで、要素（依存される側）→ 概念（要素が変わったら見直す側）です。監視層は第一弾と同じ形で、コーパス1つが Snapshot（中身の digest なので入力の並び順では変わらない）、要素を見た概念ごとに Observation が1つできます。`hasElement` はその観測を `lock`（主張した記録）として持ち、`captured_at` があれば `observed_at` に入ります。要素が未観測（`null`）の概念には観測がありません。`hasElement` は観察の段（observed）、`genusElement`・`differentiaElement` は `define` の結果（derived、類似先が未観測なら hypothesis）です。`hasName` は名前側（読み・英名・学名・別名・同音語・名前の由来・シリーズ名）で、観察の段ですが定義には入りません。

### 🔭 第一弾のクラスと関係

| クラス | 識別子 | 出ていく関係 → 先 |
| --- | --- | --- |
| `Observation` | `observation:` スナップショット digest ＋ PR | `hasRun` → ActionsRun・`targetsBranch` → Branch・`hasBase` / `hasHead` / `hasMain` → Commit・`hasCompletion` → CompletionRecord・`hasEvidence` → Evidence・`missingEvidence` → EvidenceGap・`changesFile` / `updates` → File・`hasPin` → FixedSHA・`hasGeneratedArtifact` → GeneratedArtifact・`hasIssue` → Issue・`missingFromMain` → MainGap・`observes` / `targets` → PullRequest・`hasReview` → Review・`derived_from` → Snapshot・`hasTask` → Task |
| `PullRequest` | `pr:` リポジトリ ＋ PR 番号 | `integrates_into` → Branch・`verified_by` → Evidence・`has_status` → Observation・`blocks` / `dependsOn` / `depends_on` / `duplicates` / `overlapsWith` → PullRequest・`belongsTo` → Repository |
| `Repository` | `repo:` owner/name | `has_status` → Observation・`same_as` → Repository |
| `Snapshot` | `snapshot:` digest | `supersedes` → Snapshot |
| `Commit` | `commit:` リポジトリ ＋ 完全 SHA | `belongsTo` → Repository |
| `Branch` | `branch:` リポジトリ ＋ ブランチ名 | `belongsTo` → Repository |
| `File` | `file:` リポジトリ ＋ 相対パス | `belongsTo` → Repository |
| `ActionsRun` | `run:` リポジトリ ＋ run ID ＋ attempt | `runsAt` → Commit・`hasJob` → Job・`belongsTo` → Repository |
| `Job` | `job:` run ＋ attempt ＋ job ID | — |
| `Task` | `task:` 観測（または台帳）＋ キー | `verifiesCommit` → Commit・`migration_source` → File・`has_status` → Observation・`migration_target` → Repository・`precedes` → Task |
| `CompletionRecord` | `completion:` 観測 ＋ digest | `verifiesCommit` → Commit |
| `FixedSHA` | `fixedsha:` 観測 ＋ digest | `pinsCommit` → Commit |
| `GeneratedArtifact` | `generatedartifact:` 観測 ＋ digest | `generatedFrom` → Commit |
| `Issue` | `issue:` 観測 ＋ digest | `belongsTo` → Repository |
| `Review` | `review:` 観測 ＋ digest | — |
| `Evidence` | `evidence:` 観測 ＋ digest | — |
| `EvidenceGap` | `evidencegap:` 観測 ＋ digest | — |
| `MainGap` | `main-gap:` 観測 | — |

```mermaid
flowchart TD
  O[Observation] -->|derived_from| N[Snapshot]
  O -->|observes| P[PullRequest]
  O -->|hasHead / hasBase / hasMain| C[Commit]
  O -->|hasRun| W[ActionsRun]
  O -->|changesFile| F[File]
  O -->|hasTask| T[Task]
  W -->|runsAt| C
  P -->|dependsOn| P
  P -->|belongsTo| R[Repository]
  C -->|belongsTo| R
  T -->|migration_source| F
  T -->|migration_target| R
```

## 🪜 手順を並べて見る（rules と plan）

| 段 | 🧩 第二弾 `rules`（〇〇の定義） | 🔭 第一弾 `plan`（統合順序） |
| --- | --- | --- |
| 1 集める | 類似と要素（`similar`・`concepts`） | PR ごとの観測（スナップショット、複数なら履歴） |
| 2 選ぶ | `seeds` の〇〇とその類似 | PR ごとに最新の観測（同時刻の矛盾はエラー） |
| 3 組む | 類 AND ・ 最短の種差（1つまで欠けてよい）・ NOR / NAND 類似の固有（控え）・ 全要素 | main 未導入の PR と `dependsOn` |
| 4 当てる | 全概念に当てて FN・FP | 芯の `order`（graphlib） |
| 5 止める | FP・FN → `refuted`、未観測 → `to_model` | 循環・その下流・未観測の依存先 → `blocked` |
| 6 答える | 可逆な最初の規則 = 定義（`derived`） | 依存の順（CI・レビュー・競合は別に確認） |
| 7 確かめる | `holdout`: 概念を1つ隠して作り直し、隠した概念で測る（🙈 初見）・要素を1つ隠して測る（🎭 マスク）。`guess`: 何問で当たるか（🎯 当てっこ）。`wobble`: 名前を揺らして、1文字違い・もの側に紛れた名前を見る（🔤） | ➖ |
| 終了コード 2 | 可逆な定義が無い〇〇がある | ブロック・循環・棚卸しが不確か |

どちらも「見ていないものを完了・成立と読まない」点が同じです。未観測は第二弾では `to_model`、第一弾では `blocked` に残ります。

## 🧰 tools を並べて見る

本体の芯を組み合わせて、名前の意味（オントロジー → トートロジー）に沿った問いに答えます。実装を二重に持たず、芯を呼ぶだけです。

| ファイル | 関数 | 🧩 第二弾で | 🔭 第一弾（`gh_audit/`）で |
| --- | --- | --- | --- |
| ⚖️ `tautology.py` | `holds` `judge` `rules` `holdout` `guess` `guess_report` `wobble` `equivalent` | 規則での判定・定義・初見とマスクでの評価・当てっこ・名前の表記揺れ・真理値表（CLI あり） | ➖ |
| ✅ `tautology.py` | `standing` `gaps` `entailed` | 定義が立つ段・証明未満の辺 | 監査の辺が立つ段・証明未満の辺 |
| 📚 `ontology.py` | `classes` `violations` `identity` | 鍵に昇格できる属性の組（種差と同じ考え方） | 語彙の検査（`validate` が使う）・クラス一覧 |
| 🕸️ `knowledgegraph.py` | `relation_cycles` `topological_order` | ➖ | 親の `fleet_records` / `vendor_fleet_plan` と同じ名前・形 |

## 📊 例データでの結果を並べて見る

どちらも同じ芯のコマンドで問えます（🧩 第二弾は `python -S tools/tautology.py`、🔭 第一弾は `python -S gh_audit/gh_audit.py` に続けて実行）。

| 問い | 🧩 第二弾 `examples/concepts-20261115.json` | 🔭 第一弾 `examples/audit-20261114.json` |
| --- | --- | --- |
| グラフ | 290 ノード・568 辺（Element 183・Name 50・Concept 28・Observation 28・Snapshot 1） | 720 ノード・2,342 辺（File 542・ActionsRun 93・Commit 32・PullRequest 15・Observation 14 ほか） |
| `check` | 所見なし | 所見なし |
| `reach` | `elem:カフェイン含有` → エナジードリンク・コーヒー・カクテル（カフェインは無いが類似なので見直す） | `file:myon-bioinformatics/Aoi:README.md` → 159 ノード（PR 12） |
| `ladder` | 観測 435・導出 123・候補 10・証明 0 | 観測 2,292・導出 50・候補 25・証明 0 |
| 手順 | `rules`: 6 つの〇〇すべてに可逆な定義（終了コード 0）。`holdout`: 初見の誤り 0/162。`guess`: 28 概念すべて平均 4.4 問で当たる（確かめの1問込み）、知らない相手に 96% で「知らない」。`wobble`: 1文字違い 3 組、もの側に紛れた名前 2（サケ属・サケ科。終了コード 2） | `plan`: 順序 5・ブロック 1（`SakAnalytics#45` が未観測の `#44` を待つ。終了コード 2） |

🔭 の例は 2026年11月14日 23:12 JST の監査から抜き出した履歴（8 リポジトリ、観測した PR は 14 件）で、今の GitHub の状態ではありません。

## 🧩 第二弾: 類似から定義を作る（本体・`tools/tautology.py`）

### 📥 集めるもの

```json
{
  "schema": "ontautology-concepts/1",
  "seeds": ["ギター", "ピカチュウ", "鮭", "iPhone", "エナジードリンク", "ルイージ"],
  "similar": [{"left": "ギター", "right": "ベース", "basis": "observed"}],
  "maybe": {"ギター": ["金属弦"]},
  "names": {"ギター": ["英名:Guitar"]},
  "concepts": {
    "ギター": ["楽器", "弦楽器", "撥弦", "フレット", "ボディ", "6弦標準", "中高音主体"],
    "ベース": ["楽器", "弦楽器", "撥弦", "フレット", "ボディ", "4弦標準", "低音主体"]
  }
}
```

- 🌱 `seeds`: 定義したい〇〇。増やすときは `seeds` と `similar`・`concepts` に足すだけです。
- 🔗 `similar`: 「〇〇は🔳🔳の類似」。1つの〇〇に何本でも足せます。`[left, right]` の短い形も可。
- 🤷 `maybe`: 外れているかもしれない紐付け（人がうろ覚えで付けるようなもの）。根拠の段は `hypothesis` で、定義や判定には使わず、当てっこで食い違っても減点しません。例: ベースの `有名なリフ:Seven Nation Army`（実はギターを1オクターブ下げた音）、ミミッキュの `黄色`（黄色いのはピカチュウに似せた布）。
- 🏷️ `names`: 名前側。読み・英名・学名・和名・別名・同音語・名前の由来・シリーズ名など、「何と呼ぶか」を `concepts` と同じ「属性:値」で書きます。名前を聞くのは答えを言うのと同じなので、定義と当てっこの質問には使わず、`wobble`（表記揺れ）だけが使います。
- 🧺 `concepts`: 観察した要素。まだ見ていない概念は `null`（判定モデルへ回る）。値を持つ要素は `開放弦:EADGBE`・`進化の段:1進化ポケモン`・`種族値合計:320`・`商品:レッドブル` のように「属性:値」で書くと、値が違うことがそのまま見分けになります。1つの属性に値をいくつ書いても、当てっこでは1問、定義では1つの手がかりです。

### 🔄 流れ

```mermaid
flowchart LR
  S[🔗 類似を集める] --> G[∩ 類 = 共通項 AND]
  G --> R[🧮 規則の候補<br/>類 · 類 ∧ 最短の種差（1つまで欠けてよい） · 類 NOR 類似の固有 · 類 NAND … · 全要素]
  R --> J[⚖️ 全概念に当てて FN・FP]
  J -->|FN=FP=0| D[✅ 可逆 = 定義 derived]
  J -->|要素が未観測| M[🤖 to_model 判定モデルへ]
  D --> H[🙈 初見・🎭 マスクで測る holdout]
  D --> E[🔁 書き換えが真理値表で同じ = proof]
```

TalkCompress の判定モデルと同じ分け方で、まず規則が決め、規則で決められないものだけを判定モデル（LLM）に回します。OTL 自身は LLM を呼びません。

### 📊 6つの〇〇の定義

`examples/concepts-20261115.json`（28 概念、類似 21 組、seeds 6）で `rules` を実行した結果です。どの〇〇にも類似を2つ以上入れています。ギターには類似ではないのに類が同じになる紛らわしい相手（ピアノ）もいます。見分ける手がかりは「属性:値」で足しています。

| 〇〇 | 足した手がかり |
| --- | --- |
| 🎸 ギター | 開放弦・代表モデル（ストラトキャスター・レスポール）・有名なリフ |
| ⚡ ピカチュウ | タイプ・分類・進化の段（たね／1進化／2進化ポケモン）・進化方法・初登場世代・種族値（各値と合計） |
| 🐟 鮭 | 産卵・陸封型・料理。🏷️ 名前側に 読み（さけ・しゃけ）・同音語（酒・避け）・別名（アキアジ・トキシラズ）・和名・学名・英名 |
| 📱 iPhone | 音声通話・国内OSシェア（MMD研究所 2026年8月、iPhone 45.6%・Android 54.1%）・見守り（スクリーンタイム／ファミリーリンク）・アクセサリ（MagSafe・Apple Pencil） |
| 🥤 エナジードリンク | 商品（レッドブル・モンスターエナジー・ZONe）。ヌメロンのバイトではなくヒットを狙う、一つ具体的な階層 |
| 🟢 ルイージ | 帽子のマーク・初登場年・誕生（マリオの2Pカラー）。🏷️ 名前側に 主役シリーズ・名前の由来（イタリアで多い名前・日本語の「類似」）・英名 |

| 〇〇 | 類似 | 類（共通項） | 定義 = 類 ∧ 手がかり（1つまで欠けてよい） | 「類だけ」の精度（FP） |
| --- | --- | --- | --- | --- |
| 🎸 ギター | ベース・ウクレレ・三味線・バイオリン | 楽器・弦楽器・ボディ | `6弦標準`・代表モデル・有名なリフ の2つ以上 | 0.82（ベース・ウクレレ・三味線・バイオリン・ピアノ） |
| ⚡ ピカチュウ | ライチュウ・ピチュー・デデンネ・プラスル・マイナン・パチリス・ミミッキュ・モルペコ | ポケモン | 種族値 `HP:35` `こうげき:55` `すばやさ:90` `とくぼう:50` `合計:320` の4つ以上 | 0.71（類似の8匹すべて） |
| 🐟 鮭 | サクラマス・スチールヘッド | 魚類・サケ科・サケ属・遡河回遊魚・食用 | `銀白色の体側`・料理 の1つ以上 | 0.93（サクラマス・スチールヘッド） |
| 📱 iPhone | Android・iPad | タッチパネル・アプリ実行環境 | `iOS`・`アクセサリ:MagSafe`・`国内OSシェア:45.6%` の2つ以上 | 0.93（Android・iPad） |
| 🥤 エナジードリンク | コーヒー・カクテル | 飲料 | `タウリン・ビタミンB群`・`炭酸`・商品 の2つ以上 | 0.93（コーヒー・カクテル） |
| 🟢 ルイージ | マリオ・ワリオ・ワルイージ | 任天堂・ゲームキャラクター・人間・帽子・オーバーオール | `初登場年:1983` `帽子のマーク:L` `弟` `緑色` `誕生:マリオの2Pカラー` の4つ以上 | 0.89（マリオ・ワリオ・ワルイージ） |

- 「類だけ」の規則は毎回その類似を通してしまいます（FP）。
- 🔑 **鍵は、いちばん短い種差を「1つまで欠けてよい」でまとめます。** 2つなら OR、5つなら4つそろえば認めます。長い種差は他と共有する要素の組み合わせで、初めて見る相手を通しやすいので使いません。
- 🧺 **1つの属性は1つの手がかりです。** `料理:ちゃんちゃん焼き`・`料理:ルイベ`・`料理:塩焼き` はどれか1つあればよく、3つあっても1つと数えます。当てっこで「料理は？」が1問なのと同じです。
- 🏷️ **定義は もの側だけから作ります。** 名前側（別名・同音語・名前の由来・シリーズ名…）を分ける前は、鮭の定義が別名と同音語に、ルイージの定義がシリーズ名と名前の由来に寄っていました。
- ✋ **「持っているもの」で決める形を先にします。** 類似の固有を NOR で除く形は、見たことのある類似しか除けないので控えです。同じ形どうしなら、短い規則と、類から組んだ規則を先にします。
- 🟢 ルイージの `配管工` は鍵になりません（マリオも持つ）。🎸 ギターは、ピアノが類だけを共有するので鍵が要ります。
- ⚡ ピカチュウはミミッキュ（でんきではない）とデデンネたち（ねずみポケモンではない）が加わって、類が `ポケモン` だけに狭まりました。その分、種族値の値で見分けます。

### 🙈 初見と 🎭 マスク（`holdout`）

集めたものでだけ満点になる定義を見抜くための測り方です。ナレッジグラフ・オントロジーでは、いずれ初めて見るデータや欠けた観測に向き合うので、最初から測ります。

| 測り方 | やること | 数えるもの |
| --- | --- | --- |
| 🙈 初見 | 他の概念を1つ隠して定義を作り直し、隠した概念に当てる | 隠した概念を通してしまった数（FP） |
| 🎭 マスク | 〇〇自身の要素を1つ隠して、元の定義に当てる | 〇〇を認められなくなった数（FN） |

| 段 | 概念 | 🙈 初見の誤り | 🎭 マスクで落ちる | ✂️ 定義の要素数（平均） |
| --- | --- | --- | --- | --- |
| 初回（類似1つずつ） | 12 | 6 / 66（9.1%） | 26 / 40（65%） | 6.5 |
| 類似と紛らわしい相手を増やす | 17 | 6 / 96（6.3%） | 25 / 40（62.5%） | 6.0 |
| ＋見分ける属性・最短の種差だけ | 17 | 4 / 96（4.2%） | 24 / 49（49%） | 6.7 |
| ＋類似を全部2つ以上・鍵は1つまで欠けてよい | 22 | 0 / 126（0%） | 20 / 53（38%） | 6.0 |
| ＋具体的な手がかり（商品・モデル・リフ・料理…）・1つの属性は1つの手がかり | 28 | 0 / 162（0%） | 17 / 77（22%） | 7.5 |
| 名前側を分ける（定義は もの側だけ） | 28 | 0 / 162（0%） | 17 / 67（25%） | 7.3 |

- 🙈 **初回の満点は見かけでした。** 6つの〇〇すべてで、いちばん近い類似を隠すと、作り直した定義がそれを通しました。類似を増やすだけでは、ギターは隠したウクレレを、ピカチュウは隠したピチューを通したままでした。
- ⚡ **ピカチュウは、本当に違う属性で直りました。** 進化の段と種族値を入れると、種族値の値が違うので、隠したピチューを弾けます。種族値が1つ欠けても他で認められるので、マスクにも強くなりました。
- 🎸 **ギターは、OR を最短の種差だけにして直りました。** ウクレレを隠すと、`中高音主体 ∧ 撥弦` のような長い種差まで OR でつながり、ウクレレがその枝で通っていました。最短の `6弦標準`・`開放弦:EADGBE` だけにすると弾け、2つあるので片方が欠けても認められます。
- 🎭 **マスクに弱いのは AND です。** 類として AND で並べた要素は、1つ欠けるだけで落ちます。
- 🧩 **残っていた4件は、データと決め方の両方で消えました。** 類似（スチールヘッド・iPad・カクテル・ワリオ・ワルイージ）と属性（産卵・陸封型・音声通話・帽子のマーク・初登場年）を足すだけだと 3/126、決め方だけ変えると 1/96、両方で 0/126 です。
- 🟢 **鍵1つで通すと、隠した双子が入ります。** `配管工` はマリオとルイージだけが持つので、マリオを隠すとルイージの鍵に見えます。「1つまで欠けてよい」なら、配管工しか持たないマリオは弾けます。
- 🥤 **NOR は見た相手しか除けません。** コーヒーを隠すと「カクテルではない飲料」が短くて可逆ですが、コーヒーもカクテルではないので通ります。持っているもので決める形を先にして弾きます。
- 🎭 **マスクで落ちるのは類（AND）の要素だけになりました。** 鍵は1つまで欠けても認めるからです。類が狭まるほど（ピカチュウは `ポケモン` だけ）落ちにくくなります。

### 🎯 当てっこ（`guess`）

ヌメロンやワードウルフのように、問い合わせの回数で正解に着けるかを測ります。厳しく見分けられるかより、「人が当てっこするときのように、少ない質問で着くか」を見ます。

- ❓ **質問は2種類です。** 「その要素がある？」（はい／いいえ）と、`属性:値` の要素に対する「開放弦は？」のような値で返る質問です。値で返る分、ヌメロンのように二択より多くを1問で知れます。
- ✂️ **毎回、残った候補をいちばん均等に割る質問を選びます。** 見込みは二択で理想的に割れたときの回数（log₂ 候補数）です。
- 🧍 **人間らしい失敗を許せます。** `--lies N` で、食い違いを N 回までは候補を残します。`maybe` の紐付けは食い違っても減点しません。
- ✅ **1人に絞れても、まだ答えません。** 絞るのに使った答えは、知らない誰かと共有しているかもしれないので、数えません。その1人だけが持つ答え（全概念の中でいちばん珍しく、まだ聞いていないもの）を聞いて、確信度を積みます。
- ⚖️ **確信度は、推定回数と同じ物差しです。** 1つの答えの重さは log₂(候補数 ÷ 同じ答えの数) ÷ log₂(候補数) で、誰も持っていない答えが1つ合えば 1（1人分を言い当てた重さ）です。合えば足し、合わなければ引きます。それまでに合わなかった答えも、先に引いておきます。
- 🏁 **確信度が `--sure`（既定 1）に届いたら答えます。** 届く前に、許す回数を超えて食い違えば「知らない」です。聞けることが残っておらず、反する答えも無ければ、そのまま答えます（確信度は低いまま返します）。

`examples/concepts-20261115.json`（28 概念、二択での見込み 5 問）の結果です。

| 許す食い違い | 確信度 | 😊 正直に答える | 🎭 1つ忘れる | 🙈 知らない相手を出す |
| --- | --- | --- | --- | --- |
| 0 回 | 0（確かめない） | 28 / 28 当たる・平均 3.4 問（最大 7） | 238 / 287 当たる（83%） | 16 / 28 で「知らない」と言えた（57%） |
| 0 回 | 1 | 28 / 28 当たる・平均 4.4 問（最大 8） | 210 / 287（73%） | 27 / 28（96%） |
| 0 回 | 2 | 28 / 28 当たる・平均 5.6 問（最大 9） | 177 / 287（62%） | 28 / 28（100%） |
| 1 回 | 0（合わなかった分だけ確かめる） | 28 / 28 当たる・平均 7.3 問（最大 14） | 287 / 287（100%） | 23 / 28（82%） |
| 1 回 | 1 | 28 / 28 当たる・平均 8.3 問（最大 15） | 287 / 287（100%） | 28 / 28（100%） |
| 1 回 | 2 | 28 / 28 当たる・平均 9.6 問（最大 16） | 287 / 287（100%） | 28 / 28（100%） |

- 🎯 **おすすめは2通りです。** 速さなら `--lies 0 --sure 1`（平均 4.4 問、知らない相手に 96%）、取りこぼしたくないなら `--lies 1 --sure 1`（平均 8.3 問、忘れても知らない相手でも 100%）です。確かめの問い数は確信度しだいなので、答えが珍しければ1問、ありふれていれば2問以上になります。
- ⚡ **正直なら見込みより少ない問いで着きます。** 確かめの1問を入れても平均 4.4 問です。値で返る質問が効いていて、ピカチュウは「タイプは？ → でんき」「種族値とくこうは？ → 50」で絞り、「種族値HPは？ → 35」で確かめる3問です。
- 🥤 **具体的な階層はヒットになります。** エナジードリンクは最後の「商品は？ → レッドブル・モンスターエナジー・ZONe」で1つに決まります。
- ✅ **確かめると、知らない相手を言い当てなくなります。** 鮭を知らないと「産卵は？ → 一生に一度」でサクラマスが残りますが、「料理は？ → ちゃんちゃん焼き・ルイベ・塩焼き」で、ます寿司のサクラマスではないと分かります。iPhone を知らないときも、iPad に「アクセサリは？ → MagSafe」で違うと分かります。
- 🎭 **許さないときは、確かめに使った要素を忘れていると正解を言えません**（確信度1で 83% → 73%）。1回許すと、合わなかった分を確信度から引いて確かめ直すので、忘れても知らない相手でも当たります。
- 🥤 **許さず確信度1のとき、残る1件は隠れた双子です。** エナジードリンクを知らないと、コーヒーを「カフェイン含有」で確かめて通してしまいます。カフェインは隠れたエナジードリンクとだけ共有する特徴なので、知っている範囲ではコーヒーにしか無い手がかりに見えるからです（`holdout` で見た形と同じです）。確信度を2にすれば、もう1問聞いて弾けます。
- 🏷️ **名前は聞きません。** 「英名は？」は答えを言わせるのと同じで、1問で終わってしまうからです。質問は もの側だけです。

### 🔤 名前を揺らす（`wobble`）

表記を少し揺らすと、名前どうしの近さや、もの側に紛れた名前が見えてきます。照合の段は TalkCompress と同じ考え方で、厳密に一致（`exact`）→ 表記ゆれを畳むと一致（`notation`）→ 1文字違い（`near`）の順に広げます。

- 🧹 **畳む表記ゆれ:** 全角半角（NFKC）・大文字小文字・区切り（空白 `-` `_` `・`）・カタカナとひらがな・長音（`ー` は前の母音に）。`ピカチュー`・`ﾋﾟｶﾁｭｳ`・`ぴかちゅう` は同じです。
- 🔎 **見るもの:** 名前が1文字違いの組（類似かどうかも）、2つの概念が同じ表記を持つ名前（割れる名前）、もの側の要素に紛れた自分の名前や読み（名前の言い換え）です。1文字の語どうしは何でも1文字違いになるので、2文字以上で比べます。
- 🚦 **終了コード:** もの側に名前が紛れていれば 2 です。

`examples/concepts-20261115.json` の結果です。

| 見たもの | 結果 |
| --- | --- |
| 🔤 1文字違い | ピカチュウ・ピチュー（類似）、ルイージ・ワルイージ（類似）、マリオ・ワリオ（類似に入れていない） |
| 🔁 もの側に紛れた名前（名前側に移す前） | 8: `白鮭(O.keta)`・`主役シリーズ` ×4（マリオ・ルイージ・ワリオ）・`iPadOS`・`代表モデル:ジャズベース` / `プレシジョンベース` |
| 🔁 もの側に紛れた名前（移した後） | 2: 鮭の `サケ属`・`サケ科`（読み `さけ` を名前側に書いたので見つかった） |
| 🔎 語を引く | `シャケ` → 鮭（読み:しゃけ、表記ゆれ）・`酒` → 鮭（同音語:酒）・`salmon` → 鮭（英名）・`るいじ` → ルイージ（1文字違い） |

- 🐟 **残る2つは、分類名そのものが鮭にちなんでいます。** 日本語の `サケ属` は鮭の読みを含みますが、学名にすると Oncorhynchus で、鮭の名前に頼りません。訳すと名前の層から離れる例です。
- 🟢 **`るいじ` を引くとルイージに当たります。** 名前の由来（日本語の「類似」）が、表記を揺らすと1文字違いとして出てきます。
- 🍶 **`酒` は鮭に「同音語として」当たります。** `via` がどの名前で当たったかを示すので、同じ語と、同じ音の別の語を取り違えません。

### ⚖️ 判定の読み方

| 判定 | 意味 | 何が覆すか |
| --- | --- | --- |
| 命題（規則 → 〇〇）・対偶 | 規則が通すなら〇〇 | FP（他の概念を通した） |
| 逆（〇〇 → 規則）・裏 | 〇〇なら規則が通す | FN（〇〇を落とした） |
| `reversible` | FN も FP も 0、未観測もなし | 根拠の段は `derived` |
| `to_model` | 要素が未観測で規則では決められない | 判定モデルへ回す |
| `equivalent` | 2本の規則が真理値表の全通りで同じ | 根拠の段は `proof` |

規則は JSON の木で、`["AND", "弦楽器", ["NOR", "4弦標準", "低音主体"]]` のように AND・OR・NOT・NAND・NOR を入れ子にします。空の AND は常に真、空の OR は常に偽です。

### 🔁 往復と類・種差

- `define` は類似群の共通項（類）と、他の全概念から見分ける最小の要素の組（種差）を出します。
- `roundtrip` は要素の集合から元の語へ戻せるかを見ます。`カフェイン含有 飲料` はエナジードリンクとコーヒーの両方に当たり `collides`、`炭酸` を足すとエナジードリンクだけに戻ります（`unique`）。
- 反例（`6弦ベース` など）が来ると `collides` になり、最小識別鍵が組み替わります。類似先が未観測（`null`）や `basis=hypothesis` だけなら `derived` に上がりません。

### ⚠️ 限界と次

- `reversible` は集めた概念の範囲での話です。`holdout` の初見の誤りがその隙間です。
- 初見の誤りが 0 なのは 28 概念の範囲での話です。類似が増えれば、また隠れた双子が出ます。増やすときは、類似を2つ以上と、値で見分けられる「属性:値」を一緒に足します。
- 🔢 鍵の探索は5つで止まります。そのためギターの `開放弦:EADGBE` は、鍵の候補にあっても定義に入っていません（当てっこでは使います）。
- 📅 `国内OSシェア` は 2026年8月の調査の値で、変わります。鮭の輸出入のように年ごとに変わる数字は、出典と時点を付けて足します（まだ入れていません）。
- 🎭 マスクで残るのは類（AND）の要素です。類も「1つまで欠けてよい」にすると、類だけを共有する紛らわしい相手（ピアノ）を通しやすくなるので、測りながら決めます。
- 🎯 当てっこの確かめは、知っている範囲でいちばん珍しい答えを使うので、許さず確信度1のままでは隠れた双子（コーヒーのカフェイン）を見抜けません。確信度2か、1回許すと弾けます。
- 🔤 `wobble` が見つけるのは、もの側に自分の名前や読みがそのまま入っている場合だけです。`iOS` のように名前と綴りが重ならない言い換えや、漢字の読み（`類似` → るいじ）は取れません。読みは名前側に仮名で書いておきます。
- 🧱 「訳しても同じ名前（固有名詞）」かどうかは、まだ測っていません（マリオ → Mario を同じと見るには、ローマ字にする表が要ります）。
- 🤝 マリオ・ワリオは名前が1文字違いですが、類似にはまだ入っていません。入れるかは集める側で決めます。

## 🔭 第一弾: GitHub 監査（`gh_audit/`）

第一弾は `gh_audit/gh_audit.py` に閉じています。GitHub 固有のもの（リポジトリ・PR・コミット・run・job・タスク・移管）はここだけに置き、本体と tools には入れません。第一弾の enhancement はこのフォルダに足します。

入力は継続監査サイトの「統合証跡JSON」（`integration-audit/3`）です。観測 JSON の `{"aoi_integration": {...}}` で包まれた形も受け付けます。GitHub への取得・書き込みは行いません。

### 👀 観測の扱い

- 観測に取得日時・出典・作業状態・merged・mergeable・main 包含を残します。未取得は `null` のままで、false にしません。変更ファイルの未取得は `files_observed=false` で区別します。
- run は自分のコミット（`runsAt`）にだけ結び付けます。PR の head と同じだとは仮定せず、head が未取得の run にはコミットを作りません。attempt ごとに別のノードです。
- 同じリポジトリで変更パスが重なったときだけ `overlapsWith` を導出します（basis は derived）。Git の競合を意味しません。
- 依存は監査側の主張として取り込み、出典と観測 ID を関係に付けます。Turtle では `rdf:Statement` で表し、古い依存を今も有効な事実に昇格させません。
- `edges_of(graph)` が監査グラフを芯の辺に直します。`dependsOn` と `changesFile` は向きを返し、向きのない `overlapsWith` は両向きにします。循環と順序は `cycles GRAPH dependsOn`、`order GRAPH dependsOn` のように依存の辺だけで問います。

### 🪜 統合順序（`plan`）の補足

PR ごとに最新の観測を選び、`contained_in_main=true` の依存先を消化済みとして、芯の `order` で順序を出します。merged だけでは main への導入を推定しません。未観測の依存先、循環、その下流は `blocked` に残し、独立した部分の順序は出します。同時刻に矛盾するスナップショットがあればエラーにします。順序は依存関係の制約だけで、CI・未解決レビュー・競合・保留の受入条件は監査ビューで確認します。

### 📋 open PR の棚卸し（任意）

`open_pr_inventory` は任意のトップレベル配列です。無い入力は従来どおりに計画します。空配列は「どのリポジトリも範囲に含めない」という宣言で、「どこも PR がゼロ」ではありません。各要素は owner/name 1つに対応します。

```json
{"repository":"myon-bioinformatics/Ironmate","checked_at":"2026-11-15T12:00:00Z",
 "complete":true,"open_pr_numbers":[]}
```

- ✅ 完全な要素は、重複のない正の PR 番号（Draft を含む）を並べます。`[]` は、その確認時点でそのリポジトリに open PR が無いことを明示します。取得失敗や部分取得は `"complete":false,"open_pr_numbers":null` で、空配列にはしません。
- 📸 入力ごとに `Snapshot` ノードを作ります（records が無くても）。digest・観測時刻・明示の棚卸しを残し、`derived_from` で PR の観測とつなぎます。Turtle では構造化メタデータを JSON テキストの文字列リテラルにします。
- 🪜 `plan` はリポジトリごとに最新の `checked_at` を使います（不完全でも）。範囲が不完全なら古い PR を予定に入れず `inventory_uncertainty` を返します。完全な範囲がメンバーを決めますが、並んだ PR には同じスナップショットの行が必要で、無ければ `missing_rows` と `blocked` に出ます。古い証跡を今の証跡に昇格しません。同時刻の矛盾は ambiguous として拒否します。
- 🚫 消えたことは完了ではありません。依存先が見えなくなっても、観測で `contained_in_main: true` が確かめられない限り下流をブロックします。履歴のノードと証跡は消しません。不完全な棚卸しでは `plan` の終了コードは 2 です。これは依存の計画であって、マージの許可や CI の判定ではありません。

### 📦 Flutter の未吸収機能

`examples/flutter-absorption.json` に、固定 SHA の元ファイル、移管先候補、受入条件、検証 SHA・Actions 証跡を記録します。初期登録は主要機能 12 群と追加要望 2 件で、全パターンの棚卸し完了や吸収完了は意味しません。アーカイブ後も元 SHA への紐付けを保ち、Flutter の active 監視とは分けます。

- `transfers` は未完了または棚卸し範囲が未確定なら終了コード 2、入力不整合なら 1 です。
- `state=完了` には、元 SHA と移管先 SHA に一致する receipt、移管先ファイル、main 反映の記録、全受入条件の ID、移管先の Actions URL が必要です。これは記録の整合性検査で、CI 結果・main 包含・機能同等性の独立検証ではありません。移管先が未決でも `target.repository=null` で残せます。
- 機能は Task として `migration_source`（元 File）・`migration_target`（移管先 Repository）に結び、5 状態と Snapshot・Evidence を保ちます。追加要望は `kind=request` で既存機能の未吸収と区別します。

監査の入力には「常に成り立つ」と言える関係がないので、証明の段は 0 本です。第二弾の `equivalent` のように、他で証明された関係を辺として渡したときに埋まります。

## 🧠 共通の芯

### 🪜 根拠の段

| basis | 意味 |
| --- | --- |
| `hypothesis` | 誰も確かめていない候補。`reach` は候補として示すだけで、その先へ進まない |
| `derived` | 記録に対する決まった規則（同じ変更パス、名前の一致、集めた概念での可逆な定義など） |
| `observed` | 記録から読んだ。見ていないものについては何も言わない（省略時の既定） |
| `proof` | 見ていない場合も含めて常に成り立つ。ここがトートロジーの段 |

`why` は辿った道で一番弱い段（`weakest`）を返すので、途中に候補が1つあれば証明済みとは読めません。

### 🔗 芯の辺

`{"kind", "source", "target"}` に、呼び出し側が持つもの（`basis`、主張している記録 `lock`、記録自身の時刻 `observed_at` など）を足した dict です。向きは **source = 依存される側 → target = source が変わったら見直す側**。前向きに辿れば影響先、後ろ向きに辿れば根拠です。

| 関数 | 答えること |
| --- | --- |
| `check(edges, nodes=None)` | 形の崩れ、未知の basis、存在しない参照、同じ記録・同じ時刻の主張で中身が違うもの。直さず報告する |
| `reach(edges, start)` | 変更が届く先。深さ・経路・その辺。DAG を仮定しない |
| `why(edges, node)` | 判断が拠っているもの。`cut` は深さ制限で読み残したこと |
| `cycles(edges)` | 循環の代表例。報告するだけで止めない |
| `order(edges, nodes=())` | 「先に必要」の辺から、並行できる組を順に返す（graphlib）。循環とその下流は `blocked`、残りは順序を出す |
| `ladder(edges)` | 段ごと・種類ごとの本数 |
| `key_report(items, candidates)` | 属性の組が鍵になるか: `key` / `repeat` / `collides` / `incomplete` |

同一性は最後に決まります。意味を持たない取っ手を振り、観測を足し、区別できないものをまとめ、新しい観測で割れることを許し、欠けがなく一意な属性の組だけを鍵に昇格させ、衝突は上書きせず報告します。`key_report` はその最後の2段で、第二弾の種差も同じ考え方です。

### ⌨️ コマンド

🧠 共通の芯 — `ontautology.py`（どの CLI からも使える）

| コマンド | 入力 | 答え |
| --- | --- | --- |
| 🧪 `check` 💥 `reach` 🔎 `why` 🔁 `cycles` 🪜 `order` `ladder` | どれでも | 所見・影響先・根拠・循環・順序・段ごとの本数 |
| 🔑 `keys GRAPH FIELDS...` | `"items"` を持つ JSON | 属性の組（`id+run` など）が鍵になるか |

🧩 第二弾 — `ontautology.py`（define・roundtrip）と `tools/tautology.py`（rules・judge・equivalent）

| コマンド | 入力 | 答え |
| --- | --- | --- |
| ⚖️ `rules CORPUS [CONCEPT...]` | 類似コーパス | 〇〇ごとの規則の候補と判定、可逆な定義（既定は `seeds`） |
| 🧮 `judge CORPUS CONCEPT RULE` | 類似コーパス | 1本の規則の FN・FP・精度・命題／逆／裏／対偶 |
| 🙈 `holdout CORPUS [CONCEPT...]` | 類似コーパス | 🙈 初見（概念を隠して作り直す）と 🎭 マスク（要素を隠す）での誤り。初見の誤りがあれば終了コード 2 |
| 🎯 `guess CORPUS [CONCEPT...] [--lies N] [--sure S]` | 類似コーパス | 当てっこ: 何問で当たるか（正直・1つ忘れる・知らない相手）。1人に絞れたら確信度 S（既定 1）まで確かめる。正直に答えて当たらない〇〇があれば終了コード 2 |
| 🔤 `wobble CORPUS [WORD...]` | 類似コーパス | 名前を揺らす: 1文字違いの組・割れる名前・もの側に紛れた名前、語を引く（厳密・表記ゆれ・1文字違い）。もの側に名前が紛れていれば終了コード 2 |
| ✅ `equivalent RULE RULE` | 規則2本 | 全通りで同じか（`proof`）、違う場合の反例 |
| 🧩 `define CORPUS [CONCEPT...]` | 類似コーパス | 類・種差・往復判定 |
| 🔁 `roundtrip CORPUS ELEM...` | 類似コーパス | 要素をすべて満たす概念（一意・衝突・空） |

🔭 第一弾 — `gh_audit/gh_audit.py`

| コマンド | 入力 | 答え |
| --- | --- | --- |
| 🔭 `audit FILE...` | 監査スナップショット | グラフ（`--format turtle` で RDF） |
| 🪜 `plan GRAPH` | 監査グラフ | main 未導入の PR の依存順・ブロック・未観測の依存先 |
| 🆚 `diff BEFORE AFTER` | 監査グラフ2つ | 追加・削除・変化した PR |
| 🐢 `turtle GRAPH` | 監査グラフ | RDF/Turtle |
| 📦 `transfers LEDGER` | 移管台帳 | 未吸収・移管先・受入の整合性 |

`tools/tautology.py` と `gh_audit/gh_audit.py` は本体の口 `main(commands=..., load=...)` に自分のコマンドを足すので、🧠 のコマンドもそのまま使え、CLI・標準入力の決まり・終了コードは1つです。「どれでも」は類似コーパス・素の `{"edges": [...], "nodes": [...]}`・（🔭 第一弾の CLI なら）監査グラフです。全コマンドに `-o FILE` があり、ファイル名を `-` にすると標準入力の UTF-8 JSON を読みます（1コマンドにつき1回）。

終了コード: `0` 答えた / `1` 入力エラー / `2` 答えたが要確認（所見・循環・ブロック・未知のノード・鍵にならない・差分あり・定義の衝突や未観測・可逆でない・同値でない）。`2` は道具の失敗ではなく、入力についての答えです。

### 🐍 Python・Node から呼ぶ

```python
import ontautology as ot
from tools import tautology
from gh_audit import gh_audit

tautology.rules(corpus, "ギター")["definition"]       # 🧩 第二弾: 可逆な最初の規則
ot.define_concepts(corpus, ["ギター"])                 # 🧩 第二弾: 類と種差
gh_audit.plan(gh_audit.audit([snapshot]))             # 🔭 第一弾: 監査グラフ → 依存順
```

Node からは `vendor/py_launch.cjs` の `--call 関数名` で、`if __name__ == "__main__"` を通さずに関数を名前で呼べます（引数は1つずつ JSON）。大きな JSON は引数ではなく CLI のファイル入力か標準入力で渡します。GraphQL は取得側で `integration-audit/3` へ変換する境界で、本体から認証・HTTP を呼びません。Rust への切り出しは同じ JSON と終了コードを保つ案で、未実装・未測定です。

## 🧪 テスト

```sh
python -S -m unittest discover -s tests                     # 標準ライブラリだけ（Node 26+ があれば Node 経由も）
uv run --no-project --with redis python -m unittest discover -s tests -p test_tools.py -k RedisCrossCheck -v   # 🧱 Redis で答え合わせ
```

| ファイル | 対象 |
| --- | --- |
| `test_ontautology.py` | 芯（辿る・循環・順序・所見・鍵・CLI） |
| `test_concepts.py` | 第二弾の類・種差・往復 |
| `test_tools.py` | tools（判定・可逆・真理値表・語彙・依存の向き）と Redis の答え合わせ |
| `test_gh_audit.py` | 第一弾の監査 |
| `test_fleet.py` | vendor のロック・Action の SHA 固定・Node 経由と Python の一致 |

🧱 `RedisCrossCheck` は、外部モジュールで先に考え方を確かめるための足場です。Redis の集合で同じ問い（`reach` の到達先、`key_report` の判定、規則が通す概念を `SINTER`・`SUNION`・`SDIFF` で、類と種差を `SINTER`・`SDIFF` で）を別に解き、乱数で作った入力すべてで本体と一致するかを見ます。`redis` パッケージか `redis-server` が無ければ skip し、CI の `redis` ジョブでだけ skip を失敗にします。サーバーは一時ディレクトリの unix socket で立て、ポートも保存も使いません。本体と tools は Redis を import しません。

## 🧭 置くもの・置かないもの

- 置く: 横断して見るためのグラフのロジック、類似から定義を作る判定、その用途としての GitHub 監査の読み取り。
- 置かない: GitHub や Git からの取得、各リポジトリ固有の記録形式の解釈、LLM の呼び出し、画面。それらは記録を書くリポジトリ・親（myon-bioinformatics）・TalkCompress の役目で、ここを呼ぶ側です。画面が要るときも HTML・CSS・JS は Python 側（`web_ui.py` など）で組みます。
- OWL 準拠は主張しません。SPARQL や GraphQL の代わりに、関数を名前で呼びます。

## 📝 方針メモ（たたき台）

リポジトリのあり方をルールとしてグラフに載せる案は、[docs/policy-rules.md](docs/policy-rules.md) にあります。実装ではなく、見直し前提の設計メモです。
