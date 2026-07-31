# -*- coding: utf-8 -*-
"""penny_radar 설정. 값만 바꿔서 튜닝하세요."""
import os

# ---------------------------------------------------------------------------
# 텔레그램. 우선순위: 환경변수 -> 아래 값 -> 키움 봇 config에서 자동 재사용
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.environ.get("PENNY_RADAR_TG_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("PENNY_RADAR_TG_CHAT", "")
TELEGRAM_TIMEOUT_SEC = 10

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    # 이미 키움 봇에 넣어둔 토큰을 그대로 재사용 (평문 토큰을 한 곳에만 두기 위함).
    # sys.path + "import config"는 이 파일 자신을 가리키므로 파일 경로로 직접 로드한다.
    try:
        import importlib.util as _ilu

        _path = r"C:\trading_ai\kiwoom_vwap_breakout_auto\config.py"
        _spec = _ilu.spec_from_file_location("_kiwoom_config", _path)
        _mod = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        TELEGRAM_BOT_TOKEN = TELEGRAM_BOT_TOKEN or getattr(_mod, "TELEGRAM_BOT_TOKEN", "")
        TELEGRAM_CHAT_ID = TELEGRAM_CHAT_ID or getattr(_mod, "TELEGRAM_CHAT_ID", "")
    except Exception:
        pass

# ---------------------------------------------------------------------------
# 대상 종목 범위 (동전주 정의)
# ---------------------------------------------------------------------------
MIN_PRICE = 0.15          # 이 아래는 상폐/역분할 위험이 급증해서 제외
MAX_PRICE = 5.00
MIN_AVG_VOLUME = 300_000  # 평균 거래량 하한 (유동성)
# 당일 거래대금 하한($). 이 아래는 호가가 비어 사실상 못 빠져나온다.
# 하한은 낮게 두어 후보를 확보하고, $1M 미만은 "거래대금 얇음" 경고로 표시한다.
MIN_DOLLAR_VOLUME = 300_000

# 소셜/뉴스를 조회할 후보 상한. 늘리면 정확도↑ 속도↓ (종목당 요청 2회)
MAX_CANDIDATES_TO_ENRICH = 25
TOP_N = 10                # 텔레그램으로 보낼 개수

# 외부 요청 간 딜레이(초). 낮추면 빠르지만 차단 위험
REQUEST_DELAY_SEC = 0.5
HTTP_TIMEOUT_SEC = 15

# ---------------------------------------------------------------------------
# Finviz 후보 스크린. 필터 문자열은 Finviz URL의 f= 값과 동일.
# 여러 스크린의 결과를 합집합으로 모은다 (한 스크린이 0건이어도 나머지로 커버).
# ---------------------------------------------------------------------------
FINVIZ_SCREENS = [
    # 거래량이 평소의 1.5배 이상 터지면서 오늘 상승 중인 저가주
    ("relvol_up", "geo_usa,sh_price_u5,sh_relvol_o1.5,ta_perf_dup"),
    # 오늘 +5% 이상 오른 저가주
    ("gainer", "geo_usa,sh_price_u5,ta_perf_d5o"),
    # 갭 상승으로 출발한 저가주 (프리마켓 재료 반영)
    ("gap_up", "geo_usa,sh_price_u5,ta_gap_u3"),
    # 거래량 자체가 폭발한 저가주 (방향 무관 - 재료 발생 신호)
    ("volume_blast", "geo_usa,sh_price_u5,sh_relvol_o3"),
    # 넓은 그물: 오늘 오른 저가주 전반 (거래량 하한으로 잡음 억제)
    ("today_up", "geo_usa,sh_price_u5,sh_avgvol_o300,ta_perf_dup"),
]

# ---------------------------------------------------------------------------
# 점수 가중치 (합계 100). 화제성을 볼 것이냐 실제 수급을 볼 것이냐의 균형.
# ---------------------------------------------------------------------------
W_SOCIAL = 40    # StockTwits 트렌딩/메시지 밀도/관심등록
W_NEWS = 25      # 최근 24시간 뉴스 건수
W_VOLUME = 20    # 평소 대비 거래량 배수
W_MOMENTUM = 15  # 당일 상승률

# 경고 임계값
FLAG_ALREADY_SPIKED_PCT = 100.0  # 이미 이만큼 올랐으면 추격 경고
FLAG_LOW_PRICE = 0.30            # 이 아래는 초저가 경고

# 급락 중인 종목 제외. 뉴스·소셜이 시끄러워도 오늘 이만큼 빠지고 있으면
# "급등 후보"가 아니라 악재 종목이다 (예: 실적 쇼크, 유상증자 발표).
EXCLUDE_BELOW_CHANGE_PCT = -5.0
