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

import bisect
import json
import os
from datetime import datetime, timedelta
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
GAP_MINUTES = 30                 # 相鄰兩筆間隔超過此值＝記錄中斷、切段（正常為 1 筆/分）。
                                 # 設 30 分而非 5 分：記錄程式每隔幾小時常有 5~9 分鐘的
                                 # 良性斷點（實測 07-22~07-27 有 26 次），1 分取樣下這麼短
                                 # 的洞不可能藏得下一次完整補氣（進氣本身就要 4~7 分、完整
                                 # 緩降是數小時），把它們當中斷會把整段緩降切碎、每段都貼著
                                 # 斷點而被判「非完整」→ 所有循環被排除。門檻只需擋得住「久到
                                 # 足以藏一次補氣」的真中斷（如 2026-07-22 夜的 14.6 小時
                                 # Windows 更新停機，仍會被抓）。即使補氣落在洞裡造成跨洞的
                                 # 壓力位移，_detect_refills 仍會在洞邊界抓成一次補氣，不會漏。
MIN_CYCLE_MINUTES = 20           # 短於此的片段視為切分雜訊（如多步補氣），不計為循環


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
_RISE_TOL = 0.003        # 上升段容忍的微小回跌（雜訊），超過才算上升段結束


def _detect_refills(p: list) -> set:
    """偵測補氣事件（壓力回升），回傳每次補氣後「高點」的索引。
    **抓持續上升段**而非只看單步——反應器補氣可能一分鐘跳完，也可能分幾分鐘慢慢充；
    只要一段上升的累積漲幅 > REFILL_JUMP 就算一次補氣，標記其頂點（＝新循環的高壓起點）。
    這修正了「補氣分多步、單步 <門檻 而完全抓不到」的問題。"""
    n = len(p)
    refills = set()
    i = 1
    while i < n:
        if p[i] - p[i - 1] > _RISE_TOL:                 # 進入上升段
            start_low = p[i - 1]
            peak, peak_idx = p[i], i
            j = i + 1
            while j < n:
                if p[j] > peak:                          # 續創新高＝仍在補氣
                    peak, peak_idx = p[j], j
                elif peak - p[j] > _RISE_TOL:            # 明確跌離頂點＝上升段結束
                    break
                j += 1
            if peak - start_low > REFILL_JUMP:          # 整段累積漲幅夠大＝一次補氣
                refills.add(peak_idx)                    # 頂點＝補氣後高點
            i = peak_idx + 1                             # 從頂點之後繼續找下一次
        else:
            i += 1
    return refills


def _segment(recs: list):
    """把記錄序列切成「相鄰兩次補氣／記錄中斷之間」的段落起點。
    回傳 (p, orp, ts, refills, gaps, starts)，供 compute_cycles 與即時面板共用。
    切段點有兩種：
      - 補氣：壓力持續回升（_detect_refills，容多步慢充）
      - 記錄中斷：相鄰兩筆時間間隔過大（gaps）——反應器仍在跑但沒記到，不可跨越
    切開後每一段都是「連續記錄、中間沒有補氣」的純下降段，速率才有意義。"""
    p = [float(r.get("pressure") or 0.0) for r in recs]
    orp = [float(r.get("orp") or 0.0) for r in recs]
    ph = [float(r.get("ph") or 0.0) for r in recs]
    ts = [_parse(r["timestamp"]) for r in recs]
    refills = _detect_refills(p)
    gaps = {i for i in range(1, len(recs))
            if (ts[i] - ts[i - 1]).total_seconds() > GAP_MINUTES * 60}
    starts = sorted({0} | refills | gaps)
    return p, orp, ph, ts, refills, gaps, starts


