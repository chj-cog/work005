"""Step 4: independent review of table.csv against the original image.

Usage:  .venv\\Scripts\\python.exe src\\review.py
Reads : input/census-table.png, outputs/ocr/{ocr_lines.json, table.csv, manifest.json,
        structure_crosscheck.json}, src/reference_manual.csv
Writes (outputs/ocr/review/):
  review_side_by_side.png  original (status-coloured boxes) | table.csv rendered at same y
  review.html              per-row review screen: original row crop vs CSV values
  cell_mapping.csv         every cell: header, label, value, OCR bbox, geometry checks
  review_items.csv         every item flagged for review + evidence + resolution
  needs_confirmation.csv   items a human must (필수) or should (권장) confirm
  corrections.csv          before / after / original coordinates / reason
  review_summary.md        final summary

The mapping here is recomputed with *different* rules from reconstruct.py
(column bounds from the printed vertical rules, row by vertical overlap with the
label box) so that a disagreement exposes a possible mis-link.  Nothing is
filled in automatically: an empty or unverifiable cell stays empty and is flagged.
"""
import base64
import csv
import io
import json
import re
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OCR_DIR = ROOT / "outputs" / "ocr"
OUT = OCR_DIR / "review"
IMG = ROOT / "input" / "census-table.png"

REVIEW_SCORE = 0.97        # review-list threshold (stricter than 0.90 status threshold)
MIN_Y_OVERLAP = 0.60       # value box must overlap its label box vertically by >= 60 %
INK_THRESHOLD = 140        # grey level below which a pixel counts as ink
COLS = ("area", "population")
COL_TITLE = {"area": "Gross area (land and water) in square miles.", "population": "Population: 1910"}

NEED, RECOMMEND = "확인 필요", "사람 확인 권장"
AUTO_OK, VISUAL_OK = "검증됨(자동)", "검토 완료(육안)"
COLOR = {AUTO_OK: (0, 150, 70), VISUAL_OK: (0, 110, 220), "수정": (230, 120, 0),
         NEED: (220, 0, 0), "공란": (140, 60, 200)}


# ----------------------------------------------------------------- helpers
def font(size, bold=False):
    for name in (("malgunbd.ttf" if bold else "malgun.ttf"), "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def y_overlap(a, b):
    inter = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return inter / max(1, min(a[3] - a[1], b[3] - b[1]))


def num_value(text):
    s = text.replace(" ", "")
    return int(s.replace(",", "")) if re.fullmatch(r"\d{1,3}(,\d{3})*", s) else None


def png_b64(im):
    buf = io.BytesIO(); im.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


# ------------------------------------------------- 1. image geometry
gray = cv2.imread(str(IMG), cv2.IMREAD_GRAYSCALE)
H, W = gray.shape
ink = (gray < INK_THRESHOLD).astype(np.uint8)
vmask = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 120)))
hmask = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (150, 1)))
rule_x = [int(x) for x in np.where(vmask.sum(0) > 0)[0]]
inner = sorted({x for x in rule_x if 20 < x < W - 20})
groups = []                                      # merge adjacent x (double-width rules)
for x in inner:
    if groups and x - groups[-1][-1] <= 2:
        groups[-1].append(x)
    else:
        groups.append([x])
rules = [(g[0], g[-1]) for g in groups]
assert len(rules) == 2, f"expected 2 inner vertical rules, found {rules}"
BOUNDS = {"label": (0, rules[0][0]), "area": (rules[0][1] + 1, rules[1][0]),
          "population": (rules[1][1] + 1, W)}
text_ink = ink & (1 - vmask) & (1 - hmask)        # ink without printed rules
# Rule fragments that the morphological opening misses (broken / slightly slanted
# segments) are removed with a +-4 px band around every detected rule position.
rule_band = np.zeros_like(ink)
for x in rule_x:
    rule_band[:, max(0, x - 4):x + 5] = 1
for y in np.where(hmask.sum(1) > 0)[0]:
    rule_band[max(0, y - 3):y + 4, :] = 1
RULE_Y = sorted({int(y) for y in np.where(hmask.sum(1) > 0)[0]})


def col_at(x):
    """Column whose bounds contain x; 'rule' if x sits on a printed column rule."""
    for c, (a, z) in BOUNDS.items():
        if a <= x < z:
            return c
    return "rule"


def components(x0, y0, x1, y1):
    crop = text_ink[max(0, y0):y1, max(0, x0):x1]
    n, _, st, _ = cv2.connectedComponentsWithStats(crop, 8)
    return [dict(x=int(s[0]) + max(0, x0), y=int(s[1]) + max(0, y0), w=int(s[2]), h=int(s[3]), a=int(s[4]))
            for s in st[1:] if s[4] >= 4]


