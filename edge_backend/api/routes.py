import io
import os
import re
import time
from datetime import datetime
import numpy as np
from fastapi import APIRouter, HTTPException, File, UploadFile, Query
from fastapi.responses import StreamingResponse
# ⚠ 不要在模組層級 import core.inference：它會拉進 torch（實測磁碟
#   496 MB），而服務一啟動就付這個代價，與有沒有人用推論無關。
#   改為在需要的函式內延遲載入，行為不變。見 docs/系統重構架構。
def _inference():
    from core.inference import get_pressure_prediction, sensor_buffer
    return get_pressure_prediction, sensor_buffer


# ⚠ 2026-09-03 量測：延遲匯入只把成本往後挪，沒有避免它。CSV 匯入路徑在
#   預熱 LSTM buffer 時呼叫 _inference()，一次上傳就把 torch → sklearn →
#   scipy 全部拉進常駐行程，**RSS 62 MB → 348 MB**，而且模組不會卸載。
#
#   而那個預測值前端根本不用：MonitorView 只渲染 imported /
#   anomalies_detected / orp_stats 三個欄位，回應裡的 prediction 被丟掉。
#   資料本身只有 1.6 MB（9944 筆），286 MB 全是 import 開銷。
#
#   LSTM 的去留是待確認事項（見架構文件 §8），所以這裡不刪功能，只是
#   預設不在 CSV 匯入時付這筆錢。要恢復：set REACTOR_ENABLE_LSTM=1
# ⚠ 要走 core.config 不能直接讀 os.environ：config 的合約是
#   「環境變數 > .env > 內建預設」，直接讀 environ 會讓寫在 .env 的
#   REACTOR_ENABLE_LSTM 完全沒有作用，而部署時設定就是寫在 .env。
from core import config as _config
_LSTM_ON = _config.get('REACTOR_ENABLE_LSTM') == '1'

from core.data_store import sensor_records, append_record, clear_all
from core.signal_processor import ORPSignalProcessor
from core.feature_extractor import ORPFeatureExtractor
# data_pipeline.loader 會拉進 pandas（磁碟 61.9 MB），但它只在 CSV
# 匯入時用得到。同樣改為延遲載入。
from api.schemas import (SensorDataPayload, SensorRecord,
                         ExperimentRunCreate, ExperimentRunUpdate, ExperimentStartPayload)
from core import experiment_store as exp
from core import experiment_report as exp_report

_feature_extractor = ORPFeatureExtractor(
    window=30,
    sigma_threshold=5.0,
    orp_low=480.0,
    orp_high=650.0,
    drift_window=120,
)

router = APIRouter()

_BOOT_TS = time.time()


# ==========================================
# 健康檢查（給桌面控制台輪詢用）
# ==========================================
@router.get("/health")
def health():
    """極輕量的存活與資料新鮮度檢查——控制台每幾秒打一次，不可做重運算。

    2026-07-22 監控電腦自動更新後記錄靜默中斷 17.5 小時無人察覺，故此端點的
    重點不只是「後端活著」，而是「**資料還有在進來嗎**」：data_stale 為 True
    代表後端雖然活著，但已經很久沒收到新的感測資料，需要人介入檢查記錄來源。
    """
    last_ts = None
    stale_min = None
    if sensor_records:
        last_ts = max((r.get("timestamp") or "") for r in sensor_records) or None
        if last_ts:
            try:
                delta = datetime.now() - datetime.strptime(last_ts, "%Y-%m-%d %H:%M:%S")
                stale_min = round(max(delta.total_seconds() / 60.0, 0.0), 1)
            except ValueError:
                pass

    running = next((r for r in exp.experiment_runs if r.get("status") == "running"), None)
    return {
        "status":         "ok",
        "uptime_min":     round((time.time() - _BOOT_TS) / 60.0, 1),
        "record_count":   len(sensor_records),
        "last_timestamp": last_ts,
        "staleness_min":  stale_min,
        # 門檻與 experiment_store 的斷點判定一致，兩邊對「多久算沒資料」有共同定義
        "data_stale":     stale_min is not None and stale_min > exp.GAP_MINUTES,
        "running_run":    running["run_id"] if running else None,
        "n_runs":         len(exp.experiment_runs),
    }


# ⚠ /predict_pressure 已移除（2026-08-31）。全專案掃描確認只有定義、
#   沒有任何呼叫端：前端三個 view 都沒用它，也沒有其他腳本打它。
#   原始碼保留在 routes.py.before_slim。

# ==========================================
# 通道 2：前端/感測器傳送最新數據過來
# ==========================================
@router.post("/upload_sensor")
def upload_sensor_data(payload: SensorDataPayload):
    print(f"[成功接收數據] ORP: {payload.orp:.1f} mV, pH: {payload.ph:.2f}, 溫度: {payload.temp:.1f} °C")
    try:
        get_pressure_prediction, _ = _inference()
        result = get_pressure_prediction({
            'orp':      payload.orp,
            'ph':       payload.ph,
            'temp':     payload.temp,
            'pressure': payload.pressure,   # None 時 inference 會沿用上次壓力
        })
        prediction = result
    except Exception:
        prediction = None
    return {
        "status":     "success",
        "message":    "感測器數據已寫入",
        "prediction": prediction,
    }


