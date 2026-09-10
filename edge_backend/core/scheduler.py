
# -*- coding: utf-8 -*-
"""批次排程：到點自動開始、到點自動結束紀錄。

2026-09-02 新增。在此之前 scheduled_start 與 target_hours 只是被存起來
顯示用，沒有任何東西去執行它們——「排定開始時間」實際上仍要人記得去按。

⚠ 這套系統只讀不控。它只讀記錄程式產生的 CSV，沒有任何對設備下指令的路徑。
  所以「自動停止」只是**自動結束紀錄並計算結果**，不會關閥、不會停反應器。
  現場仍必須有人去實際排氣。介面上必須寫明這件事，否則有人會以為排好
  時間就不用到場。

⚠ 自動結束用「應結束時刻」而不是「排程器發現的時刻」。後端若停機 5 小時
  再開，批次仍結束在它該結束的時間，不會被延後 5 小時；量測結果的時間窗
  才會與設計一致。

⚠ 自動結束不會填手動峰值。沒有人在現場，peaks 留空、退回自動抓取，並記
  ended_by="auto"。感測器 1 筆/分鐘常錯過排氣瞬間的 CH4 峰，所以自動結束
  的批次一定要提示「排氣時刻與峰值待確認」，讓人事後補正 end_time。

⚠ 資料中斷**不是**自動結束的條件。記錄程式掛掉、感測器脫落都會造成資料
  斷，但那不代表實驗結束——自動結束會把一個不完整的批次標成「完成」並算
  出錯的結果。資料中斷只在 get_live_status 示警（staleness_min），不動狀態。

預設全部關閉：auto_start / auto_stop 兩個旗標不開就完全維持原本的手動流程。
既有批次的 JSON 裡沒有這兩個欄位，.get() 取到 None＝關閉，不受影響。

只用標準函式庫（threading + datetime）。不引入 APScheduler 之類的排程套件——
那會吃掉監控電腦僅有的 60 MB 預算。
"""
import threading
from datetime import datetime

from core import experiment_store as exp

POLL_SECONDS = 30           # 檢查間隔。實驗以小時計，30 秒綽綽有餘

_thread = None
_stop_evt = threading.Event()
_lock = threading.Lock()    # 序列化排程器自己的動作，避免同一 tick 內重入
_last_tick = None
_log = []                   # 最近的自動動作，供面板顯示「是誰結束的」
LOG_MAX = 50


# 應結束時刻的定義放在 experiment_store（本模組匯入它，反向會循環匯入）。
due_time = exp.due_time


def pending_actions(runs, now=None):
    """算出此刻該做哪些動作。**純函式**，不改任何狀態。

    抽出來是為了可測：system_test 可以餵各種 now 進去驗證判定，不必等 30 秒
    也不必真的動到批次。
    """
    now = now or datetime.now()
    out = []
    for r in runs:
        st = r.get("status")
        if st == "planned" and r.get("auto_start") and r.get("scheduled_start"):
            try:
                at = exp._parse(exp._normalize_ts(r["scheduled_start"]))
            except ValueError:
                continue
            if at <= now:
                out.append({"action": "start", "run_id": r["run_id"],
                            "at": r["scheduled_start"]})
        elif st == "running" and r.get("auto_stop"):
            due = due_time(r)
            if due and due <= now:
                out.append({"action": "vent", "run_id": r["run_id"],
                            "at": due.strftime("%Y-%m-%d %H:%M:%S")})
    return out


def tick(now=None):
    """執行一輪。回傳這輪實際做了什麼。"""
    global _last_tick
    with _lock:
        now = now or datetime.now()
        _last_tick = now.strftime("%Y-%m-%d %H:%M:%S")
        done = []
        for act in pending_actions(exp.experiment_runs, now):
            try:
                if act["action"] == "start":
                    exp.start_run(act["run_id"], at=act["at"], by="auto")
                else:
                    # ⚠ peaks 不填：沒有人在現場觀測，硬填等於捏造數字。
                    exp.vent_run(act["run_id"], at=act["at"], by="auto")
                done.append(act)
                _record(act, ok=True)
            except (ValueError, KeyError) as e:
                _record(act, ok=False, err=str(e))
        return done


def _record(act, ok, err=""):
    _log.append({"ts": exp._now(), "action": act["action"],
                 "run_id": act["run_id"], "at": act["at"],
                 "ok": ok, "error": err})
    del _log[:-LOG_MAX]
    tag = "自動開始" if act["action"] == "start" else "自動結束紀錄"
    if ok:
        print("[scheduler] %s：批次 %s（記為 %s）" % (tag, act["run_id"], act["at"]))
    else:
        print("[scheduler] %s失敗：批次 %s — %s" % (tag, act["run_id"], err))


def _loop():
    while not _stop_evt.is_set():
        try:
            tick()
        except Exception as e:                       # noqa: BLE001
            # ⚠ 排程器絕不能因為單次例外就死掉——它死了不會有人發現，
            #   自動開始/結束就默默不再發生。印出來，下一輪繼續。
            print("[scheduler] 這輪出錯（下一輪繼續）: %s" % e)
        _stop_evt.wait(POLL_SECONDS)


def start():
    """啟動背景排程執行緒（daemon，隨主程序結束）。重複呼叫無作用。"""
    global _thread
    if _thread and _thread.is_alive():
        return _thread
    _stop_evt.clear()
    _thread = threading.Thread(target=_loop, name="exp-scheduler", daemon=True)
    _thread.start()
    print("[scheduler] 批次排程已啟動（每 %d 秒檢查）" % POLL_SECONDS)
    return _thread


def stop():
    _stop_evt.set()


def status():
    """給面板看的：排程器活著沒、下一件事是什麼、最近做過什麼。"""
    now = datetime.now()
    upcoming = []
    for r in exp.experiment_runs:
        if r.get("status") == "planned" and r.get("auto_start") \
                and r.get("scheduled_start"):
            upcoming.append({"run_id": r["run_id"], "action": "start",
                             "at": r["scheduled_start"]})
        elif r.get("status") == "running" and r.get("auto_stop"):
            due = due_time(r)
            if due:
                upcoming.append({
                    "run_id": r["run_id"], "action": "vent",
                    "at": due.strftime("%Y-%m-%d %H:%M:%S"),
                    "hours_left": round((due - now).total_seconds() / 3600.0, 2)})
    upcoming.sort(key=lambda x: x["at"])
    return {
        "alive": bool(_thread and _thread.is_alive()),
        "poll_seconds": POLL_SECONDS,
        "last_tick": _last_tick,
        "upcoming": upcoming,
        "recent": _log[-10:][::-1],
        # ⚠ 面板必須顯示這句：自動停止只結束紀錄，不會停反應器。
        "note": "自動停止只結束紀錄並計算結果，不會關閥或停機，現場仍須有人排氣",
    }