def superscript_check(b):
    """Return (is_superscript, detail) for the leftmost glyph of a number box."""
    comps = sorted(components(*b), key=lambda c: c["x"])
    tall = [c for c in comps if c["h"] >= 12]
    if not comps or not tall:
        return False, "glyph 측정 불가"
    med_h = float(np.median([c["h"] for c in tall]))
    baseline = float(np.median([c["y"] + c["h"] for c in tall]))
    first = comps[0]
    small = 0.45 * med_h <= first["h"] <= 0.75 * med_h
    raised = (first["y"] + first["h"]) <= baseline - 0.3 * med_h
    return small and raised, (f"첫 글자 높이 {first['h']}px / 숫자 중앙값 {med_h:.0f}px, "
                              f"아래끝 y={first['y'] + first['h']} / 기준선 y={baseline:.0f}")


def ink_in_cell(col, y0, y1):
    """Glyph-sized ink inside a cell region (dot leaders are ~3 px and are ignored)."""
    x0, x1 = BOUNDS[col]
    return [c for c in components(x0 + 2, y0, x1 - 2, y1) if c["h"] >= 8]


# ------------------------------------------------- 2. load data
lines = json.loads((OCR_DIR / "ocr_lines.json").read_text(encoding="utf-8"))["lines"]
manifest = json.loads((OCR_DIR / "manifest.json").read_text(encoding="utf-8"))
cross = json.loads((OCR_DIR / "structure_crosscheck.json").read_text(encoding="utf-8"))
with open(OCR_DIR / "table.csv", encoding="utf-8-sig", newline="") as fh:
    table = list(csv.DictReader(fh))
with open(ROOT / "src" / "reference_manual.csv", encoding="utf-8") as fh:
    ref = {r["label"]: r for r in csv.DictReader(fh)}
col_check_pass = {c: all(ch["pass"] for ch in manifest["reconstruction"]["checks"] if ch["name"].startswith(c))
                  for c in COLS}
struct_only = set(cross["numbers_only_in_structure"])


S_ROWS = cross["pp_structure_v3_cells"]
S_NUMS = lambda cell: [t.replace(" ", "") for t in re.findall(r"\d{1,3}(?:,\s?\d{3})*", cell)]
S_ALL = {n for r_ in S_ROWS for c_ in r_[1:] for n in S_NUMS(c_)}


def structure_disagreement(row, col, raw):
    """Compare one cell with PP-StructureV3.
    read : PP-StructureV3 has no number equal to this OCR value anywhere in the table.
    pos  : the PP-StructureV3 row whose label cell contains this label does not hold
           this value in the same column (merged rows / shifted values)."""
    v = raw.replace(" ", "")
    read = "" if v in S_ALL else "PP-StructureV3 표 어디에도 같은 숫자가 없음 (다르게 판독)"
    ci = 1 if col == "area" else 2
    s_row = next((r_ for r_ in S_ROWS[1:] if row["label"] in r_[0]), None)
    if s_row is None:
        pos = "PP-StructureV3에서 이 레이블의 행을 찾지 못함"
    elif v not in S_NUMS(s_row[ci]):
        pos = f"PP-StructureV3는 이 행의 {col} 셀에 '{s_row[ci]}'를 둠"
    else:
        merged_with = [r_["label"] for r_ in table if r_["label"] != row["label"] and r_["label"] in s_row[0]]
        if merged_with:
            pos = f"PP-StructureV3가 '{', '.join(merged_with)}' 행과 한 셀로 병합: '{s_row[0]}' → '{s_row[ci]}'"
        elif len(S_NUMS(s_row[ci])) > 1:
            pos = f"PP-StructureV3가 이 행의 {col} 셀에 숫자 {len(S_NUMS(s_row[ci]))}개를 넣음 (값 밀림): '{s_row[ci]}'"
        else:
            pos = ""
    return read, pos


def find_line(raw, near_y=None):
    cands = [l for l in lines if l["text"] == raw]
    if near_y is not None:
        cands.sort(key=lambda l: abs((l["bbox_xyxy"][1] + l["bbox_xyxy"][3]) / 2 - near_y))
    return cands[0] if cands else None, len(cands)


# ------------------------------------------------- 3. per-cell mapping + checks
mapping, items, corrections = [], [], []
row_geo = {}


def add_item(row, col, raw, bbox, category, reason, evidence, resolution):
    items.append({"row_id": row["row_id"], "label": row["label"], "column": col, "raw_text": raw,
                  "bbox_xyxy": json.dumps(bbox) if bbox else "", "category": category,
                  "reason": reason, "evidence": evidence, "resolution": resolution})


