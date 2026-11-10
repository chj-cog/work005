"""Step 3: re-open every generated file and verify it independently.

Usage:  .venv\\Scripts\\python.exe src\\verify.py
Writes outputs/ocr/verification_report.json; exit code 1 if any check fails.
"""
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "ocr"
results = []


def check(name, ok, detail=""):
    results.append({"check": name, "pass": bool(ok), "detail": detail})
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


def num(s):
    return int(s) if s not in ("", None) else None


manifest = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))

# 1. input untouched
h = hashlib.sha256((ROOT / manifest["input"]["path"]).read_bytes()).hexdigest()
check("input sha256 unchanged", h == manifest["input"]["sha256"], h[:16])
copy = OUT / manifest["input"]["copy_in_outputs"]
check("input copy in outputs/ocr is byte-identical",
      copy.is_file() and hashlib.sha256(copy.read_bytes()).hexdigest() == h, copy.name)
src = manifest.get("source", {})
check("manifest records source URL, pages, license, run location",
      all(src.get(k) for k in ("url", "pdf_page", "printed_page", "license")) and manifest.get("run_location"),
      f"pdf p.{src.get('pdf_page')} / printed p.{src.get('printed_page')}")

# 2. every file listed in manifest exists and is non-empty
missing = [p for p in manifest["outputs"] if not (OUT / p).is_file() or (OUT / p).stat().st_size == 0]
check("manifest outputs exist & non-empty", not missing, ", ".join(missing))

# 3. JSON / images open
raw = json.loads((OUT / "raw" / "ocr" / "census-table_res.json").read_text(encoding="utf-8"))
lines = json.loads((OUT / "ocr_lines.json").read_text(encoding="utf-8"))["lines"]
check("raw OCR JSON has texts/scores/polys of equal length",
      len(raw["rec_texts"]) == len(raw["rec_scores"]) == len(raw["rec_polys"]) == len(lines) > 0,
      f"{len(lines)} lines")
for img in ("ocr_visualization.png", "raw/ocr/census-table_ocr_res_img.png"):
    with Image.open(OUT / img) as im:
        im.verify()
    check(f"image opens: {img}", True)

# 4. table.csv re-read
with open(OUT / "table.csv", encoding="utf-8-sig", newline="") as fh:
    rows = list(csv.DictReader(fh))
check("table.csv rows == 11", len(rows) == 11, str(len(rows)))
area = {r["row_id"]: num(r["area_sq_mi"]) for r in rows}
pop = {r["row_id"]: num(r["population_1910"]) for r in rows}
comps = [r["row_id"] for r in rows if r["parent_row_id"] == "3"]
check("CSV: area components sum == Outlying", sum(area[i] or 0 for i in comps) == area["3"])
check("CSV: population components sum == Outlying", sum(pop[i] or 0 for i in comps) == pop["3"])
check("CSV: area total == excl + outlying", area["1"] == area["2"] + area["3"])
check("CSV: population total == excl + outlying", pop["1"] == pop["2"] + pop["3"])
raw_kept = all(r["population_raw"] for r in rows) and all(r["label_raw"] for r in rows)
check("CSV keeps raw OCR text alongside corrected values", raw_kept)
need = [r["label"] for r in rows if "확인 필요" in (r["area_status"], r["population_status"])]
check("CSV '확인 필요' cells listed", True, f"{len(need)}: {need}")

# 5. compare with manual visual transcription of the original image
with open(ROOT / "src" / "reference_manual.csv", encoding="utf-8") as fh:
    ref = list(csv.DictReader(fh))
mism = []
for a, b in zip(rows, ref):
    for k_out, k_ref in (("label", "label"), ("area_sq_mi", "area_sq_mi"),
                         ("population_1910", "population_1910"), ("population_footnote", "population_footnote")):
        if a[k_out] != b[k_ref]:
            mism.append(f"row {a['row_id']} {k_out}: out={a[k_out]!r} ref={b[k_ref]!r}")
check("cell-by-cell match with manual reference", not mism and len(rows) == len(ref), "; ".join(mism))

# 6. raw OCR accuracy (before correction) vs reference — honest error rate
raw_err = [f"{r['label']}: raw {r['population_raw']!r}" for r, b in zip(rows, ref)
           if r["population_raw"] and int(r["population_raw"].replace(",", "").replace(" ", "")) != int(b["population_1910"])]
raw_err += [f"{r['label']}: raw {r['area_raw']!r}" for r, b in zip(rows, ref)
            if r["area_raw"] and int(r["area_raw"].replace(",", "").replace(" ", "")) != int(b["area_sq_mi"])]
n_numeric = sum(1 for b in ref for k in ("area_sq_mi", "population_1910") if b[k])
check("raw OCR numeric errors recorded (informational)", True, f"{len(raw_err)}/{n_numeric} wrong before correction: {raw_err}")

# 7. review log covers every corrected value
with open(OUT / "review_log.csv", encoding="utf-8-sig", newline="") as fh:
    log = list(csv.DictReader(fh))
corrected = {(r["row_id"], "population") for r in rows if r["population_status"] == "수정"}
logged = {(e["row_id"], e["column"]) for e in log if e["action"] == "각주 위첨자 분리"}
check("every '수정' cell has a review_log entry", corrected == logged and corrected, str(sorted(corrected)))

# 8. document.md re-read: table has 11 body rows and same numbers as CSV
md = (OUT / "document.md").read_text(encoding="utf-8")
md_rows = [l for l in md.splitlines() if l.startswith("|")]
first = md_rows.index(next(l for l in md_rows if l.startswith("|---")))
body = []
for l in md_rows[first + 1:]:
    if l.startswith("|---") or l.startswith("| 검사"):
        break
    body.append(l)
md_nums = [int(x.replace(",", "")) for l in body for x in re.findall(r"(?<![\w<])\d[\d,]*(?=<sup>|\s*\|)", l)]
csv_nums = [v for r in rows for v in (num(r["area_sq_mi"]), num(r["population_1910"])) if v is not None]
check("document.md table rows == 11", len(body) == 11, str(len(body)))
check("document.md numbers == table.csv numbers", md_nums == csv_nums, f"{len(md_nums)} vs {len(csv_nums)}")
check("document.md has footnotes", "1. Population in 1903." in md and "2. Population in 1912." in md)

ok = all(r["pass"] for r in results)
(OUT / "verification_report.json").write_text(
    json.dumps({"all_passed": ok, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
print("ALL PASSED" if ok else "SOME CHECKS FAILED")
sys.exit(0 if ok else 1)
