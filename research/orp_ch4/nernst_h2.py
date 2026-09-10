
# -*- coding: utf-8 -*-
"""
把 ΔORP 換算成 H2 分壓變化，並檢查物理一致性
════════════════════════════════════════════════════════════════════════

**動機**：相干疊加證實 ORP 在每個循環內系統性上升 +39 ~ +134 mV
（置換虛無 p = 0.002），且方向符合 H2 被消耗。若能換成 H2 分壓，
就能直接得到生物速率——因為化學計量給了一個乾淨的錨點：

    CO2 + 4H2 → CH4 + 2H2O
    5 mol 氣體進、1 mol 出 ⇒ **淨移除 4 mol，其中 H2 消耗 4 mol**
    ⇒ **ΔP(H2) ＝ 生物淨移除的氣體量**   （1:1 對應）

**Nernst（H2/H+ 對，30 °C）**：

    E = E°' − 30.1·log10 P(H2) − 60.2·pH        [mV]
    ⇒ Δlog10 P(H2) = −(ΔE + 60.2·ΔpH) / S

  S = 有效能斯特斜率（理論 30.1 mV/decade）。
  只用 Δ ⇒ **電極偏移 E°' 自動消掉**；同時用到 ORP 與 pH ⇒ 真正的多變量。

**但本檔的重點是兩個一致性檢查，而不是直接給數字**：

  C1  絕對值檢查：文獻記載產甲烷菌需 ORP < −300 mV（最佳約 −330）。
      本反應器讀數為 +368 ~ +761 mV，扣掉 Ag/AgCl 參考的 +197 仍為
      +570 ~ +960 mV vs SHE。**差了約一千毫伏**，而排氣確實含
      31.6–43.0 % CH4。兩者不可能同時成立。

  C2  質量守恆檢查：生物移除量不可能超過總移除量。
      由此反推 S 的下界——若下界遠大於理論的 30.1，代表電極
      **不是理想的 H2 電極**（混合電位），Nernst 換算不可用。

輸出 -> docs/analysis_charts_3batch/nernst_h2.csv
"""
# ── 搬進子資料夾後，research/ 根層的共用模組（analyze_three_batches 等）
#    不再在 sys.path 上。這一行補回來，其餘邏輯完全未動。
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import sys
import csv

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import OUT                              # noqa: E402
from coherent_stacking import stack                                # noqa: E402

R, F, T = 8.314, 96485.0, 303.15
S_TH = 2.303*R*T/(2*F)*1000        # 理論斜率 mV/decade
S_PH = 2.303*R*T/F*1000            # pH 係數 mV/pH
FH2 = {'1:1': 0.5}
DEFAULT_FH2 = 0.8

# 文獻：產甲烷菌所需 ORP（vs SHE）
LIT_ORP_MAX = -300.0
AGAGCL_OFFSET = 197.0              # Ag/AgCl(sat. KCl) vs SHE @25 °C


