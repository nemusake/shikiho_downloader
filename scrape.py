import csv
import os
import random
import re
import sys
import time
from typing import Dict, List, Optional

from playwright.sync_api import TimeoutError as PWTimeoutError, sync_playwright


TARGET_URL = "https://shikiho.toyokeizai.net/stocks/{code}"
MARKET_REGEX = re.compile(r"(東証(?:プライム|スタンダード|グロース))")


class NonRetryableError(Exception):
    pass


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


def extract_fields(page, max_industries: int = 3) -> Dict[str, str]:
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
    if max_industries is not None and max_industries > 0 and len(industries_items) > max_industries:
        industries_items = industries_items[:max_industries]
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


def scrape_one(page, code: str, max_industries: int = 3) -> Dict[str, str]:
    url = TARGET_URL.format(code=code)
    resp = page.goto(url, wait_until="networkidle")
    try:
        status = resp.status if resp else None
    except Exception:
        status = None
    # 404/410 は恒久的エラーとみなしリトライしない
    if status in (404, 410):
        raise NonRetryableError(f"HTTP {status} for code {code}")

    # 既知のモーダル等があれば閉じる（失敗しても続行）
    for sel in ["#tpModal .pi_close", "button:has-text('同意')", "button:has-text('OK')", "[aria-label='close']"]:
        try:
            if page.locator(sel).first.is_visible():
                page.locator(sel).first.click()
                break
        except Exception:
            pass

    fields = extract_fields(page, max_industries=max_industries)
    fields.update({"code": code})
    return fields


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Shikiho Online scraper")
    parser.add_argument("--input", default="codelist.csv", help="input CSV path (with header 'code')")
    parser.add_argument("--output", default="result.csv", help="output CSV path")
    parser.add_argument("--sleep", type=float, default=1.0, help="sleep seconds between requests")
    parser.add_argument("--limit", type=int, default=0, help="limit number of codes (0=all)")
    parser.add_argument(
        "--max-industries", type=int, default=3, help="maximum number of industries to keep (0=unlimited)"
    )
    parser.add_argument(
        "--fields",
        default="code,company_name,market,feature,business_composition,industries,themes",
        help="comma-separated output fields (default: all)",
    )
    # Timeouts and UA
    parser.add_argument("--timeout", type=int, default=20000, help="default action timeout in milliseconds")
    parser.add_argument("--nav-timeout", type=int, default=20000, help="navigation timeout in milliseconds")
    parser.add_argument(
        "--user-agent",
        default=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        help="custom User-Agent string",
    )
    # Retry/jitter options (defaults keep current behavior: disabled)
    parser.add_argument("--retries", type=int, default=0, help="number of retries on transient failures")
    parser.add_argument(
        "--retry-base", type=float, default=1.0, help="base seconds for exponential backoff"
    )
    parser.add_argument(
        "--retry-factor", type=float, default=1.6, help="multiplicative factor for backoff"
    )
    parser.add_argument(
        "--retry-max", type=float, default=15.0, help="maximum backoff per attempt (seconds)"
    )
    parser.add_argument(
        "--jitter-frac", type=float, default=0.0, help="fractional jitter for --sleep (e.g., 0.3 => ±30%)"
    )
    # Failure tracking and resume/append
    parser.add_argument("--failures", default="", help="path to write failed codes CSV (code,reason). empty=disable")
    parser.add_argument("--resume", action="store_true", help="skip codes already present in --output")
    parser.add_argument("--append", action="store_true", help="append to --output if it exists (no header)")
    parser.add_argument("--verbose", action="store_true", help="enable more verbose logs")
    parser.add_argument(
        "--from-failures",
        default="",
        help="read input codes from a failures CSV (uses 'code' column) instead of --input",
    )
    # Browser mode
    parser.add_argument("--headed", dest="headless", action="store_false", help="run with browser UI (non-headless)")
    parser.add_argument("--headless", dest="headless", action="store_true", help="run headless (default)")
    parser.set_defaults(headless=True)
    args = parser.parse_args()

    try:
        if args.from_failures:
            # Read codes from failures CSV (expects a 'code' header; ignores 'reason')
            codes: List[str] = []
            with open(args.from_failures, "r", encoding="utf-8-sig", newline="") as f:
                r = csv.DictReader(f)
                if not r.fieldnames or "code" not in r.fieldnames:
                    raise ValueError("failures CSV must have a 'code' header")
                seen = set()
                for row in r:
                    c = (row.get("code") or "").strip()
                    if not c or c in seen:
                        continue
                    seen.add(c)
                    codes.append(c)
            if args.verbose:
                print(f"[INFO] loaded {len(codes)} codes from failures: {args.from_failures}", file=sys.stderr)
        else:
            codes = read_codes(args.input)
    except Exception as e:
        src = args.from_failures or args.input
        print(f"[ERROR] failed to read {src}: {e}", file=sys.stderr)
        sys.exit(1)

    if args.limit > 0:
        codes = codes[: args.limit]

    default_fields = [
        "code",
        "company_name",
        "market",
        "feature",
        "business_composition",
        "industries",
        "themes",
    ]
    # Build fieldnames from --fields
    raw_fields = [f.strip() for f in args.fields.split(",") if f.strip()]
    allowed = set(default_fields)
    fieldnames = [f for f in raw_fields if f in allowed] or default_fields
    if "code" not in fieldnames:
        fieldnames.insert(0, "code")

    failures: List[str] = []
    processed: List[str] = []
    skipped_count = 0
    success_count = 0

    # Resume support: load already processed codes from existing output
    if args.resume and os.path.exists(args.output):
        try:
            with open(args.output, "r", encoding="utf-8-sig", newline="") as fr:
                r = csv.DictReader(fr)
                if "code" in (r.fieldnames or []):
                    for row in r:
                        c = (row.get("code") or "").strip()
                        if c:
                            processed.append(c)
            if args.verbose:
                print(f"[INFO] resume enabled: {len(processed)} codes already processed", file=sys.stderr)
        except Exception as e:
            print(f"[WARN] failed to read existing output for resume: {e}", file=sys.stderr)

    # Configure output writer (append or write)
    out_exists = os.path.exists(args.output)
    out_mode = "a" if (args.append and out_exists) else "w"
    # Excelなどでの文字化け回避のためUTF-8 BOM付きで出力
    with open(args.output, out_mode, encoding="utf-8-sig", newline="") as fo:
        writer = csv.DictWriter(fo, fieldnames=fieldnames, extrasaction="ignore")
        if out_mode == "w":
            writer.writeheader()

        # Failures CSV writer (optional)
        fail_writer = None
        fail_fp = None
        if args.failures:
            try:
                fail_exists = os.path.exists(args.failures)
                fail_mode = "a" if fail_exists else "w"
                fail_fp = open(args.failures, fail_mode, encoding="utf-8-sig", newline="")
                fail_writer = csv.DictWriter(fail_fp, fieldnames=["code", "reason"])
                if fail_mode == "w":
                    fail_writer.writeheader()
            except Exception as e:
                print(f"[WARN] cannot open failures CSV '{args.failures}': {e}", file=sys.stderr)

        start_ts = time.time()
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=args.headless)
            context = browser.new_context(user_agent=args.user_agent)
            page = context.new_page()
            # apply timeouts once per page
            try:
                page.set_default_timeout(args.timeout)
                page.set_default_navigation_timeout(args.nav_timeout)
            except Exception:
                pass

            for i, code in enumerate(codes, 1):
                if args.resume and code in processed:
                    if args.verbose:
                        print(f"[{i}/{len(codes)}] Skip {code} (resume)", file=sys.stderr)
                    skipped_count += 1
                    continue
                print(f"[{i}/{len(codes)}] Fetching {code}...", file=sys.stderr)
                attempt = 0
                while True:
                    try:
                        record = scrape_one(page, code, max_industries=args.max_industries if args.max_industries > 0 else 999999)
                        writer.writerow(record)
                        success_count += 1
                        break
                    except NonRetryableError as e:
                        print(f"[WARN] non-retryable for {code}: {e}", file=sys.stderr)
                        failures.append(code)
                        if fail_writer:
                            try:
                                fail_writer.writerow({"code": code, "reason": str(e)})
                            except Exception:
                                pass
                        break
                    except PWTimeoutError:
                        if attempt < args.retries:
                            # exponential backoff with full jitter
                            base = args.retry_base * (args.retry_factor ** attempt)
                            wait = min(args.retry_max, base)
                            jitter = random.uniform(0.0, wait)
                            msg = f"[RETRY] timeout for {code}, attempt {attempt+1}/{args.retries}, wait {jitter:.2f}s"
                            if args.verbose:
                                print(msg, file=sys.stderr)
                            time.sleep(jitter)
                            attempt += 1
                            continue
                        print(f"[WARN] timeout for code {code}", file=sys.stderr)
                        failures.append(code)
                        if fail_writer:
                            try:
                                fail_writer.writerow({"code": code, "reason": "timeout"})
                            except Exception:
                                pass
                        break
                    except Exception as e:
                        if attempt < args.retries:
                            base = args.retry_base * (args.retry_factor ** attempt)
                            wait = min(args.retry_max, base)
                            jitter = random.uniform(0.0, wait)
                            if args.verbose:
                                print(
                                    f"[RETRY] error for {code}: {e}, attempt {attempt+1}/{args.retries}, wait {jitter:.2f}s",
                                    file=sys.stderr,
                                )
                            time.sleep(jitter)
                            attempt += 1
                            continue
                        print(f"[WARN] error for code {code}: {e}", file=sys.stderr)
                        failures.append(code)
                        if fail_writer:
                            try:
                                fail_writer.writerow({"code": code, "reason": str(e)})
                            except Exception:
                                pass
                        break

                # baseline sleep with optional jitter
                if args.jitter_frac > 0:
                    jf = max(0.0, args.jitter_frac)
                    delta = args.sleep * random.uniform(-jf, jf)
                    time.sleep(max(0.0, args.sleep + delta))
                else:
                    time.sleep(max(0.0, args.sleep))

            context.close()
            browser.close()

        if fail_fp:
            try:
                fail_fp.close()
            except Exception:
                pass

    if failures:
        if len(failures) <= 20:
            detail = ", ".join(failures)
            print(f"[DONE] Completed with failures: {len(failures)} codes -> {detail}", file=sys.stderr)
        else:
            print(f"[DONE] Completed with failures: {len(failures)} codes", file=sys.stderr)
        if args.failures:
            print(f"[INFO] failure list written to: {args.failures}", file=sys.stderr)
    else:
        print("[DONE] Completed successfully", file=sys.stderr)

    # Final summary line (last line)
    elapsed = time.time() - start_ts
    h = int(elapsed // 3600)
    m = int((elapsed % 3600) // 60)
    s = int(elapsed % 60)
    total = len(codes)
    print(
        f"[SUMMARY] success={success_count}, failure={len(failures)}, skipped={skipped_count}, total={total}, elapsed={h:02d}:{m:02d}:{s:02d}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
