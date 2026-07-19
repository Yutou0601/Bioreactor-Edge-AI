"""
實驗批次資料倉儲
================
在既有的逐分鐘 sensor_records 之上，加一層「批次（實驗 run）」的概念。
每個批次標記一段時間窗（進氣→排氣），量測結果由該時間窗內的感測訊號自動計算。

設計對應 2026-07-17 與洪博定案的實驗：
    進氣至 1.2 → 每小時循環 n 分鐘（1/5/10）→ 排氣至 1.0 → 重複
    3 水準 × 3 重複 = 9 批次（編號 1.1 / 1.2 / 1.3 …）

**只用可信訊號計算量測結果**（反應槽壓力 / ORP / pH）。CO2/CH4 只在排氣峰值取一個
「參考值」，不參與任何速率或統計計算（依 2026-07-16 確認：拖尾無效、峰值僅供參考）。
"""

from datetime import datetime
from typing import List, Optional

from core.data_store import sensor_records

# 每批次以 dict 儲存，欄位見 add_run()
experiment_runs: List[dict] = []

# 歷史資料換算的中位下降速率（kg/cm²/hr），用於「running 批次」預估排氣剩餘時間。
# 來源：docs/循環時間與排氣壓力設計說明_2026-07-17.md
DEFAULT_DROP_RATE = 0.0146

# 排氣峰值取樣：排氣時刻往前幾分鐘內取 CH4 最大值當參考峰值
VENT_PEAK_WINDOW_MIN = 5


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _records_between(start: Optional[str], end: Optional[str]) -> list:
    """取出 [start, end] 時間窗內的感測記錄（timestamp 為固定格式字串，可字典序比較）。
    start 為 None（尚未開始）時回傳空；end 為 None（進行中）時取到目前最新一筆。"""
    if not start:
        return []
    end = end or "9999-99-99 99:99:99"
    recs = [r for r in sensor_records
            if r.get("timestamp") and start <= r["timestamp"] <= end]
    return sorted(recs, key=lambda r: r["timestamp"])


def compute_results(run: dict) -> dict:
    """由批次時間窗內的感測訊號自動計算量測結果。核心量化指標＝下降壓力速率。"""
    recs = _records_between(run["start_time"], run.get("end_time"))
    out = {
        "n_points":           len(recs),
        "total_hours":        None,
        "pressure_start":     None,
        "pressure_end":       None,
        "pressure_drop_rate": None,   # kg/cm²/hr —— 主要量化指標
        "vent_ph":            None,
        "vent_orp":           None,
        "vent_ch4_peak_ref":  None,   # 僅供參考，不得作為證據
    }
    if len(recs) < 2:
        return out

    first, last = recs[0], recs[-1]
    t0 = datetime.strptime(first["timestamp"], "%Y-%m-%d %H:%M:%S")
    t1 = datetime.strptime(last["timestamp"], "%Y-%m-%d %H:%M:%S")
    hours = (t1 - t0).total_seconds() / 3600.0
    p0 = float(first.get("pressure") or 0.0)
    p1 = float(last.get("pressure") or 0.0)

    out["total_hours"] = round(hours, 2)
    out["pressure_start"] = round(p0, 3)
    out["pressure_end"] = round(p1, 3)
    if hours > 0:
        out["pressure_drop_rate"] = round((p0 - p1) / hours, 5)
    out["vent_ph"] = round(float(last.get("ph") or 0.0), 2)
    out["vent_orp"] = round(float(last.get("orp") or 0.0), 1)

    # CH4 排氣峰值（僅參考）：末段 VENT_PEAK_WINDOW_MIN 分鐘內的最大值
    tail = recs[-VENT_PEAK_WINDOW_MIN:] if len(recs) >= VENT_PEAK_WINDOW_MIN else recs
    ch4_vals = [float(r.get("ch4_pct") or 0.0) for r in tail]
    if ch4_vals:
        out["vent_ch4_peak_ref"] = round(max(ch4_vals), 2)
    return out


def _with_results(run: dict) -> dict:
    """回傳批次 dict（含即時計算的量測結果）。"""
    r = dict(run)
    r["results"] = compute_results(run)
    return r