header_lines = [l for l in lines if l["bbox_xyxy"][3] <= 97]
# header ↔ column correspondence
for l in header_lines:
    xc = (l["bbox_xyxy"][0] + l["bbox_xyxy"][2]) / 2
    col = col_at(xc)
    inside = BOUNDS[col][0] <= l["bbox_xyxy"][0] and l["bbox_xyxy"][2] <= BOUNDS[col][1]
    mapping.append({"kind": "header", "row_id": "", "label": "", "column": col, "column_title": l["text"],
                    "raw_text": l["text"], "value": "", "ocr_score": l["score"],
                    "bbox_xyxy": json.dumps(l["bbox_xyxy"]), "within_column_bounds": inside,
                    "y_overlap_with_label": "", "independent_mapping_agrees": inside, "status": ""})
    if l["score"] < REVIEW_SCORE:
        items.append({"row_id": "header", "label": "", "column": col, "raw_text": l["text"],
                      "bbox_xyxy": json.dumps(l["bbox_xyxy"]), "category": "낮은 신뢰도",
                      "reason": f"OCR 점수 {l['score']} < {REVIEW_SCORE}",
                      "evidence": "원본 육안 대조: 헤더 문자열 일치 (산술 검증 대상 아님)", "resolution": VISUAL_OK})

