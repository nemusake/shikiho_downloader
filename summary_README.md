# summary README

## 概要
- 入力CSV（`YYYYMMDD_result.csv`）の `business_composition` を解析し、以下の列を `themes` の右側に追加した `YYYYMMDD_summary.csv` を出力します。
  - `business1,business2,business3`
  - `business_sales1,business_sales2,business_sales3`
  - `business_profit1,business_profit2,business_profit3`
  - `overseas`

## 前提
- パッケージ管理: uv（AGENTS.md準拠）
- 依存: なし（標準ライブラリのみ）
- Python 3.9+（本プロジェクトは 3.9 で動作確認）

## 実行方法
- 例（2025/09/14の結果を集計）
  - `uv run python summary.py --input 20250914_result.csv`
  - 同ディレクトリに `20250914_summary.csv` が出力されます
- 出力先を明示する場合
  - `uv run python summary.py --input 20250914_result.csv --output custom_summary.csv`

## 解析仕様
- `business_composition` の例: `水産55(3)、生鮮22(5)、食品22(3)、物流サービス1(10)、他0(12)【海外】11 <25.3>`
  - 事業エントリ: `名称(日本語)+売上寄与度(整数)+利益率(括弧内の整数)`
  - 区切り: `、` または `,`
  - 「他」は除外
  - 海外売上比率: `【海外】11` の数値を抽出（存在しない場合は空欄）
  - 末尾の補足（例: `<25.3>`）は無視して解析
- 上位抽出
  - 売上寄与度の降順で最大3件（同点は元の並びを維持）
  - 欠損は空欄

## 出力仕様
- 文字コード: UTF-8（BOM付き、Excelでの文字化け回避）
- 列順: 既存列の `themes` の直後に上記追加列を挿入
- 数値列（sales/profit/overseas）は整数を文字列として格納（空欄は空文字）

