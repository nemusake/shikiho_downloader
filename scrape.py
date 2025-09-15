import csv
import re
import sys
import time
from typing import Dict, List, Optional

from playwright.sync_api import TimeoutError as PWTimeoutError, sync_playwright


TARGET_URL = "https://shikiho.toyokeizai.net/stocks/{code}"
MARKET_REGEX = re.compile(r"(東証(?:プライム|スタンダード|グロース))")


def read_codes(csv_path: str) -> List[str]:
    codes: List[str] = []
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if "code" not in reader.fieldnames:
            raise ValueError("codelist.csv に 'code' 列がありません")
        for row in reader:
            code = (row.get("code") or "").strip()
            if not code:
                continue
            codes.append(code)
    return codes


def normalize_text(s: Optional[str]) -> str:
    if not s:
        return ""
    # collapse whitespace and trim
    return re.sub(r"\s+", " ", s).strip()


def extract_fields(page) -> Dict[str, str]:
    # 企業名: 見出しから推定
    company_name = ""
    for sel in [
        "h1",
        "header h1",
        "main h1",
        "[class*=company] h1",
        "[class*=Company] h1",
    ]:
        try:
            if page.locator(sel).first.is_visible():
                company_name = normalize_text(page.locator(sel).first.inner_text())
                if company_name:
                    break
        except Exception:
            pass

    # 市場名: ページ全体テキストから抽出
    try:
        whole_text: str = page.evaluate("() => document.body ? document.body.innerText : ''")
    except Exception:
        whole_text = ""
    market_match = MARKET_REGEX.search(whole_text)
    market = market_match.group(1) if market_match else ""

    # ラベルに基づく値抽出（dt/dd, th/td, 兄弟要素などに対応）
    def find_by_labels(labels: List[str]) -> Dict[str, Optional[str]]:
        js_func = r"""
        (labels) => {
          function clean(t){return (t||'').replace(/\s+/g,' ').trim()}
          function pickItems(el){
            const items = Array.from(el.querySelectorAll('a')).map(a=>clean(a.innerText)).filter(Boolean);
            return items;
          }
          const candidates = Array.from(document.querySelectorAll('dt,th,div,span,p,li,strong,b'));
          for (const label of labels){
            const target = candidates.find(e => {
              if(!e || !e.innerText) return false;
              const t = clean(e.innerText).replace(/\s+/g,'');
              const L = label.replace(/\s+/g,'');
              return t.startsWith(L) || t === L;
            });
            if(!target) continue;
            let text = '';
            let items = [];
            if (target.tagName === 'DT'){
              const dd = target.nextElementSibling;
              if (dd && dd.tagName === 'DD'){
                text = clean(dd.innerText);
                items = pickItems(dd);
              }
            } else if (target.tagName === 'TH'){
              let td = target.nextElementSibling;
              if (!(td && td.tagName === 'TD') && target.parentElement){
                td = target.parentElement.querySelector('td');
              }
              if (td){
                text = clean(td.innerText);
                items = pickItems(td);
              }
            } else {
              const sib = target.nextElementSibling;
              if (sib){
                text = clean(sib.innerText);
                items = pickItems(sib);
              }
            }
            // 補助: 近傍コンテナからタグ・リンクを収集
            if ((!text || !text.trim()) && target){
              const container = target.closest('section,article,div,dl,table,ul,ol') || target.parentElement;
              if (container){
                const more = Array.from(container.querySelectorAll('a, .tag, li, span'))
                  .map(n => clean(n.innerText))
                  .filter(Boolean);
                if (more.length){
                  items = more;
                  text = more.join(' ');
                }
              }
            }
            return { text, items };
          }
          return { text: '', items: [] };
        }
        """
        try:
            res = page.evaluate(js_func, labels)
            return {"text": res.get("text") or "", "items": res.get("items") or []}
        except Exception:
            return {"text": "", "items": []}

    def dt_items(label: str, stop_text: Optional[str] = None) -> List[str]:
        js = r"""
        (label, stopText) => {
          function clean(t){return (t||'').replace(/\s+/g,' ').trim()}
          const dts = Array.from(document.querySelectorAll('dt'));
          const dt = dts.find(e => clean(e.innerText) === label);
          if(!dt) return [];
          const dd = dt.nextElementSibling;
          if(!dd || dd.tagName !== 'DD') return [];
          let items = [];
          const stopEl = stopText ? Array.from(dd.querySelectorAll('*')).find(n => clean(n.innerText).includes(stopText)) : null;
          const stopTop = stopEl ? stopEl.getBoundingClientRect().top : null;
          const anchors = Array.from(dd.querySelectorAll('a, .tag, .chip, li, span'));
          for (const n of anchors){
            if (stopTop !== null){
              const top = n.getBoundingClientRect().top;
              if (top >= stopTop) continue;
            }
            const t = clean(n.innerText);
            if (t) items.push(t);
          }
          return items;
        }
        """
        try:
            return page.evaluate(js, label, stop_text) or []
        except Exception:
            return []

    def dt_extract(label: str) -> Dict[str, str]:
        js = r"""
        (label) => {
          function clean(t){return (t||'').replace(/\s+/g,' ').trim()}
          const dts = Array.from(document.querySelectorAll('dt'));
          const dt = dts.find(e => clean(e.innerText) === label);
          if(!dt) return { text: '' };
          const dd = dt.nextElementSibling;
          if(!dd || dd.tagName !== 'DD') return { text: '' };
          return { text: clean(dd.innerText) };
        }
        """
        try:
            return page.evaluate(js, label) or {"text": ""}
        except Exception:
            return {"text": ""}

    feature = find_by_labels(["特色"]).get("text", "")
    business = find_by_labels(["連結事業", "単独事業", "連結(単独)事業", "連結・単独事業", "連結/単独事業"]).get("text", "")
    # 余計な尾部テキスト（例: セグメント収益）を削除
    if business:
        business = re.split(r"\s*セグメント収益", business)[0]

    industries_list = dt_items("所属業界", stop_text="比較会社")
    # 比較会社リストは除外対象
    comp_names = set(dt_items("比較会社"))
    if not comp_names:
        comp_res = find_by_labels(["比較会社"])
        comp_names = set([x for x in (comp_res.get("items", []) or []) if isinstance(x, str)])
        # テキストからも補完
        comp_text = normalize_text(comp_res.get("text", ""))
        if comp_text:
            for t in re.split(r"[、,\s]+", comp_text):
                if t:
                    comp_names.add(t)
    # フィルタ: 4桁数字や数字混在は除外、重複除去
    def filt(xs: List[str]) -> List[str]:
        # 一次フィルタ: 数字/不要語/比較会社の除外
        tmp: List[str] = []
        for x in xs:
            if not x:
                continue
            if x == "他":
                continue
            if re.search(r"\d", x):
                continue
            if x in ("比較会社", "市場テーマ"):
                continue
            if x in comp_names:
                continue
            tmp.append(x)

        # 日本語が含まれるトークンが一つでもあれば、日本語を含むもののみ採用
        jp_re = re.compile(r"[\u3040-\u30ff\u3400-\u9fff（）]")
        has_jp = any(jp_re.search(t) for t in tmp)
        cand = [t for t in tmp if (jp_re.search(t) is not None)] if has_jp else tmp

        # 重複除去の上、返却
        seen = set()
        out: List[str] = []
        for t in cand:
            if t not in seen:
                seen.add(t)
                out.append(t)
        return out
    industries_items = filt(industries_list)
    if not industries_items:
        industries_res = find_by_labels(["所属業界"])
        industries_items = filt(industries_res.get("items", []) or [])  # type: ignore
    if not industries_items:
        # dd素テキストから分割抽出のフォールバック
        ind_text = normalize_text(dt_extract("所属業界").get("text", ""))
        if ind_text:
            tokens = [t for t in re.split(r"[、,\s]+", ind_text) if t]
            # 過去に収集した比較会社・不要語・数字・テーマ語は除外（テーマ語は後段確定後にも再除外）
            tmp = []
            for t in tokens:
                if t == "他":
                    continue
                if re.search(r"\d", t):
                    continue
                if t in ("比較会社", "市場テーマ"):
                    continue
                if t in comp_names:
                    continue
                tmp.append(t)
            # 日本語優先の選別
            jp_re = re.compile(r"[\u3040-\u30ff\u3400-\u9fff（）]")
            has_jp = any(jp_re.search(x) for x in tmp)
            cand = [x for x in tmp if jp_re.search(x)] if has_jp else tmp
            # 重複除去して一旦候補に
            seen=set(); industries_items=[]
            for x in cand:
                if x not in seen:
                    seen.add(x); industries_items.append(x)
    # 比較会社名を除外（後でテーマ語も除外し、最後に文字列化する）
    industries_items = [x for x in industries_items if x not in comp_names]
    # 先頭の少数カテゴリに限定（ノイズ防止）
    if len(industries_items) > 3:
        industries_items = industries_items[:3]
    industries = ""  # finalize after themes filtering

    themes_list = dt_items("市場テーマ", stop_text="比較会社")
    # テーマは数字混入を除外し、比較会社系を排除
    def filt_theme(xs: List[str]) -> List[str]:
        seen = set(); out: List[str] = []
        for x in xs:
            if not x: continue
            if re.search(r"\d", x):
                continue
            if "比較会社" in x:
                continue
            if x not in seen:
                seen.add(x); out.append(x)
        return out
    filtered_theme_items = filt_theme(themes_list)
    # 比較会社名や汎用語『他』は除外
    filtered_theme_items = [t for t in filtered_theme_items if t not in comp_names and t != "他"]
    themes = ",".join(filtered_theme_items)
    if not themes:
        # ddの素のテキストから分割抽出（最も厳密）
        dd_text = normalize_text(dt_extract("市場テーマ").get("text", ""))
        if dd_text:
            parts = [t for t in re.split(r"[、,\s]+", dd_text) if t and not re.search(r"\d", t) and "比較会社" not in t]
            parts = [t for t in parts if t not in comp_names and t != "他"]
            themes = ",".join(dict.fromkeys(parts))
    if not themes:
        # 最後の手段: ラベル探索のテキストを使用し、同様に分割・フィルタ
        themes_res = find_by_labels(["市場テーマ", "テーマ"])  # 念のため「テーマ」も含める
        raw = normalize_text(themes_res.get("text", ""))
        if raw:
            raw = re.split(r"\s*比較会社", raw)[0]
            parts = [t for t in re.split(r"[、,\s]+", raw) if t and not re.search(r"\d", t)]
            parts = [t for t in parts if t not in comp_names and t != "他"]
            themes = ",".join(dict.fromkeys(parts))
    if not themes:
        # 本文テキストからの正規表現抽出（市場テーマ行限定）
        try:
            body_text: str = page.evaluate("() => document.body ? document.body.innerText : ''") or ""
        except Exception:
            body_text = ""
        m = re.search(r"市場テーマ\s*[:：]?\s*([^\n]+)", body_text)
        if m:
            raw = m.group(1)
            raw = re.split(r"\s*比較会社", raw)[0]
            parts = [t for t in re.split(r"[、,\s]+", raw) if t and not re.search(r"\d", t)]
            parts = [t for t in parts if t not in comp_names and t != "他"]
            if parts:
                themes = ",".join(dict.fromkeys(parts))
    # テーマ語が業界に混入している場合は除外（例: 注文住宅 など）
    theme_tokens = set([t.strip() for t in themes.split(',') if t.strip()]) if themes else set()
    if theme_tokens and industries_items:
        filtered_industries = [x for x in industries_items if x not in theme_tokens]
        # 業界が全消失する場合は削りすぎなので元を優先（例: 135A は業界=AIかつテーマ=AI）
        if filtered_industries:
            industries_items = filtered_industries
    # finalize industries string
    industries = ",".join(industries_items) if industries_items else normalize_text(locals().get('industries_text', ""))

    # 本文テキストからの安易な補完は誤抽出につながるため行わない

    return {
        "company_name": normalize_text(company_name),
        "market": normalize_text(market),
        "feature": normalize_text(feature),
        "business_composition": normalize_text(business),
        "industries": normalize_text(industries),
        "themes": normalize_text(themes),
    }


