"""
實驗批次資料倉儲
================
在既有的逐分鐘 sensor_records 之上，加一層「批次（實驗 run）」的概念。
每個批次＝一個 n 水準的實驗（約 48hr），期間反應槽自動補氣數次，量測結果由
批次時間窗內的感測訊號自動計算。

設計對應 2026-07-22 與洪博定案的實驗協定：
    洗管線到基準（CH4 9% / CO2 21% / 壓力 1.185）→ 進氣至 1.185（上限 1.20）
    → 每小時循環 n 分鐘（第1-2天 n=1、第3-4天 n=5、第5-6天 n=10）
    → 壓力自動掉到下限 0.90 時自動補氣（約 20hr 一次、48hr 內約 3 次）
    → 48hr 後排氣、洗管線回基準，換下一個 n。

**已知混淆（重要）**：n 與「時間／菌群成熟度」共線——n=1/5/10 分別在不同天，
而菌群這 6 天持續成熟、成熟度會主導壓力下降速率（見證據鏈文件）。洗管線只重置
氣相、不重置生物。**因此系統會自動記錄每次補氣「進氣前的 ORP」當菌群成熟度的
代理共變數**（進氣前 ORP＝上一循環末、H2 耗盡、ORP 已恢復的高點），事後分析時
可用它把菌群漂移從 n 效應中扣除。見 compute_cycles() 的 pre_injection_orp。

**只用可信訊號計算**（反應槽壓力 / ORP / pH）。CO2/CH4 只在排氣峰值取參考值。
"""

import json
import os
from datetime import datetime
from typing import List, Optional

from core.data_store import sensor_records

experiment_runs: List[dict] = []

# 批次設定落地儲存：只存 run 設定 + 起訖時間（量測結果由 sensor_records 重算，不落地）。
# 重開後端會自動還原批次，配合重新匯入 sensor 資料即可恢復量測結果。
_STORE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "experiment_runs.json")

DEFAULT_DROP_RATE = 0.0146       # 歷史中位下降速率 kg/cm²/hr，資料不足時的預估用
REFILL_JUMP = 0.05               # 反應槽壓力單步跳升超過此值＝一次自動補氣
VENT_PEAK_WINDOW_MIN = 5         # 排氣峰值：末段幾分鐘取 CH4 最大值當參考
ORP_CRASH_WINDOW_MIN = 40        # 進氣後幾分鐘內找 ORP 崩落最低點


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _normalize_ts(ts: Optional[str]) -> Optional[str]:
    """把外部傳入的時間字串正規化成感測器的 'YYYY-MM-DD HH:MM:SS' 格式。
    前端 <input type=datetime-local> 送出的是 '2026-07-22T14:30'（T 分隔、無秒），
    直接拿去跟感測器時間戳字串比較會失效（'T' > 空格），且 strptime 會失敗——
    這會讓「指定過去時間開始」抓不到既有資料。此函式修正該問題。"""
    if not ts:
        return ts
    ts = ts.strip().replace("T", " ")
    date_time = ts.split(" ")
    if len(date_time) == 2 and date_time[1].count(":") == 1:   # 只有 HH:MM，補上 :00
        ts = f"{date_time[0]} {date_time[1]}:00"
    return ts