def compute_cycles(run: dict) -> list:
    """把批次時間窗切成「相鄰兩次自動補氣之間」的循環週期，每週期算：
    下降壓力速率、進氣前 ORP（菌群成熟度共變數）、ORP 崩落深度、斜率平緩化。
    這是給模型用的每循環特徵表。

    **記錄中斷處必須切段**（2026-07-22 監控電腦自動更新事件後補強）：記錄中斷
    期間反應器仍在跑、仍會自動補氣，但那次補氣沒有被記到。若讓一個週期跨過斷點，
    會把「斷線前的下降」和「斷線後另一次補氣的下降」黏成同一段，得到
    偏低的下降速率與**假的斜率平緩化（看起來像產甲烷）**——正是本研究要量的訊號，
    且匯出後從數值上看不出異常。故在斷點處一律切開，並標記資料完整性。
    """
    recs = _records_between(run["start_time"], run.get("end_time"))
    if len(recs) < 2:
        return []

    p, orp, ph, ts, refills, gaps, starts = _segment(recs)

    # 第一段的起點沒有「跳升」可觀測（記錄從實驗開始才有）。若起始壓力就在基準值
    # 附近，代表批次是從進氣當下開始記的，該段為完整循環；否則是從半途接上的殘段。
    base_p = float(run.get("baseline_pressure") or 0.0)
    head_complete = base_p > 0 and abs(p[0] - base_p) <= REFILL_JUMP

    cycles = []
    for k, a in enumerate(starts):
        b = starts[k + 1] if k + 1 < len(starts) else len(recs)   # 下個切點（不含）或資料末端
        seg = recs[a:b]
        if len(seg) < 3:
            continue
        t0, t1 = ts[a], ts[b - 1]
        hours = (t1 - t0).total_seconds() / 3600.0
        if hours * 60 < MIN_CYCLE_MINUTES:      # 過短＝切分雜訊（例如分多步完成的補氣）
            continue

        # 下降段量到「谷底」而非段末：補氣邊界標在頂點，但補氣的上升邊有時陡（1 分）
        # 有時緩（十幾分）。若量到段末(b-1)，遇到緩升補氣時段末點會落在下一次補氣的
        # 上升邊上（壓力已回升到近頂），使 drop_rate=(頂−近頂)/時 ≈ 0，把一段真下降
        # 誤算成「幾乎沒降」。故下降段一律取 [段首 → 段內壓力最低點(谷底)]，上升邊歸還
        # 給下一循環。（2026-07-27 以 07-22~27 實測資料抓到此假象後修正。）
        tro = a + int(min(range(b - a), key=lambda j: p[a + j]))   # 谷底索引
        dec_hours = (ts[tro] - t0).total_seconds() / 3600.0
        p0, p1 = p[a], p[tro]            # 段首高點 → 谷底低點

        # 資料完整性：起點要是「有觀測到的補氣」、終點要是「有觀測到的下次補氣」，
        # 且兩端都不是記錄中斷造成的。中斷處的壓力跳升不算補氣——我們無從得知
        # 那次補氣發生在斷線期間的哪個時刻，起始高點也可能已經掉了一段。
        started_by_refill = (a in refills and a not in gaps) if a > 0 else head_complete
        ended_by_refill = b < len(recs) and b in refills and b not in gaps
        complete = started_by_refill and ended_by_refill
        if complete:
            quality = "完整"
        elif (a in gaps) or (b < len(recs) and b in gaps):
            quality = "記錄中斷"
        elif b >= len(recs):
            quality = "進行中"
        else:
            quality = "起點未觀測"

        # 進氣前 ORP：本週期進氣「之前」那一筆（上一循環末、H2 已耗盡、ORP 已恢復的高點）
        # ＝菌群成熟度代理共變數。段首非實際觀測到的補氣時，此值不具意義。
        pre_orp = round(orp[a - 1], 1) if (a > 0 and started_by_refill) else None
        # 進氣前 pH：同理，本週期進氣前一筆的 pH（洪博：ORP、pH 都要對 slope 做關聯）。
        pre_ph = round(ph[a - 1], 2) if (a > 0 and started_by_refill and ph[a - 1] > 0) else None
        crash_to = bisect.bisect_right(ts, t0 + timedelta(minutes=ORP_CRASH_WINDOW_MIN), a, b)
        orp_crash = round(min(orp[a:crash_to]), 1) if crash_to > a else round(orp[a], 1)

        # 週期內斜率平緩化（洪博：產甲烷→CH4 稀釋 CO2→溶解變慢→斜率平緩）。
        # 分早段/晚段各自的下降速率；flattening = 早 − 晚，>0 代表減速（曲線先陡後平）。
        # 以「時間中點」而非索引中點切分（記錄有缺漏時兩者不一致）。
        # 只對完整週期計算：殘段的早/晚段不是同一件事，比較沒有意義。
        # 注意：平緩化同時可能來自物理溶解趨近飽和，需搭配 pre_injection_orp 共變數
        # 才能判斷是生物還是物理造成，單看此值不能分離（見證據鏈文件）。
        slope_early = slope_late = flattening = None
        if complete and tro - a >= 4:      # 早/晚段各至少 2 點；同樣只看下降段 [a→谷底]
            tdec = ts[tro]
            mid = bisect.bisect_left(ts, t0 + (tdec - t0) / 2, a, tro)
            if mid - a >= 2 and tro - mid >= 2:
                hr_e = (ts[mid] - t0).total_seconds() / 3600.0
                hr_l = (tdec - ts[mid]).total_seconds() / 3600.0
                if hr_e > 0 and hr_l > 0:
                    slope_early = round((p[a] - p[mid]) / hr_e, 5)
                    slope_late = round((p[mid] - p[tro]) / hr_l, 5)
                    flattening = round(slope_early - slope_late, 5)

        cycles.append({
            "cycle":               len(cycles) + 1,
            "start":               seg[0]["timestamp"][:16],
            "end":                 seg[-1]["timestamp"][:16],
            "duration_hr":         round(hours, 2),        # 整個循環（含補氣上升邊）時長
            "decline_hr":          round(dec_hours, 2),    # 純下降段（段首→谷底）時長
            "pressure_start":      round(p0, 3),
            "pressure_end":        round(p1, 3),           # 谷底壓力
            "drop_rate":           round((p0 - p1) / dec_hours, 5) if dec_hours > 0 else None,
            "slope_early":         slope_early,   # 早段下降速率
            "slope_late":          slope_late,    # 晚段下降速率
            "flattening":          flattening,    # 早−晚，>0=平緩化（疑似產甲烷）
            "pre_injection_orp":   pre_orp,       # ← 菌群成熟度共變數
            "pre_injection_ph":    pre_ph,        # ← 進氣前 pH（洪博：ORP、pH 都做）
            "refill_index":        len(cycles) + 1,  # ← 補氣次數/週期序（批次內累積成熟度軸）
            "orp_crash":           orp_crash,
            "is_refill_start":     started_by_refill,
            "complete":            complete,      # 僅完整週期進入統計與建模
            "quality":             quality,
        })
    return cycles


