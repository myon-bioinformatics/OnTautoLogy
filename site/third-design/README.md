# 第三弾 設計・評価ワークボード

既存の監査ボードと分離した手動ワークボード。GitHub Pagesは静的配信だけを行い、GitHubへの投稿、モデル呼び出し、CI起動は行わない。

- 公開先: https://myon-bioinformatics.github.io/OnTautoLogy/third-design/
- 公開処理はPSWBと同じ親の `reusable-pages-static.yml` を固定SHAで再利用。
- `shared/scroll.css`・`scroll.js` はPSWBの既存実装を無改変で抽出。出典・固定SHA・内容ハッシュは `shared/provenance.json`、ライセンスは同じディレクトリ。
- 設計・比較条件・基準値はOTL側が所有する。共通横スクロールの新実装は追加しない。
- `baseline-evidence.json` は2026-11-17に既存コードSHA `79eba5343276f328d1de0854f162c42a21849e7b` と固定28概念入力を再実行した公開評価資料。現在mainの評価結果とは区別する。中間層結果は捏造せず未測定。
- 手動編集はブラウザ内保存。JSON保存・読み込みで移行する。以前のSites版の手動記録は自動移行されないため、Sites版でJSON保存し、Pages版へ読み込む。
- 公開するのは初期の公開資料だけ。個人の下書き・手動入力はブラウザに保存され、リポジトリへ自動送信されない。

更新時は同じ入力・評価設定・順序で既存方式を測定し固定してから比較案を記録する。条件を変えた結果は再評価対象になる。

「事例と知識グラフ」には、PR #23の固定入力で再実行した4事例とグラフ接続方式の比較を掲載する。現行結果と提案を区別し、手動編集の評価結果とは独立させる。再現コマンドは `python -S tools/tautology.py cases examples/concepts-20261115.json --sure 1`。K002の不一致により終了コードは2。