def _parse(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")


def _records_between(start: Optional[str], end: Optional[str]) -> list:
    """取出 [start, end] 時間窗內的感測記錄。start 為 None（未開始）回傳空；
    end 為 None（進行中）取到目前最新一筆。"""
    if not start:
        return []
    end = end or "9999-99-99 99:99:99"
    recs = [r for r in sensor_records
            if r.get("timestamp") and start <= r["timestamp"] <= end]
    return sorted(recs, key=lambda r: r["timestamp"])


# ── 每循環（補氣週期）分析 ──────────────────────────────
def compute_cycles(run: dict) -> list:
    """把批次時間窗切成「相鄰兩次自動補氣之間」的循環週期，每週期算：
    下降壓力速率、進氣前 ORP（菌群成熟度共變數）、ORP 崩落深度。
    這是給模型用的每循環特徵表。"""
    recs = _records_between(run["start_time"], run.get("end_time"))
    if len(recs) < 2:
        return []

    p = [float(r.get("pressure") or 0.0) for r in recs]
    orp = [float(r.get("orp") or 0.0) for r in recs]

    # 補氣事件＝壓力單步跳升。每次補氣後是一個「高壓起點」，之後壓力下降到下次補氣前。
    # 一個循環週期＝從補氣後高點 → 下次補氣前的低點（只取下降段，不含下次跳升）。
    refills = [i for i in range(1, len(recs)) if p[i] - p[i - 1] > REFILL_JUMP]
    starts = [0] + refills               # 每個都是進氣後的高壓起點（含實驗最初的進氣）

    cycles = []
    for k, a in enumerate(starts):
        b = starts[k + 1] if k + 1 < len(starts) else len(recs)   # 下次進氣（不含）或資料末端
        seg = recs[a:b]
        if len(seg) < 3:
            continue
        t0, t1 = _parse(seg[0]["timestamp"]), _parse(seg[-1]["timestamp"])
        hours = (t1 - t0).total_seconds() / 3600.0
        p0, p1 = p[a], p[b - 1]          # 進氣後高點 → 下次進氣前低點

        # 進氣前 ORP：本週期進氣「之前」那一筆（上一循環末、H2 已耗盡、ORP 已恢復的高點）
        # ＝菌群成熟度代理共變數。第一個週期（實驗最初進氣）沒有「之前」，取起點值。
        pre_orp = orp[a - 1] if a > 0 else orp[a]
        crash_end = min(a + ORP_CRASH_WINDOW_MIN, b)
        orp_crash = min(orp[a:crash_end]) if crash_end > a else orp[a]

        cycles.append({
            "cycle":               k + 1,
            "start":               seg[0]["timestamp"][:16],
            "end":                 seg[-1]["timestamp"][:16],
            "duration_hr":         round(hours, 2),
            "pressure_start":      round(p0, 3),
            "pressure_end":        round(p1, 3),
            "drop_rate":           round((p0 - p1) / hours, 5) if hours > 0 else None,
            "pre_injection_orp":   round(pre_orp, 1),   # ← 菌群成熟度共變數
            "orp_crash":           round(orp_crash, 1),
            "is_refill_start":     a in refills,
        })
    return cycles


def compute_results(run: dict) -> dict:
    """批次的彙整量測結果（跨所有循環週期）。核心量化指標＝各週期下降速率的中位數。"""
    recs = _records_between(run["start_time"], run.get("end_time"))
    out = {
        "n_points":            len(recs),
        "total_hours":         None,
        "n_cycles":            0,
        "drop_rate_median":    None,   # 各週期下降速率中位數 —— 主要量化指標
        "pre_orp_first":       None,   # 第一次補氣前 ORP
        "pre_orp_last":        None,   # 最後一次補氣前 ORP
        "culture_drift":       None,   # 進氣前 ORP 隨週期的漂移（末-首），監測菌群成熟
        "vent_ph":             None,
        "vent_orp":            None,
        "vent_ch4_peak_ref":   None,
    }
    if len(recs) < 2:
        return out

    first, last = recs[0], recs[-1]
    hours = (_parse(last["timestamp"]) - _parse(first["timestamp"])).total_seconds() / 3600.0
    out["total_hours"] = round(hours, 2)

    cycles = compute_cycles(run)
    out["n_cycles"] = len(cycles)
    rates = [c["drop_rate"] for c in cycles if c["drop_rate"] is not None]
    if rates:
        rates_sorted = sorted(rates)
        out["drop_rate_median"] = round(rates_sorted[len(rates_sorted) // 2], 5)
    pre_orps = [c["pre_injection_orp"] for c in cycles if c.get("is_refill_start")]
    if pre_orps:
        out["pre_orp_first"] = pre_orps[0]
        out["pre_orp_last"] = pre_orps[-1]
        out["culture_drift"] = round(pre_orps[-1] - pre_orps[0], 1)

    out["vent_ph"] = round(float(last.get("ph") or 0.0), 2)
    out["vent_orp"] = round(float(last.get("orp") or 0.0), 1)
    tail = recs[-VENT_PEAK_WINDOW_MIN:] if len(recs) >= VENT_PEAK_WINDOW_MIN else recs
    ch4_vals = [float(r.get("ch4_pct") or 0.0) for r in tail]
    if ch4_vals:
        out["vent_ch4_peak_ref"] = round(max(ch4_vals), 2)
    return out


def _with_results(run: dict) -> dict:
    r = dict(run)
    r["results"] = compute_results(run)
    return r


# ── 批次生命週期 ────────────────────────────────────
def add_run(run_id: str, n_minutes: float, gas_ratio: str = "4:1",
            intake_lower: float = 0.90, intake_upper: float = 1.185,
            baseline_ch4: float = 9.0, baseline_co2: float = 21.0,
            baseline_pressure: float = 1.185, target_hours: float = 48.0,
            scheduled_start: Optional[str] = None, note: str = "") -> dict:
    """新增一個批次（status=planned）。run_id 不可重複。
    scheduled_start 可預先排定開始時間；未填則由 start_run 時記為當下。"""
    if any(r["run_id"] == run_id for r in experiment_runs):
        raise ValueError(f"批次 {run_id} 已存在")
    run = {
        "run_id":            run_id,
        "n_minutes":         n_minutes,
        "gas_ratio":         gas_ratio,
        "intake_lower":      intake_lower,
        "intake_upper":      intake_upper,
        "baseline_ch4":      baseline_ch4,
        "baseline_co2":      baseline_co2,
        "baseline_pressure": baseline_pressure,
        "target_hours":      target_hours,
        "scheduled_start":   _normalize_ts(scheduled_start),
        "start_time":        None,
        "end_time":          None,
        "status":            "planned",
        "note":              note,
    }
    experiment_runs.append(run)
    _save()
    return _with_results(run)


def start_run(run_id: str, at: Optional[str] = None) -> dict:
    """開始實驗（記錄起始時間）。at 可指定特定時間（如排定的開始時刻），
    未填則用排程時間 scheduled_start，再退回當下。"""
    run = _find(run_id)
    run["start_time"] = _normalize_ts(at) or run.get("scheduled_start") or _now()
    run["end_time"] = None
    run["status"] = "running"
    _save()
    return _with_results(run)


def vent_run(run_id: str, at: Optional[str] = None) -> dict:
    """標記實驗結束排氣（設定 end_time、status=done）。"""
    run = _find(run_id)
    if not run.get("start_time"):
        raise ValueError(f"批次 {run_id} 尚未開始，無法排氣")
    run["end_time"] = _normalize_ts(at) or _now()
    run["status"] = "done"
    _save()
    return _with_results(run)


def update_run(run_id: str, fields: dict) -> dict:
    run = _find(run_id)
    allowed = {"n_minutes", "gas_ratio", "intake_lower", "intake_upper",
               "baseline_ch4", "baseline_co2", "baseline_pressure", "target_hours",
               "scheduled_start", "start_time", "end_time", "status", "note"}
    time_fields = {"scheduled_start", "start_time", "end_time"}
    for k, v in fields.items():
        if k in allowed and v is not None:
            run[k] = _normalize_ts(v) if k in time_fields else v
    _save()
    return _with_results(run)


def delete_run(run_id: str) -> dict:
    run = _find(run_id)
    experiment_runs.remove(run)
    _save()
    return {"status": "deleted", "run_id": run_id}


def list_runs() -> list:
    return [_with_results(r) for r in sorted(experiment_runs, key=lambda r: _run_sort_key(r["run_id"]))]


def get_cycles(run_id: str) -> dict:
    """單一批次的每循環特徵表。"""
    run = _find(run_id)
    return {"run_id": run_id, "n_minutes": run["n_minutes"], "cycles": compute_cycles(run)}


def all_cycles() -> list:
    """所有批次的每循環特徵攤平成一張表（每列＝一個循環週期，含批次/n 標籤）。
    這才是餵模型的資料：drop_rate 為反應變數、pre_injection_orp 為菌群共變數、
    n_minutes 為控制因子。"""
    rows = []
    for run in sorted(experiment_runs, key=lambda r: _run_sort_key(r["run_id"])):
        for cy in compute_cycles(run):
            rows.append({"run_id": run["run_id"], "n_minutes": run["n_minutes"], **cy})
    return rows


def get_live_status(run_id: str) -> dict:
    """進行中批次的即時狀態：目前壓力、距下次自動補氣（下限）、本實驗已跑/剩餘時間。"""
    run = _find(run_id)
    recs = _records_between(run["start_time"], run.get("end_time"))
    if not recs:
        return {"run_id": run_id, "status": run["status"], "message": "尚無感測資料"}

    last = recs[-1]
    cur_p = float(last.get("pressure") or 0.0)
    lower = float(run["intake_lower"])

    live_rate = None
    if len(recs) >= 30:
        cyc = compute_cycles(run)
        rates = [c["drop_rate"] for c in cyc if c["drop_rate"]]
        if rates:
            live_rate = rates[-1]
    rate = live_rate if (live_rate and live_rate > 0) else DEFAULT_DROP_RATE

    remaining = cur_p - lower
    eta_refill = round(remaining / rate, 1) if rate > 0 and remaining > 0 else 0.0
    elapsed = (_parse(last["timestamp"]) - _parse(run["start_time"])).total_seconds() / 3600.0
    return {
        "run_id":            run_id,
        "status":            run["status"],
        "current_pressure":  round(cur_p, 3),
        "current_orp":       round(float(last.get("orp") or 0.0), 1),
        "intake_lower":      lower,
        "remaining_kg":      round(remaining, 3),
        "rate_used":         round(rate, 5),
        "rate_is_live":      bool(live_rate and live_rate > 0),
        "eta_refill_hours":  eta_refill,
        "elapsed_hours":     round(elapsed, 1),
        "target_hours":      run.get("target_hours"),
        "n_cycles_so_far":   len(compute_cycles(run)),
    }


# ── 內部工具 ──────────────────────────────────────────
def _find(run_id: str) -> dict:
    for r in experiment_runs:
        if r["run_id"] == run_id:
            return r
    raise KeyError(f"找不到批次 {run_id}")


def _run_sort_key(run_id: str):
    try:
        return tuple(int(p) for p in run_id.split("."))
    except (ValueError, AttributeError):
        return (float("inf"), run_id)


def clear_all() -> int:
    count = len(experiment_runs)
    experiment_runs.clear()
    _save()
    return count


# ── 落地儲存 ──────────────────────────────────────────
def _save() -> None:
    """把批次設定寫入 JSON（原子寫入：先寫暫存再改名，避免中途中斷寫壞）。"""
    try:
        tmp = _STORE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(experiment_runs, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _STORE_PATH)
    except Exception as e:
        print(f"[experiment_store] 批次儲存失敗（不影響運作）: {e}")


def _load() -> None:
    """模組載入時從 JSON 還原批次（檔案不存在或損壞則從空白開始，不中斷服務）。"""
    try:
        if os.path.exists(_STORE_PATH):
            with open(_STORE_PATH, encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, list):
                experiment_runs.clear()
                experiment_runs.extend(loaded)
                print(f"[experiment_store] 已還原 {len(loaded)} 個批次")
    except Exception as e:
        print(f"[experiment_store] 批次還原失敗（從空白開始）: {e}")


_load()   # 模組載入時自動還原