def compute_results(run: dict) -> dict:
    """批次的彙整量測結果（跨所有循環週期）。核心量化指標＝各週期下降速率的中位數。"""
    recs = _records_between(run["start_time"], run.get("end_time"))
    out = {
        "n_points":            len(recs),
        "total_hours":         None,
        "n_cycles":            0,
        "n_cycles_complete":   0,      # 完整週期數 —— 只有這些進入統計與建模
        "n_gaps":              0,      # 記錄中斷次數
        "gap_hours":           None,   # 記錄中斷合計時數（反應器仍在跑，只是沒記到）
        "drop_rate_median":    None,   # 完整週期下降速率中位數 —— 主要量化指標
        "drop_rate_iqr":       None,   # 下降速率四分位距（離散度，投稿需附）
        "drop_rate_min":       None,
        "drop_rate_max":       None,
        "pre_orp_first":       None,   # 第一次補氣前 ORP
        "pre_orp_last":        None,   # 最後一次補氣前 ORP
        "culture_drift":       None,   # 進氣前 ORP 隨週期的漂移（末-首），監測菌群成熟
        "vent_ph":             None,
        "vent_orp":            None,
        "vent_ch4_peak_ref":   None,
        "vent_co2":            None,
        "peaks_manual":        [],     # 哪些峰值是手動輸入的（現場觀測，較準）
    }
    mp = run.get("manual_peaks") or {}
    if len(recs) < 2:
        # 即使還沒資料，手動峰值也要能顯示（例如先建批次、事後補填）
        for k, key in (("orp", "vent_orp"), ("ph", "vent_ph"),
                       ("ch4", "vent_ch4_peak_ref"), ("co2", "vent_co2")):
            if k in mp:
                out[key] = mp[k]; out["peaks_manual"].append(k)
        return out

    first, last = recs[0], recs[-1]
    hours = (_parse(last["timestamp"]) - _parse(first["timestamp"])).total_seconds() / 3600.0
    out["total_hours"] = round(hours, 2)

    # 記錄中斷統計：讓「這批資料到底有多完整」在報表上是明講的，而不是要人自己發現
    ts = [_parse(r["timestamp"]) for r in recs]
    gaps = [(ts[i] - ts[i - 1]).total_seconds() / 3600.0 for i in range(1, len(ts))
            if (ts[i] - ts[i - 1]).total_seconds() > GAP_MINUTES * 60]
    out["n_gaps"] = len(gaps)
    out["gap_hours"] = round(sum(gaps), 2) if gaps else 0.0

    cycles = compute_cycles(run)
    out["n_cycles"] = len(cycles)
    done = [c for c in cycles if c.get("complete")]
    out["n_cycles_complete"] = len(done)
    # 只用完整週期算中位數：殘段的起點不是進氣後高點，速率會系統性偏低
    rates = [c["drop_rate"] for c in done if c["drop_rate"] is not None]
    if rates:
        out["drop_rate_median"] = round(_quantile(rates, 0.5), 5)
        out["drop_rate_min"] = round(min(rates), 5)
        out["drop_rate_max"] = round(max(rates), 5)
        # IQR 需至少 2 點才有意義；單一完整循環時留 None，不要報 0 讓人以為「零散布」
        if len(rates) >= 2:
            out["drop_rate_iqr"] = round(_quantile(rates, 0.75) - _quantile(rates, 0.25), 5)
    pre_orps = [c["pre_injection_orp"] for c in cycles
                if c.get("is_refill_start") and c.get("pre_injection_orp") is not None]
    if pre_orps:
        out["pre_orp_first"] = pre_orps[0]
        out["pre_orp_last"] = pre_orps[-1]
        # 漂移要有頭尾兩點才算得出來；只有一次補氣時留 None，不要報 0 讓人誤讀成「沒漂移」
        if len(pre_orps) >= 2:
            out["culture_drift"] = round(pre_orps[-1] - pre_orps[0], 1)

    # 自動抓的排氣值（末筆 ORP/pH、末段 CH4/CO2 峰值）
    out["vent_ph"] = round(float(last.get("ph") or 0.0), 2)
    out["vent_orp"] = round(float(last.get("orp") or 0.0), 1)
    tail = recs[-VENT_PEAK_WINDOW_MIN:] if len(recs) >= VENT_PEAK_WINDOW_MIN else recs
    ch4_vals = [float(r.get("ch4_pct") or 0.0) for r in tail]
    co2_vals = [float(r.get("co2_pct") or 0.0) for r in tail]
    if ch4_vals:
        out["vent_ch4_peak_ref"] = round(max(ch4_vals), 2)
    if co2_vals:
        out["vent_co2"] = round(max(co2_vals), 2)

    # 手動峰值覆蓋：有填就用現場觀測值（較準），並記在 peaks_manual 供報表標示
    for k, key in (("orp", "vent_orp"), ("ph", "vent_ph"),
                   ("ch4", "vent_ch4_peak_ref"), ("co2", "vent_co2")):
        if k in mp:
            out[key] = mp[k]
            out["peaks_manual"].append(k)
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
        # 手動峰值：排氣時操作員在現場 HMI 觀測到的真實峰值。感測器 1 筆/分鐘常錯過
        # 排氣瞬間的峰（尤其 CH4），手動輸入比自動抓的更準。空＝用自動抓的值。
        "manual_peaks":      {},   # {"orp":.., "ph":.., "co2":.., "ch4":..}
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


