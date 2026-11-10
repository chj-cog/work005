# census-table OCR → 표 복원 (PaddleOCR 3.x)

`input/census-table.png`(1910년 미국 센서스 Table 1, 면적·인구)를 PaddleOCR로 읽고, 행·열 구조와 숫자 관계를 복원하여 검색·편집 가능한 CSV / Markdown으로 만든다.

## 0. 입력 자료의 출처와 공유 조건

| 항목 | 값 |
|---|---|
| 원문 | 미국 인구조사국(U.S. Bureau of the Census), *Thirteenth Census of the United States, 1910 — Volume I: Population* (1913년 발행) |
| 위치 | PDF 2쪽 · 인쇄 22쪽, Table 1 (면적과 인구) |
| 링크 | <https://www2.census.gov/library/publications/decennial/1910/volume-1/volume-1-p3.pdf> |
| 입력 이미지 | 과제에서 제공한 표 영역 이미지(200 dpi 추출) → `input/census-table.png` |
| 공유 조건 | 퍼블릭 도메인(미국 연방정부 발행물). 개인정보·기밀 자료는 들어 있지 않다. |

같은 정보가 `outputs/ocr/manifest.json`의 `source`와 `document.md` 머리말에 기록된다.

## 1. 환경 (실제 실행 환경)

| 항목 | 값 |
|---|---|
| 실행 위치 | 로컬 PC (Colab 아님) |
| OS | Windows 11 Home (10.0.26200), AMD Ryzen 9 7945HX, **CPU 실행** |
| Python | 3.11.9 (`.venv` 가상환경; 시스템 기본 3.14는 사용하지 않음) |
| paddlepaddle | 3.2.0 (CPU) |
| paddleocr | 3.7.0 (`[doc-parser]` extra, paddlex 3.7.2) |
| 전체 고정 목록 | `requirements-lock.txt` (`pip freeze`) |

