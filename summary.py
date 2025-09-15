import argparse
import csv
import os
import re
import sys
from typing import Dict, List, Tuple


BUSINESS_RE = re.compile(r"^\s*([^\d]+?)(\d+)\((\d+)\)\s*$")
OVERSEAS_RE = re.compile(r"【海外】(\d+)")


def parse_business_composition(text: str) -> Tuple[List[Tuple[str, int, int]], int]:
    if not text:
        return [], 0

    # Remove angle-bracketed tail like "<25.3>" if present
    cleaned = re.split(r"<", text, maxsplit=1)[0]

    # Extract overseas ratio
    overseas = 0
    m = OVERSEAS_RE.search(cleaned)
    if m:
        overseas = int(m.group(1))
        cleaned = OVERSEAS_RE.sub("", cleaned)

    # Split by Japanese/ASCII commas
    parts = re.split(r"[、,]", cleaned)
    items: List[Tuple[str, int, int]] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        m2 = BUSINESS_RE.match(p)
        if not m2:
            continue
        name = m2.group(1).strip()
        if name == "他":
            continue
        try:
            sales = int(m2.group(2))
            profit = int(m2.group(3))
        except ValueError:
            continue
        items.append((name, sales, profit))

    # Sort by sales descending, stable for ties
    items.sort(key=lambda t: t[1], reverse=True)
    return items, overseas


def derive_output_path(input_path: str) -> str:
    base = os.path.basename(input_path)
    m = re.match(r"(\d{8})_result\.csv$", base)
    if m:
        ymd = m.group(1)
        return os.path.join(os.path.dirname(input_path), f"{ymd}_summary.csv")
    # Fallbacks for non-standard names
    if base.endswith("_result.csv"):
        out = base[:-11] + "_summary.csv"
        return os.path.join(os.path.dirname(input_path), out)
    # Last resort: append _summary
    root, _ = os.path.splitext(input_path)
    sys.stderr.write(
        f"[WARN] input filename does not match 'YYYYMMDD_result.csv'; writing {root}_summary.csv\n"
    )
    return f"{root}_summary.csv"


def main():
    parser = argparse.ArgumentParser(description="Expand business_composition columns and write *_summary.csv")
    parser.add_argument("--input", required=True, help="input CSV path (e.g., 20250914_result.csv)")
    parser.add_argument(
        "--output",
        default="",
        help="optional explicit output path; defaults to derived YYYYMMDD_summary.csv",
    )
    args = parser.parse_args()

    input_path = args.input
    output_path = args.output or derive_output_path(input_path)

    # Columns to append (after 'themes')
    extra_cols = [
        "business1",
        "business2",
        "business3",
        "business_sales1",
        "business_sales2",
        "business_sales3",
        "business_profit1",
        "business_profit2",
        "business_profit3",
        "overseas",
    ]

    try:
        with open(input_path, "r", encoding="utf-8-sig", newline="") as fi:
            reader = csv.DictReader(fi)
            fieldnames_in = reader.fieldnames or []
            required = [
                "code",
                "company_name",
                "market",
                "feature",
                "business_composition",
                "industries",
                "themes",
            ]
            for col in required:
                if col not in fieldnames_in:
                    raise ValueError(f"missing required column: {col}")

            # Build output fieldnames: insert extra cols right after 'themes'
            out_fields: List[str] = []
            for name in fieldnames_in:
                out_fields.append(name)
                if name == "themes":
                    out_fields.extend(extra_cols)

            with open(output_path, "w", encoding="utf-8-sig", newline="") as fo:
                writer = csv.DictWriter(fo, fieldnames=out_fields, extrasaction="ignore")
                writer.writeheader()

                for row in reader:
                    text = (row.get("business_composition") or "").strip()
                    items, overseas = parse_business_composition(text)
                    # Top 3
                    top = items[:3]
                    # Prepare extra values
                    extras: Dict[str, str] = {}
                    for idx in range(3):
                        name = sales = profit = ""
                        if idx < len(top):
                            bname, bsales, bprofit = top[idx]
                            name = bname
                            sales = str(bsales)
                            bprofit_s = str(bprofit)
                            profit = bprofit_s
                        extras[f"business{idx+1}"] = name
                        extras[f"business_sales{idx+1}"] = sales
                        extras[f"business_profit{idx+1}"] = profit
                    extras["overseas"] = str(overseas) if overseas else ""

                    out = dict(row)
                    out.update(extras)
                    writer.writerow(out)

        sys.stderr.write(f"[DONE] wrote {output_path}\n")
    except Exception as e:
        sys.stderr.write(f"[ERROR] {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()