def vent_run(run_id: str, at: Optional[str] = None, peaks: Optional[dict] = None) -> dict:
    """標記實驗結束排氣（設定 end_time、status=done）。
    peaks 可帶現場觀測的手動峰值 {"orp","ph","co2","ch4"}，只更新有填的欄位。"""
    run = _find(run_id)
    if not run.get("start_time"):
        raise ValueError(f"批次 {run_id} 尚未開始，無法排氣")
    run["end_time"] = _normalize_ts(at) or _now()
    run["status"] = "done"
    _set_manual_peaks(run, peaks)
    _save()
    return _with_results(run)


def _set_manual_peaks(run: dict, peaks: Optional[dict]) -> None:
    """把有填的手動峰值寫入 run['manual_peaks']；None/空字串代表清除該欄。"""
    if not peaks:
        return
    mp = dict(run.get("manual_peaks") or {})
    for k in ("orp", "ph", "co2", "ch4"):
        if k in peaks:
            v = peaks[k]
            if v is None or v == "":
                mp.pop(k, None)              # 清除
            else:
                try:
                    mp[k] = float(v)
                except (TypeError, ValueError):
                    pass                      # 非數字忽略
    run["manual_peaks"] = mp


def update_run(run_id: str, fields: dict) -> dict:
    run = _find(run_id)
    allowed = {"n_minutes", "gas_ratio", "intake_lower", "intake_upper",
               "baseline_ch4", "baseline_co2", "baseline_pressure", "target_hours",
               "scheduled_start", "start_time", "end_time", "status", "note"}
    time_fields = {"scheduled_start", "start_time", "end_time"}
    for k, v in fields.items():
        if k in allowed and v is not None:
            run[k] = _normalize_ts(v) if k in time_fields else v
    if "manual_peaks" in fields:            # 手動峰值可事後編輯
        _set_manual_peaks(run, fields["manual_peaks"])
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


