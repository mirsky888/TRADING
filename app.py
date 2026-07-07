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
#    APP_KEY = "PSMASpQKNi6pFrOKWAksNJafC0Iree9GWA4s"
#    APP_SECRET = "zgJPXDmrSO6OltPRNE5kdTgouqDX1waPfmkn4e98XK6OcSsx/XUQnrjGqjTPy6sqcO58pgdAw3qbOZK+xg9DF0eS4bh0vPBeU1Qu3SgsueBmGUJ/Ulwq3G95cnqgBgz8vvzj9315TFwYjuwxamLfz6W+ikNdmIe3OkOtg2XDvq+RjZZlBKc="
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
# 3-1. 국내선물옵션 일봉 조회 (KOSPI200 선물 등)
#   ※ tr_id/파라미터는 KIS 공식 API 가이드의
#     "[국내선물옵션] 기본시세 > 선물옵션기간별시세(일/주/월/년)" 문서 기준으로
#     작성했습니다. 실행 시 오류가 나면 이 문서를 열어 정확한 값으로
#     맞춰주셔야 할 수 있습니다 (특히 FID_COND_MRKT_DIV_CODE 값).
# =========================================================
def get_futures_daily_ohlcv(token, futures_code, start_date, end_date):
    headers = auth_headers(token, APP_KEY, APP_SECRET, "FHKIF03020100")
    params = {
        "FID_COND_MRKT_DIV_CODE": "F",
        "FID_INPUT_ISCD": futures_code,
        "FID_INPUT_DATE_1": start_date,
        "FID_INPUT_DATE_2": end_date,
        "FID_PERIOD_DIV_CODE": "D",
        "FID_ORG_ADJ_PRC": "1",  # 국내주식 API처럼 수정주가 여부 파라미터를 추가 요구할 수 있어 포함
    }
    res = requests.get(
        f"{URL_BASE}/uapi/domestic-futureoption/v1/quotations/inquire-daily-fuopchartprice",
        headers=headers, params=params,
    )
    res.raise_for_status()
    body = res.json()
    rows = body.get("output2") or body.get("output1") or []
    df = pd.DataFrame(rows).rename(columns={
        "stck_bsop_date": "일자", "futs_oprc": "시가", "futs_hgpr": "고가",
        "futs_lwpr": "저가", "futs_prpr": "종가", "acml_vol": "거래량",
        # 일부 응답은 stck_ 접두어를 그대로 쓰는 경우도 있어 아래도 함께 매핑
        "stck_oprc": "시가", "stck_hgpr": "고가", "stck_lwpr": "저가", "stck_clpr": "종가",
    })
    keep = [c for c in ["일자", "종가", "시가", "고가", "저가", "거래량"] if c in df.columns]
    df = df[keep]
    for c in ["종가", "시가", "고가", "저가", "거래량"]:
        if c in df.columns:
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

asset_type = st.radio("종목 유형", ["주식", "국내선물(KOSPI200 등)"], horizontal=True)

if asset_type == "주식":
    stock_code = st.text_input("종목코드 입력 (예: 005930 삼성전자, 000810 삼성화재)", value="005930")
else:
    stock_code = st.text_input(
        "선물 종목코드 입력 (예: 101S06 형식 - 정확한 코드는 KIS 종목정보파일/HTS에서 확인 필요)",
        value="",
        help="선물 종목코드는 만기월마다 바뀝니다. HTS에 표시되는 코드(F202609 등)와 "
             "KIS API가 요구하는 코드 형식이 다를 수 있어, 오류가 나면 KIS Developers "
             "포털의 '종목정보파일' 메뉴에서 정확한 코드를 확인해 입력해주세요.",
    )

days = st.slider("조회 기간 (일)", 30, 180, 60)

if st.button("조회 시작") and APP_KEY and APP_SECRET and stock_code:
    try:
        token = get_access_token(APP_KEY, APP_SECRET, URL_BASE)

        end = datetime.today().strftime("%Y%m%d")
        start = (datetime.today() - timedelta(days=days)).strftime("%Y%m%d")

        if asset_type == "주식":
            st.subheader("1. 현재가")
            price_data = get_current_price(token, stock_code)
            col1, col2, col3 = st.columns(3)
            col1.metric("현재가", f"{int(price_data['stck_prpr']):,}원")
            col2.metric("전일대비", f"{price_data.get('prdy_vrss', '-')}")
            col3.metric("등락률", f"{price_data.get('prdy_ctrt', '-')}%")

            st.subheader("2. 일봉 + 지표")
            df = get_daily_ohlcv(token, stock_code, start, end)
            related_dfs = {}
        else:
            st.subheader("1~2. 선물 일봉 데이터")

            # --- 디버그: API 원본 응답 확인용 (문제 해결 후 지워도 됩니다) ---
            debug_headers = auth_headers(token, APP_KEY, APP_SECRET, "FHKIF03020100")
            debug_params = {
                "FID_COND_MRKT_DIV_CODE": "F",
                "FID_INPUT_ISCD": stock_code,
                "FID_INPUT_DATE_1": start,
                "FID_INPUT_DATE_2": end,
                "FID_PERIOD_DIV_CODE": "D",
            }
            debug_res = requests.get(
                f"{URL_BASE}/uapi/domestic-futureoption/v1/quotations/inquire-daily-fuopchartprice",
                headers=debug_headers, params=debug_params,
            )
            with st.expander("🔍 API 원본 응답 (디버그용 - 문제 진단 후 삭제 가능)"):
                st.write("상태 코드:", debug_res.status_code)
                st.json(debug_res.json())
            # --- 디버그 끝 ---

            df = get_futures_daily_ohlcv(token, stock_code, start, end)
            if len(df) > 0:
                latest = df.iloc[-1]
                st.metric("최근 종가", f"{latest['종가']:,.2f}")

            # 상관관계 분석용 관련종목 (KOSPI200 선물 세력방향 근사에 활용)
            related_dfs = {}
            try:
                related_dfs["SK하이닉스"] = get_daily_ohlcv(token, "000660", start, end)
                related_dfs["삼성전자"] = get_daily_ohlcv(token, "005930", start, end)
            except Exception:
                st.caption("⚠️ 관련종목(SK하이닉스/삼성전자) 조회 실패 - 세력방향 분석에서 제외됩니다")

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
        report_md = generate_report(df, stock_name=stock_code, related_dfs=related_dfs)
        st.markdown(report_md)

    except Exception as e:
        st.error(f"오류 발생: {e}")
else:
    st.info("종목코드 입력 후 '조회 시작' 버튼을 눌러주세요. (앱키가 없으면 사이드바에 입력)")
