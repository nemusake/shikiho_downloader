# スクレイピング使用手順書

本手順書は、四季報オンラインから銘柄情報を取得するスクリプト（scrape.py）の実行方法と運用上の注意点をまとめたものです。

## 1. 前提
- 管理: uv（Pythonの実行・依存管理に使用）
- 依存: Playwright（Chromium）
- 取得対象URL: `https://shikiho.toyokeizai.net/stocks/{code}`

## 2. 初回セットアップ
1) ブラウザのインストール（初回のみ）
- `uv run --python 3.11 python -m playwright install chromium`

2) 入力CSVの準備
- ファイル: `codelist.csv`
- 文字コード: UTF-8（BOM付き）
- 列: ヘッダに `code` を含める（例: 1332, 130A, 9984 などの4桁英数字）

## 3. 実行コマンド
- 単体動作確認（1件）
  - `uv run python scrape.py --limit 1`
- 先頭N件（例: 2件）
  - `uv run python scrape.py --limit 2 --sleep 1.2`
- 全件実行（推奨スリープ例 5秒）
  - `uv run python scrape.py --sleep 5.0`

ブラウザ表示の切替（デバッグ向け）
- UI表示（非ヘッドレス）で挙動確認
  - `uv run python scrape.py --headed --limit 1 --verbose`
※ 既定はヘッドレス。明示する場合は `--headless`

リトライ・ジッター付きの例
- 軽めの再試行＋スリープに±30%ジッター
  - `uv run python scrape.py --sleep 2.0 --retries 2 --jitter-frac 0.3`
- バックオフを強める（base=1.5, factor=2.0, max=20）
  - `uv run python scrape.py --retries 3 --retry-base 1.5 --retry-factor 2.0 --retry-max 20`

運用補助の例（レジューム/失敗CSV/追記）
- 既取得コードをスキップして再開
  - `uv run python scrape.py --resume`
- 失敗銘柄の一覧をCSV出力（`code,reason`）
  - `uv run python scrape.py --failures failures.csv`
- 既存出力へ追記（ヘッダ重複なし）
  - `uv run python scrape.py --append`
- 失敗CSVからの再実行（前回失敗分のみ）
  - `uv run python scrape.py --from-failures failures.csv --append`

タイムアウトやUAの調整
- ナビゲーション/操作のタイムアウトを延長（ミリ秒）
  - `uv run python scrape.py --nav-timeout 40000 --timeout 40000`
- User-Agent を変更
  - `uv run python scrape.py --user-agent "Mozilla/5.0 ... Chrome/124.0.0.0 Safari/537.36"`

主なオプション
- `--input`: 入力CSV（既定: `codelist.csv`）
- `--output`: 出力CSV（既定: `result.csv`）
- `--sleep`: リクエスト間隔秒（既定: 1.0）
- `--limit`: 上位N件のみ処理（0は全件）
- `--retries`: 一時的失敗のリトライ回数（既定: 0=無効）
- `--retry-base`: バックオフ基準秒（既定: 1.0）
- `--retry-factor`: 乗数（既定: 1.6）
- `--retry-max`: 1回の最大待機秒（既定: 15.0）
- `--jitter-frac`: 通常スリープに±割合のジッター（例: 0.3=±30%）
- `--failures`: 失敗銘柄CSVの出力パス（空で無効）
- `--resume`: 既存 `--output` を読み既取得コードをスキップ
- `--append`: 既存 `--output` に追記（無ければ新規作成）
- `--verbose`: 詳細ログ（リトライ詳細等）
- `--from-failures`: 失敗CSV（`code` 列）から対象銘柄のみ再実行
- `--headed` / `--headless`: ブラウザUIの表示切替（既定はヘッドレス）
- `--timeout`: 操作のデフォルトタイムアウト（ミリ秒、既定: 20000）
- `--nav-timeout`: ナビゲーションのタイムアウト（ミリ秒、既定: 20000）
- `--user-agent`: 使用するUser-Agent文字列

## 4. 出力仕様
- 出力ファイル: `result.csv`
- 文字コード: UTF-8（BOM付き）
- 列順: `code, company_name, market, feature, business_composition, industries, themes`
- 空欄となる場合: ページに該当セクションが無い/非リンク等の表記差がある場合

## 5. 抽出ロジック（要点）
- 企業名: 見出し（h1 等）から抽出
- 市場名: 本文テキストから「東証プライム/スタンダード/グロース」を正規表現抽出
- 特色: 「特色」ラベルの dd/td/兄弟要素から抽出
- 事業構成: 「連結事業/単独事業」に対応。末尾の「セグメント収益」は除去
- 所属業界（industries）
  - dd内のリンク群を抽出（比較会社領域以降は除外）
  - 除外: 「他」、数字を含む語、比較会社名、ラベル語（比較会社/市場テーマ）
  - 日本語優先（日本語語があれば日本語のみ）
  - テーマ語が混入する場合は除外。ただし除外で0件になる場合は元を保持（例: 135A=AI）
  - 要素が取れない場合は dd 素テキストの分割で補完
  - 上限: 最大3件、重複除去
- 市場テーマ（themes）
  - dd内リンク群 → 数字/比較会社/「他」を除外
  - 取れない場合は dd 素テキスト分割 → さらに取れない場合は本文「市場テーマ 行」を正規表現で抽出

## 6. ログと確認
- 実行ログは標準エラー（stderr）に出力
  - 例: `[1/20] Fetching 130A...`、`[DONE] Completed successfully`
- `result.csv` の先頭行や該当銘柄行を確認
- 例（検証済みケース）
  - 130A: themes=創薬
  - 135A: industries=AI（themes=AIでも保持）
  - 138A: industries=外食（居酒）、themes=FC
  - 1431: industries=戸建て,九州沖縄、themes=注文住宅（テーマ語は業界から除外）

## 7. トラブルシュート
- タイムアウト/読み込みに時間がかかる
  - `--sleep` を増やす（例: 5.0）
  - `scrape.py` の Playwright タイムアウト値を延長
  - `launch(headless=False)` に変更して挙動確認
  - `--retries` を指定して指数バックオフで再試行（`--retry-*` で調整）。404/410 は再試行しません
- 失敗の切り分け
  - `--failures` で `code,reason` を記録し再実行に活用
  - `--resume` と組み合わせて未取得分のみ再処理
- ブラウザ未インストール
  - `uv run --python 3.11 python -m playwright install chromium`
- CSVが文字化けする
  - 出力はBOM付きUTF-8です。Excelで開くことを推奨
- 一部の項目が空欄
  - セクション非掲示/リンク無し等の表記差によるもの。仕様。フォールバックで可能な限り補完済み

## 8. 運用
- サイト負荷への配慮: 5秒以上を推奨（用途や時間帯に応じ調整）
- CSVは再実行で上書き。必要に応じてバックアップ
- 仕様変更に備えて、定期的に抽出ロジックの見直しを推奨

## 9. 拡張のヒント
- 項目拡張: 決算期、従業員数、所在地 等
- 個別調整: 銘柄別の除外/採用ワードを設定ファイル化
- レポート: 空欄項目の集計、失敗コードの別CSV出力