def complete_cycle_trajectories() -> list:
    """取出所有『完整循環』的壓力軌跡（給灰箱機理分析擬合用）。
    每個循環回傳其補氣後高點到下次補氣前的逐分鐘壓力序列 + 中繼資訊。
    只取完整循環——殘段/記錄中斷的軌跡形狀不可信，不能拿去擬合機理模型。"""
    out = []
    for run in experiment_runs:
        recs = _records_between(run["start_time"], run.get("end_time"))
        if len(recs) < 10:
            continue
        p, orp, ph, ts, refills, gaps, starts = _segment(recs)
        base_p = float(run.get("baseline_pressure") or 0.0)
        head_complete = base_p > 0 and abs(p[0] - base_p) <= REFILL_JUMP
        for k, a in enumerate(starts):
            b = starts[k + 1] if k + 1 < len(starts) else len(recs)
            if b - a < 6:
                continue
            started = (a in refills and a not in gaps) if a > 0 else head_complete
            ended = b < len(recs) and b in refills and b not in gaps
            if not (started and ended):        # 只要完整循環
                continue
            # 只取下降段 [段首→谷底]，剪掉下一次補氣的上升邊（與 compute_cycles 一致）。
            # 否則緩升補氣的上升邊會混進軌跡，讓灰箱把「真下降+回升」誤讀成快慢兩群、
            # 產生假的暫態/穩態對比。
            tro = a + int(min(range(b - a), key=lambda j: p[a + j]))
            if tro - a < 5:                        # 下降段太短，形狀不足以擬合
                continue
            dt_min = (ts[a + 1] - ts[a]).total_seconds() / 60.0 or 1.0
            out.append({
                "run_id":     run["run_id"],
                "n_minutes":  run["n_minutes"],
                "start":      recs[a]["timestamp"][:16],
                "pressure":   [round(v, 4) for v in p[a:tro + 1]],
                "dt_min":     round(dt_min, 2),
                "baseline_p": round(base_p, 4) if base_p else round(p[a], 4),
            })
    return out