def main():
    from multivariate_increments import load4, seg, cond_of        # noqa: E402
    from regime_changepoints import TD                             # noqa: E402
    import glob
    import datetime as dt

    print('══ ΔORP → ΔP(H2) 換算與一致性檢查 ══\n')
    print(f'   理論能斯特斜率 S = {S_TH:.1f} mV/decade（H2/H+，30 °C）')
    print(f'   pH 係數          = {S_PH:.1f} mV/pH\n')

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

    seen, byc = {}, {}
    orp_abs = []
    for path, tag in folders:
        try:
            raw = load4(path)
        except Exception:
            continue
        if len(raw) < 2000:
            continue
        ts = [r[0] for r in raw]
        P = np.array([r[1] for r in raw]); O = np.array([r[2] for r in raw])
        H = np.array([r[3] for r in raw])
        h = np.array([(x-ts[0]).total_seconds()/3600 for x in ts])
        orp_abs.append(O)
        for a, b in seg(h, P):
            key = (ts[a].replace(second=0), round(h[b]-h[a], 1))
            if key in seen:
                continue
            seen[key] = 1
            c, _ = cond_of(tag, ts[a].date())
            if c == 'other':
                continue
            byc.setdefault(c, []).append(
                (h[a:b+1]-h[a],
                 {'P': P[a:b+1], 'ORP': O[a:b+1], 'pH': H[a:b+1]},
                 P[a], P[b], h[b]-h[a]))

    # ── C1 絕對值一致性 ──────────────────────────────────
    allo = np.concatenate(orp_abs)
    print('── C1  絕對 ORP vs 文獻要求 ──')
    print(f'   實測 ORP        {np.percentile(allo,1):.0f} ~ '
          f'{np.percentile(allo,99):.0f} mV（中位 {np.median(allo):.0f}）')
    print(f'   換算 vs SHE     +{np.median(allo)+AGAGCL_OFFSET:.0f} mV'
          f'（假設 Ag/AgCl 參考，+{AGAGCL_OFFSET:.0f} mV）')
    print(f'   文獻要求        < {LIT_ORP_MAX:.0f} mV vs SHE（最佳約 −330）')
    gap = np.median(allo)+AGAGCL_OFFSET-LIT_ORP_MAX
    print(f'   差距            **{gap:.0f} mV**')
    print('   同時排氣含 31.6–43.0 % CH4 ⇒ 產甲烷確實在進行。')
    print('   ⇒ **兩者不可能同時成立**：ORP 通道有偏移、參考電極不明，'
          '或探頭未浸在液相中。')

    # ── 換算與 C2 質量守恆下界 ───────────────────────────
    print('\n── ΔORP／ΔpH → Δlog P(H2)，以及質量守恆下界 ──')
    print(f'   {"條件":<10}{"n":>4}{"ΔORP":>9}{"ΔpH":>9}'
          f'{"Δlog P(H2)":>12}{"隱含 ΔP(H2)":>13}{"實測 ΔP":>10}{"S 下界":>10}')
    print('   '+'-'*78)
    rows = []
    for c in sorted(byc, key=lambda k: -len(byc[k])):
        cyc = byc[c]
        if len(cyc) < 5:
            continue
        G, MO = stack([(t, y) for t, y, *_ in cyc], 'ORP')
        _, MH = stack([(t, y) for t, y, *_ in cyc], 'pH')
        dE = MO[:, -1].mean(); dpH = MH[:, -1].mean()
        dlog = -(dE+S_PH*dpH)/S_TH
        P0 = np.mean([p0 for *_, p0, p1, dur in cyc])
        dP_obs = np.mean([p0-p1 for *_, p0, p1, dur in cyc])
        f = FH2.get(c, DEFAULT_FH2)
        PH2_0 = f*P0
        dPH2 = PH2_0*(1-10**dlog)
        # C2：dPH2 ≤ dP_obs  ⇒  1 − 10^(−|dE'|/S) ≤ dP_obs/PH2_0
        frac = min(dP_obs/PH2_0, 0.999999)
        eff = abs(dE+S_PH*dpH)
        Smin = eff/(-np.log10(1-frac)) if frac > 0 else np.inf
        print(f'   {c:<10}{len(cyc):>4}{dE:>9.1f}{dpH:>9.4f}'
              f'{dlog:>12.2f}{dPH2:>13.3f}{dP_obs:>10.3f}{Smin:>10.0f}')
        rows.append([c, len(cyc), f'{dE:.2f}', f'{dpH:.5f}', f'{dlog:.3f}',
                     f'{dPH2:.4f}', f'{dP_obs:.4f}', f'{Smin:.1f}'])

    Smins = [float(r[7]) for r in rows if np.isfinite(float(r[7]))]
    print(f'\n── C2  質量守恆給出的有效斜率下界 ──')
    print(f'   生物移除量不可能超過總移除量 ⇒ S ≥ {max(Smins):.0f} mV/decade')
    print(f'   理論值 S = {S_TH:.1f} mV/decade')
    print(f'   ⇒ 需要 **{max(Smins)/S_TH:.0f}×** 理論值才不違反質量守恆')
    print('   ⇒ 這支電極**不是理想的 H2 電極**（混合電位／響應遲鈍），')
    print('      在未校準前，ΔORP 不可換算為 H2 分壓。')

    print('\n── 結論 ──')
    print('   ✓ ORP 的循環內上升是**真實且條件相依**的（疊加 + 置換虛無已證）')
    print('   ✘ 但它**現在不能**換算成生物速率，理由有二且互相獨立：')
    print('      C1 絕對值與文獻差約 1000 mV，而反應器確實在產甲烷')
    print(f'      C2 質量守恆要求有效斜率 ≥ {max(Smins)/S_TH:.0f}× 理論值')
    print('   ⇒ 缺的是**電極校準**，不是分析方法。')
    print('      可用零成本方式取得：每次排氣同時記 CH4 目測與當下 ORP，')
    print('      以 CH4 的絕對量反推該電極的有效斜率。')

    with open(f'{OUT}/nernst_h2.csv', 'w', newline='',
              encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['cond', 'n', 'dORP_mV', 'dpH', 'dlogPH2',
                    'implied_dPH2', 'observed_dP', 'S_min_mV_per_decade'])
        w.writerows(rows)
    print(f'\n輸出 → {OUT}/nernst_h2.csv')


if __name__ == '__main__':
    main()