def scrape_one(page, code: str) -> Dict[str, str]:
    url = TARGET_URL.format(code=code)
    page.set_default_timeout(20000)
    page.set_default_navigation_timeout(20000)
    page.goto(url, wait_until="networkidle")

    # 既知のモーダル等があれば閉じる（失敗しても続行）
    for sel in ["#tpModal .pi_close", "button:has-text('同意')", "button:has-text('OK')", "[aria-label='close']"]:
        try:
            if page.locator(sel).first.is_visible():
                page.locator(sel).first.click()
                break
        except Exception:
            pass

    fields = extract_fields(page)
    fields.update({"code": code})
    return fields


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Shikiho Online scraper")
    parser.add_argument("--input", default="codelist.csv", help="input CSV path (with header 'code')")
    parser.add_argument("--output", default="result.csv", help="output CSV path")
    parser.add_argument("--sleep", type=float, default=1.0, help="sleep seconds between requests")
    parser.add_argument("--limit", type=int, default=0, help="limit number of codes (0=all)")
    args = parser.parse_args()

    try:
        codes = read_codes(args.input)
    except Exception as e:
        print(f"[ERROR] failed to read {args.input}: {e}", file=sys.stderr)
        sys.exit(1)

    if args.limit > 0:
        codes = codes[: args.limit]

    fieldnames = [
        "code",
        "company_name",
        "market",
        "feature",
        "business_composition",
        "industries",
        "themes",
    ]

    failures: List[str] = []

    # Excelなどでの文字化け回避のためUTF-8 BOM付きで出力
    with open(args.output, "w", encoding="utf-8-sig", newline="") as fo:
        writer = csv.DictWriter(fo, fieldnames=fieldnames)
        writer.writeheader()

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            page = context.new_page()

            for i, code in enumerate(codes, 1):
                print(f"[{i}/{len(codes)}] Fetching {code}...", file=sys.stderr)
                try:
                    record = scrape_one(page, code)
                    writer.writerow(record)
                except PWTimeoutError:
                    print(f"[WARN] timeout for code {code}", file=sys.stderr)
                    failures.append(code)
                except Exception as e:
                    print(f"[WARN] error for code {code}: {e}", file=sys.stderr)
                    failures.append(code)
                time.sleep(max(0.0, args.sleep))

            context.close()
            browser.close()

    if failures:
        print(f"[DONE] Completed with failures: {len(failures)} codes -> {', '.join(failures)}", file=sys.stderr)
    else:
        print("[DONE] Completed successfully", file=sys.stderr)


if __name__ == "__main__":
    main()