def get_live_status(run_id: str) -> dict:
    """進行中批次的即時狀態：目前壓力、距下次自動補氣（下限）、本實驗已跑/剩餘時間。"""
    run = _find(run_id)
    recs = _records_between(run["start_time"], run.get("end_time"))
    if not recs:
        return {"run_id": run_id, "status": run["status"], "message": "尚無感測資料"}

    last = recs[-1]
    cur_p = float(last.get("pressure") or 0.0)
    cur_orp = float(last.get("orp") or 0.0)
    lower = float(run["intake_lower"])
    base_p = float(run.get("baseline_pressure") or 0.0)

    p, orp, ph, ts, refills, gaps, starts = _segment(recs)

    # ── 記錄健康度（2026-07-22 事故後新增）：面板凍住時要能一眼看出是記錄死了 ──
    # staleness＝最後一筆距現在多久。逾 GAP_MINUTES 代表記錄可能已中斷，前端轉紅告警。
    # 負值＝最後一筆時間在未來，通常是記錄端與本機時鐘不同步，另行標記。
    raw_stale = (datetime.now() - ts[-1]).total_seconds() / 60.0
    clock_skew = raw_stale < -GAP_MINUTES
    staleness_min = round(max(raw_stale, 0.0), 1)
    gap_hours = round(sum((ts[i] - ts[i - 1]).total_seconds() / 3600.0 for i in gaps), 2)

    # ── 本循環（最後一段）即時曲線 + 早晚段斜率，供前端小圖與平緩化觀測 ──
    seg_a = starts[-1]
    seg = recs[seg_a:]
    series = _downsample([{"t": r["timestamp"][11:16], "p": round(p[seg_a + j], 3)}
                          for j, r in enumerate(seg)], 80)
    cyc = compute_cycles(run)

    # 本循環還沒結束，compute_cycles 不會給它算平緩化（完整性未達）。但即時觀測正需要
    # 看它「正在」變平沒有，故在此另算一份**臨時**早/晚段斜率——僅供顯示、不落地、不進建模。
    prov_early = prov_late = prov_flat = None
    if len(seg) >= 6:
        t0, t1 = ts[seg_a], ts[-1]
        mid = bisect.bisect_left(ts, t0 + (t1 - t0) / 2, seg_a, len(recs))
        if mid - seg_a >= 2 and len(recs) - mid >= 2:
            hr_e = (ts[mid] - t0).total_seconds() / 3600.0
            hr_l = (t1 - ts[mid]).total_seconds() / 3600.0
            if hr_e > 0 and hr_l > 0:
                prov_early = round((p[seg_a] - p[mid]) / hr_e, 5)
                prov_late = round((p[mid] - p[-1]) / hr_l, 5)
                prov_flat = round(prov_early - prov_late, 5)

    live_rate = None
    if len(recs) >= 30:
        rates = [c["drop_rate"] for c in cyc if c.get("complete") and c["drop_rate"]]
        if rates:
            live_rate = rates[-1]
    rate = live_rate if (live_rate and live_rate > 0) else DEFAULT_DROP_RATE

    # 進氣前 ORP 參考值：本批次最近一個「有觀測到補氣」的循環之共變數
    pre_orps = [c["pre_injection_orp"] for c in cyc
                if c.get("is_refill_start") and c.get("pre_injection_orp") is not None]

    remaining = cur_p - lower
    eta_refill = round(remaining / rate, 1) if rate > 0 and remaining > 0 else 0.0
    elapsed = (ts[-1] - _parse(run["start_time"])).total_seconds() / 3600.0
    return {
        "run_id":            run_id,
        "status":            run["status"],
        "current_pressure":  round(cur_p, 3),
        "current_orp":       round(cur_orp, 1),
        "intake_lower":      lower,
        "remaining_kg":      round(remaining, 3),
        "rate_used":         round(rate, 5),
        "rate_is_live":      bool(live_rate and live_rate > 0),
        "eta_refill_hours":  eta_refill,
        "elapsed_hours":     round(elapsed, 1),
        "target_hours":      run.get("target_hours"),
        "n_cycles_so_far":   len(cyc),
        # ── 記錄健康度 ──
        "last_timestamp":    last["timestamp"],
        "staleness_min":     staleness_min,
        "stale":             staleness_min > GAP_MINUTES,
        "clock_skew":        clock_skew,
        "n_gaps":            len(gaps),
        "gap_hours":         gap_hours,
        # ── 基準對照（只顯示，不建議調整閾值）──
        "baseline_pressure": round(base_p, 3) if base_p else None,
        "pressure_vs_base":  round(cur_p - base_p, 3) if base_p else None,
        "pre_injection_orp": pre_orps[-1] if pre_orps else None,
        "orp_vs_pre":        round(cur_orp - pre_orps[-1], 1) if pre_orps else None,
        # ── 本循環即時觀測（臨時值，循環未結束前僅供觀測，不進建模）──
        "cycle_series":      series,
        "cycle_slope_early": prov_early,
        "cycle_slope_late":  prov_late,
        "cycle_flattening":  prov_flat,
        "cycle_provisional": True,
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


def _downsample(seq: list, n: int) -> list:
    """把序列均勻抽稀到最多 n 點（保留首末），控制即時面板傳輸量。"""
    if len(seq) <= n:
        return seq
    step = (len(seq) - 1) / (n - 1)
    idx = sorted({round(i * step) for i in range(n)} | {len(seq) - 1})
    return [seq[i] for i in idx]


def _quantile(vals: list, q: float) -> float:
    """線性內插分位數（不引入 numpy，維持後端輕量）。vals 需非空。"""
    s = sorted(vals)
    if len(s) == 1:
        return s[0]
    pos = q * (len(s) - 1)
    lo = int(pos)
    frac = pos - lo
    if lo + 1 < len(s):
        return s[lo] + frac * (s[lo + 1] - s[lo])
    return s[lo]


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
