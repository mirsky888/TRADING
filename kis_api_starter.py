# -*- coding: utf-8 -*-
"""
한국투자증권 KIS Developers API 시작 스크립트
=================================================
- 앱키/앱시크릿만 본인 것으로 채워 넣으면 바로 실행됩니다.
- 처음엔 반드시 모의투자(IS_PAPER_TRADING=True)로 먼저 테스트하세요.
- 필요 패키지: pip install requests pandas --break-system-packages

실행 순서 (하나씩 주석 풀어가며 테스트 권장):
1) get_access_token()          -> 토큰 발급 확인
2) get_current_price()         -> 삼성전자 현재가 조회
3) get_daily_ohlcv()           -> 일봉 데이터 조회 (통합매매법 분석용 표)
4) get_futures_price()         -> KOSPI200 선물 현재가 조회 (종목코드 확인 필요)
"""

import requests
import json
import pandas as pd
from datetime import datetime, timedelta

# =========================================================
# 0. 계정 설정 - 본인 정보로 반드시 교체하세요
# =========================================================
APP_KEY = "여기에_발급받은_앱키_입력"
APP_SECRET = "여기에_발급받은_앱시크릿_입력"

# 모의투자 True / 실전투자 False
IS_PAPER_TRADING = False

URL_BASE = (
    "https://openapivts.koreainvestment.com:29443"  # 모의투자
    if IS_PAPER_TRADING
    else "https://openapi.koreainvestment.com:9443"  # 실전투자
)

# 토큰은 발급 후 24시간 유효 - 캐시해서 재사용 권장 (아래는 간단 버전, 매 실행마다 재발급)
_ACCESS_TOKEN = None


# =========================================================
# 1. 접근토큰 발급
# =========================================================
def get_access_token():
    """OAuth 접근토큰 발급. 모든 API 호출 전에 반드시 먼저 실행."""
    global _ACCESS_TOKEN
    headers = {"content-type": "application/json"}
    body = {
        "grant_type": "client_credentials",
        "appkey": PSo4AeQ1opKjx2cXoMxjYlkLOPZ4DixWrhzW
        "appsecret": yxbndw4btvVbae+DqHJKgxFZdghnNSIGCTpIxtVva6c76P+vsAQX31CNqzPiafADxmCD2DHxQ0MGtePgde6XiZWi1Fvgf/ALvUHv8Eo36DyakIgQxq0nJHlCSgtonX2p1pDZo/Yt1ErfxtrgVCIbzKi17yUTIMjVBvSp2xj9vS2KnuTw5oU=
    }
    res = requests.post(f"{URL_BASE}/oauth2/tokenP", headers=headers, data=json.dumps(body))
    res.raise_for_status()
    _ACCESS_TOKEN = res.json()["access_token"]
    print("[OK] 토큰 발급 성공")
    return _ACCESS_TOKEN


def _auth_headers(tr_id: str) -> dict:
    """공통 인증 헤더 생성. tr_id는 API마다 다른 고유 코드."""
    if _ACCESS_TOKEN is None:
        get_access_token()
    return {
        "content-type": "application/json",
        "authorization": f"Bearer {_ACCESS_TOKEN}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": tr_id,
    }


# =========================================================
# 2. 국내주식 현재가 조회 (감 잡기용 예제 - 삼성전자 등)
# =========================================================
def get_current_price(stock_code: str) -> dict:
    """
    stock_code 예: "005930" (삼성전자), "000810" (삼성화재)
    """
    headers = _auth_headers("FHKST01010100")
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",  # J = 주식
        "FID_INPUT_ISCD": stock_code,
    }
    res = requests.get(
        f"{URL_BASE}/uapi/domestic-stock/v1/quotations/inquire-price",
        headers=headers,
        params=params,
    )
    res.raise_for_status()
    data = res.json()["output"]
    print(f"[{stock_code}] 현재가: {data['stck_prpr']}원 "
          f"(전일대비 {data.get('prdy_vrss', '-')}, {data.get('prdy_ctrt', '-')}%)")
    return data


