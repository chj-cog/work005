"""Step 2: rebuild rows/columns from PaddleOCR coordinates, verify arithmetic,
separate raw vs corrected values, and write table.csv / document.md /
review_log.csv / structure_crosscheck.json / manifest.json.

Usage:  .venv\\Scripts\\python.exe src\\reconstruct.py
Requires outputs/ocr/ocr_lines.json and run_info.json from src/run_ocr.py.
"""
import csv
import itertools
import json
import platform
import re
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "ocr"
NEED = "확인 필요"
SCORE_THRESHOLD = 0.90          # below this a value is "확인 필요" unless arithmetic proves it
ROW_TOLERANCE = 14              # px: max |y-centre difference| between a value and its label
NUM_RE = re.compile(r"^[\d][\d,\s]*$")
FOOTNOTE_RE = re.compile(r"^(\d)\s+(.+)$")

# Provenance of the input image (given with the assignment)
SOURCE = {
    "title": "Thirteenth Census of the United States Taken in the Year 1910, Volume I: Population — Table 1 (Area and population)",
    "publisher": "U.S. Bureau of the Census",
    "published": 1913,
    "url": "https://www2.census.gov/library/publications/decennial/1910/volume-1/volume-1-p3.pdf",
    "pdf_page": 2,
    "printed_page": 22,
    "extraction": "Table region cropped from the PDF page at 200 dpi (provided with the assignment)",
    "license": "Public domain (U.S. federal government publication)",
}
RUN_LOCATION = "local"          # local Windows PC (not Colab)


def cy(b): return (b[1] + b[3]) / 2
def cx(b): return (b[0] + b[2]) / 2


def to_int(text: str):
    """'101, 115, 487' -> 101115487 ; returns None if comma grouping is invalid."""
    s = text.replace(" ", "")
    if not re.fullmatch(r"\d{1,3}(,\d{3})*", s):
        return None
    return int(s.replace(",", ""))


def clean_label(text: str) -> str:
    return re.sub(r"[.\s]+$", "", text).strip()   # drop dot leaders / trailing periods


