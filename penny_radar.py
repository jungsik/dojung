# -*- coding: utf-8 -*-
"""
penny_radar — 미국 동전주 화제성 레이더

이 프로그램은 "오늘 급등할 종목"을 예측하지 않습니다(그건 불가능합니다).
지금 이 순간 ① 소셜/뉴스에서 실제로 거론되고 있고 ② 거래량이 평소보다
터지고 있는 저가주를 점수순으로 추려 텔레그램으로 보내는 스캐너입니다.
결과는 매수 추천이 아니라 관찰 리스트입니다.

데이터 소스 (모두 무료·무인증):
  - Finviz screener : 가격/거래량/상대거래량/등락률 (후보 수집)
  - StockTwits      : 트렌딩 심볼, 관심등록 수, 최근 메시지 밀도 (소셜)
  - Google News RSS : 티커별 최근 24시간 뉴스 건수/헤드라인 (뉴스)

사용법:
  python penny_radar.py            # 스캔 후 텔레그램 발송
  python penny_radar.py --dry      # 콘솔 출력만 (발송 안 함)
  python penny_radar.py --top 15   # 상위 15개
"""
import argparse
import csv
import math
import re
import sys
import time
import warnings
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

warnings.filterwarnings("ignore")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

from config import (
    EXCLUDE_BELOW_CHANGE_PCT,
    FINVIZ_SCREENS,
    FLAG_ALREADY_SPIKED_PCT,
    FLAG_LOW_PRICE,
    HTTP_TIMEOUT_SEC,
    MAX_CANDIDATES_TO_ENRICH,
    MAX_PRICE,
    MIN_AVG_VOLUME,
    MIN_DOLLAR_VOLUME,
    MIN_PRICE,
    REQUEST_DELAY_SEC,
    TOP_N,
    W_MOMENTUM,
    W_NEWS,
    W_SOCIAL,
    W_VOLUME,
)
from market_calendar import KST, market_status
from telegram_notifier import TelegramNotifier

REPORT_DIR = Path(__file__).resolve().parent / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

