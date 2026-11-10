"""Step 1: PaddleOCR 3.x text OCR + PP-StructureV3 table recognition.

Usage:  .venv\\Scripts\\python.exe src\\run_ocr.py
Outputs (outputs/ocr/):
  raw/ocr/          PaddleOCR native result (save_to_json / save_to_img)
  raw/structure/    PP-StructureV3 native result (json / markdown / images)
  ocr_lines.json    simplified line list: text, score, polygon, bbox
  ocr_visualization.png   boxes + index numbers drawn on a copy of the input
  census-table.png  unmodified copy of the input image
"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "input" / "census-table.png"
OUT = ROOT / "outputs" / "ocr"

# Settings recorded verbatim in manifest.json
OCR_CONFIG = {
    "use_doc_orientation_classify": False,  # scan is upright
    "use_doc_unwarping": False,             # flat scan, no page curvature
    "use_textline_orientation": False,      # all text is horizontal
    "lang": "en",
}
STRUCT_CONFIG = {
    "use_doc_orientation_classify": False,
    "use_doc_unwarping": False,
    "use_textline_orientation": False,
    "use_table_recognition": True,
    "use_seal_recognition": False,
    "use_formula_recognition": False,
    "use_chart_recognition": False,
    "lang": "en",
}


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def collect_model_names(obj, seen=None, depth=0) -> list:
    """Walk a PaddleX pipeline object and collect every `model_name` actually loaded."""
    seen = set() if seen is None else seen
    names = []
    if id(obj) in seen or depth > 6:
        return names
    seen.add(id(obj))
    name = getattr(obj, "model_name", None)
    if isinstance(name, str):
        names.append(name)
    attrs = getattr(obj, "__dict__", {})
    for v in attrs.values():
        if hasattr(v, "__dict__") and type(v).__module__.startswith(("paddlex", "paddleocr")):
            names += collect_model_names(v, seen, depth + 1)
    return names


def main() -> None:
    if not INPUT.is_file():
        sys.exit(f"[ERROR] input image not found: {INPUT}")
    before = sha256(INPUT)
    with Image.open(INPUT) as im:
        size = im.size
    print(f"[input] {INPUT} {size} sha256={before}")

    (OUT / "raw" / "ocr").mkdir(parents=True, exist_ok=True)
    (OUT / "raw" / "structure").mkdir(parents=True, exist_ok=True)
    # Byte-identical copy of the input next to the outputs (checked by verify.py)
    shutil.copy2(INPUT, OUT / INPUT.name)

    # ---- 1. PaddleOCR (PP-OCRv5 pipeline) --------------------------------
    from paddleocr import PaddleOCR, PPStructureV3

    ocr = PaddleOCR(**OCR_CONFIG)
    results = ocr.predict(str(INPUT))
    res = results[0]
    res.save_to_json(str(OUT / "raw" / "ocr"))
    res.save_to_img(str(OUT / "raw" / "ocr"))
    data = res.json["res"]

    lines = []
    for i, (text, score, poly, box) in enumerate(
        zip(data["rec_texts"], data["rec_scores"], data["rec_polys"], data["rec_boxes"])
    ):
        lines.append({
            "id": i,
            "text": text,
            "score": round(float(score), 4),
            "polygon": [[int(x), int(y)] for x, y in poly],
            "bbox_xyxy": [int(v) for v in box],
        })
    (OUT / "ocr_lines.json").write_text(
        json.dumps({"source": str(INPUT.relative_to(ROOT)), "image_size": size,
                    "config": OCR_CONFIG, "model_settings": data.get("model_settings"),
                    "text_det_params": data.get("text_det_params"),
                    "lines": lines}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"[ocr] {len(lines)} text lines")

    # Own visualization: numbered boxes, red when score < 0.90
    with Image.open(INPUT) as im:
        vis = im.convert("RGB")
    draw = ImageDraw.Draw(vis)
    font = ImageFont.load_default()
    for ln in lines:
        color = (220, 0, 0) if ln["score"] < 0.90 else (0, 140, 255)
        draw.polygon([tuple(p) for p in ln["polygon"]], outline=color, width=2)
        x0, y0 = ln["polygon"][0]
        draw.text((x0, max(0, y0 - 11)), str(ln["id"]), fill=color, font=font)
    vis.save(OUT / "ocr_visualization.png")

    # ---- 2. PP-StructureV3 (layout + table structure) --------------------
    pipe = PPStructureV3(**STRUCT_CONFIG)
    sres = pipe.predict(str(INPUT))[0]
    sres.save_to_json(str(OUT / "raw" / "structure"))
    sres.save_to_markdown(str(OUT / "raw" / "structure"))
    sres.save_to_img(str(OUT / "raw" / "structure"))
    tables = sres.json["res"].get("table_res_list", [])
    print(f"[structure] tables found: {len(tables)}")

    after = sha256(INPUT)
    assert before == after, "input file changed!"
    print("[input] unchanged (sha256 verified)")

    run_info = {
        "input": {"path": str(INPUT.relative_to(ROOT)), "size_px": size, "sha256": before},
        "paddleocr": {"config": OCR_CONFIG,
                      "models_loaded": sorted(set(collect_model_names(ocr.paddlex_pipeline)))},
        "pp_structure_v3": {"config": STRUCT_CONFIG,
                            "models_loaded": sorted(set(collect_model_names(pipe.paddlex_pipeline))),
                            "model_settings_reported": sres.json["res"].get("model_settings")},
    }
    (OUT / "run_info.json").write_text(json.dumps(run_info, indent=2), encoding="utf-8")
    print("[models]", json.dumps(run_info["paddleocr"]["models_loaded"]),
          json.dumps(run_info["pp_structure_v3"]["models_loaded"]))


if __name__ == "__main__":
    main()