def add_run(run_id: str, n_minutes: float, gas_ratio: str = "4:1",
            intake_pressure: float = 1.2, vent_pressure: float = 1.0,
            note: str = "") -> dict:
    """新增一個批次（status=planned，尚未開始）。run_id 不可重複。
    9 個批次通常一次規劃好、之後分天依序執行，故新增時不記起始時間。"""
    if any(r["run_id"] == run_id for r in experiment_runs):
        raise ValueError(f"批次 {run_id} 已存在")
    run = {
        "run_id":          run_id,
        "n_minutes":       n_minutes,
        "gas_ratio":       gas_ratio,
        "intake_pressure": intake_pressure,
        "vent_pressure":   vent_pressure,
        "start_time":      None,
        "end_time":        None,
        "status":          "planned",
        "note":            note,
    }
    experiment_runs.append(run)
    return _with_results(run)


def start_run(run_id: str) -> dict:
    """開始進氣：記錄起始時間、status=running。此後這段時間窗的訊號即歸入本批次。"""
    run = _find(run_id)
    run["start_time"] = _now()
    run["end_time"] = None
    run["status"] = "running"
    return _with_results(run)


def vent_run(run_id: str) -> dict:
    """標記批次排氣（設定 end_time、status=done），量測結果隨即由時間窗計算。"""
    run = _find(run_id)
    if not run.get("start_time"):
        raise ValueError(f"批次 {run_id} 尚未開始，無法排氣")
    run["end_time"] = _now()
    run["status"] = "done"
    return _with_results(run)


def update_run(run_id: str, fields: dict) -> dict:
    """修改批次設定或手動填入的欄位（例如手動修正起訖時間）。"""
    run = _find(run_id)
    allowed = {"n_minutes", "gas_ratio", "intake_pressure", "vent_pressure",
               "start_time", "end_time", "status", "note"}
    for k, v in fields.items():
        if k in allowed and v is not None:
            run[k] = v
    return _with_results(run)


def delete_run(run_id: str) -> dict:
    run = _find(run_id)
    experiment_runs.remove(run)
    return {"status": "deleted", "run_id": run_id}


def list_runs() -> list:
    """所有批次（含量測結果），依 run_id 排序。"""
    return [_with_results(r) for r in sorted(experiment_runs, key=lambda r: _run_sort_key(r["run_id"]))]


def get_live_status(run_id: str) -> dict:
    """進行中批次的即時狀態：目前壓力、距排氣目標還差多少、預估剩餘時間。"""
    run = _find(run_id)
    recs = _records_between(run["start_time"], run.get("end_time"))
    if not recs:
        return {"run_id": run_id, "status": run["status"], "message": "尚無感測資料"}

    last = recs[-1]
    cur_p = float(last.get("pressure") or 0.0)
    target = float(run["vent_pressure"])

    # 即時下降速率：用本批次目前資料估；不足則用歷史中位速率
    live_rate = None
    if len(recs) >= 30:
        res = compute_results(run)
        live_rate = res.get("pressure_drop_rate")
    rate = live_rate if (live_rate and live_rate > 0) else DEFAULT_DROP_RATE

    remaining = cur_p - target
    eta_hours = round(remaining / rate, 1) if rate > 0 and remaining > 0 else 0.0
    return {
        "run_id":         run_id,
        "status":         run["status"],
        "current_pressure": round(cur_p, 3),
        "vent_target":    target,
        "remaining_kg":   round(remaining, 3),
        "rate_used":      round(rate, 5),
        "rate_is_live":   bool(live_rate and live_rate > 0),
        "eta_hours":      eta_hours,
        "reached_target": remaining <= 0,
        "n_points":       len(recs),
    }


# ── 內部工具 ──────────────────────────────────────────
def _find(run_id: str) -> dict:
    for r in experiment_runs:
        if r["run_id"] == run_id:
            return r
    raise KeyError(f"找不到批次 {run_id}")


def _run_sort_key(run_id: str):
    """讓 "1.1" < "1.2" < "2.1" < "10.1" 正確排序。"""
    try:
        parts = run_id.split(".")
        return tuple(int(p) for p in parts)
    except (ValueError, AttributeError):
        return (float("inf"), run_id)


def clear_all() -> int:
    count = len(experiment_runs)
    experiment_runs.clear()
    return count
