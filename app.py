# -*- coding: utf-8 -*-
"""
통합매매법 v2-4 - KIS API 연동 Streamlit 대시보드
=================================================
로컬에 파이썬 설치 없이, Streamlit Cloud에 올려서 웹에서 바로 확인하는 버전입니다.

배포 방법 요약 (README 참고):
1. 이 파일 + requirements.txt를 GitHub 저장소에 업로드 (웹 브라우저에서 직접 업로드 가능, 설치 불필요)
2. share.streamlit.io 접속 -> GitHub 계정 연동 -> 이 저장소 선택 -> Deploy
3. 앱키/시크릿은 코드에 직접 쓰지 말고, Streamlit Cloud의 "Secrets" 메뉴에 등록해서 사용
"""

import streamlit as st
import requests
import json
import pandas as pd
from datetime import datetime, timedelta
from integrated_analysis import generate_report

st.set_page_config(page_title="통합매매법 KIS 대시보드", layout="wide")

# =========================================================
# 0. 앱키/시크릿 - Streamlit Cloud의 Secrets에서 불러옵니다
#    (Settings -> Secrets 에서 아래처럼 등록)
#    APP_KEY = "..."
#    APP_SECRET = "..."
# =========================================================
try:
    APP_KEY = st.secrets["APP_KEY"]
    APP_SECRET = st.secrets["APP_SECRET"]
    IS_PAPER_TRADING = st.secrets.get("IS_PAPER_TRADING", False)
except Exception:
    st.warning("Secrets가 설정되지 않았습니다. 사이드바에 직접 입력해서 테스트할 수 있습니다.")
    APP_KEY = st.sidebar.text_input("APP KEY", type="password")
    APP_SECRET = st.sidebar.text_input("APP SECRET", type="password")
    IS_PAPER_TRADING = st.sidebar.checkbox("모의투자 사용", value=False)

URL_BASE = (
    "https://openapivts.koreainvestment.com:29443"
    if IS_PAPER_TRADING
    else "https://openapi.koreainvestment.com:9443"
)


# =========================================================
# 1. 인증
# =========================================================
@st.cache_data(ttl=60 * 60 * 12)  # 12시간 캐시 (토큰 재발급 최소화)
def get_access_token(app_key, app_secret, url_base):
    headers = {"content-type": "application/json"}
    body = {"grant_type": "client_credentials", "appkey": app_key, "appsecret": app_secret}
    res = requests.post(f"{url_base}/oauth2/tokenP", headers=headers, data=json.dumps(body))
    res.raise_for_status()
    return res.json()["access_token"]


def auth_headers(token, app_key, app_secret, tr_id):
    return {
        "content-type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": tr_id,
    }


# =========================================================
# 2. 현재가 조회
# =========================================================
def get_current_price(token, stock_code):
    headers = auth_headers(token, APP_KEY, APP_SECRET, "FHKST01010100")
    params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": stock_code}
    res = requests.get(
        f"{URL_BASE}/uapi/domestic-stock/v1/quotations/inquire-price",
        headers=headers, params=params,
    )
    res.raise_for_status()
    return res.json()["output"]