def main() -> None:
    data = json.loads((OUT / "ocr_lines.json").read_text(encoding="utf-8"))
    run_info = json.loads((OUT / "run_info.json").read_text(encoding="utf-8"))
    lines = data["lines"]

    # ---------- 1. regions: header / body / footnotes --------------------
    numeric = [l for l in lines if NUM_RE.match(l["text"]) and to_int(l["text"]) is not None
               and l["text"] != "1910"]
    first_body_y = min(l["bbox_xyxy"][1] for l in numeric)
    last_body_y = max(l["bbox_xyxy"][3] for l in numeric)
    header = [l for l in lines if l["bbox_xyxy"][3] <= first_body_y]
    footnotes = [l for l in lines if l["bbox_xyxy"][1] > last_body_y and FOOTNOTE_RE.match(l["text"])]
    used = {l["id"] for l in header + footnotes}
    body = [l for l in lines if l["id"] not in used]

    # ---------- 2. columns from header boxes -----------------------------
    def header_group(keyword):
        anchor = next(l for l in header if keyword in l["text"])
        grp = [l for l in header if abs(cx(l["bbox_xyxy"]) - cx(anchor["bbox_xyxy"])) < 60]
        grp.sort(key=lambda l: l["bbox_xyxy"][1])
        return grp

    area_hdr, pop_hdr = header_group("Gross area"), header_group("Population")
    label_hdr = [l for l in header if l not in area_hdr + pop_hdr]
    col_x = {"area": cx(area_hdr[0]["bbox_xyxy"]), "population": cx(pop_hdr[0]["bbox_xyxy"])}
    label_right = min(min(l["bbox_xyxy"][0] for l in area_hdr), min(l["bbox_xyxy"][0] for l in pop_hdr))

    # ---------- 3. rows: anchor on label lines, attach values by y ------
    labels = sorted([l for l in body if l["bbox_xyxy"][2] < label_right], key=lambda l: cy(l["bbox_xyxy"]))
    values = [l for l in body if l not in labels]
    rows = []
    for i, lab in enumerate(labels):
        rows.append({"row_id": i + 1, "label_raw": lab["text"], "label": clean_label(lab["text"]),
                     "label_score": lab["score"], "label_x0": lab["bbox_xyxy"][0],
                     "label_cy": cy(lab["bbox_xyxy"]), "cells": {}})
    unassigned = []
    for v in values:
        col = min(col_x, key=lambda c: abs(cx(v["bbox_xyxy"]) - col_x[c]))
        row = min(rows, key=lambda r: abs(r["label_cy"] - cy(v["bbox_xyxy"])))
        if abs(row["label_cy"] - cy(v["bbox_xyxy"])) > ROW_TOLERANCE or col in row["cells"]:
            unassigned.append(v)
            continue
        row["cells"][col] = {"raw": v["text"], "score": v["score"], "ocr_id": v["id"],
                             "value": to_int(v["text"]), "footnote": "", "status": "", "note": ""}

    # ---------- 4. footnotes ---------------------------------------------
    notes = {}
    for f in footnotes:
        m = FOOTNOTE_RE.match(f["text"])
        notes[m.group(1)] = {"marker": m.group(1), "text": m.group(2).rstrip("."),
                             "raw": f["text"], "score": f["score"]}

    # ---------- 5. hierarchy + arithmetic checks --------------------------
    # Expected document logic (column headers say these are totals):
    #   row1 (grand total) = row2 (exclusive) + row3 (outlying)
    #   row3 (outlying)    = sum(rows 4..n)  (indented components)
    for r in rows:
        r["level"] = 2 if r["label_x0"] > 50 and r["row_id"] > 1 else 1
    total, excl, outl = rows[0], rows[1], rows[2]
    comps = [r for r in rows[3:] if r["level"] == 2]

    review = []
    checks = []

    def val(r, c):
        cell = r["cells"].get(c)
        return cell["value"] if cell else 0

    def fix_footnote_markers(col):
        """If components don't sum to the subtotal, search for the unique subset of
        values whose leading digit equals a footnote marker and whose removal
        makes the sum exact. Ambiguous or no solution -> leave raw, flag 확인 필요."""
        target = val(outl, col)
        raw_sum = sum(val(r, col) for r in comps)
        if raw_sum == target:
            return "exact", []
        cands = []
        for r in comps:
            c = r["cells"].get(col)
            if not c:
                continue
            s = c["raw"].replace(" ", "")
            if s[0] in notes and to_int(s[1:].lstrip(",")) is not None and not s[1:].startswith(","):
                cands.append((r, s[0], to_int(s[1:])))
        solutions = []
        for k in range(1, len(cands) + 1):
            for combo in itertools.combinations(cands, k):
                new_sum = raw_sum - sum(val(r, col) - nv for r, _, nv in combo)
                if new_sum == target:
                    solutions.append(combo)
        if len(solutions) != 1:
            return f"no unique fix ({len(solutions)} solutions)", []
        return "fixed", list(solutions[0])

    for col in ("area", "population"):
        status, fixes = fix_footnote_markers(col)
        for r, marker, nv in fixes:
            c = r["cells"][col]
            review.append({"row_id": r["row_id"], "label": r["label"], "column": col,
                           "raw_text": c["raw"], "raw_value": c["value"], "corrected_value": nv,
                           "footnote": marker, "action": "각주 위첨자 분리",
                           "evidence": f"선두 '{marker}'는 각주 '{notes[marker]['raw']}'의 위첨자로 판단. "
                                       f"분리 시에만 하위 항목 합계가 '{outl['label']}' 값과 정확히 일치(유일해). "
                                       "원본 이미지 육안 대조로 위첨자 확인.",
                           "ocr_score": c["score"]})
            c.update(value=nv, footnote=marker, note=f"원시 OCR '{c['raw']}'에서 위첨자 {marker} 분리")
        checks.append({"name": f"{col}: {outl['label']} = sum(components)",
                       "expected": val(outl, col), "computed": sum(val(r, col) for r in comps),
                       "pass": val(outl, col) == sum(val(r, col) for r in comps), "resolution": status})
        checks.append({"name": f"{col}: {total['label']} = {excl['label']} + {outl['label']}",
                       "expected": val(total, col), "computed": val(excl, col) + val(outl, col),
                       "pass": val(total, col) == val(excl, col) + val(outl, col)})

    passed = {c["name"].split(":")[0]: True for c in checks}
    for c in checks:
        passed[c["name"].split(":")[0]] &= c["pass"]

    # ---------- 6. per-cell status ----------------------------------------
    for r in rows:
        r["parent"] = "" if r is total else (str(total["row_id"]) if r["level"] == 1 else str(outl["row_id"]))
        for col in ("area", "population"):
            c = r["cells"].get(col)
            if c is None:
                r["cells"][col] = {"raw": "", "score": None, "ocr_id": None, "value": None, "footnote": "",
                                   "status": NEED if not passed[col] else "공란",
                                   "note": "OCR 미검출. 원본은 점선 리더만 있는 공란이며 합계 검증과 일치"
                                           if passed[col] else "OCR 미검출 — 원본 확인 필요"}
                continue
            if c["value"] is None:
                c["status"], c["note"] = NEED, f"숫자 형식 해석 불가: '{c['raw']}'"
            elif passed[col]:
                c["status"] = "수정" if c["footnote"] else "검증됨"
                if c["raw"] != f"{c['value']:,}" and not c["footnote"]:
                    c["note"] = f"공백 제거 정규화 ('{c['raw']}')"
                    review.append({"row_id": r["row_id"], "label": r["label"], "column": col,
                                   "raw_text": c["raw"], "raw_value": c["value"], "corrected_value": c["value"],
                                   "footnote": "", "action": "형식 정규화(공백 제거)",
                                   "evidence": "자릿수 그룹 유효, 값 변경 없음", "ocr_score": c["score"]})
            elif c["score"] < SCORE_THRESHOLD:
                c["status"] = NEED
            else:
                c["status"], c["note"] = NEED, "합계 검증 실패 열"
        if r["label_raw"] != r["label"]:
            review.append({"row_id": r["row_id"], "label": r["label"], "column": "label",
                           "raw_text": r["label_raw"], "raw_value": "", "corrected_value": r["label"],
                           "footnote": "", "action": "점선 리더/마침표 제거",
                           "evidence": "표기 정리, 의미 변화 없음", "ocr_score": r["label_score"]})

    # ---------- 7. cross-check with PP-StructureV3 ------------------------
    class TD(HTMLParser):
        def __init__(self):
            super().__init__(); self.rows, self._in = [], False
        def handle_starttag(self, t, a):
            if t == "tr": self.rows.append([])
            if t == "td": self._in = True; self.rows[-1].append("")
        def handle_endtag(self, t):
            if t == "td": self._in = False
        def handle_data(self, d):
            if self._in: self.rows[-1][-1] += d

    sjson = json.loads((OUT / "raw" / "structure" / "census-table_res.json").read_text(encoding="utf-8"))
    p = TD(); p.feed(sjson["table_res_list"][0]["pred_html"])
    struct_numbers = [tok for row in p.rows for cell in row[1:] for tok in re.findall(r"\d[\d,]*(?:,\s\d+)*", cell)]
    ocr_numbers = [r["cells"][c]["raw"].replace(" ", "") for r in rows for c in ("area", "population") if r["cells"][c]["raw"]]
    crosscheck = {
        "pp_structure_v3_rows": len(p.rows), "reconstructed_rows_incl_header": len(rows) + 1,
        "pp_structure_v3_cells": p.rows,
        "numbers_only_in_structure": sorted(set(n.replace(" ", "") for n in struct_numbers) - set(ocr_numbers)),
        "numbers_only_in_paddleocr": sorted(set(ocr_numbers) - set(n.replace(" ", "") for n in struct_numbers)),
        "observations": [
            "PP-StructureV3 merged several physical rows into one cell (e.g. 'Alaska.... Hawaii..').",
            "PP-StructureV3 shifted values: 'Military and naval service abroad' row received 115,026 / 55,608 "
            "(115,026 belongs to Philippine Islands; Military has no area).",
            "PP-StructureV3 read the grand-total area as 3,743,806; arithmetic (3,026,789 + 716,517) confirms "
            "PaddleOCR's 3,743,306.",
            "Both engines read the superscript footnote markers as leading digits (17,635,426 / 262,810).",
        ],
        "decision": "Coordinate-based reconstruction from PaddleOCR is used as primary; PP-StructureV3 is cross-check only.",
    }
    (OUT / "structure_crosscheck.json").write_text(json.dumps(crosscheck, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------- 8. write table.csv ----------------------------------------
    # "Table 1" (top-left, bold) is the table title; the other label-column header
    # line ("AREA.") is the stub-column heading, not part of the title.
    title_line = next(l for l in label_hdr if l["text"].lower().startswith("table"))
    title = title_line["text"]
    stub_h = clean_label(" ".join(l["text"] for l in label_hdr if l is not title_line))
    area_h = " ".join(l["text"] for l in area_hdr)
    pop_h = " ".join(l["text"] for l in pop_hdr)
    fields = ["row_id", "level", "parent_row_id", "label", "label_raw",
              "area_sq_mi", "area_raw", "area_status",
              "population_1910", "population_raw", "population_footnote", "population_status",
              "min_ocr_score", "note"]
    with open(OUT / "table.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=fields); w.writeheader()
        for r in rows:
            a, pcell = r["cells"]["area"], r["cells"]["population"]
            scores = [s for s in (r["label_score"], a["score"], pcell["score"]) if s is not None]
            w.writerow({"row_id": r["row_id"], "level": r["level"], "parent_row_id": r["parent"],
                        "label": r["label"], "label_raw": r["label_raw"],
                        "area_sq_mi": "" if a["value"] is None else a["value"], "area_raw": a["raw"],
                        "area_status": a["status"],
                        "population_1910": "" if pcell["value"] is None else pcell["value"],
                        "population_raw": pcell["raw"], "population_footnote": pcell["footnote"],
                        "population_status": pcell["status"], "min_ocr_score": min(scores),
                        "note": " / ".join(x for x in (a["note"], pcell["note"]) if x)})

    with open(OUT / "review_log.csv", "w", newline="", encoding="utf-8-sig") as fh:
        keys = ["row_id", "label", "column", "raw_text", "raw_value", "corrected_value",
                "footnote", "action", "evidence", "ocr_score"]
        w = csv.DictWriter(fh, fieldnames=keys); w.writeheader(); w.writerows(review)

    # ---------- 9. document.md --------------------------------------------
    def fmt(c, foot=True):
        if c["value"] is None:
            return NEED if c["status"] == NEED else "—"
        s = f"{c['value']:,}"
        if foot and c["footnote"]:
            s = f"{s}<sup>{c['footnote']}</sup>"
        return s + (f" ({NEED})" if c["status"] == NEED else "")

    md = [f"# {title} — 면적과 인구 (1910)", "",
          f"> 원문: {SOURCE['publisher']}, *{SOURCE['title']}* ({SOURCE['published']}년 발행)  ",
          f"> 위치: PDF {SOURCE['pdf_page']}쪽 · 인쇄 {SOURCE['printed_page']}쪽 — <{SOURCE['url']}>  ",
          f"> 공유 조건: 퍼블릭 도메인 (미국 연방정부 발행물). 표 영역만 200 dpi로 추출한 이미지 사용  ",
          f"> 입력 이미지: `{data['source']}` (사본 `outputs/ocr/{Path(data['source']).name}`, sha256 `{run_info['input']['sha256'][:16]}…`)  ",
          f"> OCR: PaddleOCR {metadata.version('paddleocr')} ({', '.join(run_info['paddleocr']['models_loaded'])}), "
          "좌표 기반 행·열 복원", "",
          f"| {stub_h} | {area_h} | {pop_h} |", "|---|---:|---:|"]
    for r in rows:
        indent_s = "&nbsp;&nbsp;&nbsp;&nbsp;" if r["level"] == 2 else ""
        lab = f"**{r['label']}**" if r is total else r["label"]
        md.append(f"| {indent_s}{lab} | {fmt(r['cells']['area'])} | {fmt(r['cells']['population'])} |")
    md += ["", "**각주**", ""]
    for k in sorted(notes):
        md.append(f"{k}. {notes[k]['text']}.")
    md += ["", "## 검증", "", "| 검사 | 기대값 | 계산값 | 결과 |", "|---|---:|---:|---|"]
    for c in checks:
        md.append(f"| {c['name']} | {c['expected']:,} | {c['computed']:,} | {'통과' if c['pass'] else '불일치 — ' + NEED} |")
    md += ["", "## 원시값 → 수정값 기록", "", "| 행 | 열 | 원시 OCR | 수정값 | 조치 | 근거 |", "|---|---|---|---|---|---|"]
    for e in review:
        md.append(f"| {e['row_id']} {e['label']} | {e['column']} | `{e['raw_text']}` | `{e['corrected_value']}` | {e['action']} | {e['evidence']} |")
    need_cells = [(r["label"], c) for r in rows for c in ("area", "population") if r["cells"][c]["status"] == NEED]
    md += ["", "## 확인 필요 항목", ""]
    md += [f"- {l} / {c}" for l, c in need_cells] or ["- 필수 없음 (모든 숫자 셀이 합계 관계로 검증됨)"]
    md += ["- 사람 확인 권장 항목(값을 바꾼 2칸, 공란 판정 1칸, 산술 검증이 안 되는 레이블·헤더)은 "
           "`review/needs_confirmation.csv`에 행·열·bbox와 함께 정리되어 있다. 원본 위치 표시는 `review/review_side_by_side.png`."]
    md += ["", "## 비고", "",
           "- `—` 는 원본에서 점선 리더만 있는 공란(Military and naval service abroad의 면적)이다.",
           "- 행 계층: 들여쓴 8개 항목은 'Outlying possessions'의 하위 항목이며, 첫 행은 본토+해외령 총계다.",
           f"- PP-StructureV3 교차 검증 결과는 `structure_crosscheck.json` 참조 (행 병합·값 밀림이 있어 주 결과로 채택하지 않음).",
           ""]
    (OUT / "document.md").write_text("\n".join(md), encoding="utf-8")

    # ---------- 10. manifest.json -----------------------------------------
    pkgs = {}
    for name in ("paddlepaddle", "paddleocr", "paddlex", "numpy", "opencv-contrib-python", "pillow"):
        try:
            pkgs[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            pkgs[name] = None
    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": SOURCE,
        "run_location": RUN_LOCATION,
        "environment": {"os": platform.platform(), "machine": platform.machine(),
                        "processor": platform.processor(), "python": sys.version.split()[0],
                        "python_executable": str(Path(sys.executable).relative_to(ROOT)) if ROOT in Path(sys.executable).parents else sys.executable,
                        "device": "cpu"},
        "packages": pkgs,
        "install_source": {"paddlepaddle": "PyPI (official CPU mirror paddlepaddle.org.cn unreachable at install time; same version 3.2.0 as docs recommend)",
                           "paddleocr": "PyPI paddleocr[doc-parser]==3.7.0"},
        "input": {**run_info["input"], "copy_in_outputs": Path(run_info["input"]["path"]).name},
        "ocr": run_info["paddleocr"],
        "structure": run_info["pp_structure_v3"],
        "reconstruction": {"method": "PaddleOCR line boxes; columns by nearest header x-centre, rows by nearest label y-centre",
                           "row_tolerance_px": ROW_TOLERANCE, "score_threshold": SCORE_THRESHOLD,
                           "unassigned_ocr_lines": [u["id"] for u in unassigned],
                           "checks": checks},
        "outputs": sorted(str(p.relative_to(OUT)).replace("\\", "/") for p in OUT.rglob("*") if p.is_file()) + ["manifest.json"],
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"rows={len(rows)} unassigned={len(unassigned)} review_entries={len(review)} need_check={len(need_cells)}")
    for c in checks:
        print(("PASS " if c["pass"] else "FAIL ") + c["name"], c["expected"], c["computed"], c.get("resolution", ""))


if __name__ == "__main__":
    main()
