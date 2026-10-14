# -*- coding: utf-8 -*-
"""BTP 記錄程式的兩種輸出格式解析。

手動匯入（/api/import_csv）與串流接收（/api/ingest）共用這一份。
⚠ 欄位對應只能有一份：以前解析寫在 routes.py 裡，若串流再寫一套，日後
  改了一邊忘了另一邊，兩條路進來的同一筆資料就會落在不同欄位，而且不報錯。

⚠ 只准標準函式庫——這支在常駐核心裡。
"""
import re

# 位置式 CSV 欄位（無表頭）：
#     2026,7,2,0,0,47,_,522,3.48,6.92,30.0,0.89,0.1,1.31
#     年   月 日 時 分 秒 _ ORP  混合槽 pH 溫度 反應槽 CO2 CH4
# ⚠ 反應槽壓力是 parts[11]，混合槽是 parts[8]（2026-07-14 現場比對 HMI 面板）。
#   與 cycle_store.I_P_REACTOR = 11 一致。
I_ORP, I_MIXER, I_PH, I_TEMP, I_PRESSURE, I_CO2, I_CH4 = 7, 8, 9, 10, 11, 12, 13


def parse_csv_line(line):
    """解析一行位置式 CSV，回傳 dict；格式不符回 None。

    ⚠ 寫到一半的末行（記錄程式還在寫）欄數不足或數字不完整，這裡會回 None，
      呼叫端據此判斷「這行還不能送」。
    """
    parts = line.strip().split(',')
    if len(parts) < 14:
        return None
    try:
        ts = ('%04d-%02d-%02d %02d:%02d:%02d'
              % (int(parts[0]), int(parts[1]), int(parts[2]),
                 int(parts[3]), int(parts[4]), int(float(parts[5]))))
        return {
            'timestamp': ts, 'orp_raw': float(parts[I_ORP]),
            'pressure': float(parts[I_PRESSURE]), 'ph': float(parts[I_PH]),
            'temp': float(parts[I_TEMP]), 'mixer_pressure': float(parts[I_MIXER]),
            'co2_pct': float(parts[I_CO2]), 'ch4_pct': float(parts[I_CH4]),
        }
    except (ValueError, IndexError):
        return None


def parse_csv(text):
    """舊的 14 欄逗號格式解析（整段文字）。"""
    rows = []
    for line in text.splitlines():
        r = parse_csv_line(line)
        if r is not None:
            rows.append(r)
    return rows


def parse_labeled(text):
    """解析 BTP.SerialHarbor 記錄程式的「標籤文字」格式：
      [2026-07-22-13:59:53] ORP=534mV | 反應器壓力=2.81kg/cm² | 酸鹼值=pH 7.00 |
      溫度=30.0°C | 混合槽壓力=0.72kg/cm² | CO2濃度=0.0% | CH4濃度=0.36%

    **欄位對調**（與逗號格式一致，2026-07-27 以實測資料 + 參數表交叉驗證）：
    檔案標「反應器壓力」的高值(~3.5)其實是混合槽；標「混合槽壓力」的低值(~1.1)才是
    反應槽——後者對得上參數表「進氣後反應槽 1.179」。故 pressure 取「混合槽壓力」欄。
    """
    rows = []
    for line in text.splitlines():
        line = line.strip()
        m_ts = re.search(r"\[(\d{4})-(\d{2})-(\d{2})-(\d{2}:\d{2}:\d{2})\]", line)
        if not m_ts or "ORP=" not in line:
            continue

        def g(pat, cast=float):
            m = re.search(pat, line)
            return cast(m.group(1)) if m else None
        try:
            reactor = g(r"混合槽壓力=([\d.]+)")     # ← 標籤對調：這才是反應槽
            mixer = g(r"反應器壓力=([\d.]+)")        # ← 這其實是混合槽
            orp = g(r"ORP=(-?[\d.]+)mV")
            ph = g(r"pH\s*([\d.]+)")
            if orp is None or reactor is None:
                continue
            rows.append({
                "timestamp": f"{m_ts.group(1)}-{m_ts.group(2)}-{m_ts.group(3)} {m_ts.group(4)}",
                "orp_raw": orp, "pressure": reactor, "ph": ph if ph is not None else 7.0,
                "temp": g(r"溫度=([\d.]+)") or 30.0, "mixer_pressure": mixer or 0.0,
                "co2_pct": g(r"CO2濃度=([\d.]+)") or 0.0,
                "ch4_pct": g(r"CH4濃度=([\d.]+)") or 0.0,
            })
        except (ValueError, AttributeError):
            continue
    return rows