# =========================================================
# 3. 국내주식 일봉(OHLCV) 조회 - 통합매매법 분석용 핵심 데이터
# =========================================================
def get_daily_ohlcv(stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    start_date, end_date: "YYYYMMDD" 형식
    반환: 일자/시가/고가/저가/종가/거래량 컬럼을 가진 pandas DataFrame
          (지금까지 채팅에 붙여넣던 표와 동일한 구조)
    """
    headers = _auth_headers("FHKST03010100")
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": stock_code,
        "FID_INPUT_DATE_1": start_date,
        "FID_INPUT_DATE_2": end_date,
        "FID_PERIOD_DIV_CODE": "D",  # D=일봉, W=주봉, M=월봉
        "FID_ORG_ADJ_PRC": "1",      # 1=수정주가 반영
    }
    res = requests.get(
        f"{URL_BASE}/uapi/domestic-stock/v1/quotations/inquire-daily-price",
        headers=headers,
        params=params,
    )
    res.raise_for_status()
    rows = res.json()["output"]

    df = pd.DataFrame(rows)
    df = df.rename(columns={
        "stck_bsop_date": "일자",
        "stck_oprc": "시가",
        "stck_hgpr": "고가",
        "stck_lwpr": "저가",
        "stck_clpr": "종가",
        "acml_vol": "거래량",
    })
    cols = ["일자", "종가", "시가", "고가", "저가", "거래량"]
    df = df[cols]

    for c in ["종가", "시가", "고가", "저가", "거래량"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df["일자"] = pd.to_datetime(df["일자"], format="%Y%m%d")
    df = df.sort_values("일자", ascending=False).reset_index(drop=True)
    return df


# =========================================================
# 4. 국내선물옵션 현재가 조회 (KOSPI200 F202609 등)
#    ※ 선물 종목코드는 만기월마다 바뀌므로 정확한 코드는
#      KIS 포털의 "국내선물옵션 마스터 조회" API로 매일 갱신 확인 필요
# =========================================================
def get_futures_price(futures_code: str) -> dict:
    """
    futures_code 예시는 실제 발급 코드 확인 필요 (KIS 포털 마스터파일 참고)
    """
    headers = _auth_headers("FHMIF10000000")
    params = {
        "fid_cond_mrkt_div_code": "F",  # F = 선물
        "fid_input_iscd": futures_code,
    }
    res = requests.get(
        f"{URL_BASE}/uapi/domestic-futureoption/v1/quotations/inquire-price",
        headers=headers,
        params=params,
    )
    res.raise_for_status()
    data = res.json()
    print(data)
    return data


# =========================================================
# 5. 통합매매법 보조 계산 - 이동평균 / 스토캐스틱 / MACD / 4등분채널
#    (지금까지 수동으로 계산해온 로직을 함수화)
# =========================================================
def add_moving_averages(df: pd.DataFrame, price_col: str = "종가") -> pd.DataFrame:
    """일자 오름차순 정렬 후 호출 권장"""
    df = df.sort_values("일자").reset_index(drop=True)
    for period in [5, 10, 20, 60, 120]:
        df[f"MA{period}"] = df[price_col].rolling(period).mean()
    return df


def add_stochastic(df: pd.DataFrame, k_period: int = 14, d_period: int = 3) -> pd.DataFrame:
    df = df.sort_values("일자").reset_index(drop=True)
    low_min = df["저가"].rolling(k_period).min()
    high_max = df["고가"].rolling(k_period).max()
    df["Sto_%K"] = (df["종가"] - low_min) / (high_max - low_min) * 100
    df["Sto_%D"] = df["Sto_%K"].rolling(d_period).mean()
    return df


def add_macd(df: pd.DataFrame, price_col: str = "종가",
             fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    df = df.sort_values("일자").reset_index(drop=True)
    ema_fast = df[price_col].ewm(span=fast, adjust=False).mean()
    ema_slow = df[price_col].ewm(span=slow, adjust=False).mean()
    df["MACD"] = ema_fast - ema_slow
    df["Signal"] = df["MACD"].ewm(span=signal, adjust=False).mean()
    df["OSC"] = df["MACD"] - df["Signal"]
    return df


def calc_channel_levels(high: float, low: float) -> dict:
    """4등분 채널 계산 (통합매매법 2번 항목)"""
    rng = high - low
    return {
        "0%": low,
        "25%": low + rng * 0.25,
        "50%": low + rng * 0.50,
        "75%": low + rng * 0.75,
        "100%": high,
    }


# =========================================================
# 실행 테스트
# =========================================================
if __name__ == "__main__":
    # 1) 토큰 발급 테스트
    get_access_token()

    # 2) 삼성전자 현재가 조회 테스트
    get_current_price("005930")

    # 3) 최근 30일 일봉 조회 + 지표 계산 테스트 (삼성화재 예시)
    end = datetime.today().strftime("%Y%m%d")
    start = (datetime.today() - timedelta(days=30)).strftime("%Y%m%d")

    df = get_daily_ohlcv("000810", start, end)
    df = add_moving_averages(df)
    df = add_stochastic(df)
    df = add_macd(df)

    print(df.tail(10))

    latest_high = df["고가"].tail(20).max()
    latest_low = df["저가"].tail(20).min()
    channel = calc_channel_levels(latest_high, latest_low)
    print("\n최근 20일 4등분 채널:")
    for k, v in channel.items():
        print(f"  {k}: {v:,.0f}")
