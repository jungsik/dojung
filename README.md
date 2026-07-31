# penny_radar — 미국 동전주 화제성 레이더

미국 저가주($0.15~$5) 중 **지금 소셜·뉴스에서 거론되고 있고 + 거래량이 실제로 터진** 종목을
점수순으로 추려 **텔레그램으로 보내는** 스캐너.

> ⚠️ **이 프로그램은 "오늘 급등할 종목"을 예측하지 않습니다. 그건 불가능합니다.**
> 결과는 **매수 추천이 아니라 관찰 리스트**입니다. 소셜에서 화제인 동전주는
> 펌프앤덤프·상장폐지 위험이 매우 큽니다. 화제성 순위 ≠ 주가 상승.

---

## 자동 실행 (GitHub Actions) ⭐

PC를 켜둘 필요 없이 **평일 한국시간 18:03 / 20:03에 자동 발송**됩니다.
(정각은 GitHub 전체가 붐벼 지연되므로 3분 비켜서 예약)

- 워크플로: `.github/workflows/penny_radar.yml`
- **미국 증시 휴장일이면 아무것도 보내지 않습니다** — 주말 + 연방 공휴일 10종을
  `market_calendar.py`가 미국 동부 날짜 기준으로 판정 (성금요일·대체휴일 포함).
- 수동 실행: 저장소 **Actions 탭 → penny radar → Run workflow** (휴장일 강제/드라이런 옵션 제공)
- 결과 CSV는 실행 아티팩트로 14일 보관됩니다.

### 최초 1회 설정 — 텔레그램 시크릿 등록
저장소에 토큰을 커밋하면 안 되므로 **GitHub Secrets**에 넣습니다.

```bash
gh secret set PENNY_RADAR_TG_TOKEN --repo jungsik/dojung
gh secret set PENNY_RADAR_TG_CHAT  --repo jungsik/dojung
```

실행하면 값을 물어봅니다. 값은 로컬 `C:\trading_ai\kiwoom_vwap_breakout_auto\config.py`의
`TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`와 같은 것을 쓰면 됩니다.
(웹에서 하려면 Settings → Secrets and variables → Actions → New repository secret)

---

## 수동 실행 (로컬)

```bash
cd C:/trading_ai/penny_radar
C:/trading_ai/venv/Scripts/python.exe penny_radar.py         # 스캔 + 텔레그램 발송
C:/trading_ai/venv/Scripts/python.exe penny_radar.py --dry   # 콘솔 확인만 (발송 X)
C:/trading_ai/venv/Scripts/python.exe penny_radar.py --top 15
C:/trading_ai/venv/Scripts/python.exe penny_radar.py --force # 휴장일에도 강제 실행
```

또는 **`run_radar.bat` 더블클릭**. 소요 시간 1~2분(종목당 외부 요청 2회).

로컬 실행 시 텔레그램 토큰은 환경변수가 없으면 키움 봇 `config.py`에서 자동으로 재사용합니다.

### 언제 돌리면 좋은가 (한국 시간)
| 시간대 | 미국장 | 효과 |
|---|---|---|
| **17:00~22:30** | 프리마켓 | ⭐ 최적 — 당일 재료가 막 반영되는 구간 |
| 22:30~05:00 | 정규장 | 실시간 급등주 포착 |
| 06:00~16:00 | 마감 후 | 전일 종가 기준이라 후보가 적음 |

---

## 데이터 소스 (모두 무료·무인증)

| 소스 | 쓰는 것 |
|---|---|
| **Finviz screener** | 가격·거래량·상대거래량·등락률 (후보 수집) |
| **StockTwits** | 트렌딩 심볼, 관심등록 수, **메시지 속도(건/시간)** |
| **Google News RSS** | 티커별 최근 24시간 뉴스 건수 + 최신 헤드라인 |

### ❌ 쓸 수 없는 것 (솔직히)
- **트위터/X**: 무료 API가 사실상 없어짐(유료 전용) → 불가
- **Reddit**: 무인증 JSON이 403으로 차단됨(OAuth 앱 등록 필요) → 현재 미사용

즉 "트위터에서 화제"는 대신 **StockTwits**(미국 주식 전용 소셜)로 커버합니다.
실제로 페니스톡 화제성은 StockTwits가 트위터보다 신호가 정확한 편입니다.

---

## 점수 (100점 만점)

| 항목 | 배점 | 측정 |
|---|---|---|
| **소셜** | 40 | StockTwits 트렌딩 포함(15) + 메시지 속도(15) + 관심등록 수(10) |
| **뉴스** | 25 | 최근 24시간 뉴스 건수 (6건이면 만점) |
| **거래량** | 20 | 평소 대비 배수(Rel Volume). 10배면 만점 |
| **모멘텀** | 15 | 당일 상승률. +30%면 만점 |

> **메시지 "속도"를 쓰는 이유**: StockTwits API는 최근 30개만 돌려주므로 단순 건수는
> 활발한 종목이 전부 30으로 붙어 변별이 안 됩니다. 그래서 그 30개가 쌓이는 데 걸린
> 시간을 재서 **시간당 메시지 수**로 환산합니다 (조용한 종목 1.7건/h vs 폭발 103건/h).

### 자동 경고 (⚠️로 표시)
- `초저가` — $0.30 미만 (역분할·상폐 위험)
- `이미 +100% 폭등` — 추격 위험
- `거래대금 얇음` — 못 빠져나올 수 있음
- `재료 불명` — 뉴스도 없고 트렌딩도 아닌데 오른 것 (작전 의심)
- 레버리지/인버스 **ETF는 자동 제외** (주식이 아님)

---

## 설정 (`config.py`)

```python
MIN_PRICE / MAX_PRICE      = 0.15 / 5.00     # 동전주 범위
MIN_DOLLAR_VOLUME          = 300_000         # 거래대금 하한
MAX_CANDIDATES_TO_ENRICH   = 25              # 소셜·뉴스 조회할 후보 수(속도 ↔ 정확도)
TOP_N                      = 10              # 발송 개수
W_SOCIAL/W_NEWS/W_VOLUME/W_MOMENTUM = 40/25/20/15   # 가중치
FINVIZ_SCREENS             = [...]           # 후보 수집 스크린 (합집합)
```

**텔레그램**: 환경변수 `PENNY_RADAR_TG_TOKEN`/`PENNY_RADAR_TG_CHAT` → 없으면
`config.py` 값 → 그래도 없으면 **키움 봇 config의 토큰을 자동 재사용**합니다
(평문 토큰을 한 곳에만 두기 위함).

---

## 산출물
`reports/radar_YYYYMMDD_HHMM.csv` — 상위 후보 전체 + 점수 분해(social/news/volume/momentum) + 경고.
나중에 "점수 높았던 종목이 실제로 올랐나"를 검증할 수 있게 매 실행분을 남깁니다.

---

## 구현 메모
- **Finviz 티커 파싱**: finvizfinance 1.3.0은 현재 Finviz HTML에서 티커 첫 글자를
  중복시킵니다(`MGRX` → `MMGRX`). 이 프로그램은 셀의 `data-boxover-ticker` 속성에서
  직접 읽어 정확한 티커를 얻습니다. (같은 버그가 `C:\trading_ai\finviz_screener`에도
  영향을 줄 수 있음)
- Finviz 뷰 번호: Overview=111, Valuation=121, Ownership=131, **Performance=141**, Financial=161, Technical=171
- 한 스크린이 실패해도 나머지로 계속 진행합니다(부분 실패 내성).
