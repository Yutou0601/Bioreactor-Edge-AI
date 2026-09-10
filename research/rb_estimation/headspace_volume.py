# -*- coding: utf-8 -*-
"""從兩支壓力計反推反應槽頭空體積——可驗證版。

原理。閥3 開啟時氣體由 1L 預混槽送進反應槽頭空，預混槽此時與鋼瓶隔離
（已向設備方確認）。同溫下理想氣體的質量守恆給

    V_premix * dP_premix = V_head * dP_reactor
    V_head = 1 L * dP_premix / dP_reactor

⚠ 只有壓力**差**進入算式，所以錶壓與絕對壓的偏移自動抵消，不必換算。

⚠ 欄位陷阱：原始紀錄的兩個標籤是對調的。
    紀錄寫「反應器壓力」 → 實為預混槽
    紀錄寫「混合槽壓力」 → 實為反應槽
  analyze_three_batches.load_txt 已在解析時換回，本檔直接沿用它的
  p_reactor / p_mix，不自行解析，避免再踩一次。

可驗證性設計（這是本檔的重點）：
  1 不報單一數字，報整個分布與四分位
  2 依時期切開比對——真實的體積在同一時期內應該穩定
  3 反推液體體積 = 5 - V_head，必須為正且合理
  4 列出事件數與逐次的原始壓差，可人工抽查
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import sys

import numpy as np

sys.path.insert(0, __import__('os').path.dirname(__file__))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from analyze_three_batches import load_all

V_PREMIX = 1.0          # L，洪博計畫簡報明載
VESSEL = 5.0            # L，同上
RISE = 0.03             # kg/cm²，與論文切分門檻一致


def main():
    df = load_all()
    print('原始列數 %d   時間 %s ~ %s'
          % (len(df), df.ts.iloc[0].date(), df.ts.iloc[-1].date()))
    print('p_reactor（反應槽）%.2f ~ %.2f    p_mix（預混槽）%.2f ~ %.2f'
          % (df.p_reactor.min(), df.p_reactor.max(),
             df.p_mix.min(), df.p_mix.max()))

    t = df.ts.values
    pr = df.p_reactor.values
    pm = df.p_mix.values
    dt = np.diff(t) / np.timedelta64(1, 'm')
    dR = np.diff(pr)
    ok = (dR > RISE) & (dt <= 3)          # 一次補氣在數分鐘內完成
    idx = np.flatnonzero(ok) + 1
    print('\n候選補氣事件 %d 次（反應槽單步升 >%.2f）' % (idx.size, RISE))

    rec = []
    for i in idx:
        a, b = max(0, i - 3), min(len(pr) - 1, i + 3)
        dr = pr[i] - pr[i - 1]                    # 反應槽升幅
        dm = pm[a:i].max() - pm[i:b + 1].min()    # 預混槽在事件窗內的降幅
        if dm <= 0.01 or dr <= 0:
            continue
        v = V_PREMIX * dm / dr
        if 0.2 < v < VESSEL:                      # 物理上必須小於槽體
            rec.append((df.ts.iloc[i], dm, dr, v))

    if len(rec) < 5:
        print('有效事件僅 %d 次，不足以下結論' % len(rec))
        return
    V = np.array([r[3] for r in rec])
    print('有效事件 %d 次（預混槽確有下降、且比值落在物理範圍內）\n' % len(rec))
    print('  頭空體積  中位 %.2f L   四分位 %.2f ~ %.2f   全距 %.2f ~ %.2f'
          % (np.median(V), *np.percentile(V, [25, 75]), V.min(), V.max()))
    print('  → 反推液體體積 = %.1f - %.2f = %.2f L（佔槽體 %.0f%%）'
          % (VESSEL, np.median(V), VESSEL - np.median(V),
             (VESSEL - np.median(V)) / VESSEL * 100))

    print('\n依年份切開（真實體積在同一時期內應該穩定）：')
    yr = np.array([r[0].year for r in rec])
    for y in sorted(set(yr)):
        m = yr == y
        if m.sum() >= 3:
            print('  %d 年  n=%3d   中位 %.2f L   四分位 %.2f ~ %.2f'
                  % (y, m.sum(), np.median(V[m]),
                     *np.percentile(V[m], [25, 75])))

    print('\n可人工抽查的前 8 次事件：')
    print('  時間                預混槽降   反應槽升   體積')
    for ts, dm, dr, v in rec[:8]:
        print('  %s   %6.3f    %6.3f   %5.2f L'
              % (ts.strftime('%Y-%m-%d %H:%M'), dm, dr, v))


if __name__ == '__main__':
    main()
