# scrape README

## 概要
- 四季報オンライン銘柄ページ `https://shikiho.toyokeizai.net/stocks/{code}` から項目を取得し、CSVに出力します。
- 対象項目: `code, company_name, market, feature, business_composition, industries, themes`
- SPAのためPlaywrightでレンダリング後のDOMから抽出します。
- 出力CSVは Excel 等での文字化け回避のため「UTF-8 BOM付き」で出力します。

## 前提
- パッケージ管理: uv（AGENTS.md準拠）
- 依存は `pyproject.toml` に定義済み（`playwright`）

## 初回セットアップ
- Chromiumのインストール（初回のみ）
  - `uv run --python 3.11 python -m playwright install chromium`

## 実行方法
- 1件だけ検証
  - `uv run python scrape.py --limit 1`
- 先頭N件（例: 2件）
  - `uv run python scrape.py --limit 2 --sleep 1.2`
- 全件（`codelist.csv` 全コード）
  - 標準: `uv run python scrape.py --sleep 1.0`
  - サイト負荷配慮（推奨例）: `uv run python scrape.py --sleep 5.0`

### リトライ・ジッター付きの例
- 軽めの再試行とスリープに±30%ジッター
  - `uv run python scrape.py --sleep 2.0 --retries 2 --jitter-frac 0.3`
- バックオフを強める（指数バックオフ: base=1.5, factor=2.0, max=20）
  - `uv run python scrape.py --retries 3 --retry-base 1.5 --retry-factor 2.0 --retry-max 20`

### 運用補助の例（レジューム/失敗CSV/追記）
- 既存の出力を読み込み既取得コードをスキップ（レジューム）
  - `uv run python scrape.py --resume`
- 失敗銘柄を別CSVに出力
  - `uv run python scrape.py --failures failures.csv`
- 既存の出力に追記（ヘッダ重複なし）
  - `uv run python scrape.py --append`
- 失敗CSVからの再実行（前回失敗分のみ）
  - `uv run python scrape.py --from-failures failures.csv --append`

### 主なオプション
- `--input`: 入力CSVパス（デフォルト: `codelist.csv`、UTF-8 BOM付、ヘッダ`code`必須）
- `--output`: 出力CSVパス（デフォルト: `result.csv`）
- `--sleep`: 取得間隔秒（デフォルト: 1.0）
- `--limit`: 上位N件のみ処理（0は全件）
- `--retries`: 一時的失敗時のリトライ回数（デフォルト: 0=無効）
- `--retry-base`: 指数バックオフの基準秒（デフォルト: 1.0）
- `--retry-factor`: バックオフ乗数（デフォルト: 1.6）
- `--retry-max`: 1回の最大待機秒（デフォルト: 15.0）
- `--jitter-frac`: 通常スリープに対する±割合ジッター（例: 0.3=±30%）
- `--failures`: 失敗銘柄CSVの出力パス（空文字で無効）
- `--resume`: 既存 `--output` から既取得コードを読み取りスキップ
- `--append`: 既存 `--output` に追記（無ければ新規作成しヘッダ出力）
- `--verbose`: 詳細ログを有効化（リトライの詳細など）
- `--from-failures`: 失敗CSV（`code` 列必須）から入力コードを読み込み、該当銘柄のみ再実行

## 入出力仕様
- 入力CSV: `codelist.csv`
  - 文字コード: UTF-8 with BOM（`utf-8-sig`で読込）
  - 列: `code`（4桁英数字。例: 1332, 130A, 9984）
- 出力CSV: `result.csv`
  - 文字コード: UTF-8 BOM付き（Excelで文字化けしない）
  - 列順: `code, company_name, market, feature, business_composition, industries, themes`
  - 空欄: ページに項目が無い場合や取得不可の場合は空文字

## 抽出ロジック要点（最新）
- company_name: 見出し（h1など）から取得
- market: ページ本文から「東証プライム/スタンダード/グロース」を正規表現抽出
- feature: 「特色」ラベルのdd/td/兄弟要素から取得
- business_composition: 「連結事業/単独事業」ラベルに対応し末尾の「セグメント収益」は除去
- industries（所属業界）
  - dd内のリンク群（`a/.tag/.chip/li/span`）を抽出。比較会社領域以降は除外
  - 除外: 「他」、数字を含む語、比較会社名、ラベル語（比較会社/市場テーマ）
  - 日本語優先（日本語を含む語があれば日本語のみ抽出）
  - テーマ語が混入していれば除外。ただし除外後にゼロ件となる場合は元を優先（例: 135Aは業界=AIを保持）
  - 要素が取れない場合はdd素テキストを分割抽出（同様のフィルタ）
  - 最大3件に制限、重複除去
- themes（市場テーマ）
  - dd内のリンク群を抽出 → 数字/比較会社/「他」を除外 → 重複除去
  - 取れない場合はdd素テキストから分割抽出 → さらに取れない場合は本文テキストの「市場テーマ 行」を正規表現抽出
  - 比較会社や数字混入の誤抽出を抑制

## ロギング/エラー耐性
- 進捗・警告は `stderr` に出力（CSVは`stdout`には出さない）
- タイムアウト・解析失敗はスキップして継続、終了時に完了メッセージ
- UAは一般的なChrome相当を使用（`scrape.py`内で設定）
- リトライ: タイムアウト/一時的例外は指数バックオフ＋フルジッターで再試行（`--retries`>0 のとき）
- 非リトライ対象: HTTP 404/410 は恒久的エラーとみなし再試行しない
- 失敗CSV: `--failures` を指定すると `code,reason` を追記
- レジューム: `--resume` で既存出力の `code` をスキップ、`--append` で追記運用

## よくあるトラブルと対処
- タイムアウト: `scrape.py`のタイムアウト延長、`--sleep` 増加、またはヘッドレスOFFで確認
- ブラウザ未インストール: `uv run --python 3.11 python -m playwright install chromium`
- 結果が空欄: セクション非掲示/リンク無し等の可能性（仕様）。dd素テキスト分割で補完済み
- デバッグ実行: `launch(headless=False)` に変更し挙動確認

## 運用ノート
- アクセス間隔は1.0秒以上（推奨例: 5.0秒）。サイト負荷に配慮して調整してください
- 再実行でCSVを上書きするため、必要に応じて加工/バックアップしてください
- 仕様変更に備え、抽出ロジックは定期的に見直し推奨

## 検証ハイライト（例）
- 130A: themes=創薬（比較会社は除外）
- 135A: industries=AI（テーマ=AIでも業界は維持）
- 138A: industries=外食（居酒）、themes=FC
- 1431: industries=戸建て,九州沖縄、themes=注文住宅（テーマ語は業界から除外）
