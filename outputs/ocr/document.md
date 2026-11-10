# Table 1 — 면적과 인구 (1910)

> 원문: U.S. Bureau of the Census, *Thirteenth Census of the United States Taken in the Year 1910, Volume I: Population — Table 1 (Area and population)* (1913년 발행)  
> 위치: PDF 2쪽 · 인쇄 22쪽 — <https://www2.census.gov/library/publications/decennial/1910/volume-1/volume-1-p3.pdf>  
> 공유 조건: 퍼블릭 도메인 (미국 연방정부 발행물). 표 영역만 200 dpi로 추출한 이미지 사용  
> 입력 이미지: `input\census-table.png` (사본 `outputs/ocr/census-table.png`, sha256 `fd72e32c16dc0ce4…`)  
> OCR: PaddleOCR 3.7.0 (PP-OCRv6_medium_det, PP-OCRv6_medium_rec), 좌표 기반 행·열 복원

| AREA | Gross area (land and water) in square miles. | Population: 1910 |
|---|---:|---:|
| **United States, with outlying possessions** | 3,743,306 | 101,115,487 |
| United States, exclusive of outlying possessions | 3,026,789 | 91,972,266 |
| Outlying possessions | 716,517 | 9,143,221 |
| &nbsp;&nbsp;&nbsp;&nbsp;Alaska | 590,884 | 64,356 |
| &nbsp;&nbsp;&nbsp;&nbsp;Hawaii | 6,449 | 191,909 |
| &nbsp;&nbsp;&nbsp;&nbsp;Porto Rico | 3,435 | 1,118,012 |
| &nbsp;&nbsp;&nbsp;&nbsp;Military and naval service abroad | — | 55,608 |
| &nbsp;&nbsp;&nbsp;&nbsp;Philippine Islands | 115,026 | 7,635,426<sup>1</sup> |
| &nbsp;&nbsp;&nbsp;&nbsp;Panama Canal Zone | 436 | 62,810<sup>2</sup> |
| &nbsp;&nbsp;&nbsp;&nbsp;Guam (population estimated) | 210 | 9,000 |
| &nbsp;&nbsp;&nbsp;&nbsp;Samoa (population estimated) | 77 | 6,100 |

**각주**

1. Population in 1903.
2. Population in 1912.

## 검증

| 검사 | 기대값 | 계산값 | 결과 |
|---|---:|---:|---|
| area: Outlying possessions = sum(components) | 716,517 | 716,517 | 통과 |
| area: United States, with outlying possessions = United States, exclusive of outlying possessions + Outlying possessions | 3,743,306 | 3,743,306 | 통과 |
| population: Outlying possessions = sum(components) | 9,143,221 | 9,143,221 | 통과 |
| population: United States, with outlying possessions = United States, exclusive of outlying possessions + Outlying possessions | 101,115,487 | 101,115,487 | 통과 |

## 원시값 → 수정값 기록

| 행 | 열 | 원시 OCR | 수정값 | 조치 | 근거 |
|---|---|---|---|---|---|
| 8 Philippine Islands | population | `17,635,426` | `7635426` | 각주 위첨자 분리 | 선두 '1'는 각주 '1 Population in 1903.'의 위첨자로 판단. 분리 시에만 하위 항목 합계가 'Outlying possessions' 값과 정확히 일치(유일해). 원본 이미지 육안 대조로 위첨자 확인. |
| 9 Panama Canal Zone | population | `262,810` | `62810` | 각주 위첨자 분리 | 선두 '2'는 각주 '2 Population in 1912.'의 위첨자로 판단. 분리 시에만 하위 항목 합계가 'Outlying possessions' 값과 정확히 일치(유일해). 원본 이미지 육안 대조로 위첨자 확인. |
| 1 United States, with outlying possessions | population | `101, 115, 487` | `101115487` | 형식 정규화(공백 제거) | 자릿수 그룹 유효, 값 변경 없음 |
| 2 United States, exclusive of outlying possessions | population | `91, 972,266` | `91972266` | 형식 정규화(공백 제거) | 자릿수 그룹 유효, 값 변경 없음 |
| 2 United States, exclusive of outlying possessions | label | `United States, exclusive of outlying possessions.` | `United States, exclusive of outlying possessions` | 점선 리더/마침표 제거 | 표기 정리, 의미 변화 없음 |
| 3 Outlying possessions | label | `Outlying possessions.` | `Outlying possessions` | 점선 리더/마침표 제거 | 표기 정리, 의미 변화 없음 |
| 4 Alaska | label | `Alaska.` | `Alaska` | 점선 리더/마침표 제거 | 표기 정리, 의미 변화 없음 |
| 5 Hawaii | label | `Hawaii.` | `Hawaii` | 점선 리더/마침표 제거 | 표기 정리, 의미 변화 없음 |
| 6 Porto Rico | label | `Porto Rico.` | `Porto Rico` | 점선 리더/마침표 제거 | 표기 정리, 의미 변화 없음 |
| 8 Philippine Islands | label | `Philippine Islands.` | `Philippine Islands` | 점선 리더/마침표 제거 | 표기 정리, 의미 변화 없음 |

## 확인 필요 항목

- 필수 없음 (모든 숫자 셀이 합계 관계로 검증됨)
- 사람 확인 권장 항목(값을 바꾼 2칸, 공란 판정 1칸, 산술 검증이 안 되는 레이블·헤더)은 `review/needs_confirmation.csv`에 행·열·bbox와 함께 정리되어 있다. 원본 위치 표시는 `review/review_side_by_side.png`.

## 비고

- `—` 는 원본에서 점선 리더만 있는 공란(Military and naval service abroad의 면적)이다.
- 행 계층: 들여쓴 8개 항목은 'Outlying possessions'의 하위 항목이며, 첫 행은 본토+해외령 총계다.
- PP-StructureV3 교차 검증 결과는 `structure_crosscheck.json` 참조 (행 병합·값 밀림이 있어 주 결과로 채택하지 않음).