for row in table:
    lab_line, _ = find_line(row["label_raw"])
    lb = lab_line["bbox_xyxy"]
    row_geo[row["row_id"]] = lb
    ref_row = ref.get(row["label"])
    # label checks
    label_inside = lb[2] <= BOUNDS["label"][1]
    mapping.append({"kind": "label", "row_id": row["row_id"], "label": row["label"], "column": "label",
                    "column_title": "AREA", "raw_text": row["label_raw"], "value": row["label"],
                    "ocr_score": lab_line["score"], "bbox_xyxy": json.dumps(lb),
                    "within_column_bounds": label_inside, "y_overlap_with_label": 1.0,
                    "independent_mapping_agrees": label_inside, "status": ""})
    if lab_line["score"] < REVIEW_SCORE:
        add_item(row, "label", row["label_raw"], lb, "낮은 신뢰도", f"OCR 점수 {lab_line['score']} < {REVIEW_SCORE}",
                 "원본 육안 대조: 레이블 일치" if ref_row else "참조 전사본에 없음",
                 VISUAL_OK if ref_row else NEED)
    if row["label_raw"] != row["label"]:
        corrections.append({"row_id": row["row_id"], "label": row["label"], "column": "label",
                            "before": row["label_raw"], "after": row["label"], "bbox_xyxy": json.dumps(lb),
                            "polygon": json.dumps(lab_line["polygon"]), "ocr_score": lab_line["score"],
                            "change_type": "표기 정리", "reason": "끝의 점선 리더/마침표 제거 (의미 변화 없음)",
                            "evidence": "원본에서 레이블 뒤에 점선 리더가 이어짐"})

    for col in COLS:
        raw = row[f"{col}_raw"]
        status_csv = row[f"{col}_status"]
        val = row["area_sq_mi" if col == "area" else "population_1910"]
        ref_val = ref_row["area_sq_mi" if col == "area" else "population_1910"] if ref_row else None
        rec = {"kind": "value", "row_id": row["row_id"], "label": row["label"], "column": col,
               "column_title": COL_TITLE[col], "raw_text": raw, "value": val}

        # ---- empty cell: never fill, prove emptiness from pixels or flag
        if not raw:
            glyphs = ink_in_cell(col, lb[1] - 2, lb[3] + 2)
            region = [BOUNDS[col][0], lb[1] - 2, BOUNDS[col][1], lb[3] + 2]
            leader = components(BOUNDS[col][0] + 2, lb[1], BOUNDS[col][1] - 2, lb[3])
            if glyphs:
                res, ev = NEED, f"OCR 미검출인데 셀 영역에 글자 크기 잉크 {len(glyphs)}개 존재 → 값 누락 가능"
            else:
                res = "공란"
                ev = (f"셀 영역 {region}에 높이 8px 이상 글자 없음; 점 {len(leader)}개(점선 리더)만 존재. "
                      f"열 합계 검증 {'통과' if col_check_pass[col] else '실패'}")
            rec.update(ocr_score="", bbox_xyxy=json.dumps(region), within_column_bounds="",
                       y_overlap_with_label="", independent_mapping_agrees=not glyphs, status=res)
            mapping.append(rec)
            add_item(row, col, "", region, "빈 셀 / 연결 위험",
                     "OCR 값 없음. 레이블의 점선 리더가 세로 구분선을 넘어 이 열까지 이어져, "
                     "다른 행의 값이 잘못 붙거나 점선이 숫자로 오인될 위험", ev, res)
            continue

        line, n_same = find_line(raw, (lb[1] + lb[3]) / 2)
        b = line["bbox_xyxy"]
        xc = (b[0] + b[2]) / 2
        indep_col = col_at(xc)
        within = BOUNDS[col][0] <= b[0] and b[2] <= BOUNDS[col][1]
        ov = round(y_overlap(b, lb), 3)
        best_label = max(table, key=lambda r: y_overlap(b, row_geo.get(r["row_id"]) or find_line(r["label_raw"])[0]["bbox_xyxy"]))
        indep_row_ok = best_label["row_id"] == row["row_id"]
        agrees = indep_col == col and indep_row_ok
        is_sup, sup_detail = superscript_check(b)
        rec.update(ocr_score=line["score"], bbox_xyxy=json.dumps(b), within_column_bounds=within,
                   y_overlap_with_label=ov, independent_mapping_agrees=agrees)

        # ---- evidence available for this cell
        arith = col_check_pass[col]
        ref_match = ref_val is not None and str(val) == ref_val
        reasons = []
        if line["score"] < REVIEW_SCORE:
            reasons.append(("낮은 신뢰도", f"OCR 점수 {line['score']} < {REVIEW_SCORE}"))
        if " " in raw:
            reasons.append(("숫자 형식 이상", "숫자 안에 공백"))
        if num_value(raw) is None:
            reasons.append(("숫자 형식 이상", "천 단위 쉼표 그룹 형식 불일치"))
        if is_sup:
            reasons.append(("숫자 형식 이상", f"선두 글자가 위첨자(각주 기호) 형태: {sup_detail}"))
        if not within:
            reasons.append(("연결 위험", f"값 박스 {b}가 열 경계 {BOUNDS[col]}를 벗어남"))
        if ov < MIN_Y_OVERLAP:
            reasons.append(("연결 위험", f"레이블과 세로 겹침 {ov} < {MIN_Y_OVERLAP}"))
        if not agrees:
            reasons.append(("연결 위험", f"독립 재배정 결과 다름: 열={indep_col}, 행={best_label['label']}"))
        if n_same > 1:
            reasons.append(("연결 위험", f"같은 문자열 OCR 라인 {n_same}개"))
        s_read, s_pos = structure_disagreement(row, col, raw)
        if s_read:
            reasons.append(("엔진 간 판독 불일치", s_read))
        if s_pos:
            reasons.append(("엔진 간 위치 불일치", s_pos))

        corrected = status_csv == "수정"
        if corrected and not is_sup:
            reasons.append(("수정 근거 부족", "수정된 값인데 위첨자 형태가 기하적으로 확인되지 않음"))

        # ---- resolution
        if status_csv == NEED or (corrected and not (is_sup and arith)) or not agrees or not arith:
            resolution = NEED
        elif corrected:
            resolution = "수정"
        else:
            resolution = AUTO_OK
        rec["status"] = resolution
        mapping.append(rec)

        evidence = "; ".join(filter(None, [
            f"열 합계 검증 {'통과' if arith else '실패'}",
            "독립 행·열 재배정 일치" if agrees else "독립 재배정 불일치",
            f"육안 전사본 {'일치' if ref_match else '불일치/없음'} ({ref_val})" if ref_val is not None else "",
            sup_detail if is_sup else ""]))
        for cat, why in reasons:
            add_item(row, col, raw, b, cat, why, evidence, resolution)

        if corrected or raw.replace(" ", "") != raw:
            corrections.append({
                "row_id": row["row_id"], "label": row["label"], "column": col, "before": raw,
                "after": f"{int(val):,}" + (f" (각주 {row['population_footnote']})" if corrected else ""),
                "bbox_xyxy": json.dumps(b), "polygon": json.dumps(line["polygon"]), "ocr_score": line["score"],
                "change_type": "값 수정" if corrected else "형식 정규화",
                "reason": (f"선두 '{raw[0]}'은 각주 {row['population_footnote']}의 위첨자 → 값에서 분리"
                           if corrected else "숫자 사이 공백 제거 (값 불변)"),
                "evidence": (f"기하: {sup_detail}; 산술: 하위 항목 합 = Outlying possessions (유일해)"
                             if corrected else "쉼표 그룹 유효")})

# ------------------------------------------------- 4. OCR-missed ink anywhere in the table body
covered = np.zeros_like(text_ink)
for l in lines:
    x0, y0, x1, y1 = l["bbox_xyxy"]
    covered[max(0, y0 - 3):y1 + 3, max(0, x0 - 3):x1 + 3] = 1