# ==========================================
# 通道 3：感測器記錄 CRUD
# ==========================================
# 研究分析統計端點
# ==========================================
@router.get("/report/stats")
def get_report_stats():
    recs = _sorted_records()
    if len(recs) < 10:
        return {"error": "資料不足（至少需 10 筆）"}

    orp      = np.array([r['orp']                    for r in recs], dtype=float)
    pressure = np.array([r.get('pressure', 0)        for r in recs], dtype=float)
    ph       = np.array([r.get('ph', 7)              for r in recs], dtype=float)
    temp     = np.array([r.get('temp', 30)           for r in recs], dtype=float)
    ch4      = np.array([r.get('ch4_pct', 0)         for r in recs], dtype=float)
    co2      = np.array([r.get('co2_pct', 0)         for r in recs], dtype=float)
    anomaly  = np.array([1 if r.get('is_anomaly') else 0 for r in recs], dtype=int)

    # 1. ORP 分布直方圖
    cnt, edges = np.histogram(orp, bins=24)
    orp_histogram = {
        "bins":   [round((edges[i]+edges[i+1])/2, 1) for i in range(len(cnt))],
        "counts": cnt.tolist(),
    }

    # 2. 壓力分布直方圖
    p_cnt, p_edges = np.histogram(pressure, bins=24)
    pressure_histogram = {
        "bins":   [round((p_edges[i]+p_edges[i+1])/2, 3) for i in range(len(p_cnt))],
        "counts": p_cnt.tolist(),
    }

    # 3. 相關係數熱力圖（6×6）``
    matrix   = np.array([orp, ph, temp, pressure, ch4, co2])
    labels   = ['ORP', 'pH', '溫度', '壓力', 'CH4', 'CO2']
    corr_raw = np.corrcoef(matrix)
    # NaN 替換為 0（全常數欄位）
    corr_raw = np.where(np.isnan(corr_raw), 0.0, corr_raw)
    correlation = {
        "labels": labels,
        "matrix": [[round(float(v), 3) for v in row] for row in corr_raw],
    }

    # 4. 每日異常統計
    date_total   = {}
    date_anomaly = {}
    for r in recs:
        d = (r.get('timestamp') or '')[:10] or 'unknown'
        date_total[d]   = date_total.get(d, 0) + 1
        if r.get('is_anomaly'):
            date_anomaly[d] = date_anomaly.get(d, 0) + 1
    anomaly_by_date = [
        {"date": d, "total": date_total[d], "anomalies": date_anomaly.get(d, 0)}
        for d in sorted(date_total)
    ]

    # 5. CH4 / CO2 日均值趨勢
    date_ch4 = {}
    date_co2 = {}
    for r in recs:
        d = (r.get('timestamp') or '')[:10] or 'unknown'
        date_ch4.setdefault(d, []).append(r.get('ch4_pct', 0))
        date_co2.setdefault(d, []).append(r.get('co2_pct', 0))
    gas_daily = [
        {
            "date":    d,
            "avg_ch4": round(float(np.mean(date_ch4[d])), 2),
            "avg_co2": round(float(np.mean(date_co2[d])), 2),
        }
        for d in sorted(date_ch4)
    ]

    # 6. pH-ORP 散點（最多取 600 點，避免前端過載）
    step    = max(1, len(recs) // 600)
    scatter = [
        {"orp": round(float(orp[i]), 1), "ph": round(float(ph[i]), 2), "ch4": round(float(ch4[i]), 1)}
        for i in range(0, len(recs), step)
    ]

    # 7. 摘要統計
    summary = {
        "total_records":  len(recs),
        "anomaly_count":  int(anomaly.sum()),
        "anomaly_rate":   round(float(anomaly.mean()) * 100, 1),
        "orp_mean":       round(float(orp.mean()), 1),
        "orp_std":        round(float(orp.std()), 2),
        "pressure_mean":  round(float(pressure.mean()), 3),
        "pressure_max":   round(float(pressure.max()), 3),
        "ch4_mean":       round(float(ch4.mean()), 2),
    }

    return {
        "summary":          summary,
        "orp_histogram":    orp_histogram,
        "pressure_histogram": pressure_histogram,
        "correlation":      correlation,
        "anomaly_by_date":  anomaly_by_date,
        "gas_daily":        gas_daily,
        "orp_ph_scatter":   scatter,
    }


# ==========================================
def _sorted_records() -> list:
    """依 timestamp 排序，確保時間軸正確（支援跨日期多次匯入的情境）。"""
    return sorted(sensor_records, key=lambda r: r.get("timestamp") or "")


# ==========================================
# 通道 5：生物相位偵測
# ==========================================

def _compute_phases_from_records(recs: list):
    """
    從 sensor_records 的 EMA-ORP 序列計算生物相位標籤序列。
    移植自 ch4_peak_analysis.detect_phases()，不引入 matplotlib。
    """
    import pandas as pd

    n = len(recs)
    orp_ema = np.array([r['orp'] for r in recs], dtype=float)

    slope = np.zeros(n)
    if n > 5:
        slope[5:] = (orp_ema[5:] - orp_ema[:-5]) / 5

    smooth_window = min(60, n)
    smoothed = (pd.Series(slope)
                .rolling(window=smooth_window, center=True, min_periods=1)
                .mean().values)

    mu    = float(np.mean(smoothed))
    sigma = float(np.std(smoothed)) + 1e-9
    k     = 0.5
    lo    = mu - k * sigma
    hi    = mu + k * sigma

    raw_labels = np.where(smoothed < lo, 1,
                 np.where(smoothed > hi, 3, 2)).astype(int)

    labels  = raw_labels.copy()
    min_dur = min(30, max(1, n // 10))
    i = 0
    while i < n:
        cur = labels[i]
        j = i
        while j < n and labels[j] == cur:
            j += 1
        if (j - i) < min_dur and i > 0:
            labels[i:j] = labels[i - 1]
        i = j

    return labels, (mu, sigma, lo, hi), smoothed


_PHASE_META = {
    1: ('底物利用期',    'Phase 1 – Substrate Utilization', '#e74c3c'),
    2: ('產甲烷活躍期',  'Phase 2 – Active Methanogenesis', '#2ecc71'),
    3: ('底物耗盡期',    'Phase 3 – Substrate Depletion',   '#e67e22'),
}


@router.get("/phase")
def get_phase():
    recs = _sorted_records()
    n = len(recs)
    if n < 10:
        return {
            'phase': 0, 'label_zh': '資料不足', 'label_en': 'Insufficient Data',
            'color': '#666', 'duration_min': 0, 'slope_current': 0.0,
            'thresholds': {'mu': 0, 'sigma': 0, 'lo': 0, 'hi': 0},
            'transitions': [], 'total_records': n,
            'message': f'需至少 10 筆資料（目前 {n} 筆）',
        }

    labels, (mu, sigma, lo, hi), smoothed = _compute_phases_from_records(recs)

    # 建立相位切換歷史（合併連續相同相位）
    transitions = []
    prev, seg_start = int(labels[0]), 0
    for idx in range(1, n):
        if int(labels[idx]) != prev:
            meta = _PHASE_META.get(prev, ('未知', '?', '#666'))
            transitions.append({
                'phase': prev, 'label_zh': meta[0], 'color': meta[2],
                'start': (recs[seg_start].get('timestamp') or '')[:16],
                'duration_min': idx - seg_start, 'is_current': False,
            })
            prev, seg_start = int(labels[idx]), idx

    meta = _PHASE_META.get(prev, ('未知', '?', '#666'))
    transitions.append({
        'phase': prev, 'label_zh': meta[0], 'color': meta[2],
        'start': (recs[seg_start].get('timestamp') or '')[:16],
        'duration_min': n - seg_start, 'is_current': True,
    })

    current_meta = _PHASE_META.get(prev, ('未知', 'Unknown', '#666'))
    return {
        'phase':         prev,
        'label_zh':      current_meta[0],
        'label_en':      current_meta[1],
        'color':         current_meta[2],
        'duration_min':  n - seg_start,
        'slope_current': round(float(smoothed[-1]), 4),
        'thresholds': {
            'mu': round(mu, 4), 'sigma': round(sigma, 4),
            'lo': round(lo, 4), 'hi':    round(hi, 4),
        },
        'transitions':   transitions[-14:],
        'total_records': n,
        'message': f'基於 {n} 筆 ORP 序列，當前相位持續 {n - seg_start} 分鐘',
    }


# ==========================================
# 通道 6：CH4 峰值即時預測
# ==========================================
@router.get("/ch4_prediction")
def ch4_prediction():
    """對進行中的週期即時預測排氣時的 CH4 峰值。

    回傳一律附帶 n_train / cv_rmse / reliability / caveat——CH4 為參考級訊號
    且歷史完整週期樣本極少，只給數字會誤導。樣本不足時回 status="insufficient"
    且不給預測值，這是刻意設計。
    """
    from core import ch4_realtime
    try:
        return ch4_realtime.predict(_sorted_records())
    except Exception as e:
        # 這是選配的分析功能，壞掉不應讓前端整頁報錯或讓控制台誤判後端掛了
        return {"status": "error", "n_train": 0, "predicted_peak": None,
                "cv_rmse": None, "current_phase": None, "features": None, "history": [],
                "reliability": f"分析失敗：{type(e).__name__}: {e}",
                "caveat": "CH4 為參考級訊號，預測僅供操作參考，不作為證據。"}


# ==========================================
# 通道 7：共變數關聯分析（點一下即分析當前每循環資料）
# ==========================================
def _why_no_cycles() -> str:
    """兩個分析都吃 exp.all_cycles()，空的時候要講清楚缺的是哪一段。

    ⚠ 這裡有一個很容易踩的坑：系統有**兩條互不相通的 CSV 路徑**——
      · POST /api/ingest_folder → SQLite cycle 表 → 速率頁（/rate、/cycles）
      · POST /api/import_csv    → 記憶體 sensor_records → 監控頁與本組分析
      用資料夾匯入了幾百個循環，這兩個分析仍然是空的，而舊訊息只說
      「尚無完整循環」，看不出是路徑不對還是資料不夠。
    """
    n_rec = len(sensor_records)
    n_run = len(exp.experiment_runs)
    if n_rec == 0 and n_run == 0:
        return ("尚無資料。這兩個分析吃的是 sensor_records，"
                "請用「上傳 CSV」（POST /api/import_csv，單檔）匯入，"
                "再建立一個批次並把開始時間設到該段資料的起點。"
                "⚠ 資料夾匯入（/api/ingest_folder）寫的是另一個資料表，"
                "只餵速率頁，不會餵到這裡。")
    if n_rec == 0:
        return (f"已有 {n_run} 個批次，但 sensor_records 是空的——"
                "批次只是時間窗，訊號要另外匯入。"
                "請用「上傳 CSV」（單檔）匯入涵蓋該批次時間範圍的資料。")
    if n_run == 0:
        first = sensor_records[0].get("timestamp", "")
        last = sensor_records[-1].get("timestamp", "")
        return (f"已有 {n_rec} 筆感測資料（{first[:16]} → {last[:16]}），"
                "但還沒有批次。請新增一個批次，並把開始時間設到 "
                f"{first[:16]}，分析才知道要取哪一段。")
    return (f"已有 {n_rec} 筆資料、{n_run} 個批次，但切不出**完整**循環"
            "（完整＝頭尾都在批次時間窗內、且中間沒有記錄斷點）。"
            "多半是批次的起訖時間沒有涵蓋到資料，或該段沒有補氣循環。")


@router.get("/covariate_analysis")
def covariate_analysis():
    """對目前所有批次的每循環特徵，即時跑「進氣前 ORP → 下降速率／平緩化」關聯分析，
    回答「斜率平緩化是生物還是物理」。吃記憶體中的 all_cycles，不需匯出 CSV。

    只用完整循環；同批次多循環為偽重複，以批次分群叢集穩健標準誤折算檢定力。
    這是關聯分析（找關係），非機理分離（灰箱那支太慢、屬離線工具）。
    """
    try:
        import pandas as pd
        from co2_covariate_association import compute
    except Exception as e:
        return {"status": "error", "message": f"分析模組載入失敗：{type(e).__name__}: {e}"}

    rows = exp.all_cycles()      # 每列一個循環（含 run_id/n_minutes/drop_rate/flattening/…）
    # 只取完整循環（跨斷點的循環平緩化不可信）
    rows = [r for r in rows if r.get("complete")]
    if not rows:
        return {"status": "insufficient", "n_cycles": 0, "n_batches": 0,
                "message": _why_no_cycles()}
    try:
        return compute(pd.DataFrame(rows))
    except Exception as e:
        return {"status": "error", "message": f"分析失敗：{type(e).__name__}: {e}"}


# ==========================================
# 通道 8：灰箱機理分析（可分離度就緒指標）
# ==========================================
@router.get("/greybox_analysis")
def greybox_analysis():
    """對真實完整循環軌跡跑灰箱兩狀態模型，回報「可分離度就緒」：
    穩態資料下物理速率 kLa 不可辨識 → 尚不可分離（需暫態/對照）；
    含暫態時 kLa 可辨識 → 可進行溶解/生物分離。

    比關聯分析慢（profile likelihood），但已限制只擬合最像暫態的少數循環，數秒內完成。
    這回答的是「你收集到的資料夠不夠分離」，是機理路線的就緒指標。
    """
    try:
        from co2_greybox_identifiability import analyze_real
    except Exception as e:
        return {"status": "error", "message": f"分析模組載入失敗：{type(e).__name__}: {e}"}
    try:
        cycles = exp.complete_cycle_trajectories()
    except Exception as e:
        return {"status": "error", "message": f"取軌跡失敗：{type(e).__name__}: {e}"}
    if not cycles:
        return {"status": "insufficient", "n_cycles": 0,
                "message": _why_no_cycles()}
    try:
        return analyze_real(cycles)
    except Exception as e:
        return {"status": "error", "message": f"分析失敗：{type(e).__name__}: {e}"}


@router.get("/analysis")
def get_analysis():
    """
    對目前 data_store 的 EMA 序列進行穩態判定與基準漂移分析。
    回傳：穩態旗標、σ、均值、漂移率 (mV/hr)、持續穩態時間。
    """
    result = _feature_extractor.analyze(_sorted_records())
    return {
        "is_steady":       result.is_steady,
        "sigma":           result.sigma,
        "orp_mean":        result.orp_mean,
        "drift_rate":      result.drift_rate,
        "steady_minutes":  result.steady_minutes,
        "window_size":     result.window_size,
        "record_count":    len(sensor_records),
        "message":         result.message,
    }


@router.get("/records")
def get_records(limit: int = Query(4320, ge=0, description="0 = 不限制，回傳全部；預設 4320 ≈ 3 天（每分鐘一筆）")):
    """預設只回傳最近 limit 筆（依時間排序後取尾端），避免長時間運行後資料量
    過大拖慢前端渲染與每次輪詢的傳輸量。完整歷史仍完整保存在 sensor_records
    與 CSV 備份中，不受此限制影響，/analysis 等其他端點也不經過這裡。"""
    recs = _sorted_records()
    if limit > 0:
        recs = recs[-limit:]
    return recs


@router.post("/records")
def add_record(record: SensorRecord):
    new_record = record.dict()
    return append_record(new_record)


@router.delete("/records")
def clear_records():
    deleted = clear_all()
    return {"status": "cleared", "deleted": deleted}


@router.delete("/records/{record_id}")
def delete_record(record_id: int):
    original_len = len(sensor_records)
    to_remove = [r for r in sensor_records if r["id"] == record_id]
    if not to_remove:
        raise HTTPException(status_code=404, detail="Record not found")
    sensor_records.remove(to_remove[0])
    return {"status": "deleted", "id": record_id}


# ==========================================
# 通道 4：CSV 批次匯入（含訊號前處理）
# ==========================================
def _parse_btp_csv(text: str) -> list:
    """舊的 14 欄逗號格式解析。反應槽壓力取 parts[11]（parts[8]/parts[11] 對調，
    2026-07-14 現場比對 HMI 面板確認）。"""
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(',')
        if len(parts) < 14:
            continue
        try:
            ts = (f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
                  f" {int(parts[3]):02d}:{int(parts[4]):02d}:{int(parts[5]):02d}")
            rows.append({
                'timestamp': ts, 'orp_raw': float(parts[7]),
                'pressure': float(parts[11]), 'ph': float(parts[9]),
                'temp': float(parts[10]), 'mixer_pressure': float(parts[8]),
                'co2_pct': float(parts[12]), 'ch4_pct': float(parts[13]),
            })
        except (ValueError, IndexError):
            continue
    return rows


def _parse_btp_labeled(text: str) -> list:
    """解析 BTP.SerialHarbor 記錄程式的「標籤文字」格式：
      [2026-07-22-13:59:53] ORP=534mV | 反應器壓力=2.81kg/cm² | 酸鹼值=pH 7.00 |
      溫度=30.0°C | 混合槽壓力=0.72kg/cm² | CO2濃度=0.0% | CH4濃度=0.36%

    **欄位對調**（與逗號格式一致，2026-07-27 以實測資料 + 參數表交叉驗證）：
    檔案標「反應器壓力」的高值(~3.5)其實是混合槽；標「混合槽壓力」的低值(~1.1)才是
    反應槽——後者對得上參數表「進氣後反應槽 1.179」。故 pressure 取「混合槽壓力」欄。
    """
    import re
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


def _import_csv_btp_daily(text: str, detected_date: str) -> dict:
    """處理 usb_receiver.py 產生的 BTP_Sensor_log 格式：資料已完成訊號前處理，
    直接沿用 orp/orp_raw/orp_cleaned/is_anomaly 等既有結果寫入 sensor_records，
    不重跑 ORPSignalProcessor（避免對已處理過的訊號二次處理）。
    """
    from data_pipeline.loader import read_btp_daily
    df = read_btp_daily(io.StringIO(text))
    if df.empty:
        return {
            'status': 'skipped', 'date': detected_date, 'imported': 0,
            'anomalies_detected': 0, 'message': '檔案中沒有可用資料列',
            'orp_stats': {'min': 0, 'max': 0, 'avg': 0},
        }

    df = df.copy()
    df['timestamp'] = df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
    existing_ts = {r['timestamp'] for r in sensor_records}
    df = df[~df['timestamp'].isin(existing_ts)]

    if df.empty:
        return {
            'status': 'skipped', 'date': detected_date, 'imported': 0,
            'anomalies_detected': 0, 'message': '所有資料已存在，無新資料匯入',
            'orp_stats': {'min': 0, 'max': 0, 'avg': 0},
        }

    rows = df.to_dict('records')
    imported = 0
    anomaly_count = 0
    ema_values: list[float] = []

    for row in rows:
        is_anomaly = bool(row.get('is_anomaly', False))
        note_val = row.get('note')
        note = note_val if isinstance(note_val, str) and note_val else f'CSV · {detected_date}'
        append_record({
            'timestamp':      row['timestamp'],
            'orp':            row['orp'],
            'orp_raw':        row['orp_raw'],
            'orp_cleaned':    row['orp_cleaned'],
            'is_anomaly':     is_anomaly,
            'pressure':       row.get('pressure', 0.0),
            'ph':             row.get('ph', 7.0),
            'temp':           row.get('temp', 30.0),
            'mixer_pressure': row.get('mixer_pressure', 0.0),
            'co2_pct':        row.get('co2_pct', 0.0),
            'ch4_pct':        row.get('ch4_pct', 0.0),
            'note':           note,
        })
        imported += 1
        if is_anomaly:
            anomaly_count += 1
        ema_values.append(row['orp'])

    # 預熱 LSTM buffer：前 N-1 筆直接 append，最後一筆透過正式介面傳入
    if _LSTM_ON:
        for row in rows[-35:-1]:
            _, _lstm_buffer = _inference()
            _lstm_buffer.append([row['orp_raw'], row['ph'], row['temp'], row['pressure']])

    try:
        if not _LSTM_ON:
            raise RuntimeError('LSTM 預測已停用（省 286 MB）；前端未使用此欄位')
        last = rows[-1]
        get_pressure_prediction, _ = _inference()
        pred = get_pressure_prediction({
            'orp':      last['orp_raw'],
            'ph':       last['ph'],
            'temp':     last['temp'],
            'pressure': last['pressure'],
        })
    except Exception:
        pred = None

    prediction_payload = None
    if pred and '緩衝' not in pred.get('status', ''):
        prediction_payload = {
            'current_pressure_kg_cm2': pred['current_pressure_kg_cm2'],
            'predicted_pressure_5min': pred['predicted_pressure_5min'],
            'predicted_ch4_5min':      pred.get('predicted_ch4_5min', 0.0),
            'status':                  pred['status'],
        }

    return {
        'status':             'success',
        'date':               detected_date,
        'imported':           imported,
        'anomalies_detected': anomaly_count,
        'prediction':         prediction_payload,
        'orp_stats': {
            'min': round(min(ema_values), 1) if ema_values else 0,
            'max': round(max(ema_values), 1) if ema_values else 0,
            'avg': round(sum(ema_values) / len(ema_values), 1) if ema_values else 0,
        },
    }


# ==========================================
# 通道 6：實驗批次管理
# ==========================================
@router.get("/experiment/runs")
def list_experiment_runs():
    """所有批次（含由感測訊號自動計算的量測結果）。"""
    return exp.list_runs()


@router.get("/experiment/scheduler")
def experiment_scheduler_status():
    """排程器狀態：活著沒、下一件自動動作是什麼、最近做過什麼。

    ⚠ 回傳的 note 欄請直接顯示在面板上：自動停止只結束紀錄，不會關閥或停機。
    """
    from core import scheduler
    return scheduler.status()


@router.post("/experiment/scheduler/tick")
def experiment_scheduler_tick():
    """立刻檢查一輪（不必等 30 秒）。給測試與「我不想等」用。"""
    from core import scheduler
    return {"applied": scheduler.tick()}


@router.post("/experiment/runs")
def create_experiment_run(payload: ExperimentRunCreate):
    """新增一個批次（status=planned，可帶基準值與排定開始時間）。"""
    try:
        return exp.add_run(
            run_id=payload.run_id, n_minutes=payload.n_minutes, gas_ratio=payload.gas_ratio,
            intake_lower=payload.intake_lower, intake_upper=payload.intake_upper,
            baseline_ch4=payload.baseline_ch4, baseline_co2=payload.baseline_co2,
            baseline_pressure=payload.baseline_pressure, target_hours=payload.target_hours,
            scheduled_start=payload.scheduled_start, note=payload.note or "",
            auto_start=bool(payload.auto_start), auto_stop=bool(payload.auto_stop),
            scheduled_end=payload.scheduled_end,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/experiment/plan")
def create_experiment_plan(payload: dict = None):
    """一鍵建立標準批次計畫。依 2026-07-22 協定，每個 n 水準＝一個 48hr 實驗，
    預設 3 水準（n=1/5/10），故建立 3 個批次（編號 1/2/3）。
    body 可帶 n_levels（預設 [1,5,10]）、baseline_ch4/co2/pressure、intake_lower/upper。"""
    payload = payload or {}
    n_levels = payload.get("n_levels", [1, 5, 10])
    kw = {k: payload[k] for k in
          ("baseline_ch4", "baseline_co2", "baseline_pressure",
           "intake_lower", "intake_upper", "target_hours") if k in payload}
    created, skipped = [], []
    for bi, n in enumerate(n_levels, 1):
        rid = str(bi)
        try:
            exp.add_run(rid, n_minutes=n, **kw)
            created.append(rid)
        except ValueError:
            skipped.append(rid)
    return {"created": created, "skipped": skipped, "runs": exp.list_runs()}


@router.post("/experiment/runs/{run_id}/start")
def start_experiment_run(run_id: str, payload: ExperimentStartPayload = None):
    """開始進氣：記錄起始時間（可指定時刻），之後的訊號歸入本批次。"""
    try:
        return exp.start_run(run_id, at=(payload.at if payload else None))
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/experiment/runs/{run_id}/cycles")
def experiment_run_cycles(run_id: str):
    """單一批次的每循環特徵表（含進氣前 ORP 共變數）。"""
    try:
        return exp.get_cycles(run_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/experiment/runs/{run_id}/vent")
def vent_experiment_run(run_id: str, payload: ExperimentStartPayload = None):
    """標記批次排氣（設定結束時間，量測結果隨即由時間窗計算）。
    可帶 at 指定排氣時刻（人工輸入／往後幾分鐘抓 CH4 峰值）；未填則用當下。
    可帶 peak_orp/peak_ph/peak_co2/peak_ch4 現場觀測峰值（較準，覆蓋自動抓的值）。"""
    try:
        peaks = None
        if payload:
            peaks = {"orp": payload.peak_orp, "ph": payload.peak_ph,
                     "co2": payload.peak_co2, "ch4": payload.peak_ch4}
        return exp.vent_run(run_id, at=(payload.at if payload else None), peaks=peaks)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/experiment/runs/{run_id}")
def update_experiment_run(run_id: str, payload: ExperimentRunUpdate):
    try:
        return exp.update_run(run_id, payload.dict(exclude_unset=True))
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/experiment/runs/{run_id}")
def delete_experiment_run(run_id: str):
    try:
        return exp.delete_run(run_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/experiment/runs/{run_id}/live")
def experiment_run_live(run_id: str):
    """進行中批次的即時狀態：目前壓力、距排氣目標、預估剩餘時間。"""
    try:
        return exp.get_live_status(run_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/experiment/export")
def export_experiment_report(fmt: str = Query("xlsx", pattern="^(xlsx|csv)$")):
    """匯出批次結果報表。fmt=xlsx（洪博綠底表格）或 csv。"""
    runs = exp.list_runs()
    stamp = time.strftime("%Y%m%d_%H%M")
    if fmt == "csv":
        text = exp_report.to_csv(runs)
        data = ("﻿" + text).encode("utf-8")   # BOM 讓 Excel 正確辨識中文
        return StreamingResponse(
            io.BytesIO(data), media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="experiment_report_{stamp}.csv"'})
    data = exp_report.to_xlsx_bytes(runs)
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="experiment_report_{stamp}.xlsx"'})


@router.get("/experiment/export/cycles")
def export_experiment_cycles(fmt: str = Query("xlsx", pattern="^(xlsx|csv)$")):
    """匯出每循環特徵表（餵模型用，每列＝一個補氣循環，含進氣前 ORP 共變數）。"""
    rows = exp.all_cycles()
    stamp = time.strftime("%Y%m%d_%H%M")
    if fmt == "csv":
        data = ("﻿" + exp_report.cycles_to_csv(rows)).encode("utf-8")
        return StreamingResponse(
            io.BytesIO(data), media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="experiment_cycles_{stamp}.csv"'})
    data = exp_report.cycles_to_xlsx_bytes(rows)
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="experiment_cycles_{stamp}.xlsx"'})


@router.post("/import_csv")
async def import_csv(file: UploadFile = File(...)):
    """
    接受兩種來源格式：
      1. BTP_Sensor_log-YYYY-MM-DD.csv — usb_receiver.py 的每日備份（已完成訊號前處理，
         含 timestamp/orp/orp_raw/orp_cleaned/is_anomaly 等標題列），直接沿用其處理結果寫入
         sensor_records，不重跑訊號前處理。
      2. 感測板原始序列埠格式（無標題列，14 欄），套用一階差分突波排除 + 線性內插重建 +
         EMA 濾波後寫入 sensor_records（沿用既有流程）。
    """
    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', file.filename or '')
    detected_date = date_match.group(1) if date_match else 'unknown'

    content = await file.read()
    text = content.decode('utf-8-sig', errors='ignore')

    first_line = text.splitlines()[0] if text.strip() else ''
    from data_pipeline.loader import _detect_schema
    if _detect_schema(first_line) == 'btp_daily':
        return _import_csv_btp_daily(text, detected_date)

    # 每次匯入建立獨立的處理器實例（不共用 USB 那個）
    processor = ORPSignalProcessor(ema_window=10, spike_threshold=-20.0, spike_max_minutes=15)

    # ── 解析 ────────────────────────────────────
    # 先試新的「標籤文字」格式（BTP.SerialHarbor 記錄程式輸出）：
    #   [2026-07-22-13:59:53] ORP=534mV | 反應器壓力=2.81kg/cm² | 酸鹼值=pH 7.00 | ...
    # 此格式無逗號，舊的逗號解析會整批跳過。若不是此格式再走逗號解析。
    parsed_rows = _parse_btp_labeled(text)
    if not parsed_rows:
        parsed_rows = _parse_btp_csv(text)

    # ── 去重：過濾掉 sensor_records 中已存在的 timestamp ──
    existing_ts = {r['timestamp'] for r in sensor_records}
    parsed_rows = [r for r in parsed_rows if r['timestamp'] not in existing_ts]

    if not parsed_rows:
        return {
            'status':             'skipped',
            'date':               detected_date,
            'imported':           0,
            'anomalies_detected': 0,
            'message':            '所有資料已存在，無新資料匯入',
            'orp_stats':          {'min': 0, 'max': 0, 'avg': 0},
        }

    row_by_ts = {r['timestamp']: r for r in parsed_rows}

    # ── 訊號前處理 ────────────────────────────────
    all_points = []
    for row in parsed_rows:
        all_points.extend(processor.process(row['timestamp'], row['orp_raw']))
    all_points.extend(processor.flush())  # 檔案結尾強制 flush 突波緩衝

    # ── 寫入記憶體 ────────────────────────────────
    imported = 0
    anomaly_count = 0
    ema_values: list[float] = []

    for pt in all_points:
        src = row_by_ts.get(pt.timestamp, {})
        append_record({
            'timestamp':      pt.timestamp,
            'orp':            pt.ema,
            'orp_raw':        pt.raw,
            'orp_cleaned':    pt.cleaned,
            'is_anomaly':     pt.is_anomaly,
            'pressure':       src.get('pressure', 0.0),
            'ph':             src.get('ph', 7.0),
            'temp':           src.get('temp', 30.0),
            'mixer_pressure': src.get('mixer_pressure', 0.0),
            'co2_pct':        src.get('co2_pct', 0.0),
            'ch4_pct':        src.get('ch4_pct', 0.0),
            'note':           f'CSV · {detected_date}',
        })
        imported += 1
        if pt.is_anomaly:
            anomaly_count += 1
        ema_values.append(pt.ema)

    # ── 預熱 LSTM buffer：前 29 筆直接 append，最後一筆透過正式介面傳入
    #    這樣 latest_actual_pressure 也能被正確更新
    if _LSTM_ON:
        for row in parsed_rows[-35:-1]:
            _, _lstm_buffer = _inference()
            _lstm_buffer.append([row['orp_raw'], row['ph'], row['temp'], row['pressure']])

    try:
        if not _LSTM_ON:
            raise RuntimeError('LSTM 預測已停用（省 286 MB）；前端未使用此欄位')
        last = parsed_rows[-1]
        get_pressure_prediction, _ = _inference()
        pred = get_pressure_prediction({
            'orp':      last['orp_raw'],
            'ph':       last['ph'],
            'temp':     last['temp'],
            'pressure': last['pressure'],
        })
    except Exception:
        pred = None

    prediction_payload = None
    if pred and '緩衝' not in pred.get('status', ''):
        prediction_payload = {
            'current_pressure_kg_cm2': pred['current_pressure_kg_cm2'],
            'predicted_pressure_5min': pred['predicted_pressure_5min'],
            'predicted_ch4_5min':      pred.get('predicted_ch4_5min', 0.0),
            'status':                  pred['status'],
        }

    return {
        'status':             'success',
        'date':               detected_date,
        'imported':           imported,
        'anomalies_detected': anomaly_count,
        'prediction':         prediction_payload,
        'orp_stats': {
            'min': round(min(ema_values), 1) if ema_values else 0,
            'max': round(max(ema_values), 1) if ema_values else 0,
            'avg': round(sum(ema_values) / len(ema_values), 1) if ema_values else 0,
        },
    }


# ==========================================
# 循環速率：論文 Algorithm 1 的線上結果
# ==========================================
# ⚠ 只依賴 core.cycle_store（numpy + sqlite3）。不得在此引入 pandas
#   等重量級套件——常駐核心的記憶體預算是 60 MB，見
#   docs/系統重構架構_2026-08-31.md。

@router.get("/cycles")
def api_cycles(limit: int = Query(500, ge=1, le=5000),
               screened_only: bool = False):
    """逐段的估計結果：k̂、r̂_b、曲率、振幅、時長。"""
    from core import cycle_store as cs
    return cs.list_cycles(limit=limit, screened_only=screened_only)


@router.post("/import_csv_batch")
async def import_csv_batch(files: list[UploadFile] = File(...)):
    """一次匯入多個 CSV。逐檔沿用 /import_csv 的解析（它已能認三種格式）。

    ⚠ 檔案先依檔名排序再匯入。BTP_Sensor_log 是一天一檔，順序錯了雖然
      sensor_records 最後仍會依 timestamp 排序，但逐檔的匯入摘要看起來
      會亂跳，難以核對哪一天缺資料。

    單檔失敗不中斷整批——回報哪幾個失敗，其餘照常匯入。整批中止會讓人
    以為「一個壞檔＝整批不能用」，而實際上壞的常常只是某天的截斷檔。
    """
    ordered = sorted(files, key=lambda f: (f.filename or ''))
    results, total, ok_n = [], 0, 0
    for f in ordered:
        try:
            r = await import_csv(f)
            n = int(r.get('imported') or 0)
            total += n
            ok_n += 1
            results.append({'file': f.filename, 'ok': True, 'imported': n,
                            'date': r.get('date'),
                            'anomalies': r.get('anomalies_detected', 0)})
        except Exception as e:                               # noqa: BLE001
            results.append({'file': f.filename, 'ok': False,
                            'error': '%s: %s' % (type(e).__name__, e)})
    return {'status': 'success', 'n_files': len(ordered), 'n_ok': ok_n,
            'n_failed': len(ordered) - ok_n, 'imported_total': total,
            'record_count': len(sensor_records), 'files': results}


def _envelope(xs, ys, max_points):
    """降採樣成 max_points 個點，但**保留每個區間的極值**。

    ⚠ 不能用「每 n 筆取一筆」。這個訊號是鋸齒波——補氣是幾分鐘內的陡升，
      等距抽樣很容易整個跳過那一瞬間，畫出來的波形會少掉補氣尖峰，看起來
      像平滑下降。取每桶的 min 與 max 才能保證尖峰不被抹掉。
    """
    n = len(ys)
    if n <= max_points:
        return [{'t': xs[i], 'v': ys[i]} for i in range(n)]
    bucket = max(1, n // (max_points // 2))
    out = []
    for a in range(0, n, bucket):
        seg = ys[a:a + bucket]
        if not len(seg):
            continue
        i_lo = a + int(np.argmin(seg))
        i_hi = a + int(np.argmax(seg))
        for i in sorted((i_lo, i_hi)):
            out.append({'t': xs[i], 'v': float(ys[i])})
    return out


@router.get("/waveform")
def api_waveform(signal: str = Query('pressure', pattern='^(pressure|orp|ph)$'),
                 max_points: int = Query(1500, ge=200, le=6000)):
    """匯入資料的波形，附上切段位置與每段的估計值。

    這是「匯入完想馬上看看資料長怎樣」的端點：一次拿到降採樣後的曲線、
    Algorithm 1 切出來的循環邊界、以及每段的 k̂／r̂_b／曲率。

    ⚠ 只用 numpy（cycle_estimator 是純 numpy）。不得引入 pandas。
    """
    recs = _sorted_records()
    if len(recs) < 60:
        return {'status': 'insufficient', 'n': len(recs),
                'message': '資料不足（至少 60 筆）。請先匯入 CSV。'}

    key = {'pressure': 'pressure', 'orp': 'orp', 'ph': 'ph'}[signal]
    ts = [r['timestamp'] for r in recs]
    ys = np.array([float(r.get(key) or 0.0) for r in recs], dtype=float)
    pres = np.array([float(r.get('pressure') or 0.0) for r in recs], dtype=float)

    t0 = datetime.strptime(ts[0], '%Y-%m-%d %H:%M:%S')
    hours = np.array([(datetime.strptime(t, '%Y-%m-%d %H:%M:%S')
                       - t0).total_seconds() / 3600.0 for t in ts])

    # 切段一律用**壓力**（Algorithm 1 的定義），即使畫的是 ORP／pH，
    # 這樣三個訊號疊在同一組循環邊界上才能對照。
    from core import cycle_estimator as ce
    cycles = []
    for a, b in ce.segment(hours, pres):
        row = ce.estimate_cycle(hours[a:b + 1], pres[a:b + 1])
        cycles.append({
            'start': ts[a], 'end': ts[b],
            'duration_hr': round(float(hours[b] - hours[a]), 2),
            'screened': bool(row and row['screened']),
            'curvature': round(row['curvature'], 3) if row else None,
            'k': round(row['k'], 4) if row and row.get('k') else None,
            'rb': round(row['rb'], 5) if row and row.get('rb') else None,
        })
    scr = [c for c in cycles if c['screened'] and c['rb'] is not None]
    return {
        'status': 'ok',
        'signal': signal,
        'n_records': len(recs),
        'from': ts[0], 'to': ts[-1],
        'series': _envelope(ts, ys, max_points),
        'cycles': cycles,
        'n_cycles': len(cycles),
        'n_screened': len(scr),
        # ⚠ 這裡的中位數只是「這批匯入資料」的，不是系統定版值（那個在
        #   /api/rate，走 cycle 表、且已套校準）。
        #
        # ⚠ 而且段數少時它**根本不可用**：單一循環有近兩成算出負的 r_b，
        #   十來段的中位數精度是 ±50% 以上，很容易連正負號都是錯的。
        #   所以一律連 usability 一起回傳，前端據此決定要不要顯示數字——
        #   只給一個數字，看的人會當成結果。判定與 /api/rate 同一套。
        **_rb_here(scr),
    }


def _rb_here(scr):
    """這批資料的 r_b 中位數與可用性。段數不足時明講不可用。"""
    from core.cycle_store import median_ci
    if not scr:
        return {'median_rb_here': None, 'rb_usability': 'unusable',
                'rb_note': '沒有通過曲率預篩的循環，算不出速率。'}
    vals = [c['rb'] for c in scr]
    med = float(np.median(vals))
    lo, hi = median_ci(vals)
    prec = ((hi - lo) / 2.0 / abs(med) * 100.0) if (med and lo is not None) else None
    use = ('unusable' if prec is None or prec > 30 else
           'indicative' if prec > 15 else 'usable')
    note = {
        'unusable': '段數太少，這個數字不可用（單段近兩成為負，'
                    '十來段時連正負號都可能是錯的）。要 50 段以上才進得了 ±15%。',
        'indicative': '只能當趨勢看，不要引用數值。',
        'usable': '段數足夠，可引用。',
    }[use]
    return {'median_rb_here': round(med, 5), 'n_rb': len(vals),
            'rb_ci': [round(lo, 5), round(hi, 5)] if lo is not None else None,
            'rb_precision_pct': round(prec, 1) if prec is not None else None,
            'rb_usability': use, 'rb_note': note}


@router.get("/rate")
def api_rate():
    """目前的聚合速率與其校準來源。

    論文報的是**中位數**，不是平均——逐段估計有兩成為負（簡併在單一
    循環上的表現），平均數不可用。
    """
    from core import cycle_store as cs
    return cs.summary()


@router.post("/ingest_folder")
def api_ingest_folder(folder: str = Query(..., description="CSV 資料夾路徑")):
    """把一個資料夾（＝一個期間）的 CSV 切段、估計、寫入 cycle 表。

    ⚠ 必須以資料夾為單位。BTP_Sensor_log 是一天一檔，而循環中位長
      10.2 小時、大多跨過午夜；逐檔處理會把跨日的一段攔腰砍斷。
    """
    from core import cycle_store as cs
    if not os.path.isdir(folder):
        raise HTTPException(status_code=400, detail="資料夾不存在: %s" % folder)
    return cs.ingest_folder(folder)