# =========================================================
# 3. 일봉 조회
# =========================================================
def get_daily_ohlcv(token, stock_code, start_date, end_date):
    headers = auth_headers(token, APP_KEY, APP_SECRET, "FHKST03010100")
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": stock_code,
        "FID_INPUT_DATE_1": start_date,
        "FID_INPUT_DATE_2": end_date,
        "FID_PERIOD_DIV_CODE": "D",
        "FID_ORG_ADJ_PRC": "1",
    }
    res = requests.get(
        f"{URL_BASE}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
        headers=headers, params=params,
    )
    res.raise_for_status()
    rows = res.json()["output2"]
    df = pd.DataFrame(rows).rename(columns={
        "stck_bsop_date": "일자", "stck_oprc": "시가", "stck_hgpr": "고가",
        "stck_lwpr": "저가", "stck_clpr": "종가", "acml_vol": "거래량",
    })[["일자", "종가", "시가", "고가", "저가", "거래량"]]
    for c in ["종가", "시가", "고가", "저가", "거래량"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["일자"] = pd.to_datetime(df["일자"], format="%Y%m%d")
    return df.sort_values("일자").reset_index(drop=True)


# =========================================================
# 4. 통합매매법 지표 계산
# =========================================================
def add_indicators(df):
    df = df.copy()
    for p in [5, 10, 20, 60, 120]:
        df[f"MA{p}"] = df["종가"].rolling(p).mean()
    low_min = df["저가"].rolling(14).min()
    high_max = df["고가"].rolling(14).max()
    df["Sto_%K"] = (df["종가"] - low_min) / (high_max - low_min) * 100
    df["Sto_%D"] = df["Sto_%K"].rolling(3).mean()
    ema_fast = df["종가"].ewm(span=12, adjust=False).mean()
    ema_slow = df["종가"].ewm(span=26, adjust=False).mean()
    df["MACD"] = ema_fast - ema_slow
    df["Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["OSC"] = df["MACD"] - df["Signal"]
    return df


def channel_levels(high, low):
    rng = high - low
    return {"0%": low, "25%": low + rng * 0.25, "50%": low + rng * 0.5,
            "75%": low + rng * 0.75, "100%": high}


# =========================================================
# UI
# =========================================================
st.title("📊 통합매매법 v2-4 - KIS 실시간 대시보드")

stock_code = st.text_input("종목코드 입력 (예: 005930 삼성전자, 000810 삼성화재)", value="005930")
days = st.slider("조회 기간 (일)", 30, 180, 60)

if st.button("조회 시작") and APP_KEY and APP_SECRET:
    try:
        token = get_access_token(APP_KEY, APP_SECRET, URL_BASE)

        st.subheader("1. 현재가")
        price_data = get_current_price(token, stock_code)
        col1, col2, col3 = st.columns(3)
        col1.metric("현재가", f"{int(price_data['stck_prpr']):,}원")
        col2.metric("전일대비", f"{price_data.get('prdy_vrss', '-')}")
        col3.metric("등락률", f"{price_data.get('prdy_ctrt', '-')}%")

        st.subheader("2. 일봉 + 지표")
        end = datetime.today().strftime("%Y%m%d")
        start = (datetime.today() - timedelta(days=days)).strftime("%Y%m%d")
        df = get_daily_ohlcv(token, stock_code, start, end)
        df = add_indicators(df)
        st.dataframe(df.tail(20).sort_values("일자", ascending=False), use_container_width=True)

        st.subheader("3. 4등분 채널 (최근 20일 고저 기준)")
        recent = df.tail(20)
        ch = channel_levels(recent["고가"].max(), recent["저가"].min())
        cols = st.columns(5)
        for i, (k, v) in enumerate(ch.items()):
            cols[i].metric(k, f"{v:,.0f}")

        st.subheader("4. 종가 + 이동평균 차트")
        chart_df = df.set_index("일자")[["종가", "MA5", "MA20", "MA60", "MA120"]]
        st.line_chart(chart_df)

        st.subheader("5. Stochastic / MACD")
        c1, c2 = st.columns(2)
        c1.line_chart(df.set_index("일자")[["Sto_%K", "Sto_%D"]])
        c2.line_chart(df.set_index("일자")[["MACD", "Signal"]])

        st.subheader("6. 통합매매법 15항목 자동 분석 (규칙 기반)")
        report_md = generate_report(df.rename(columns={c: c for c in df.columns}),
                                     stock_name=stock_code)
        st.markdown(report_md)

    except Exception as e:
        st.error(f"오류 발생: {e}")
else:
    st.info("종목코드 입력 후 '조회 시작' 버튼을 눌러주세요. (앱키가 없으면 사이드바에 입력)")
