# サマリー生成 使用手順書

本手順書は、`YYYYMMDD_result.csv` を入力として `YYYYMMDD_summary.csv` を生成する `summary.py` の使い方を示します。

## 1. 前提
- 管理: uv（Python実行・依存管理）
- 依存: なし（標準ライブラリのみ）
- Python 3.9+（本プロジェクトは 3.9 で動作確認）

## 2. 入力ファイル
- 形式: `YYYYMMDD_result.csv`（例: `20250914_result.csv`）
- 文字コード: UTF-8（BOM付き）
- 必須列: `code, company_name, market, feature, business_composition, industries, themes`

## 3. 出力ファイル
- 自動命名: 入力名の `YYYYMMDD_result.csv` に対応して `YYYYMMDD_summary.csv` を同じフォルダに生成
- 文字コード: UTF-8（BOM付き）
- 列: 既存列＋以下を `themes` の右側に追加
  - `business1,business2,business3`
  - `business_sales1,business_sales2,business_sales3`
  - `business_profit1,business_profit2,business_profit3`
  - `overseas`

## 4. 実行方法
- 基本
  - `uv run python summary.py --input 20250914_result.csv`
- 出力先を指定
  - `uv run python summary.py --input 20250914_result.csv --output ./out/summary.csv`

## 5. 解析仕様（要点）
- 事業エントリ: `名称+売上寄与度(整数)+利益率(整数)` の形式（例: `水産55(3)`）
- 区切り: `、` または `,`
- 「他」は除外
- 海外売上比率: `【海外】n` の `n` を整数で取得（無い場合は空欄）
- 末尾補足（例: `<25.3>`）は無視
- 上位抽出: 売上寄与度の降順で最大3件（同率は元順）

## 6. 例
入力（抜粋）
```
code,company_name,market,feature,business_composition,industries,themes
1301,極洋,東証プライム,...,水産55(3)、生鮮22(5)、食品22(3)、物流サービス1(10)、他0(12)【海外】11 <25.3>,...,水産
```
出力（抜粋）
```
...,themes,business1,business2,business3,business_sales1,business_sales2,business_sales3,business_profit1,business_profit2,business_profit3,overseas
...,水産,水産,生鮮,食品,55,22,22,3,5,3,11
```

## 7. トラブルシュート
- 必須列が無い: 入力CSVのヘッダを確認（`business_composition` 等）
- 出力ファイルが生成されない: 権限/パスを確認（`--output` で明示も可）
- 解析できないトークンが混在: 当該トークンはスキップ（WARN表示なし、必要があれば強化可能）

