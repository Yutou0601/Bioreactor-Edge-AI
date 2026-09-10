
# -*- coding: utf-8 -*-
"""
控制面／反應面自動切分（Control–Response Plane Partitioning, CRPP）
════════════════════════════════════════════════════════════════════════

**問題**：要分開「控制組態改變」與「製程狀態改變」，先前技術（Iturbe et al. 2017,
arXiv:1706.01679）需要**讀得到控制器層的變數**。本裝置的邊緣端讀不到——
只有一條頂空壓力。於是必須先回答：**由壓力導出的那些通道，哪些是控制器的，
哪些是製程的？**

**本演算法**：不需要知道控制架構，由資料自行切分。

⚠ **被否決的做法（記錄下來以免重蹈）**：原本想用「c 是否獨立於製程狀態代理 π」
來判定。**兩次都被混淆打敗**：
  · 用 kLa 當 π：kLa = r/(f·P_head)，分母與 P0 機械相關 → 假相關
  · 用正規化形狀當 π：shape = (y₀−y_mid)/(y₀−y_end)，**分母含 y_end 就是 Pend**
**任何由同一條壓力軌跡導出的代理，都與候選設定點共用端點。相關性路線走不通。**

**改用時間結構**——設定點的定義性特徵不是「與製程無關」，而是
**在同一個值上停留很久，然後階梯式跳躍**；製程結果則連續漂移。
兩個統計量都只看單一通道自身，**不涉及跨通道相關，故無混淆**：

  S1  離散度：量化後的正規化熵。設定點取少數離散值 → 低熵。
  S2  持續性：相同量化值的平均連段長度，對「破壞時間順序」的置換虛無標準化。
      設定點連段長；製程結果連段短。

  控制面 = 低熵 **且** 連段顯著長於置換虛無；其餘為反應面。

輸出 -> docs/analysis_charts_3batch/control_plane_partition.csv
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import sys
import csv
from math import erfc, sqrt, log

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import OUT                              # noqa: E402
from changepoint_forensics import gather_rich                      # noqa: E402

QUANT = 0.01        # 壓力感測器量化步階 kg/cm²
NPERM = 5000        # 置換檢定次數


def spearman(a, b):
    """Spearman ρ 與其常態近似 p 值。"""
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    r = float(np.corrcoef(ra, rb)[0, 1])
    n = len(a)
    if n < 5 or abs(r) >= 1:
        return r, np.nan
    z = 0.5*log((1+r)/(1-r))*sqrt(n-3)
    return r, erfc(abs(z)/sqrt(2))


def norm_entropy(v, quant=QUANT):
    """量化後的正規化熵。0 = 單一值（純設定點），1 = 均勻分布（純連續）。"""
    q = np.round(np.asarray(v, float)/quant).astype(int)
    _, cnt = np.unique(q, return_counts=True)
    p = cnt/cnt.sum()
    H = -np.sum(p*np.log(p))
    return H/log(len(v)) if len(v) > 1 else 0.0


def top_mass(v, k=3, quant=QUANT):
    q = np.round(np.asarray(v, float)/quant)
    _, cnt = np.unique(q, return_counts=True)
    return np.sort(cnt)[::-1][:k].sum()/cnt.sum()


def mean_run(v, quant=QUANT):
    """相同量化值的平均連段長度。"""
    q = np.round(np.asarray(v, float)/quant).astype(int)
    runs, cur = [], 1
    for i in range(1, len(q)):
        if q[i] == q[i-1]:
            cur += 1
        else:
            runs.append(cur); cur = 1
    runs.append(cur)
    return float(np.mean(runs))


def main():
    rows = gather_rich()
    n = len(rows)
    rng = np.random.default_rng(11)
    print('══ 控制面／反應面自動切分（CRPP）══')
    print(f'   循環 {n} 個（依時間排序）\n')
    print('   判準只用單一通道自身的時間結構，不涉及跨通道相關 → 無混淆')
    print('   S1 離散度：量化後正規化熵（低 = 設定點式）')
    print('   S2 持續性：相同值的平均連段長度 vs 置換虛無（長 = 設定點式）\n')

    # ⚠ 只有**與感測器同單位**的通道有資格當設定點：控制器比較的是壓力。
    #   導出量（時長 hr、kLa 1/hr、雜訊）定義上不可能是設定點，且用壓力量化步階
    #   0.01 去量化它們會產生假的低熵（雜訊值約 0.001~0.005，全部塌成一個值）。
    cands = [('Pend',  '觸發下限'), ('P0',   '補氣上限'), ('amp', '控制帶寬')]
    NOT_ELIGIBLE = [('dur', '循環時長', 'hr'), ('kla', 'kLa 代理', '1/hr'),
                    ('noise', '訊號雜訊', 'kg/cm²·量級不同')]

    print(f'   {"通道":<12}{"正規化熵":>10}{"前3值質量":>11}'
          f'{"平均連段":>10}{"虛無連段":>10}{"連段 z":>9}{"p":>10}   判定')
    print('   '+'-'*84)
    res = []
    for key, lab in cands:
        v = np.array([r[key] for r in rows], float)
        v = v[np.isfinite(v)]
        H = norm_entropy(v)
        tm = top_mass(v)
        obs = mean_run(v)
        null = np.array([mean_run(rng.permutation(v)) for _ in range(NPERM//10)])
        z = (obs-null.mean())/max(null.std(), 1e-9)
        pv = (np.sum(null >= obs)+1)/(len(null)+1)
        discrete = H < 0.50
        persist = pv < 0.05
        plane = '控制面' if (discrete and persist) else '反應面'
        why = []
        if not discrete:
            why.append('連續分布')
        if not persist:
            why.append('無持續性')
        print(f'   {lab:<12}{H:>10.3f}{tm:>11.1%}{obs:>10.2f}'
              f'{null.mean():>10.2f}{z:>+9.1f}{pv:>10.4f}   {plane}'
              + (f'（{"、".join(why)}）' if why else ''))
        res.append((lab, H, tm, obs, null.mean(), z, pv, plane))

    print('\n   不具設定點資格（單位與感測器不同，控制器無從比較）：')
    for key, lab, unit in NOT_ELIGIBLE:
        print(f'      {lab}（{unit}）→ 一律歸反應面')

    print('\n── 切分結果 ──')
    ctrl = [r[0] for r in res if r[7] == '控制面']
    resp = ([r[0] for r in res if r[7] == '反應面']
            + [l for _, l, _ in NOT_ELIGIBLE])
    print(f'   控制面：{"、".join(ctrl) if ctrl else "（無）"}')
    print(f'   反應面：{"、".join(resp)}')

    print('\n── 記錄：兩條被混淆打敗的路線（不要重試）──')
    kla = np.array([r['kla'] for r in rows], float)
    pi = np.array([r['shape'] for r in rows], float)
    for key, lab in (('Pend', '觸發下限'), ('P0', '補氣上限')):
        v = np.array([r[key] for r in rows], float)
        m1 = np.isfinite(kla) & (kla > 0) & np.isfinite(v)
        r1, p1 = spearman(v[m1], np.log(kla[m1]))
        m2 = np.isfinite(pi) & np.isfinite(v)
        r2, p2 = spearman(v[m2], pi[m2])
        print(f'   {lab:<8} vs log kLa  ρ={r1:+.3f} p={p1:.1e}'
              f'   |  vs 形狀  ρ={r2:+.3f} p={p2:.1e}')
    print('   ⚠ 兩者皆不可用：kLa 的分母 P_head 與 P0 機械相關；'
          '形狀的分母 (y₀−y_end) 含 Pend')

    with open(f'{OUT}/control_plane_partition.csv', 'w', newline='',
              encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['channel', 'norm_entropy', 'top3_mass', 'mean_run',
                    'null_run', 'z', 'p', 'plane'])
        for r in res:
            w.writerow([r[0], f'{r[1]:.4f}', f'{r[2]:.4f}', f'{r[3]:.3f}',
                        f'{r[4]:.3f}', f'{r[5]:+.2f}', f'{r[6]:.4f}', r[7]])
    print(f'\n輸出 → {OUT}/control_plane_partition.csv')


if __name__ == '__main__':
    main()
