import io
import re
import time
from datetime import datetime
import numpy as np
from fastapi import APIRouter, HTTPException, File, UploadFile, Query
from fastapi.responses import StreamingResponse
from core.inference import get_pressure_prediction, sensor_buffer as _lstm_buffer
from core.data_store import sensor_records, append_record, clear_all
from core.signal_processor import ORPSignalProcessor
from core.feature_extractor import ORPFeatureExtractor
from data_pipeline.loader import _detect_schema, read_btp_daily
from api.schemas import (PressurePredictionResponse, SensorDataPayload, SensorRecord,
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


# ==========================================
# 通道 1：前端來拿取預測結果
# ==========================================
@router.get("/predict_pressure")
def predict_pressure_api():
    # buffer 不足時，從 sensor_records 最近 35 筆自動補齊（MIN_BUF=35）
    if len(_lstm_buffer) < 35 and len(sensor_records) >= 35:
        sorted_recs = sorted(sensor_records, key=lambda r: r.get('timestamp') or '')
        for r in sorted_recs[-35:]:
            _lstm_buffer.append([
                r.get('orp_raw') or r['orp'],
                r['ph'],
                r['temp'],
                r.get('pressure', 0.0),
            ])

    try:
        t0 = time.time()
        result = get_pressure_prediction()
        inference_ms = round((time.time() - t0) * 1000, 1)
        return {
            "device":                   "Jetson Orin Nano",
            "current_pressure_kg_cm2":  round(result["current_pressure_kg_cm2"], 2),
            "predicted_pressure_5min":  round(result["predicted_pressure_5min"], 2),
            "predicted_ch4_5min":       round(result.get("predicted_ch4_5min", 0.0), 2),
            "status":                   result["status"],
            "inference_time_ms":        inference_ms,
            "message": (
            "預測即將超標，請緊急處理！" if result["status"] == "危險 (Danger)"
            else "壓力上升趨勢，請留意！" if result["status"] == "警告 (Warning)"
            else "系統穩定運行中"
        ),
        }
    except Exception as e:
        return {
            "device": "Jetson Orin Nano",
            "current_pressure_kg_cm2": 0.0, "predicted_pressure_5min": 0.0,
            "predicted_ch4_5min": 0.0, "inference_time_ms": 0.0,
            "status": "模型未載入", "message": str(e),
        }


# ==========================================
# 通道 2：前端/感測器傳送最新數據過來
# ==========================================
@router.post("/upload_sensor")
def upload_sensor_data(payload: SensorDataPayload):
    print(f"[成功接收數據] ORP: {payload.orp:.1f} mV, pH: {payload.ph:.2f}, 溫度: {payload.temp:.1f} °C")
    try:
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
        "message":    "感測器數據已成功寫入 Jetson 邊緣節點",
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

    # 3. 相關係數熱力圖（6×6）
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
def _import_csv_btp_daily(text: str, detected_date: str) -> dict:
    """處理 usb_receiver.py 產生的 BTP_Sensor_log 格式：資料已完成訊號前處理，
    直接沿用 orp/orp_raw/orp_cleaned/is_anomaly 等既有結果寫入 sensor_records，
    不重跑 ORPSignalProcessor（避免對已處理過的訊號二次處理）。
    """
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
    for row in rows[-35:-1]:
        _lstm_buffer.append([row['orp_raw'], row['ph'], row['temp'], row['pressure']])

    try:
        last = rows[-1]
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
    可帶 at 指定排氣時刻（人工輸入／往後幾分鐘抓 CH4 峰值）；未填則用當下。"""
    try:
        return exp.vent_run(run_id, at=(payload.at if payload else None))
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
    if _detect_schema(first_line) == 'btp_daily':
        return _import_csv_btp_daily(text, detected_date)

    # 每次匯入建立獨立的處理器實例（不共用 USB 那個）
    processor = ORPSignalProcessor(ema_window=10, spike_threshold=-20.0, spike_max_minutes=15)

    # ── 解析 CSV ──────────────────────────────────
    parsed_rows: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(',')
        if len(parts) < 14:
            continue
        try:
            ts = (
                f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
                f" {int(parts[3]):02d}:{int(parts[4]):02d}:{int(parts[5]):02d}"
            )
            parsed_rows.append({
                'timestamp':      ts,
                'orp_raw':        float(parts[7]),
                # parts[8]/parts[11] 對調（2026-07-14 現場比對 HMI 面板確認，見
                # usb_receiver.py 同處註解）。
                'pressure':       float(parts[11]),  # 反應槽壓力
                'ph':             float(parts[9]),
                'temp':           float(parts[10]),
                'mixer_pressure': float(parts[8]),   # 氣體混合槽壓力
                'co2_pct':        float(parts[12]),
                'ch4_pct':        float(parts[13]),
            })
        except (ValueError, IndexError):
            continue

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
    for row in parsed_rows[-35:-1]:
        _lstm_buffer.append([row['orp_raw'], row['ph'], row['temp'], row['pressure']])

    try:
        last = parsed_rows[-1]
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