## 2. 설치

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
# 공식 문서(paddleocr.ai, PaddlePaddle 설치 페이지)의 CPU 명령:
.\.venv\Scripts\python.exe -m pip install paddlepaddle==3.2.0 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
#   → 이 환경에서는 공식 미러가 "from versions: none"으로 실패하여, 같은 버전을 PyPI에서 설치함:
.\.venv\Scripts\python.exe -m pip install paddlepaddle==3.2.0
.\.venv\Scripts\python.exe -m pip install "paddleocr[doc-parser]==3.7.0"
.\.venv\Scripts\python.exe -c "import paddle; paddle.utils.run_check()"   # "PaddlePaddle works well on 1 CPU."
```

`[doc-parser]` extra는 PP-StructureV3에 필요하다(공식 문서 기준 Python 3.9 이상). 첫 실행 때 모델이 `%USERPROFILE%\.paddlex\official_models`에 자동으로 내려받아진다.

## 3. 실행

```powershell
.\run_all.ps1          # = run_ocr.py → reconstruct.py → verify.py → review.py
```

| 스크립트 | 역할 |
|---|---|
| `src/run_ocr.py` | 입력 존재와 SHA256 확인 → `PaddleOCR(...).predict()` → `PPStructureV3(...).predict()` → 원시 JSON, 시각화 이미지, 사용 모델 기록 → 원본 해시 재확인 |
| `src/reconstruct.py` | 좌표로 행·열 복원 → 산술 관계 검증 → 원시값과 수정값 분리 → `table.csv`, `document.md`, `review_log.csv`, `structure_crosscheck.json`, `manifest.json` 생성 |
| `src/verify.py` | 생성된 파일을 모두 다시 열어 검증(18개 항목). 수동 전사본 `src/reference_manual.csv`와 셀 단위로 대조 → `verification_report.json` |

사용한 API는 PaddleOCR 3.x 방식(`predict()`, 결과 객체의 `.json` / `save_to_json` / `save_to_img` / `save_to_markdown`)뿐이다. 2.x 방식의 `ocr.ocr(img, cls=True)`, `PPStructure`는 쓰지 않았다. API 시그니처는 설치된 3.7.0에서 `inspect.signature`로 직접 확인했다.

## 4. 결과물 (`outputs/ocr/`)

| 파일 | 내용 |
|---|---|
| `census-table.png` | 입력 표 이미지 사본(원본과 바이트 동일, `verify.py`에서 해시 확인) |
| `table.csv` | 최종 표(UTF-8 BOM). 11행 × (행ID, 계층, 상위행, 레이블, **원시 레이블**, 면적, **면적 원시값**, 상태, 인구, **인구 원시값**, 각주, 상태, 최소 신뢰도, 비고) |
| `document.md` | 제목, 표, 각주, 검증 결과, 원시값→수정값 기록, 확인 필요 목록 |
| `review_log.csv` | 검토 기록: 원시 텍스트, 원시값, 수정값, 조치, 근거, OCR 점수 |
| `ocr_lines.json` | 41개 텍스트 라인: 문자열, 신뢰도, 폴리곤, bbox |
| `ocr_visualization.png` | 번호를 붙인 박스 시각화(점수 0.90 미만은 빨강) |
| `raw/ocr/` | PaddleOCR 원본 출력(`save_to_json`, `save_to_img`) |
| `raw/structure/` | PP-StructureV3 원본 출력(JSON, Markdown, 레이아웃/셀 이미지) |
| `structure_crosscheck.json` | PP-StructureV3와 좌표 복원 결과의 비교 |
| `run_info.json`, `manifest.json` | 환경, 패키지, 실제로 로드된 모델, 설정, 검증 결과, 산출물 목록 |
| `verification_report.json` | `verify.py` 결과 |

## 5. 도구 선택 이유

- **PaddleOCR(PP-OCRv6_medium det/rec, `lang="en"`)를 주 엔진으로 썼다.** 41개 라인을 줄 단위 박스로 정확히 분리했고, 위첨자 2건 말고는 숫자 21개를 모두 맞게 읽었다. 좌표가 정확해서 행·열 배정을 규칙으로 설명하고 재현할 수 있다.
- **PP-StructureV3는 교차 검증용으로만 썼다.** 표 영역과 각주(footer)는 정확히 찾았지만, 셀 구조 결과에 다음 문제가 있어 주 결과로 쓰지 않았다(`structure_crosscheck.json`).
  - 물리적으로 다른 행을 한 셀로 병합했다(`Alaska.... Hawaii..`).
  - 값이 밀렸다. *Military and naval service abroad* 행에 Philippine Islands의 면적 115,026이 들어갔다.
  - 총면적을 `3,743,806`으로 오인식했다. 산술 검산(3,026,789 + 716,517)은 PaddleOCR의 `3,743,306`이 맞다고 보여준다.
- 문서 방향 분류, 왜곡 보정, 텍스트라인 방향 분류는 껐다. 똑바로 놓인 평면 스캔이라 필요 없고, 끄면 결과가 결정적이다.

## 6. 복원 방법

1. **영역 구분**: 첫 숫자 라인 위쪽은 헤더, 마지막 숫자 라인 아래에서 `^\d\s+` 패턴에 맞는 라인은 각주로 본다.
2. **열**: 숫자 라인을 x 중심이 가장 가까운 헤더 열(`Gross area`, `Population`)에 넣는다.
3. **행**: 레이블 라인을 행의 기준으로 삼고, 값은 y 중심이 가장 가까운 행에 붙인다(허용 오차 14px). 배정되지 않은 라인은 0개였다.
4. **계층**: 들여쓰기(x0)와 산술 관계로 정한다. 총계 = 본토 + 해외령이고, 해외령 = 하위 8개 항목의 합이다.
5. **수정 규칙**: 하위 항목 합계가 맞지 않을 때만 동작한다. 선두 숫자가 각주 번호와 같은 값들의 부분집합을 모두 탐색해서, 선두 숫자를 떼어 냈을 때 합계가 **정확히** 맞는 경우를 찾는다. 해가 **유일할 때만** 수정하고, 해가 없거나 여러 개면 원시값을 그대로 두고 `확인 필요`로 표시한다.

## 7. 오류와 한계 (정직한 기록)

| 구분 | 내용 |
|---|---|
| OCR 오류 2건 / 숫자 21개 | 위첨자 각주 기호가 숫자에 합쳐졌다. Philippine Islands `17,635,426` → **7,635,426¹**, Panama Canal Zone `262,810` → **62,810²**. 두 엔진 모두 같은 오류를 냈다. 위 규칙으로 수정했고, 원시값은 CSV `population_raw`와 `review_log.csv`에 남겼다. |
| 형식 정규화 | `101, 115, 487`, `91, 972,266`의 공백을 제거했다(값은 그대로). |
| 공란 | Military and naval service abroad의 면적은 원본에서 점선만 있는 공란이다. OCR이 값을 찾지 못했고, 합계 검증(716,517 일치)도 공란과 들어맞는다. CSV에는 빈 값과 상태 `공란`, Markdown에는 `—`로 표시했다. |
| 확인 필요 | 이번 실행에서는 0건이다. 모든 숫자 셀이 4개 산술 관계로 검증되었고 수동 전사본과도 21/21 일치했다. 다른 이미지에서 합계가 맞지 않거나 수정 해가 여러 개면 자동으로 `확인 필요`가 표시된다. |
| 수동 전사본의 성격 | `src/reference_manual.csv`는 원본 이미지를 사람이 직접 보고 옮긴 검증용 정답이다. 파이프라인 결과를 만드는 데는 쓰지 않고, `verify.py`의 대조에만 쓴다. |
| 일반화 한계 | 헤더 키워드(`Gross area`, `Population`), 3열 구조, 총계/소계 관계는 이 표에 맞춘 규칙이다. 다른 표에 쓰려면 규칙을 고쳐야 한다. 위첨자 판별은 기하 정보가 아니라 산술 관계에 의존하므로, 합계 행이 없는 표에서는 위첨자를 찾지 못한다. |
| 신뢰도 점수 | 가장 낮은 값은 Hawaii 레이블 0.9358, `262,810` 0.9448이다. 점수가 높아도(`17,635,426`은 0.9885) 틀릴 수 있으므로, 점수만으로 판단하지 않고 산술 검증을 함께 썼다. |
| PP-StructureV3 설정 | `use_doc_orientation_classify=False`, `use_doc_unwarping=False`를 넘겼는데도 결과의 `model_settings`에는 `use_doc_preprocessor: true`로 보고되고 방향 분류 모델이 로드된다. 이 출력은 교차 검증에만 써서 최종 결과에는 영향이 없다. |
| 설치 경로 | 공식 Paddle CPU 미러에 연결되지 않아 PyPI에서 같은 버전(3.2.0)을 설치했다(`manifest.json`의 `install_source`). |
| manifest 목록 | `manifest.json`의 `outputs`는 `verify.py`보다 먼저 만들어지므로 `verification_report.json`이 목록에 없다. |

## 8. 검토 단계 (`src/review.py` → `outputs/ocr/review/`)

`reconstruct.py`와는 **다른 규칙**으로 행·열 대응을 다시 계산하고, 두 결과가 다르면 연결 오류 가능성으로 표시한다.

- **열 경계**: 이미지에서 찾은 세로 구분선(x=670, x=855)으로 정한다. 복원 단계는 헤더 박스의 x 중심을 썼다.
- **행 대응**: 값 박스와 레이블 박스의 세로 겹침 비율(기준 0.6 이상)로 정한다. 복원 단계는 y 중심 거리를 썼다.
- **위첨자 판별(기하)**: 숫자 박스의 첫 글자 높이가 숫자 높이 중앙값의 0.45~0.75배이고, 아래 끝이 기준선보다 충분히 위에 있으면 위첨자로 본다. 산술 근거와 별개의 증거다.
- **빈 셀 판정**: 값을 채우지 않는다. 셀 영역에 높이 8px 이상인 잉크가 없을 때만 `공란`으로 판정하고, 하나라도 있으면 `확인 필요`로 둔다.
- **OCR 누락 탐지**: OCR 박스 밖에 있는 글자 크기의 잉크를 찾는다. 괘선이 지나가는 ±4px 띠는 제외한다.
- **엔진 간 비교**: PP-StructureV3와 같은 숫자를 다르게 읽었는지(판독 불일치), 같은 레이블 행에 두지 않았는지(위치 불일치)를 비교한다.
- **상태 판정**: 수정한 값은 위첨자 형태(기하)와 합계 유일해(산술)가 둘 다 성립해야 `수정`으로 인정한다. 하나라도 없으면 `확인 필요`다. 산술로 검증할 수 없고 AI의 육안 대조로만 확인한 항목은 `needs_confirmation.csv`에 **사람 확인 권장** 항목으로 남긴다.

| 파일 | 내용 |
|---|---|
| `review_side_by_side.png` | 왼쪽은 원본(상태별 색 박스와 검출한 열 구분선), 오른쪽은 table.csv를 원본과 같은 높이에 그린 것 |
| `review.html` | 행별 원본 이미지 조각과 CSV 값·OCR 원시값을 나란히 보여 주는 검토 화면(단일 파일) |
| `cell_mapping.csv` | 헤더·레이블·값 전체의 대응, bbox, 열 경계 포함 여부, 세로 겹침, 독립 재배정 일치 여부 |
| `review_items.csv` | 검토 대상(낮은 신뢰도, 숫자 형식 이상, 연결 위험, 엔진 간 불일치, 빈 셀)과 근거, 판정 |
| `corrections.csv` | 수정 전 값, 수정 후 값, 원본 bbox와 폴리곤, OCR 점수, 수정 이유, 근거 |
| `needs_confirmation.csv` | 필수(확인 필요)와 권장 항목. `reviewer_decision`, `reviewer` 열은 사람이 직접 적는다 |
| `review_summary.md` | 최종 검토 요약 |

검토 단계의 한계: 위첨자와 빈 셀 판정은 이 스캔의 글자 크기(숫자 약 16px)에 맞춘 픽셀 임계값을 쓴다. 괘선에서 ±4px 안에 있는 글자는 누락 탐지에서 빠진다.

원본 `input/census-table.png`는 수정하지 않았다(SHA256 `fd72e32c…65f4`, 실행 전후와 검증 단계에서 일치 확인).

## 9. 제출 요약

### 실행 방법

1. 2절 순서대로 `.venv`를 만들고 `paddlepaddle==3.2.0`, `paddleocr[doc-parser]==3.7.0`을 설치한다.
2. `input/census-table.png`를 둔 뒤 PowerShell에서 `.\run_all.ps1`을 실행한다. 첫 실행 때 영어 인식 모델을 자동으로 내려받는다.
3. 결과는 `outputs/ocr/`에 생긴다. `verification_report.json`의 `all_passed`가 `true`면 검증까지 통과한 것이다.

### 결과 화면 (문서화 결과)

| 파일 | 보여 주는 것 |
|---|---|
| `outputs/ocr/review/review_side_by_side.png` | 왼쪽은 원본과 셀 상태별 색 박스, 오른쪽은 복원한 표를 같은 높이로 그린 것 |
| `outputs/ocr/ocr_visualization.png` | OCR 텍스트 박스와 번호. 점수 0.90 미만은 빨간색 |
| `outputs/ocr/review/review.html` | 행마다 원본 이미지 조각, CSV 값, OCR 원시값을 나란히 보여 주는 검토 화면 |

### 원본 대조에서 발견한 오류

- **Philippine Islands / Population: 1910**: 원시 OCR은 `17,635,426`, 원본 대조 후 값은 `7,635,426`이다. 앞의 `1`은 각주 1(Population in 1903)의 위첨자다.
- **Panama Canal Zone / Population: 1910**: 원시 OCR은 `262,810`, 원본 대조 후 값은 `62,810`이다. 앞의 `2`는 각주 2(Population in 1912)의 위첨자다.
- **총계 행·본토 행 / Population**: `101, 115, 487`, `91, 972,266`처럼 쉼표 뒤에 공백이 섞여 읽혔다. 공백만 지웠고 값은 바뀌지 않았다.
- **행 이름 끝의 점선 리더**: `Alaska.`처럼 마침표가 붙어 읽혀서 떼어 냈다.
- **PP-StructureV3(교차 검증용)**: 두 행을 한 셀로 합쳤고, 값 하나를 다른 행으로 밀었고, 총면적을 `3,743,806`으로 잘못 읽었다. 그래서 최종 결과에는 쓰지 않았다.

### "확인 필요"로 남긴 부분

- **필수 확인 필요: 0건.** 모든 숫자 셀이 4개의 합계 관계로 검증되었다.
- **사람 확인 권장: 7건** (`outputs/ocr/review/needs_confirmation.csv`)
  - 값을 바꾼 2칸: Philippine Islands와 Panama Canal Zone의 인구
  - 공란으로 판정한 1칸: Military and naval service abroad의 면적
  - 산술로 검증할 수 없는 레이블·헤더 4개
  - 검토자는 `reviewer_decision`, `reviewer` 열에 판정과 이름을 적는다.

### 예상한 오류와 실제 결과

- **예상**: 과제 설명대로 낡은 인쇄 때문에 숫자 `0`이 알파벳 `O`로 읽히거나, 쉼표가 빠지거나, 들여쓴 행의 값이 다른 행에 붙는 오류를 예상했다.
- **실제 결과**
  - `0`/`O` 혼동과 행 연결 오류는 PaddleOCR 주 결과에서 한 번도 나오지 않았다. 행 연결 오류는 PP-StructureV3에서만 나왔다.
  - 실제로 값을 틀리게 만든 것은 예상하지 못한 **위첨자 각주 번호의 결합**이었다. 이 오류는 OCR 점수가 0.94~0.99로 높게 나와서 신뢰도만 봐서는 찾을 수 없었다.
  - 이 오류를 찾아낸 것은 합계 관계 검산이었다.
- **배운 점**: 오래된 통계표에서는 OCR 점수보다 표 안의 산술 관계가 더 강한 검증 수단이다.

### 제출 링크

- GitHub 저장소: <https://github.com/chj-cog/work005>
