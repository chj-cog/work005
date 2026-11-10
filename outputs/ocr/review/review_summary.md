# OCR 검토 요약

- 대상: `input/census-table.png` ↔ `outputs/ocr/table.csv` (11행 × 값 2열 = 22셀)
- 독립 열 경계(이미지 세로 구분선): label < x=670 ≤ area < x=855 ≤ population
- 검토 기준: OCR 점수 < 0.97, 숫자 형식(공백/쉼표 그룹/위첨자), 열 경계 이탈, 레이블과 세로 겹침 < 0.6, 독립 재배정 불일치, 엔진 간 불일치, 빈 셀, OCR 박스 밖 잉크

## 셀 상태

| 상태 | 셀 수 |
|---|---:|
| 검증됨(자동) | 19 |
| 수정 | 2 |
| 공란 | 1 |
| 확인 필요 | 0 |

## 행·열·헤더 대응

- 헤더 7줄 모두 해당 열 경계 안: True
- 레이블 11개 모두 label 열 안: True
- 값 셀 독립 재배정 일치: 22/22
- 레이블과 세로 겹침 최소값: 0.958
- OCR 박스 밖 글자 크기 잉크(누락 가능): 0개

## 검토 대상 항목 (분류별)

| 분류 | 건수 | 항목 |
|---|---:|---|
| 낮은 신뢰도 | 7 | header /label `Table 1`, header /population `Population:`, header /population `1910`, 1 United States, with outlying possessions/population `101, 115, 487`, 2 United States, exclusive of outlying possessions/population `91, 972,266`, 5 Hawaii/label `Hawaii.`, 9 Panama Canal Zone/population `262,810` |
| 엔진 간 판독 불일치 | 1 | 1 United States, with outlying possessions/area `3,743,306` |
| 엔진 간 위치 불일치 | 13 | 1 United States, with outlying possessions/area `3,743,306`, 4 Alaska/area `590,884`, 4 Alaska/population `64,356`, 5 Hawaii/area `6,449`, 5 Hawaii/population `191,909`, 7 Military and naval service abroad/population `55,608`, 8 Philippine Islands/area `115,026`, 8 Philippine Islands/population `17,635,426`, 9 Panama Canal Zone/population `262,810`, 10 Guam (population estimated)/area `210`, 10 Guam (population estimated)/population `9,000`, 11 Samoa (population estimated)/area `77`, 11 Samoa (population estimated)/population `6,100` |
| 숫자 형식 이상 | 4 | 1 United States, with outlying possessions/population `101, 115, 487`, 2 United States, exclusive of outlying possessions/population `91, 972,266`, 8 Philippine Islands/population `17,635,426`, 9 Panama Canal Zone/population `262,810` |
| 빈 셀 / 연결 위험 | 1 | 7 Military and naval service abroad/area `` |

## 수정 전 → 후 (원본 좌표 포함)

| 행 | 열 | 수정 전 | 수정 후 | bbox | 유형 | 이유 |
|---|---|---|---|---|---|---|
| 1 United States, with outlying possessions | population | `101, 115, 487` | `101,115,487` | `[909, 118, 1033, 144]` | 형식 정규화 | 숫자 사이 공백 제거 (값 불변) |
| 2 United States, exclusive of outlying possessions | label | `United States, exclusive of outlying possessions.` | `United States, exclusive of outlying possessions` | `[28, 163, 543, 186]` | 표기 정리 | 끝의 점선 리더/마침표 제거 (의미 변화 없음) |
| 2 United States, exclusive of outlying possessions | population | `91, 972,266` | `91,972,266` | `[922, 163, 1034, 187]` | 형식 정규화 | 숫자 사이 공백 제거 (값 불변) |
| 3 Outlying possessions | label | `Outlying possessions.` | `Outlying possessions` | `[27, 208, 246, 232]` | 표기 정리 | 끝의 점선 리더/마침표 제거 (의미 변화 없음) |
| 4 Alaska | label | `Alaska.` | `Alaska` | `[69, 251, 149, 275]` | 표기 정리 | 끝의 점선 리더/마침표 제거 (의미 변화 없음) |
| 5 Hawaii | label | `Hawaii.` | `Hawaii` | `[68, 273, 152, 298]` | 표기 정리 | 끝의 점선 리더/마침표 제거 (의미 변화 없음) |
| 6 Porto Rico | label | `Porto Rico.` | `Porto Rico` | `[69, 296, 189, 320]` | 표기 정리 | 끝의 점선 리더/마침표 제거 (의미 변화 없음) |
| 8 Philippine Islands | label | `Philippine Islands.` | `Philippine Islands` | `[69, 340, 274, 365]` | 표기 정리 | 끝의 점선 리더/마침표 제거 (의미 변화 없음) |
| 8 Philippine Islands | population | `17,635,426` | `7,635,426 (각주 1)` | `[921, 340, 1035, 365]` | 값 수정 | 선두 '1'은 각주 1의 위첨자 → 값에서 분리 |
| 9 Panama Canal Zone | population | `262,810` | `62,810 (각주 2)` | `[952, 363, 1035, 388]` | 값 수정 | 선두 '2'은 각주 2의 위첨자 → 값에서 분리 |

## 확인 필요

- **필수 0건**, 권장 7건 → `needs_confirmation.csv` (reviewer_decision / reviewer 열에 기록)
  - [권장] 5 Hawaii / label `Hawaii.` → Hawaii: 산술 검증 대상이 아니라 AI의 육안 대조만으로 확인됨
  - [권장] 7 Military and naval service abroad / area `` → 공란: 빈 셀을 공란으로 판정함 — 값이 없음을 사람 확인 권장
  - [권장] 8 Philippine Islands / population `17,635,426` → 7635426: OCR 원시값을 변경함 — 사람 서명 권장
  - [권장] 9 Panama Canal Zone / population `262,810` → 62810: OCR 원시값을 변경함 — 사람 서명 권장
  - [권장] header  / label `Table 1` → Table 1: 산술 검증 대상이 아니라 AI의 육안 대조만으로 확인됨
  - [권장] header  / population `Population:` → Population:: 산술 검증 대상이 아니라 AI의 육안 대조만으로 확인됨
  - [권장] header  / population `1910` → 1910: 산술 검증 대상이 아니라 AI의 육안 대조만으로 확인됨

## 원칙

- 빈 셀은 채우지 않았다. 셀 영역의 픽셀을 검사해 글자가 없음을 확인한 경우에만 `공란`, 아니면 `확인 필요`.
- 값 수정은 기하(위첨자 형태)와 산술(합계 유일해)이 **둘 다** 성립할 때만 `수정`으로 인정, 하나라도 없으면 `확인 필요`.
- `검토 완료(육안)`은 AI가 원본 이미지를 보고 대조한 것이므로 사람 확인을 권장 항목으로 남겼다.
