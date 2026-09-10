# -*- coding: utf-8 -*-
"""
資料探勘導出的新模型：漂移平衡壓（Drifting-Equilibrium）
════════════════════════════════════════════════════════════════════════

由來
────
以 SINDy 式稀疏迴歸 + 留一循環交叉驗證，在候選項字典
{P, 1, t_in, t_batch, P·t_in, exp(-t_in), ORP, H+, 溫度項} 上搜尋 dP/dt 的
結構，三個批次都選中 **t_batch**（批次累積時間），且 10 min 批次的最佳模型
就是 {P, 1, t_batch}——加入任何其他項都沒有樣本外增益。係數為正，代表
壓力下降隨批次進行而變慢。這與 reset_signature_separation.py 獨立找到的
「整批累積、不在補氣時重置」的狀態一致。

物理解釋：**全程不換液**，液相逐漸被 CO2／碳酸氫根載滿，氣液推動力下降。
故平衡壓不是常數，而是隨批次時間上漂：

    dP/dt = -k_La ( P - P_eq(t) ) - r_b ,   P_eq(t) = P_eq0 + alpha * t_batch

解析解（令 Q0 = P_eq0 + alpha*t_bat0 - r_b/k_La）：

    P(t) = Q0 + alpha*t - alpha/k_La + (P0 - Q0 + alpha/k_La) * exp(-k_La * t)

為什麼重要
──────────
常數項 r_b 與線性項 alpha*t 在單一循環內高度相似。若真實系統有 alpha 而模型
省略它，**被省略的漂移會被常數項吸收，直接灌大 r_b**。本檔即檢定：把 alpha
放進模型後，r_b 是否還存活。

輸出 -> docs/analysis_charts_3batch/drifting_equilibrium.csv + fig31
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import sys

import numpy as np
from scipy import optimize

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import OUT, RED, AQUA, BLUE, INK, INK2, MUTED, style  # noqa: E402
from analyze_new_methods import collect  # noqa: E402

BN = ['1.1 (1min)', '2.1 (5min)', '3.1 (10min)']


def load_with_batchclock():
    """每個循環附上「批次累積時間」的起點 t_bat0。"""
    d = {}
    for name, cycs in collect().items():
        t0 = cycs[0].ts.iloc[0]
        lst = []
        for c in cycs:
            t = (c.ts - c.ts.iloc[0]).dt.total_seconds().values / 3600.0
            tb0 = (c.ts.iloc[0] - t0).total_seconds() / 3600.0
            lst.append((t, c.p_reactor.values.astype(float), tb0))
        d[name] = lst
    return d


def traj_drift(t, P0, kla, peq0, alpha, rb, tb0):
    """P_eq 隨批次時間線性上漂的解析解。alpha=0 時退化為原模型。"""
    Q0 = peq0 + alpha * tb0 - rb / max(kla, 1e-9)
    return Q0 + alpha * t - alpha / max(kla, 1e-9) + \
        (P0 - Q0 + alpha / max(kla, 1e-9)) * np.exp(-kla * t)


def joint(d, with_alpha=True, with_rb=True):
    def sse(th):
        k1, k2, k3, peq0 = th[0], th[1], th[2], th[3]
        alpha = th[4] if with_alpha else 0.0
        rb = th[5 if with_alpha else 4] if with_rb else 0.0
        v = 0.0
        for i, b in enumerate(BN):
            k = (k1, k2, k3)[i]
            for t, P, tb0 in d[b]:
                v += float(np.sum((P - traj_drift(t, P[0], k, peq0, alpha,
                                                  rb, tb0)) ** 2))
        return v
    p0 = [0.05, 0.15, 0.17, 0.60]
    bnd = [(1e-3, 3)] * 3 + [(0, 0.95)]
    if with_alpha:
        p0 += [0.001]; bnd += [(-0.02, 0.02)]
    if with_rb:
        p0 += [0.005]; bnd += [(0, 0.1)]
    r = optimize.minimize(sse, p0, method='L-BFGS-B', bounds=bnd)
    r = optimize.minimize(sse, r.x, method='Nelder-Mead', bounds=bnd,
                          options=dict(maxiter=40000, fatol=1e-14))
    return r.x, float(r.fun)


def rmse(d, th, with_alpha, with_rb):
    k1, k2, k3, peq0 = th[0], th[1], th[2], th[3]
    alpha = th[4] if with_alpha else 0.0
    rb = th[5 if with_alpha else 4] if with_rb else 0.0
    se, n = 0.0, 0
    for i, b in enumerate(BN):
        k = (k1, k2, k3)[i]
        for t, P, tb0 in d[b]:
            r = P - traj_drift(t, P[0], k, peq0, alpha, rb, tb0)
            se += float(np.sum(r ** 2)); n += len(r)
    return np.sqrt(se / n), n


def main():
    d = load_with_batchclock()
    ncyc = sum(len(d[b]) for b in BN)
    print(f'══ 漂移平衡壓模型（{ncyc} 個循環）══\n')

    res = {}
    for tag, wa, wr in (('原模型  (常數 Peq, 有 rb)', False, True),
                        ('原模型  (常數 Peq, rb≡0)', False, False),
                        ('漂移模型 (Peq 上漂, 有 rb)', True, True),
                        ('漂移模型 (Peq 上漂, rb≡0)', True, False)):
        th, f = joint(d, wa, wr)
        rm, n = rmse(d, th, wa, wr)
        npar = 4 + int(wa) + int(wr)
        aic = n * np.log(f / n) + 2 * npar
        res[tag] = (th, rm, aic, wa, wr)
        kla = th[:3]
        alpha = th[4] if wa else 0.0
        rb = th[5 if wa else 4] if wr else 0.0
        print(f'{tag}')
        print(f'   kLa = {kla[0]:.4f} / {kla[1]:.4f} / {kla[2]:.4f}'
              f'   Peq0 = {th[3]:.4f}')
        print(f'   alpha = {alpha:+.6f} kg cm⁻² hr⁻¹     rb = {rb:.5f}')
        print(f'   RMSE = {rm:.5f}   AIC = {aic:.0f}\n')

    th_d = res['漂移模型 (Peq 上漂, 有 rb)'][0]
    th_o = res['原模型  (常數 Peq, 有 rb)'][0]
    print('══ 關鍵比較 ══')
    print(f'  原模型   rb = {th_o[4]:.5f}')
    print(f'  漂移模型 rb = {th_d[5]:.5f}'
          f'   → 變化 {(th_d[5]/max(th_o[4],1e-9)-1)*100:+.0f}%')
    print(f'  漂移量 alpha = {th_d[4]:+.6f} kg cm⁻² hr⁻¹')
    span = max(tb0 for b in BN for _, _, tb0 in d[b])
    print(f'  → 整批 {span:.0f} hr 內 Peq 上漂 {th_d[4]*span:+.4f} kg cm⁻²')
    print(f'  RMSE 改善 {(1-res["漂移模型 (Peq 上漂, 有 rb)"][1]/res["原模型  (常數 Peq, 有 rb)"][1])*100:+.1f}%'
          f'   ΔAIC = {res["漂移模型 (Peq 上漂, 有 rb)"][2]-res["原模型  (常數 Peq, 有 rb)"][2]:+.0f}')

    print('\n══ 這才是重點：漂移模型下 rb 還顯著嗎？══')
    print('  比較「漂移+rb」與「漂移+rb≡0」兩個巢狀模型：')
    d_aic = res['漂移模型 (Peq 上漂, rb≡0)'][2] - res['漂移模型 (Peq 上漂, 有 rb)'][2]
    print(f'   ΔAIC (去掉 rb) = {d_aic:+.1f}'
          f'   → {"rb 仍有貢獻" if d_aic > 2 else "★ 去掉 rb 沒有變差：rb 被 alpha 取代"}')

    import csv
    with open(f'{OUT}/drifting_equilibrium.csv', 'w', newline='',
              encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['model', 'kLa1', 'kLa2', 'kLa3', 'Peq0', 'alpha', 'rb',
                    'rmse', 'aic'])
        for tag, (th, rm, aic, wa, wr) in res.items():
            w.writerow([tag, *[f'{x:.6f}' for x in th[:4]],
                        f'{th[4] if wa else 0:.6f}',
                        f'{(th[5 if wa else 4] if wr else 0):.6f}',
                        f'{rm:.6f}', f'{aic:.1f}'])
    print(f'\n輸出 → {OUT}/drifting_equilibrium.csv')


if __name__ == '__main__':
    main()
