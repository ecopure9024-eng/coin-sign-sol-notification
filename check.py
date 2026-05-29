#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
체념 이론 (Capitulation) v2 - 알림 봇
Pine Script 전략의 '진입 신호' 부분만 옮겨 바이낸스 시세로 검사하고
신호 발생 시 텔레그램으로 알림을 보낸다.

로직 (Pine 원본과 동일):
  직전 봉:  거래량 > 평균거래량 * volSpike  (거래량 폭발)
            긴 꼬리 (아래꼬리>=range*wickRatio  → 롱 / 위꼬리 → 숏)
  현재 봉:  range < 직전봉 range * volContr   (변동성 수축)
"""

import os
import sys
import json
import time
import urllib.request
import urllib.parse

# ── 설정 ──────────────────────────────────────────────
SYMBOLS  = ["SOLUSDT", "BTCUSDT", "ETHUSDT"]   # 감시할 종목
INTERVAL = "5m"                                # 타임프레임

# Pine Script input 값과 동일
VOL_LEN    = 20     # 거래량 평균 봉
VOL_SPIKE  = 2.0    # 거래량 폭발 (평균배수)
WICK_RATIO = 0.5    # 꼬리 비율 (전체 봉 대비)
VOL_CONTR  = 0.7    # 직후 변동성 수축 비율

# 텔레그램 (GitHub Secrets 또는 환경변수에서 읽음)
TG_TOKEN = os.environ.get("TG_TOKEN", "")
TG_CHAT  = os.environ.get("TG_CHAT", "")

BINANCE_KLINES = "https://data-api.binance.vision/api/v3/klines"


# ── 바이낸스 캔들 가져오기 ────────────────────────────
def get_klines(symbol, interval, limit=50):
    params = urllib.parse.urlencode({
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
    })
    url = f"{BINANCE_KLINES}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "capit-alert"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode())
    # 각 kline: [openTime, open, high, low, close, volume, closeTime, ...]
    candles = []
    for k in data:
        candles.append({
            "time":  int(k[0]),
            "open":  float(k[1]),
            "high":  float(k[2]),
            "low":   float(k[3]),
            "close": float(k[4]),
            "vol":   float(k[5]),
        })
    return candles


# ── 체념 신호 검사 ────────────────────────────────────
def check_signal(candles):
    """
    가장 최근에 '확정된' 봉을 현재봉(cur)으로 본다.
    바이낸스 klines의 마지막 항목은 아직 진행 중인 봉이므로 제외(-1),
    cur = candles[-2], prev = candles[-3].
    반환: "롱" / "숏" / None
    """
    if len(candles) < VOL_LEN + 3:
        return None

    cur  = candles[-2]   # 직전에 막 마감된 봉 (= Pine의 현재봉)
    prev = candles[-3]   # 그 앞 봉 (= Pine의 [1] 체념봉)

    # 거래량 평균: cur 시점 기준 직전 VOL_LEN개 (cur 포함, Pine의 sma와 맞춤)
    idx = candles.index(cur)
    window = candles[idx - VOL_LEN + 1: idx + 1]
    avg_vol = sum(c["vol"] for c in window) / len(window)

    # prev 봉 = 체념봉
    p_range = prev["high"] - prev["low"]
    p_upper = prev["high"] - max(prev["close"], prev["open"])
    p_lower = min(prev["close"], prev["open"]) - prev["low"]

    vol_burst        = prev["vol"] > avg_vol * VOL_SPIKE
    long_lower_wick  = p_range > 0 and p_lower >= p_range * WICK_RATIO
    long_upper_wick  = p_range > 0 and p_upper >= p_range * WICK_RATIO

    # cur 봉 변동성 수축
    c_range     = cur["high"] - cur["low"]
    contraction = c_range < p_range * VOL_CONTR

    capit_long  = vol_burst and long_lower_wick and contraction
    capit_short = vol_burst and long_upper_wick and contraction

    if capit_long:
        return "롱"
    if capit_short:
        return "숏"
    return None


# ── 텔레그램 전송 ─────────────────────────────────────
def send_telegram(text):
    if not TG_TOKEN or not TG_CHAT:
        print("[경고] TG_TOKEN / TG_CHAT 이 설정되지 않았습니다. 메시지만 출력:")
        print(text)
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": TG_CHAT,
        "text": text,
        "parse_mode": "HTML",
    }).encode()
    req = urllib.request.Request(url, data=payload)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            r.read()
    except Exception as e:
        print(f"[텔레그램 전송 실패] {e}")


# ── 메인 ──────────────────────────────────────────────
def main():
    fired = []
    for sym in SYMBOLS:
        try:
            candles = get_klines(sym, INTERVAL, limit=VOL_LEN + 5)
            sig = check_signal(candles)
            if sig:
                price = candles[-2]["close"]
                arrow = "🟢" if sig == "롱" else "🔴"
                msg = (f"{arrow} <b>체념 신호 [{sig}]</b>\n"
                       f"종목: {sym}\n"
                       f"타임프레임: {INTERVAL}\n"
                       f"종가: {price}")
                send_telegram(msg)
                fired.append(f"{sym} {sig}")
                print(f"[신호] {sym} {sig} @ {price}")
            else:
                print(f"[신호없음] {sym}")
        except Exception as e:
            print(f"[오류] {sym}: {e}")
        time.sleep(0.3)  # API 매너

    if not fired:
        print("이번 검사에서 신호 없음.")


if __name__ == "__main__":
    main()
