
# -*- coding: utf-8 -*-
"""
LE 模型漏了什麼？——殘差的系統性形狀
════════════════════════════════════════════════════════════════════════

`simulator_check.py` 把模擬器修到十項邊際特徵**全部對上**，AUC 仍有 0.667。
邊際對、聯合不對，最可能的解釋不是雜訊模型錯，而是

    **LE 模型本身不完整**。

模擬器是從 LE 完全正確地生出來的，殘差是純雜訊；真實殘差則額外含有
LE 沒抓到的成分。分類器抓的就是那個。

檢定：把每個循環的殘差按**正規化時間**對齊、疊加平均。
  · LE 若正確 ⇒ 平均殘差曲線應在 0 附近平坦（雜訊 √N 抵消）
  · LE 若漏項 ⇒ 會浮出一條系統性曲線，其形狀指出漏了什麼

同一套流程也跑在模擬循環上當**對照**——模擬的必定平坦，
所以真實的若不平坦，差異就不是流程的產物。

輸出 -> docs/analysis_charts_3batch/residual_structure.csv
"""
import os
import sys
import csv
import glob

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import OUT                              # noqa: E402
from regime_changepoints import TD                                 # noqa: E402
from multivariate_increments import load4                          # noqa: E402
from clean_and_form import seg_clean, SKIP_MIN                     # noqa: E402
from simulator_check import fit_LE, QUANT                          # noqa: E402

NG = 40
RNG = np.random.default_rng(24601)


def collect():
    folders = []
    for d in sorted(os.listdir(TD)):
        p = os.path.join(TD, d)
        if not os.path.isdir(p):
            continue
        if glob.glob(os.path.join(p, '*.csv')):
            folders.append((p, d))
        for s in sorted(os.listdir(p)):
            sp = os.path.join(p, s)
            if os.path.isdir(sp) and glob.glob(os.path.join(sp, '*.csv')):
                folders.append((sp, f'{d}/{s}'))
    out = []
    for path, tag in folders:
        try:
            raw = load4(path)
        except Exception:
            continue
        if len(raw) < 500:
            continue
        ts = [r[0] for r in raw]
        P = np.array([r[1] for r in raw])
        h = np.array([(x-ts[0]).total_seconds()/3600 for x in ts])
        cyc, wash = seg_clean(h, P, ts)
        for a, b in cyc:
            if ts[a].date() in wash:
                continue
            t = h[a:b+1]-h[a]
            sel = t >= SKIP_MIN
            if sel.sum() < 20:
                continue
            out.append((tag, t[sel]-t[sel][0], P[a:b+1][sel]))
    return out


def stack_resid(cycles):
    """殘差按正規化時間疊加。回傳 (grid, mean, sem, n)。"""
    g = np.linspace(0, 1, NG)
    acc = []
    for item in cycles:
        t, y = item[-2], item[-1]
        f = fit_LE(t, y)
        amp = y[0]-y[-1]
        if amp <= 0:
            continue
        tn = (t-t[0])/(t[-1]-t[0])
        acc.append(np.interp(g, tn, f['resid']/amp))   # 以幅度正規化
    A = np.array(acc)
    return g, A.mean(0), A.std(0, ddof=1)/np.sqrt(len(A)), len(A)


def main():
    cyc = collect()
    print('══ LE 模型漏了什麼？殘差的系統性形狀 ══\n')
    print(f'   真實循環 {len(cyc)} 個')

    g, mr, sr, nr = stack_resid(cyc)

    # 對照：從 LE 生出來的模擬循環（殘差必定無結構）
    sims = []
    for tag, t, y in cyc:
        f = fit_LE(t, y)
        r = f['resid']
        phi = float(np.corrcoef(r[:-1], r[1:])[0, 1]) if r.std() > 0 else 0.
        phi = float(np.clip(phi*1.3, 0, 0.98))
        sd = max(f['sd'], QUANT/4)
        e = RNG.normal(0, sd*np.sqrt(1-phi**2), len(t))
        nz = np.empty(len(t)); nz[0] = RNG.normal(0, sd)
        for i in range(1, len(t)):
            nz[i] = phi*nz[i-1]+e[i]
        yy = f['peq']+f['amp']*np.exp(-f['k']*t)-f['rb']*t+nz
        sims.append((tag, t, np.round(yy/QUANT)*QUANT))
    _, ms, ss, ns = stack_resid(sims)

    print('\n── 疊加平均殘差（以循環幅度正規化）──')
    print(f'   {"正規化時間":>10}{"真實":>11}{"±SEM":>9}'
          f'{"模擬對照":>11}{"±SEM":>9}   顯著')
    print('   '+'-'*56)
    sig = 0
    for i in range(0, NG, 3):
        z = abs(mr[i])/max(sr[i], 1e-12)
        s = z > 3
        sig += s
        print(f'   {g[i]:>10.2f}{mr[i]:>+11.4f}{sr[i]:>9.4f}'
              f'{ms[i]:>+11.4f}{ss[i]:>9.4f}   {"✘" if s else "·"}')

    amp_r = float(mr.max()-mr.min())
    amp_s = float(ms.max()-ms.min())
    print(f'\n   真實平均殘差的峰谷幅度  {amp_r:.4f}（佔循環幅度）')
    print(f'   模擬對照的峰谷幅度      {amp_s:.4f}')
    print(f'   比值 {amp_r/max(amp_s,1e-12):.1f}×')

    # 形狀判讀
    print('\n── 形狀判讀 ──')
    i_min, i_max = int(np.argmin(mr)), int(np.argmax(mr))
    print(f'   最低點在 u = {g[i_min]:.2f}（殘差 {mr[i_min]:+.4f}）')
    print(f'   最高點在 u = {g[i_max]:.2f}（殘差 {mr[i_max]:+.4f}）')
    early = mr[:NG//3].mean(); mid = mr[NG//3:2*NG//3].mean()
    late = mr[2*NG//3:].mean()
    print(f'   前段 {early:+.4f}   中段 {mid:+.4f}   後段 {late:+.4f}')
    if early > 0 and mid < 0 and late > 0:
        print('   ⇒ **U 形**：LE 在前後段低估、中段高估壓力')
        print('     ＝ 真實軌跡比單一指數**更彎**；單一時間常數不夠，')
        print('       需要第二個較慢的指數項（雙時間尺度）。')
    elif early < 0 and mid > 0 and late < 0:
        print('   ⇒ **倒 U 形**：真實軌跡比 LE **更直**')
    else:
        print('   ⇒ 未見明確的 U／倒 U 形，形狀需個別檢視')

    verdict = amp_r > 3*amp_s and sig > 0
    print(f'\n══ 判定 ══')
    if verdict:
        print('   ✘ **LE 模型不完整**：真實殘差有系統性形狀，模擬對照沒有。')
        print('     ⇒ 這解釋了 simulator_check 剩下的 AUC 0.667。')
        print('     ⇒ 也代表 r_b 的估計吸收了一部分未建模的物理項，')
        print('       其絕對值**不可直接當生物速率宣稱**。')
    else:
        print('   ✓ 未見系統性殘差結構，LE 形式與資料相容。')

    with open(f'{OUT}/residual_structure.csv', 'w', newline='',
              encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['u', 'real_mean', 'real_sem', 'sim_mean', 'sim_sem'])
        for i in range(NG):
            w.writerow([f'{g[i]:.4f}', f'{mr[i]:.6f}', f'{sr[i]:.6f}',
                        f'{ms[i]:.6f}', f'{ss[i]:.6f}'])
    print(f'\n輸出 → {OUT}/residual_structure.csv')


if __name__ == '__main__':
    main()