n, _, st, _ = cv2.connectedComponentsWithStats(text_ink & (1 - covered) & (1 - rule_band), 8)
missed = [dict(x=int(s[0]), y=int(s[1]), w=int(s[2]), h=int(s[3])) for s in st[1:] if s[3] >= 8 and s[4] >= 15]
for m in missed:
    items.append({"row_id": "", "label": "", "column": col_at(m["x"]),
                  "raw_text": "", "bbox_xyxy": json.dumps([m["x"], m["y"], m["x"] + m["w"], m["y"] + m["h"]]),
                  "category": "OCR 누락 가능", "reason": f"OCR 박스 밖의 글자 크기 잉크 {m['w']}x{m['h']}px",
                  "evidence": "", "resolution": NEED})

# ------------------------------------------------- 5. write CSVs
OUT.mkdir(parents=True, exist_ok=True)


def write_csv(name, rows, fields):
    with open(OUT / name, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=fields); w.writeheader(); w.writerows(rows)


write_csv("cell_mapping.csv", mapping, ["kind", "row_id", "label", "column", "column_title", "raw_text", "value",
                                        "ocr_score", "bbox_xyxy", "within_column_bounds", "y_overlap_with_label",
                                        "independent_mapping_agrees", "status"])
item_fields = ["row_id", "label", "column", "raw_text", "bbox_xyxy", "category", "reason", "evidence", "resolution"]
write_csv("review_items.csv", items, item_fields)
write_csv("corrections.csv", corrections, ["row_id", "label", "column", "before", "after", "bbox_xyxy", "polygon",
                                           "ocr_score", "change_type", "reason", "evidence"])

# needs_confirmation: 필수 = unresolved; 권장 = resolved only by visual check, or value changed
needs = []
seen = set()
for it in items:
    key = (it["row_id"], it["column"], it["raw_text"])
    if it["resolution"] == NEED:
        prio, why = "필수", "자동 근거로 확정 불가 — 원본 확인 전까지 값 사용 금지"
    elif it["resolution"] == VISUAL_OK:
        prio, why = "권장", "산술 검증 대상이 아니라 AI의 육안 대조만으로 확인됨"
    elif it["resolution"] == "수정":
        prio, why = "권장", "OCR 원시값을 변경함 — 사람 서명 권장"
    elif it["resolution"] == "공란":
        prio, why = "권장", "빈 셀을 공란으로 판정함 — 값이 없음을 사람 확인 권장"
    else:
        continue
    if key in seen:
        continue
    seen.add(key)
    needs.append({"priority": prio, **{k: it[k] for k in ("row_id", "label", "column", "raw_text", "bbox_xyxy")},
                  "current_value": it["raw_text"] if it["row_id"] == "header" else
                                   next((m["value"] for m in mapping if str(m["row_id"]) == str(it["row_id"])
                                         and m["column"] == it["column"] and m["kind"] != "header"), ""),
                  "why": why, "evidence": it["evidence"], "reviewer_decision": "", "reviewer": ""})
needs.sort(key=lambda r: (r["priority"] != "필수", str(r["row_id"])))
write_csv("needs_confirmation.csv", needs, ["priority", "row_id", "label", "column", "raw_text", "current_value",
                                            "bbox_xyxy", "why", "evidence", "reviewer_decision", "reviewer"])

# ------------------------------------------------- 6. side-by-side image
orig = Image.open(IMG).convert("RGB")
left = orig.copy()
d = ImageDraw.Draw(left)
for x0, x1 in rules:
    d.line([(x0, 0), (x0, H)], fill=(255, 0, 255), width=1)
status_of = {}
for m in mapping:
    if m["kind"] == "value":
        status_of[(m["row_id"], m["column"])] = m["status"]
        b = json.loads(m["bbox_xyxy"])
        c = COLOR.get(m["status"], (0, 0, 0))
        d.rectangle(b, outline=c, width=3 if m["status"] != AUTO_OK else 2)
    elif m["kind"] == "label":
        d.rectangle(json.loads(m["bbox_xyxy"]), outline=(160, 160, 160), width=1)
for m in missed:
    d.rectangle([m["x"], m["y"], m["x"] + m["w"], m["y"] + m["h"]], outline=COLOR[NEED], width=3)

