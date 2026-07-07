# -*- coding: utf-8 -*-
"""
통합매매법 v2-4 - 15항목 자동 분석 모듈 (Claude API 없이 규칙 기반)
=================================================================
- 이 모듈은 순수 계산/규칙으로만 동작합니다 (AI 호출 없음)
- 7(엘리엇파동)/10(세력방향)/11(방장패턴)은 정성적 판단 영역이라
  완벽한 해석은 아니고, 단순 규칙 기반 근사치입니다.
  참고용으로만 쓰시고, 최종 판단은 직접 확인하시길 권장합니다.
"""

import pandas as pd
import numpy as np


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """이동평균 / 스토캐스틱 / MACD 계산. df는 일자 오름차순, 종가/시가/고가/저가 컬럼 필요."""
    df = df.sort_values("일자").reset_index(drop=True).copy()

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


def analyze_hourly_support_resistance(hourly_df: pd.DataFrame, current_price: float) -> list:
    """
    60분봉 데이터로 MA60/MA120 기울기와 현재가 위치, 최근 접촉 횟수를 판단해
    산강 매매법의 O자리(최초 접촉)/X자리(재접촉) 근사 판단을 만든다.
    hourly_df: 시간순 정렬된 종가/고가/저가 컬럼 포함 DataFrame (60분봉)
    """
    lines = []
    if hourly_df is None or len(hourly_df) < 25:
        lines.append("⚠️ 60분봉 데이터가 부족해 장기선 판단을 생략합니다 (최소 25개 필요)")
        return lines

    df = hourly_df.sort_values(hourly_df.columns[0] if "시간" not in hourly_df.columns else "시간").copy()
    df["MA20"] = df["종가"].rolling(20).mean()
    df["MA60"] = df["종가"].rolling(min(60, len(df) - 1)).mean()

    ma60_now = df["MA60"].iloc[-1]
    ma60_prev = df["MA60"].iloc[-6] if len(df) > 6 and pd.notna(df["MA60"].iloc[-6]) else df["MA60"].iloc[0]

    if pd.isna(ma60_now):
        lines.append("⚠️ MA60 계산에 필요한 60분봉 데이터가 부족합니다")
        return lines

    slope = "상승" if ma60_now > ma60_prev else "하락" if ma60_now < ma60_prev else "횡보"
    position = "위" if current_price > ma60_now else "아래"

    # 최근 20개 봉 동안 종가가 MA60을 교차(터치)한 횟수로 O/X 근사 판단
    recent = df.tail(20).copy()
    recent["above"] = recent["종가"] > recent["MA60"]
    touches = (recent["above"] != recent["above"].shift(1)).sum()

    lines.append(f"**9. 장기선 분석 (60분봉 MA60 기준 — 실제 데이터 반영)**")
    lines.append(f"- 60분봉 MA60: {ma60_now:,.2f} ({slope} 기울기), 현재가 이 선 {position}에 위치")
    lines.append(f"- 최근 20개 60분봉 동안 MA60 교차(터치) 횟수: {touches}회")

    if slope == "하락" and position == "아래":
        lines.append("- → 내려오는 장기선 아래: 저항으로 작동 중 (산강 원칙상 콜 진입 비우호적)")
    elif slope == "상승" and position == "위":
        lines.append("- → 올라가는 장기선 위: 지지로 작동 가능성")
    else:
        lines.append("- → 장기선과 가격이 교차 구간에 있어 방향 확정 어려움, 추가 확인 필요")

    if touches <= 1:
        lines.append("- 접촉 횟수 적음 → O자리(최초 접촉) 가능성, 신뢰도 상대적으로 높음")
    else:
        lines.append("- 접촉 횟수 많음 → X자리(재접촉) 가능성, 진입 신중 필요")

    return lines


def channel_levels(high: float, low: float) -> dict:
    rng = high - low
    return {
        "0%": low, "25%": low + rng * 0.25, "50%": low + rng * 0.5,
        "75%": low + rng * 0.75, "100%": high,
    }


def channel_position_pct(price: float, high: float, low: float) -> float:
    if high == low:
        return 50.0
    return (price - low) / (high - low) * 100


def analyze_correlation(main_df: pd.DataFrame, related_dfs: dict) -> list:
    """
    related_dfs: {"SK하이닉스": df, "삼성전자": df, ...} 형태.
    각 df는 일자/종가 컬럼 필요. main_df와 날짜를 맞춰 최근 등락률·상관계수를 비교.
    """
    lines = []
    main = main_df.set_index("일자")["종가"]
    for name, rdf in related_dfs.items():
        if rdf is None or len(rdf) < 5:
            continue
        r = rdf.set_index("일자")["종가"]
        joined = pd.concat([main, r], axis=1, join="inner")
        joined.columns = ["main", "related"]
        if len(joined) < 5:
            continue
        corr = joined["main"].pct_change().corr(joined["related"].pct_change())
        recent_change = (r.iloc[-1] - r.iloc[-2]) / r.iloc[-2] * 100 if len(r) > 1 else 0
        lines.append(f"- {name}: 최근 등락률 {recent_change:+.2f}%, 지수와의 상관계수 {corr:.2f}")
    return lines


