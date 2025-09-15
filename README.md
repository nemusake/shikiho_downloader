# shikiho_downloader

四季報オンラインの銘柄ページ `https://shikiho.toyokeizai.net/stocks/{code}` から主要項目を取得して CSV に出力するスクリプトです。

- 取得項目: `code, company_name, market, feature, business_composition, industries, themes`
- レンダリング後DOMを Playwright(Chromium) で解析します
- 出力は Excel でも文字化けしにくい UTF-8 BOM 付き CSV

## セットアップ（初回）
- 依存/実行管理は uv を使用（AGENTS.md 準拠）
- Chromium のインストール（初回のみ）

```bash
uv run --python 3.11 python -m playwright install chromium
```

## 使い方（例）
- 1件だけ検証

```bash
uv run python scrape.py --limit 1
```

- 先頭2件（1.2秒スリープ）

```bash
uv run python scrape.py --limit 2 --sleep 1.2
```

- 全件（サイト負荷配慮の推奨例 5秒スリープ）

```bash
uv run python scrape.py --sleep 5.0
```

主なオプション
- `--input`: 入力CSV（既定: `codelist.csv`、UTF-8 BOM でヘッダ `code` 必須）
- `--output`: 出力CSV（既定: `result.csv`、UTF-8 BOM）
- `--sleep`: リクエスト間隔秒（既定: 1.0）
- `--limit`: 上位N件のみ処理（0は全件）

## 入出力
- 入力: `codelist.csv`（UTF-8 with BOM、列 `code`）
- 出力: `result.csv`（UTF-8 BOM、列順は取得項目の通り）

## トラブルシュート（要点）
- タイムアウトする: `--sleep` を増やす、Playwright のタイムアウトを延長、`launch(headless=False)` で確認
- ブラウザ未インストール: 初回セットアップコマンドを再実行
- 項目が空欄: ページ非掲示/非リンク等の表記差が原因のことがあります（スクリプト側でフォールバックあり）

## ドキュメント
- 詳細 README: `scrape_README.md`
- 使用手順書: `scrape_使用手順書.md`

## 注意事項
- アクセス間隔は1秒以上を推奨。サイト負荷やご利用規約に配慮してください
- 再実行で出力CSVは上書きされます。必要に応じてバックアップしてください