RW = 820
right = Image.new("RGB", (RW, H), "white")
dr = ImageDraw.Draw(right)
f, fb, fs = font(13), font(13, True), font(11)
cx = {"label": 10, "area": 400, "population": 545, "status": 690}
dr.text((cx["label"], 8), "table.csv 재구성 (원본과 같은 높이에 배치)", fill=(0, 0, 0), font=fb)
dr.text((cx["label"], 50), "label", fill=(80, 80, 80), font=fb)
dr.text((cx["area"], 42), "area_sq_mi", fill=(80, 80, 80), font=fb)
dr.text((cx["area"], 60), "Gross area…", fill=(120, 120, 120), font=fs)
dr.text((cx["population"], 42), "population_1910", fill=(80, 80, 80), font=fb)
dr.text((cx["population"], 60), "Population: 1910", fill=(120, 120, 120), font=fs)
dr.text((cx["status"], 50), "상태 (면적 / 인구)", fill=(80, 80, 80), font=fb)
dr.line([(0, 97), (RW, 97)], fill=(0, 0, 0))
for row in table:
    lb = row_geo[row["row_id"]]
    y = (lb[1] + lb[3]) / 2 - 8
    dr.line([(0, lb[3] + 1), (RW, lb[3] + 1)], fill=(235, 235, 235))
    indent = 18 if row["level"] == "2" else 0
    lf = f if dr.textlength(row["label"], font=f) <= 375 - indent else font(11)
    dr.text((cx["label"] + indent, y), row["label"], fill=(0, 0, 0), font=lf)
    for col, key in (("area", "area_sq_mi"), ("population", "population_1910")):
        st_ = status_of.get((row["row_id"], col), "")
        v = row[key]
        txt = f"{int(v):,}" if v else "— (공란)"
        if col == "population" and row["population_footnote"]:
            txt += f"  [각주{row['population_footnote']}]"
        dr.text((cx[col], y), txt, fill=COLOR.get(st_, (0, 0, 0)), font=fb if st_ != AUTO_OK else f)
    st_a, st_p = status_of.get((row["row_id"], "area"), ""), status_of.get((row["row_id"], "population"), "")
    dr.text((cx["status"], y), f"{st_a} / {st_p}".replace("검증됨(자동)", "자동OK"), fill=(60, 60, 60), font=fs)
legend_y = H - 40
lx = 10
for k, c in COLOR.items():
    dr.rectangle([lx, legend_y, lx + 12, legend_y + 12], fill=c)
    dr.text((lx + 16, legend_y - 2), k, fill=(0, 0, 0), font=fs)
    lx += 30 + int(dr.textlength(k, font=fs))
dr.text((10, legend_y + 18), "왼쪽 분홍 세로선 = 이미지에서 검출한 열 구분선 (독립 열 경계)", fill=(120, 120, 120), font=fs)

sbs = Image.new("RGB", (W + RW + 10, H), (200, 200, 200))
sbs.paste(left, (0, 0)); sbs.paste(right, (W + 10, 0))
sbs.save(OUT / "review_side_by_side.png")

# ------------------------------------------------- 7. HTML review screen
def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


badge = {AUTO_OK: "ok", VISUAL_OK: "vis", "수정": "fix", NEED: "need", "공란": "blank"}
rows_html = []
for row in table:
    lb = row_geo[row["row_id"]]
    y0, y1 = max(0, lb[1] - 4), min(H, lb[3] + 4)
    crop = left.crop((0, y0, W, y1))
    cells = []
    for col, key in (("area", "area_sq_mi"), ("population", "population_1910")):
        st_ = status_of.get((row["row_id"], col), "")
        v = row[key]
        raw = row[f"{col}_raw"]
        val = f"{int(v):,}" if v else "—"
        if col == "population" and row["population_footnote"]:
            val += f"<sup>{row['population_footnote']}</sup>"
        raw_html = f'<div class="raw">OCR: <code>{esc(raw) or "(없음)"}</code></div>'
        cells.append(f'<td class="num"><div class="v">{val}</div>{raw_html}'
                     f'<span class="b {badge.get(st_, "")}">{esc(st_)}</span></td>')
    notes = [f"{esc(i['category'])}: {esc(i['reason'])}" for i in items if str(i["row_id"]) == row["row_id"]]
    rows_html.append(
        f'<tr><td class="id">{row["row_id"]}</td>'
        f'<td class="img"><img src="data:image/png;base64,{png_b64(crop)}" alt="row {row["row_id"]} crop"></td>'
        f'<td class="lab">{"&nbsp;&nbsp;" * (2 if row["level"] == "2" else 0)}{esc(row["label"])}</td>'
        + "".join(cells) + f'<td class="notes">{"<br>".join(notes) or "—"}</td></tr>')

need_rows = "".join(
    f'<tr><td><span class="b {"need" if n["priority"] == "필수" else "vis"}">{n["priority"]}</span></td>'
    f'<td>{esc(n["row_id"])}</td><td>{esc(n["label"])}</td><td>{esc(n["column"])}</td>'
    f'<td><code>{esc(n["raw_text"])}</code></td><td>{esc(n["current_value"])}</td><td>{esc(n["why"])}</td></tr>'
    for n in needs)
