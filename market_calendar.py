# -*- coding: utf-8 -*-
"""미국 증시(NYSE/NASDAQ) 개장일 판정.

외부 API에 의존하지 않고 규칙으로 계산한다. 휴장일은 연방 공휴일 규칙이
고정되어 있어 계산이 가능하고, 그래야 네트워크 실패로 잘못 발송되는 일이 없다.

주말 조정 규칙(NYSE): 공휴일이 토요일이면 직전 금요일, 일요일이면 다음 월요일 휴장.
※ 조기 폐장일(반나절, 예: 추수감사절 다음날)은 '개장일'로 본다 — 프리마켓은 정상.
"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

US_EASTERN = ZoneInfo("America/New_York")
KST = ZoneInfo("Asia/Seoul")


def easter_sunday(year):
    """부활절 일요일 (Anonymous Gregorian algorithm). Good Friday 계산에 필요."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _nth_weekday(year, month, weekday, n):
    """그 달의 n번째 특정 요일 (weekday: 월=0 … 일=6)."""
    day = date(year, month, 1)
    offset = (weekday - day.weekday()) % 7
    return day + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year, month, weekday):
    """그 달의 마지막 특정 요일."""
    if month == 12:
        day = date(year, 12, 31)
    else:
        day = date(year, month + 1, 1) - timedelta(days=1)
    return day - timedelta(days=(day.weekday() - weekday) % 7)


def _observed(day):
    """고정일 공휴일의 주말 조정."""
    if day.weekday() == 5:      # 토요일 -> 직전 금요일
        return day - timedelta(days=1)
    if day.weekday() == 6:      # 일요일 -> 다음 월요일
        return day + timedelta(days=1)
    return day


def nyse_holidays(year):
    """해당 연도의 NYSE 정규 휴장일 {date: 이름}."""
    holidays = {
        _observed(date(year, 1, 1)): "신정",
        _nth_weekday(year, 1, 0, 3): "마틴 루터 킹 데이",
        _nth_weekday(year, 2, 0, 3): "대통령의 날",
        easter_sunday(year) - timedelta(days=2): "성금요일",
        _last_weekday(year, 5, 0): "메모리얼 데이",
        _observed(date(year, 6, 19)): "준틴스",
        _observed(date(year, 7, 4)): "독립기념일",
        _nth_weekday(year, 9, 0, 1): "노동절",
        _nth_weekday(year, 11, 3, 4): "추수감사절",
        _observed(date(year, 12, 25)): "크리스마스",
    }
    return holidays


def us_today():
    """미국 동부 기준 오늘 날짜 (한국 18~20시 실행 시점에는 미국도 같은 날짜)."""
    return datetime.now(US_EASTERN).date()


def market_status(day=None):
    """(개장일 여부, 사유) 반환."""
    day = day or us_today()
    if day.weekday() == 5:
        return False, "토요일 (주말 휴장)"
    if day.weekday() == 6:
        return False, "일요일 (주말 휴장)"
    holiday = nyse_holidays(day.year).get(day)
    if holiday:
        return False, f"{holiday} (미국 증시 휴장)"
    return True, "개장일"


def is_trading_day(day=None):
    return market_status(day)[0]


if __name__ == "__main__":
    today = us_today()
    trading, reason = market_status(today)
    print(f"미국 동부 기준 오늘: {today} ({'개장' if trading else '휴장'}) - {reason}")
    print(f"\n{today.year}년 휴장일:")
    for holiday_date, name in sorted(nyse_holidays(today.year).items()):
        weekday = "월화수목금토일"[holiday_date.weekday()]
        print(f"  {holiday_date} ({weekday}) {name}")