# 레버리지/인버스 ETF·ETN 등 "주식이 아닌 것" 제외용
NON_STOCK_PAT = re.compile(
    r"\b(ETF|ETN|2X|3X|-1X|-2X|Daily|Leverage|Leveraged|Inverse|Ultra(Short|Pro)?)\b",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------
# 파싱 헬퍼
# --------------------------------------------------------------------------
def to_num(value):
    """'13,743,995' / '83.92%' / '9.25M' / '-' -> float 또는 None"""
    if value is None:
        return None
    s = str(value).strip().replace(",", "").replace("%", "")
    if s in ("", "-", "nan", "None"):
        return None
    mult = 1.0
    if s and s[-1] in "KMBT":
        mult = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[s[-1]]
        s = s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return None


def fmt_money(value):
    if value is None:
        return "-"
    if value >= 1e9:
        return f"${value/1e9:.1f}B"
    if value >= 1e6:
        return f"${value/1e6:.1f}M"
    if value >= 1e3:
        return f"${value/1e3:.0f}K"
    return f"${value:.0f}"


# --------------------------------------------------------------------------
# Finviz — 자체 파서
#   finvizfinance 1.3.0의 테이블 파서는 Finviz의 현재 HTML에서 티커 첫 글자를
#   중복시킨다(MGRX -> MMGRX). 진짜 티커는 셀의 data-boxover-ticker 속성에
#   들어있으므로 여기서 직접 읽는다.
# --------------------------------------------------------------------------
def _parse_screener_table(soup):
    table = soup.find("table", class_="screener_table")
    if table is None:
        return []
    rows = table.find_all("tr")
    if not rows:
        return []
    headers = [th.get_text(strip=True) for th in rows[0].find_all("th")]
    records = []
    for row in rows[1:]:
        cells = row.find_all("td")
        if len(cells) < 3:
            continue
        ticker = None
        for cell in cells:
            if cell.get("data-boxover-ticker"):
                ticker = cell["data-boxover-ticker"].strip()
                break
        if not ticker:
            link = row.find("a", href=True)
            if link and "t=" in link["href"]:
                ticker = link["href"].split("t=")[1].split("&")[0].strip()
        if not ticker:
            continue
        record = dict(zip(headers, [c.get_text(strip=True) for c in cells]))
        record["Ticker"] = ticker
        records.append(record)
    return records


def finviz_fetch(params):
    from finvizfinance.util import web_scrap  # 세션/헤더 처리를 재사용

    soup = web_scrap("https://finviz.com/screener.ashx", params)
    return _parse_screener_table(soup)


def finviz_screen(filter_str, view=111, pages=2):
    """스크린 결과. Finviz는 한 페이지에 20종목이라 pages만큼 이어서 가져온다."""
    records = []
    for page in range(pages):
        params = {"v": view, "f": filter_str}
        if page:
            params["r"] = page * 20 + 1
        chunk = finviz_fetch(params)
        if not chunk:
            break
        records.extend(chunk)
        if len(chunk) < 20:
            break
        time.sleep(REQUEST_DELAY_SEC)
    return records


def finviz_quotes(tickers, view=111):
    """티커 목록의 시세를 한 번의 요청으로 조회 (t= 파라미터)."""
    if not tickers:
        return []
    return finviz_fetch({"v": view, "t": ",".join(tickers[:100])})


# --------------------------------------------------------------------------
# StockTwits — 소셜 화제성
# --------------------------------------------------------------------------
def stocktwits_trending():
    url = "https://api.stocktwits.com/api/2/trending/symbols.json"
    try:
        response = requests.get(url, headers=UA, timeout=HTTP_TIMEOUT_SEC)
        if response.status_code != 200:
            return set()
        return {s.get("symbol", "").upper() for s in response.json().get("symbols", [])}
    except Exception as exc:
        print(f"  [ST] trending 실패: {type(exc).__name__}")
        return set()


def stocktwits_symbol(ticker):
    """관심등록 수 + 메시지 '속도'를 반환.

    API가 최근 30개만 돌려주므로 단순 개수는 활발한 종목이 전부 30으로 붙어
    변별력이 없다. 대신 그 30개가 쌓이는 데 걸린 시간을 재서 시간당 메시지 수
    (msgs_per_hour)를 구한다 -- 이게 실제 화제성의 세기다.
    """
    url = f"https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"
    out = {"watchers": None, "msgs_24h": 0, "msgs_1h": 0, "msgs_per_hour": 0.0}
    try:
        response = requests.get(url, headers=UA, timeout=HTTP_TIMEOUT_SEC)
        if response.status_code != 200:
            return out
        data = response.json()
        out["watchers"] = data.get("symbol", {}).get("watchlist_count")
        now = datetime.now(timezone.utc)
        stamps = []
        for message in data.get("messages", []):
            stamp = message.get("created_at")
            if not stamp:
                continue
            try:
                created = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            stamps.append(created)
            age = now - created
            if age <= timedelta(hours=24):
                out["msgs_24h"] += 1
            if age <= timedelta(hours=1):
                out["msgs_1h"] += 1
        if len(stamps) >= 2:
            span_h = (max(stamps) - min(stamps)).total_seconds() / 3600.0
            out["msgs_per_hour"] = round(len(stamps) / span_h, 2) if span_h > 0.05 else float(len(stamps))
    except Exception:
        pass
    return out


# --------------------------------------------------------------------------
# Google News RSS — 뉴스 화제성
# --------------------------------------------------------------------------
def google_news(ticker, hours=24):
    """최근 `hours` 시간 내 뉴스 건수와 최신 헤드라인."""
    query = f"%22{ticker}%22+stock"
    url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
    out = {"news_24h": 0, "headline": "", "headline_age_h": None}
    try:
        response = requests.get(url, headers=UA, timeout=HTTP_TIMEOUT_SEC)
        if response.status_code != 200:
            return out
        root = ET.fromstring(response.content)
        now = datetime.now(timezone.utc)
        newest = None
        for item in root.findall(".//item"):
            pub = item.findtext("pubDate")
            if not pub:
                continue
            try:
                published = datetime.strptime(pub, "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            age_h = (now - published).total_seconds() / 3600.0
            if age_h <= hours:
                out["news_24h"] += 1
                if newest is None or age_h < newest:
                    newest = age_h
                    out["headline"] = (item.findtext("title") or "").strip()
                    out["headline_age_h"] = age_h
    except Exception:
        pass
    return out


# --------------------------------------------------------------------------
# 점수 / 경고
# --------------------------------------------------------------------------
def _scale(value, low, high, cap):
    """value가 low->high로 갈 때 0->cap 으로 선형 증가."""
    if value is None or value <= low:
        return 0.0
    return min(cap, cap * (value - low) / float(high - low))


def score_row(row):
    social = 0.0
    if row.get("in_trending"):
        social += 15.0
    # 개수가 아니라 속도로 잰다 (API가 30개에서 잘리므로) — 시간당 8건이면 만점
    social += _scale(row.get("msgs_per_hour"), 0.2, 8.0, 15.0)
    watchers = row.get("watchers")
    if watchers:
        social += min(10.0, 10.0 * math.log10(max(watchers, 1)) / 5.0)  # 100,000명에서 만점
    social = min(social, 40.0) * (W_SOCIAL / 40.0)

    news_count = row.get("news_24h") or 0
    news = min(25.0, 25.0 * min(news_count, 6) / 6.0) * (W_NEWS / 25.0)

    volume = _scale(row.get("rel_volume"), 1.0, 10.0, 20.0) * (W_VOLUME / 20.0)

    change = row.get("change_pct")
    momentum = _scale(change, 0.0, 30.0, 15.0) * (W_MOMENTUM / 15.0)

    total = social + news + volume + momentum
    return round(total, 1), {
        "social": round(social, 1),
        "news": round(news, 1),
        "volume": round(volume, 1),
        "momentum": round(momentum, 1),
    }


def flags_for(row):
    flags = []
    price = row.get("price")
    change = row.get("change_pct")
    dollar_volume = row.get("dollar_volume")
    if price is not None and price < FLAG_LOW_PRICE:
        flags.append(f"초저가 ${price:.2f}")
    if change is not None and change >= FLAG_ALREADY_SPIKED_PCT:
        flags.append(f"이미 +{change:.0f}% 폭등")
    if dollar_volume is not None and dollar_volume < MIN_DOLLAR_VOLUME * 3:
        flags.append("거래대금 얇음")
    if (row.get("news_24h") or 0) == 0 and not row.get("in_trending"):
        flags.append("재료 불명")
    rel = row.get("rel_volume")
    if rel is not None and rel < 1.0:
        # 화제성만 높고 실제 수급은 평소보다 조용한 경우 (뉴스만 많은 인기주)
        flags.append(f"거래량 평소 이하 {rel:.1f}x")
    return flags


# --------------------------------------------------------------------------
# 수집 파이프라인
# --------------------------------------------------------------------------
def collect_candidates():
    """Finviz 스크린 합집합 + StockTwits 트렌딩 중 저가주."""
    seen = {}
    for name, filter_str in FINVIZ_SCREENS:
        try:
            rows = finviz_screen(filter_str)
            print(f"  [finviz:{name}] {len(rows)}건")
        except Exception as exc:
            print(f"  [finviz:{name}] 실패 {type(exc).__name__}: {exc}")
            rows = []
        for row in rows:
            seen.setdefault(row["Ticker"], row)
        time.sleep(REQUEST_DELAY_SEC)

    trending = stocktwits_trending()
    print(f"  [stocktwits] 트렌딩 {len(trending)}개")
    # 트렌딩 중 아직 후보에 없는 심볼의 시세를 한 번에 조회해 저가주만 편입
    extra = [t for t in sorted(trending) if t and t not in seen and t.isalpha()]
    if extra:
        try:
            for row in finviz_quotes(extra):
                seen.setdefault(row["Ticker"], row)
            print(f"  [finviz:trending] {len(extra)}개 시세 조회")
        except Exception as exc:
            print(f"  [finviz:trending] 실패 {type(exc).__name__}")
    return seen, trending


def normalize(raw_rows, trending):
    """Finviz 원본 행 -> 통일된 dict + 기본 필터."""
    out = []
    for ticker, row in raw_rows.items():
        company = row.get("Company", "")
        industry = row.get("Industry", "")
        if NON_STOCK_PAT.search(company) or "Exchange Traded" in industry:
            continue  # 레버리지/인버스 ETF 등은 주식이 아님
        price = to_num(row.get("Price"))
        change = to_num(row.get("Change"))
        volume = to_num(row.get("Volume"))
        if price is None or not (MIN_PRICE <= price <= MAX_PRICE):
            continue
        if change is not None and change < EXCLUDE_BELOW_CHANGE_PCT:
            continue  # 급락 중 = 급등 후보가 아니라 악재 종목
        dollar_volume = (price * volume) if (price and volume) else None
        if dollar_volume is not None and dollar_volume < MIN_DOLLAR_VOLUME:
            continue
        out.append(
            {
                "ticker": ticker,
                "company": company,
                "sector": row.get("Sector", ""),
                "price": price,
                "change_pct": change,
                "volume": volume,
                "dollar_volume": dollar_volume,
                "in_trending": ticker in trending,
            }
        )
    return out


def add_relative_volume(rows):
    """Performance 뷰(v=141)에서 Rel Volume / Avg Volume 을 붙인다."""
    tickers = [r["ticker"] for r in rows]
    lookup = {}
    for chunk_start in range(0, len(tickers), 50):
        chunk = tickers[chunk_start:chunk_start + 50]
        try:
            for row in finviz_quotes(chunk, view=141):
                lookup[row["Ticker"]] = row
        except Exception as exc:
            print(f"  [finviz:relvol] 실패 {type(exc).__name__}")
        time.sleep(REQUEST_DELAY_SEC)
    for row in rows:
        source = lookup.get(row["ticker"], {})
        rel = to_num(source.get("Rel Volume"))
        avg = to_num(source.get("Avg Volume"))
        if rel is None and avg and row.get("volume"):
            rel = row["volume"] / avg if avg else None
        row["rel_volume"] = rel
        row["avg_volume"] = avg
    return rows


def enrich(rows):
    """상위 후보에 소셜·뉴스를 붙인다 (종목당 요청 2회)."""
    total = len(rows)
    for index, row in enumerate(rows, 1):
        ticker = row["ticker"]
        social = stocktwits_symbol(ticker)
        row.update(social)
        time.sleep(REQUEST_DELAY_SEC)
        row.update(google_news(ticker))
        time.sleep(REQUEST_DELAY_SEC)
        print(f"  [{index:2}/{total}] {ticker:6} 뉴스{row.get('news_24h',0):2}건 "
              f"ST {row.get('msgs_per_hour',0):5.1f}건/h 관심{row.get('watchers') or 0:,}명")
    return rows


# --------------------------------------------------------------------------
# 출력
# --------------------------------------------------------------------------
def build_message(rows, generated_at):
    lines = [
        f"📡 페니레이더 {generated_at:%Y-%m-%d %H:%M} KST",
        f"미국 동전주 화제성 TOP {len(rows)} (${MIN_PRICE:.2f}~${MAX_PRICE:.0f})",
        "",
    ]
    for rank, row in enumerate(rows, 1):
        change = row.get("change_pct")
        change_text = f"{change:+.1f}%" if change is not None else "-"
        rel = row.get("rel_volume")
        rel_text = f"{rel:.1f}x" if rel else "-"
        lines.append(f"{rank}. ${row['ticker']} {row['price']:.2f} {change_text} · {row['score']}점")
        lines.append(f"   {row['company'][:34]}")
        detail = (f"   📰{row.get('news_24h',0)}건 "
                  f"💬{row.get('msgs_per_hour',0):.1f}건/h "
                  f"👀{(row.get('watchers') or 0):,} "
                  f"📊거래량 {rel_text} · {fmt_money(row.get('dollar_volume'))}")
        if row.get("in_trending"):
            detail += " 🔥트렌딩"
        lines.append(detail)
        headline = row.get("headline")
        if headline:
            age = row.get("headline_age_h")
            age_text = f"{age:.0f}h전" if age is not None else ""
            lines.append(f"   \"{headline[:70]}\" {age_text}")
        if row.get("flags"):
            lines.append(f"   ⚠️ {' · '.join(row['flags'])}")
        lines.append("")
    lines.append("─────────────")
    lines.append("⚠️ 매수 추천이 아닙니다. 소셜에서 화제인 동전주는")
    lines.append("펌프앤덤프·상장폐지 위험이 매우 큽니다. 화제성 순위일 뿐")
    lines.append("주가가 오른다는 뜻이 아닙니다.")
    return "\n".join(lines)


def save_csv(rows, generated_at):
    path = REPORT_DIR / f"radar_{generated_at:%Y%m%d_%H%M}.csv"
    columns = ["rank", "ticker", "company", "sector", "price", "change_pct", "volume",
               "dollar_volume", "rel_volume", "avg_volume", "in_trending", "watchers",
               "msgs_per_hour", "msgs_24h", "msgs_1h", "news_24h", "headline", "score",
               "score_social", "score_news", "score_volume", "score_momentum", "flags"]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for rank, row in enumerate(rows, 1):
            parts = row.get("score_parts", {})
            writer.writerow({
                "rank": rank,
                "ticker": row["ticker"],
                "company": row["company"],
                "sector": row.get("sector", ""),
                "price": row.get("price"),
                "change_pct": row.get("change_pct"),
                "volume": row.get("volume"),
                "dollar_volume": row.get("dollar_volume"),
                "rel_volume": row.get("rel_volume"),
                "avg_volume": row.get("avg_volume"),
                "in_trending": row.get("in_trending"),
                "watchers": row.get("watchers"),
                "msgs_per_hour": row.get("msgs_per_hour"),
                "msgs_24h": row.get("msgs_24h"),
                "msgs_1h": row.get("msgs_1h"),
                "news_24h": row.get("news_24h"),
                "headline": row.get("headline", ""),
                "score": row.get("score"),
                "score_social": parts.get("social"),
                "score_news": parts.get("news"),
                "score_volume": parts.get("volume"),
                "score_momentum": parts.get("momentum"),
                "flags": " | ".join(row.get("flags", [])),
            })
    return path


# --------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="미국 동전주 화제성 레이더")
    parser.add_argument("--dry", action="store_true", help="텔레그램 발송 없이 콘솔 출력만")
    parser.add_argument("--top", type=int, default=TOP_N, help=f"상위 N개 (기본 {TOP_N})")
    parser.add_argument("--force", action="store_true", help="휴장일에도 강제 실행")
    args = parser.parse_args()

    # GitHub Actions 러너는 UTC로 도므로 항상 KST로 명시해서 찍는다
    # (안 그러면 메시지에 "09:43 KST"처럼 9시간 어긋난 시각이 나간다).
    generated_at = datetime.now(KST)
    print(f"=== penny_radar {generated_at:%Y-%m-%d %H:%M:%S} KST ===")

    # 미국 증시가 쉬는 날에는 스캔도 발송도 하지 않는다. 휴장일 데이터는 전일
    # 종가가 그대로 남아 있어 "오늘의 급등주"로 오해할 여지가 있다.
    trading, reason = market_status()
    print(f"미국 증시: {reason}")
    if not trading and not args.force:
        print("휴장일이므로 스캔/발송을 건너뜁니다. (--force 로 무시 가능)")
        return

    print("[1/5] 후보 수집")
    raw_rows, trending = collect_candidates()
    rows = normalize(raw_rows, trending)
    print(f"  -> 가격/유동성 필터 통과: {len(rows)}종목")
    if not rows:
        print("조건에 맞는 동전주가 없습니다 (장 마감 직후이거나 시장이 조용한 상태).")
        return

    print("[2/5] 상대거래량 조회")
    rows = add_relative_volume(rows)

    # 소셜/뉴스 조회는 비싸므로 먼저 거래량·등락률로 압축
    rows.sort(key=lambda r: ((r.get("rel_volume") or 0), (r.get("change_pct") or 0)), reverse=True)
    rows = rows[:MAX_CANDIDATES_TO_ENRICH]
    print(f"[3/5] 소셜·뉴스 조회 ({len(rows)}종목)")
    rows = enrich(rows)

    print("[4/5] 점수화")
    for row in rows:
        row["score"], row["score_parts"] = score_row(row)
        row["flags"] = flags_for(row)
    rows.sort(key=lambda r: r["score"], reverse=True)
    top = rows[:args.top]

    message = build_message(top, generated_at)
    path = save_csv(rows, generated_at)
    print(message)
    print(f"\n[5/5] CSV 저장 -> {path}")

    if args.dry:
        print("(--dry: 텔레그램 발송 생략)")
        return
    notifier = TelegramNotifier()
    if not notifier.enabled:
        print("텔레그램 토큰/챗ID가 없어 발송을 건너뜁니다. config.py 확인.")
        return
    print("텔레그램 발송:", "성공" if notifier.send(message) else "실패")


if __name__ == "__main__":
    main()