corr_rows = "".join(
    f'<tr><td>{esc(c["row_id"])} {esc(c["label"])}</td><td>{esc(c["column"])}</td><td><code>{esc(c["before"])}</code></td>'
    f'<td><code>{esc(c["after"])}</code></td><td><code>{esc(c["bbox_xyxy"])}</code></td><td>{esc(c["reason"])}</td></tr>'
    for c in corrections if c["change_type"] != "표기 정리")

n_need = sum(1 for n in needs if n["priority"] == "필수")
html = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>OCR 표 검토</title>
<style>
:root{{--bg:#fff;--fg:#1b1b1b;--mut:#666;--line:#ddd;--card:#f6f7f9}}
@media (prefers-color-scheme:dark){{:root{{--bg:#16181b;--fg:#e8e8e8;--mut:#9aa;--line:#333;--card:#1f2226}}}}
body{{background:var(--bg);color:var(--fg);font:14px/1.5 "Malgun Gothic",system-ui,sans-serif;margin:0;padding:16px}}
h1{{font-size:20px;margin:0 0 4px}} h2{{font-size:16px;margin:28px 0 8px}}
.mut{{color:var(--mut)}} .wrap{{overflow-x:auto}}
.kpi{{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0}} .kpi div{{background:var(--card);padding:8px 14px;border-radius:8px}}
.kpi b{{font-size:20px;display:block}}
table{{border-collapse:collapse;width:100%}} td,th{{border-bottom:1px solid var(--line);padding:6px 8px;vertical-align:middle;text-align:left}}
td.img img{{max-width:620px;width:100%;display:block;background:#fff;border-radius:4px}}
td.num{{text-align:right;white-space:nowrap}} .v{{font-weight:600;font-variant-numeric:tabular-nums}} .raw{{font-size:12px;color:var(--mut)}}
td.notes{{font-size:12px;color:var(--mut);max-width:280px}} td.id{{color:var(--mut)}}
.b{{display:inline-block;font-size:11px;padding:1px 6px;border-radius:9px;color:#fff;margin-top:2px}}
.ok{{background:#00964a}} .vis{{background:#006edc}} .fix{{background:#e67800}} .need{{background:#dc0000}} .blank{{background:#8c3cc8}}
img.full{{max-width:100%;border:1px solid var(--line)}}
</style></head><body>
<h1>OCR 표 검토 — census-table.png</h1>
<div class="mut">각 행: 왼쪽 = 원본 이미지 해당 행(상태 색 박스), 오른쪽 = table.csv 값과 OCR 원시값</div>
<div class="kpi"><div><b>{len(table)}</b>행</div><div><b>{sum(1 for m in mapping if m['kind']=='value')}</b>값 셀</div>
<div><b>{len(items)}</b>검토 대상 항목</div><div><b>{len([c for c in corrections if c['change_type']=='값 수정'])}</b>값 수정</div>
<div><b style="color:{'#dc0000' if n_need else '#00964a'}">{n_need}</b>확인 필요(필수)</div></div>
<h2>행별 대조</h2><div class="wrap"><table>
<tr><th>#</th><th>원본</th><th>label</th><th>Gross area (sq mi)</th><th>Population 1910</th><th>검토 사유</th></tr>
{''.join(rows_html)}</table></div>
<h2>수정 전 / 후 (값)</h2><div class="wrap"><table><tr><th>행</th><th>열</th><th>수정 전</th><th>수정 후</th><th>원본 좌표 (x0,y0,x1,y1)</th><th>이유</th></tr>{corr_rows}</table></div>
<h2>확인 필요 / 사람 확인 권장</h2><div class="wrap"><table><tr><th>우선</th><th>행</th><th>label</th><th>열</th><th>OCR</th><th>현재값</th><th>사유</th></tr>{need_rows}</table></div>
<h2>전체 나란히 보기</h2><img class="full" src="data:image/png;base64,{png_b64(sbs)}" alt="side by side">
</body></html>"""
(OUT / "review.html").write_text(html, encoding="utf-8")

# ------------------------------------------------- 8. summary markdown
by_cat = {}
for it in items:
    by_cat.setdefault(it["category"], []).append(it)
val_cells = [m for m in mapping if m["kind"] == "value"]
summary = ["# OCR 검토 요약", "",
           f"- 대상: `input/census-table.png` ↔ `outputs/ocr/table.csv` ({len(table)}행 × 값 2열 = {len(val_cells)}셀)",
           f"- 독립 열 경계(이미지 세로 구분선): label < x={BOUNDS['label'][1]} ≤ area < x={BOUNDS['area'][1]} ≤ population",
           f"- 검토 기준: OCR 점수 < {REVIEW_SCORE}, 숫자 형식(공백/쉼표 그룹/위첨자), 열 경계 이탈, 레이블과 세로 겹침 < {MIN_Y_OVERLAP}, "
           "독립 재배정 불일치, 엔진 간 불일치, 빈 셀, OCR 박스 밖 잉크", "",
           "## 셀 상태", "", "| 상태 | 셀 수 |", "|---|---:|"]
for s in (AUTO_OK, "수정", "공란", NEED):
    summary.append(f"| {s} | {sum(1 for m in val_cells if m['status'] == s)} |")
summary += ["", "## 행·열·헤더 대응", "",
            f"- 헤더 {len(header_lines)}줄 모두 해당 열 경계 안: {all(m['within_column_bounds'] for m in mapping if m['kind']=='header')}",
            f"- 레이블 {len(table)}개 모두 label 열 안: {all(m['within_column_bounds'] for m in mapping if m['kind']=='label')}",
            f"- 값 셀 독립 재배정 일치: {sum(1 for m in val_cells if m['independent_mapping_agrees'] is True)}/{len(val_cells)}",
            f"- 레이블과 세로 겹침 최소값: {min(m['y_overlap_with_label'] for m in val_cells if m['y_overlap_with_label'] != '')}",
            f"- OCR 박스 밖 글자 크기 잉크(누락 가능): {len(missed)}개", "",
            "## 검토 대상 항목 (분류별)", "", "| 분류 | 건수 | 항목 |", "|---|---:|---|"]
for cat, its in by_cat.items():
    summary.append(f"| {cat} | {len(its)} | " + ", ".join(f"{i['row_id']} {i['label'] or ''}/{i['column']} `{i['raw_text']}`".strip() for i in its) + " |")
summary += ["", "## 수정 전 → 후 (원본 좌표 포함)", "", "| 행 | 열 | 수정 전 | 수정 후 | bbox | 유형 | 이유 |", "|---|---|---|---|---|---|---|"]
for c in corrections:
    summary.append(f"| {c['row_id']} {c['label']} | {c['column']} | `{c['before']}` | `{c['after']}` | `{c['bbox_xyxy']}` | {c['change_type']} | {c['reason']} |")
summary += ["", "## 확인 필요", "",
            f"- **필수 {n_need}건**, 권장 {len(needs) - n_need}건 → `needs_confirmation.csv` (reviewer_decision / reviewer 열에 기록)"]
for n in needs:
    summary.append(f"  - [{n['priority']}] {n['row_id']} {n['label']} / {n['column']} `{n['raw_text']}` → {n['current_value'] or '공란'}: {n['why']}")
summary += ["", "## 원칙", "",
            "- 빈 셀은 채우지 않았다. 셀 영역의 픽셀을 검사해 글자가 없음을 확인한 경우에만 `공란`, 아니면 `확인 필요`.",
            "- 값 수정은 기하(위첨자 형태)와 산술(합계 유일해)이 **둘 다** 성립할 때만 `수정`으로 인정, 하나라도 없으면 `확인 필요`.",
            "- `검토 완료(육안)`은 AI가 원본 이미지를 보고 대조한 것이므로 사람 확인을 권장 항목으로 남겼다.", ""]
(OUT / "review_summary.md").write_text("\n".join(summary), encoding="utf-8")

# ------------------------------------------------- 9. re-open every review output
def reread(name):
    with open(OUT / name, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


assert len(reread("cell_mapping.csv")) == len(mapping)
assert len(reread("review_items.csv")) == len(items)
assert len(reread("corrections.csv")) == len(corrections)
nc = reread("needs_confirmation.csv")
assert len(nc) == len(needs)
assert all(r["bbox_xyxy"] and r["before"] and r["reason"] for r in reread("corrections.csv"))
html_back = (OUT / "review.html").read_text(encoding="utf-8")
assert html_back.count('alt="row ') == len(table)
with Image.open(OUT / "review_side_by_side.png") as im_back:
    assert im_back.size == (W + RW + 10, H)
assert "## 확인 필요" in (OUT / "review_summary.md").read_text(encoding="utf-8")
print("re-open check: OK (all review outputs readable and consistent)")
print(f"bounds={BOUNDS} items={len(items)} corrections={len(corrections)} need={n_need} recommend={len(needs)-n_need} missed_ink={len(missed)}")
for s in (AUTO_OK, "수정", "공란", NEED):
    print(s, sum(1 for m in val_cells if m["status"] == s))