def find_recent_swing(df: pd.DataFrame, lookback: int = 20):
    """
    최근 lookback 기간 내 최고/최저와 그 날짜를 찾아 A파 후보로 사용.
    channel_window(기본 20일)와 동일한 범위를 기본값으로 써서,
    3번(채널 계산)에서 보는 것과 같은 구간을 파동 분석에도 일관되게 적용한다.
    """
    recent = df.tail(lookback)
    high_row = recent.loc[recent["고가"].idxmax()]
    low_row = recent.loc[recent["저가"].idxmin()]
    return high_row, low_row


def generate_report(df: pd.DataFrame, stock_name: str = "", channel_window: int = 20,
                     swing_lookback: int = 20, related_dfs: dict = None,
                     hourly_df: pd.DataFrame = None) -> str:
    """
    df: 일자/종가/시가/고가/저가/거래량 컬럼을 가진 DataFrame (일자 오름차순 권장)
    반환: 마크다운 텍스트 (Streamlit st.markdown()으로 바로 출력 가능)
    """
    df = add_indicators(df)
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else latest

    price = latest["종가"]
    change = price - prev["종가"]
    change_pct = change / prev["종가"] * 100 if prev["종가"] else 0

    # 채널 계산 (최근 channel_window일 고저 기준)
    recent = df.tail(channel_window)
    high, low = recent["고가"].max(), recent["저가"].min()
    ch = channel_levels(high, low)
    pos_pct = channel_position_pct(price, high, low)

    # 이동평균 배열
    ma_cols = ["MA5", "MA10", "MA20", "MA60", "MA120"]
    ma_vals = {c: latest[c] for c in ma_cols if pd.notna(latest[c])}

    # 스토캐스틱/MACD
    sto_k = latest["Sto_%K"]
    sto_d = latest["Sto_%D"]
    macd, signal, osc = latest["MACD"], latest["Signal"], latest["OSC"]

    # 파동 근사 (A파: swing_lookback일 내 최고->최저, 또는 최저->최고 중 더 최근 구간)
    high_row, low_row = find_recent_swing(df, swing_lookback)
    a_high = high_row["고가"]
    a_low = low_row["저가"]
    if high_row["일자"] < low_row["일자"]:
        a_start_val, a_end_val = a_high, a_low
        a_start_date, a_end_date = high_row["일자"], low_row["일자"]
        a_direction = "하락(고점→저점)"
    else:
        a_start_val, a_end_val = a_low, a_high
        a_start_date, a_end_date = low_row["일자"], high_row["일자"]
        a_direction = "상승(저점→고점)"
    a_move = abs(a_end_val - a_start_val)
    retrace_pct = abs(price - a_end_val) / a_move * 100 if a_move else 0

    # C파 목표 (B파 고점 - A파 하락폭, 방향에 따라 부호 조정)
    if a_direction.startswith("하락"):
        c_target = price - a_move * 0.62  # 대략적 확장 근사치
    else:
        c_target = price + a_move * 0.62

    lines = []
    title = f"{stock_name} " if stock_name else ""
    lines.append(f"## {title}통합매매법 v2-4 자동 분석 (규칙 기반)")
    lines.append("")

    # 1. 현황 파악
    lines.append("**1. 현황 파악**")
    lines.append(f"- 현재가: {price:,.0f} ({change:+,.0f}, {change_pct:+.2f}%)")
    lines.append(f"- 최근 {channel_window}일 고점 {high:,.0f} / 저점 {low:,.0f}")
    lines.append("")

    # 2. 4등분 채널
    lines.append("**2. 4등분 채널 계산**")
    for k, v in ch.items():
        lines.append(f"- {k}: {v:,.0f}")
    lines.append("")

    # 3. 현재 위치
    zone = "매수우위(75%+)" if pos_pct >= 75 else "매도우위(25%-)" if pos_pct <= 25 else "중립/균형가 부근"
    lines.append("**3. 현재 위치 판단**")
    lines.append(f"- 채널 내 위치: {pos_pct:.1f}% → {zone}")
    lines.append("")

    # 4. 지표 상태
    lines.append("**4. 지표 상태**")
    if pd.notna(sto_k):
        sto_state = "과열(90+)" if sto_k >= 90 else "과매도(10-)" if sto_k <= 10 else "중립"
        lines.append(f"- Stochastic %K: {sto_k:.1f} / %D: {sto_d:.1f} → {sto_state}")
    if pd.notna(osc):
        osc_state = "양(+) 모멘텀" if osc > 0 else "음(-) 모멘텀"
        lines.append(f"- MACD: {macd:.2f} / Signal: {signal:.2f} / OSC: {osc:.2f} → {osc_state}")
    lines.append("")

    # 5. 이평선 배열
    lines.append("**5. 이동평균 배열 + 수렴 자리**")
    for c, v in ma_vals.items():
        rel = "위" if price > v else "아래"
        lines.append(f"- {c}: {v:,.0f} (현재가 {rel})")
    if len(ma_vals) >= 2:
        vals_sorted = sorted(ma_vals.values())
        spread_pct = (vals_sorted[-1] - vals_sorted[0]) / price * 100
        density = "밀집(수렴)" if spread_pct < 3 else "분산"
        lines.append(f"- 이평선 밀집도: {spread_pct:.1f}% 차이 → {density}")
    lines.append("")

    # 6. 주간 기준가
    lines.append("**6. 주/월 기준가**")
    if len(df) >= 5:
        week_ago = df.iloc[-5]
        week_change_pct = (price - week_ago["종가"]) / week_ago["종가"] * 100
        lines.append(f"- 5거래일 전({week_ago['일자'].date()}) 대비: {week_change_pct:+.2f}%")
    lines.append("")

    # 7. 파동 위치 (근사치 - 참고용)
    lines.append("**7. 파동 위치 (엘리엇 + ABC, 규칙 기반 근사치 — 참고용)**")
    lines.append(f"- 추정 A파: {a_start_val:,.0f}({a_start_date.date()}) → "
                 f"{a_end_val:,.0f}({a_end_date.date()}), {a_direction}")
    lines.append(f"- 현재가는 A파의 {retrace_pct:.1f}% 되돌림 수준")
    lines.append(f"- (탐색 구간: 최근 {swing_lookback}거래일 — 채널 계산과 동일 구간)")
    lines.append("⚠️ 이 항목은 정성적 판단이 필요한 영역이라 자동 계산은 참고용입니다")
    lines.append("")

    # 8. 교차 원리 (파동 기반 대체 목표)
    lines.append("**8. 하락/상승 목표 (파동 기반 근사)**")
    lines.append(f"- C파 목표(근사): {c_target:,.0f}")
    lines.append("")

    # 9. 장기선 분석
    if hourly_df is not None:
        lines.extend(analyze_hourly_support_resistance(hourly_df, price))
    else:
        lines.append("**9. 장기선 분석 (MA120 기준 대체 — 60분봉 데이터 없음)**")
        if "MA120" in ma_vals:
            rel = "위" if price > ma_vals["MA120"] else "아래"
            lines.append(f"- MA120({ma_vals['MA120']:,.0f}) {rel}에 위치")
        lines.append("⚠️ 정확한 O자리/X자리 판단은 60분봉 확인 필요")
    lines.append("")

    # 10. 세력 방향 (거래량 기반 근사)
    lines.append("**10. 세력 방향 (거래량 + 관련종목 상관관계 근사 — 참고용)**")
    if "거래량" in df.columns and len(df) >= 20:
        vol_avg20 = df["거래량"].tail(20).mean()
        vol_latest = latest["거래량"]
        vol_state = "평균 대비 급증" if vol_latest > vol_avg20 * 1.5 else "평상 수준"
        lines.append(f"- 최근 거래량 {vol_latest:,.0f} vs 20일 평균 {vol_avg20:,.0f} → {vol_state}")
    if related_dfs:
        corr_lines = analyze_correlation(df, related_dfs)
        lines.extend(corr_lines)
    lines.append("⚠️ 실제 수급(외국인/기관) 데이터는 별도 확인 필요")
    lines.append("")

    # 11. 방장 패턴 (규칙 기반 근사)
    lines.append("**11. 방장 패턴 분석 (규칙 기반 근사 — 참고용)**")
    lines.append(f"- 채널 위치 {pos_pct:.1f}%, 스토캐스틱 {sto_k:.1f} 조합 기준 단순 패턴 참고만 가능")
    lines.append("")

    # 12. 콜/풋 진입 자리
    lines.append("**12. 매수/매도(콜/풋) 진입 자리**")
    lines.append(f"- 매수 관심: 채널 25%({ch['25%']:,.0f}) 지지 확인 시")
    lines.append(f"- 매도 관심: 채널 75%({ch['75%']:,.0f}) 저항 확인 시")
    lines.append("")

    # 13. 손절/목표가
    lines.append("**13. 손절 · 목표가**")
    lines.append(f"- 상단 목표: {ch['100%']:,.0f} / 하단 목표: {ch['0%']:,.0f}")
    lines.append(f"- 손절 기준(롱): {ch['0%']:,.0f} 이탈 시 / (숏): {ch['100%']:,.0f} 돌파 시")
    lines.append("")

    # 14. 재매집 구간
    lines.append("**14. 재매집(눌림목) 구간**")
    lines.append(f"- 채널 25~50%({ch['25%']:,.0f}~{ch['50%']:,.0f}) 구간이 재매집 후보")
    lines.append("")

    # 15. 합성 전략
    lines.append("**15. 합성 전략**")
    lines.append(f"- {ch['0%']:,.0f} 붕괴 시 풋 강화 / {ch['100%']:,.0f} 돌파 시 콜 강화 전략 권장")
    lines.append("- 박스권 내에서는 관망 또는 소폭 대응 원칙")
    lines.append("")

    lines.append("---")
    lines.append("⚠️ **주의**: 7/10/11번 항목은 정성적 판단 영역을 규칙으로 근사한 것으로, "
                 "실제 차트 패턴·수급·뉴스와 다를 수 있습니다. 참고 자료로만 활용하세요.")

    return "\n".join(lines)
