
# -*- coding: utf-8 -*-
"""伺服器端降採樣：只送畫得出來的點數，不要把整段歷史丟給瀏覽器。

為什麼需要
----------
監控電腦是 4 GB 的 Windows 機器，而**前端就是在這台上面看的**——瀏覽器分頁
跟後端在搶同一份記憶體。實測 `/api/records?limit=4320`（3 天）回應
**975 KB**，每 60 秒一輪；瀏覽器要把它解析成 4320 個物件、再交給 ECharts。

圖表寬度大概 1200 px，送 4320 個點去畫 1200 px 是白費的。ECharts 本來就設了
`sampling: 'lttb'`，但那只減少「畫幾個點」，**傳輸量與瀏覽器持有的物件數
一點都沒少**。真正要省，得在送出去之前就砍。

⚠ 純 numpy，不得引入 scipy／pandas。這支在常駐核心裡，預算 60 MB。

⚠ 不可以用等間隔抽樣（`recs[::n]`）。那會**跳過尖峰**：壓力在泵開的那一
  分鐘會驟降、排氣時更是幾筆之內掉 0.16，等間隔抽樣抽掉那幾筆，圖上就
  看不到了——而且沒有任何跡象顯示資料被動過。LTTB 會保留這種轉折。
"""
import numpy as np


def _lttb_indices(x, y, n_out):
    """Largest-Triangle-Three-Buckets：挑 n_out 個最能保住形狀的索引。

    把資料切成 n_out-2 個桶，每桶選一個點，使「前一個選中點、本點、下一桶
    平均點」三角形面積最大——面積大代表這個點帶的轉折資訊多。頭尾一定保留。
    """
    n = len(x)
    if n_out >= n or n_out < 3:
        return np.arange(n)

    out = np.empty(n_out, dtype=np.int64)
    out[0] = 0
    out[-1] = n - 1
    # 頭尾各佔一格，中間 n_out-2 格分掉 n-2 個點
    edges = np.linspace(1, n - 1, n_out - 1).astype(np.int64)

    a = 0                                  # 上一個被選中的點
    for i in range(n_out - 2):
        lo, hi = edges[i], edges[i + 1]
        nlo, nhi = edges[i + 1], (edges[i + 2] if i + 2 < len(edges) else n)
        if hi <= lo:
            out[i + 1] = lo
            a = lo
            continue
        # 下一桶的平均點（三角形的第三頂點）
        if nhi > nlo:
            avg_x = float(x[nlo:nhi].mean())
            avg_y = float(y[nlo:nhi].mean())
        else:
            avg_x, avg_y = float(x[-1]), float(y[-1])
        ax, ay = float(x[a]), float(y[a])
        area = np.abs((ax - avg_x) * (y[lo:hi] - ay)
                      - (ax - x[lo:hi]) * (avg_y - ay))
        pick = lo + int(np.argmax(area))
        out[i + 1] = pick
        a = pick
    return out


def pick(recs, n_out, keys=('orp', 'pressure')):
    """從 recs 挑出約 n_out 筆，保住形狀。回傳原本的 record dict（不改內容）。

    ⚠ `keys` 要列出**圖上真的會畫的欄位**，每個各跑一次 LTTB 再聯集。
      只挑一個欄位是不夠的：第一版只用 pressure，而監控頁的主圖畫的是 ORP
      四條線，結果 ORP 最小值從 488.5 飄到 491.9——壓力的轉折點跟 ORP 的
      轉折點不在同一批資料點上。圖看起來還是「對的」，只是極值被磨掉了，
      不會有人發現。

    一定會留下的：
      · 頭尾兩筆（時間軸範圍不能縮）
      · is_anomaly 的筆數——異常點在圖上是標記，掉了就等於「系統說沒有
        異常」，那是最糟的一種錯。

    ⚠ 但異常點的保留**有上限**（半個預算）。`is_anomaly` 是「ORP 每分鐘掉
      超過 20 mV」的突波標記，一次事件最多標 15 筆；這台每小時泵一開就觸發
      一次，實測循環資料 4320 筆裡有 1512 筆（35%）帶這個旗標。無上限地
      全保留的話，points=600 會回 1897 筆——降採樣等於沒做。
      超過上限時改成對異常點自己再跑一次 LTTB，最凸的那些仍然留得住。

    ⚠ 回傳的仍是原本的 dict 物件本身，不是副本。呼叫端不可以就地修改。
    """
    n = len(recs)
    if n_out <= 0 or n <= n_out or n < 3:
        return recs

    x = np.arange(n, dtype=float)
    series = [_column(recs, k) for k in keys] or [np.zeros(n, dtype=float)]

    anom = [i for i, r in enumerate(recs) if r.get('is_anomaly')]
    cap = max(1, n_out // 3)
    if len(anom) > cap:
        # 異常點太多，對它們自己再跑一次 LTTB：留下最凸的那些
        ai = np.asarray(anom, dtype=np.int64)
        anom = ai[_lttb_indices(x[ai], series[0][ai], cap)].tolist()

    # 每個欄位各分一份預算，各自 LTTB 再聯集。聯集後通常少於各份之和
    # （不同欄位的轉折點常常落在同一筆上）。
    per = max(3, (n_out - len(anom)) // len(series))
    keep = set(anom)
    for y in series:
        keep.update(_lttb_indices(x, y, per).tolist())
    keep.add(0)
    keep.add(n - 1)
    return [recs[i] for i in sorted(keep)]


def _column(recs, key):
    """取一欄成 float 陣列；缺值用前後內插補掉，免得 NaN 吃掉三角形面積。"""
    y = np.array([_num(r.get(key)) for r in recs], dtype=float)
    bad = ~np.isfinite(y)
    if bad.all():
        return np.zeros(len(recs), dtype=float)
    if bad.any():
        good = np.flatnonzero(~bad)
        y[bad] = np.interp(np.flatnonzero(bad), good, y[good])
    return y


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return float('nan')
    return f
