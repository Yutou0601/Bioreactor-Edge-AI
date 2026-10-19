# -*- coding: utf-8 -*-
"""溶解量：pH 看 CO2、ORP 看 H2，兩個通道各自估、互相對照。

2026-10-18。承 ph_abc（ABC）與 ml/npe_separation（NPE）：兩者都用 pH，都給「真實循環溶解 ≈ 0」。
這支換成**不靠模擬器**的直接化學計算，再加上第二個、物理上獨立的通道（ORP → H2）。

════════════════════════════════════════════════════════════════════════
「溶解」在這裡的定義：一個循環內，氣體從頭空**存進液相**、沒有被消耗掉的量
（液相庫存的淨變化）。被菌吃掉的不算——那是生物項。換成頭空壓力的當量來比。

CO2（pH 通道）
  鹼度固定、pH ~7.2 時 HCO3⁻ ≈ 鹼度不變，所以 [CO2(aq)] ∝ [H⁺]：
      CO2(aq)_末 / CO2(aq)_初 = 10^(−ΔpH)            （不需要知道鹼度）
  液相庫存變化 ΔDIC ≈ ΔCO2(aq) = H_CO2 · pCO2_初 · (10^(−ΔpH) − 1)
  換成頭空壓力當量：Δp = (V_L/V_G) · H_cc,CO2 · pCO2_初 · (10^(−ΔpH) − 1)
H2（ORP 通道）
  H⁺/H2 電對的 Nernst 式（30 °C，2.303RT/F = 60.15 mV）：
      log10(pH2_eff / atm) = −(E_SHE + 60.15·pH) / 30.08
  液相 H2 = H_H2 · pH2_eff → Δp = (V_L/V_G) · H_cc,H2 · ΔpH2_eff

假設（每一條都列出來，結果對它們做敏感度掃描）
  · 循環開始時液相 CO2 與頭空平衡（pCO2_初 = y_CO2 · P_絕對），y_CO2 掃 0.15–0.25（進料 1:4 → 0.20）
  · 鹼度在一個循環內不變（沒有大量 NH3／揮發酸釋出）
  · V_L/V_G 由 rb_estimation/headspace_volume.py 反推：頭空 1.92 L [1.55, 2.30]、液 3.08 L
    → 1.6 [1.2, 2.2]（⚠ 反推值，未經設備方確認）
  · ORP 電極與 H⁺/H2 達平衡。Pt 電極常是混合電位，所以 H2 另報「即使實際 H2 高 100 倍」的上界
  · ORP 原始只存絕對值，真值為負（ORP_SIGN = −1，已在 load4 還原）；Ag/AgCl → SHE +197 mV
  · Henry 常數（25 °C 值＋溫度係數，換到 30 °C）：CO2 0.034 M/atm、2400 K；H2 7.8e-4 M/atm、500 K
    ⚠ 寫進論文前要查來源並驗 DOI
排除
  · 補氣後前 60 分鐘（ORP 異常往正跳 +37～+123 mV、pH 校正也解釋不了的那一段），另掃 30／90 分
  · pH 故障值（14.00 與 5–9 以外）

輸出 -> docs/analysis/dissolution_two_channel/（summary.json、cycles.csv、png）
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
REPO = os.path.dirname(RESEARCH)
sys.path.insert(0, RESEARCH)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, 'edge_backend'))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import pump_mode_split as PM                                      # noqa: E402
from pump_rhythm import BATCHES, FOLDER                           # noqa: E402
from multivariate_increments import load4                         # noqa: E402

OUT = os.path.join(REPO, 'docs', 'analysis', 'dissolution_two_channel')

T_K = 303.15
R_ATM = 0.082057                      # L·atm/(mol·K)
ATM = 1.0332                          # kgf/cm² per atm
NERNST = 1000 * 8.314462 * T_K / 96485.33 * np.log(10)    # 60.15 mV／十倍
SHE_OFFSET = 197.0                    # Ag/AgCl → SHE（mV）


def henry(kh25, dlnk):
    return kh25 * np.exp(dlnk * (1 / T_K - 1 / 298.15))


H_CC_CO2 = henry(0.034, 2400) * R_ATM * T_K       # 無因次（液相濃度／氣相濃度）
H_CC_H2 = henry(7.8e-4, 500) * R_ATM * T_K

VLG = (1.2, 1.6, 2.2)
YCO2 = (0.15, 0.20, 0.25)
EXCL = (30, 60, 90)
END_MIN = 20                          # 端點取頭尾各 20 分鐘的中位，壓過 0.01 的量化


def cycles():
    """與 ml/build_real_cycles_3ch.py 同一組規律循環，另外帶時間戳與泵狀態。"""
    ts, h, p = PM.load()
    rows = load4(os.path.join(RESEARCH, 'Testing_data', FOLDER))
    by_ts = {r[0]: (r[2], r[3]) for r in rows}
    out = []
    for nm, tau, d0, d1 in BATCHES:
        B = PM.analyse_batch(ts, h, p, nm, tau, d0, d1)
        for k, c in enumerate(B['reg']):
            s, e = c['s'], c['e']
            on_c = B['rows_by_cyc'].get(k + 1, (B['on'], None))[0]
            tt = B['t2'][s:e + 1]
            t = (B['h2'][s:e + 1] - B['h2'][s]) * 60.0               # 分鐘
            P = B['p2'][s:e + 1].astype(float)
            orp = np.array([by_ts.get(x, (np.nan, np.nan))[0] for x in tt], float)
            ph = np.array([by_ts.get(x, (np.nan, np.nan))[1] for x in tt], float)
            ph[(ph < 5) | (ph > 9)] = np.nan
            phase = np.array([(x.minute - on_c) % 60 for x in tt], int)    # 0＝這一小時開泵的那一分
            pump = phase < B['gap']
            out.append(dict(batch=nm, tau=tau, cycle=k + 1, t=t, P=P, pH=ph, ORP=orp, pump=pump,
                            phase=phase, gap=B['gap'], t0=str(tt[0])))
    return out


def endpoints(t, y, t_from):
    m = t >= t_from
    tt, yy = t[m], y[m]
    a = yy[(tt <= tt[0] + END_MIN) & np.isfinite(yy)]
    b = yy[(tt >= tt[-1] - END_MIN) & np.isfinite(yy)]
    if len(a) < 5 or len(b) < 5:
        return np.nan, np.nan
    return float(np.median(a)), float(np.median(b))


def ph2_eff(orp_true, ph):
    """Nernst 反推的等效 H2 分壓（atm）。"""
    e_she = orp_true + SHE_OFFSET
    return 10 ** (-(e_she + NERNST * ph) / (NERNST / 2))


def per_cycle(c, excl, vlg, y):
    t, P = c['t'], c['P']
    if t[-1] - excl < 120:
        return None
    m = t >= excl
    dur_h = (t[m][-1] - t[m][0]) / 60
    p0, p1 = endpoints(t, P, excl)
    ph0, ph1 = endpoints(t, c['pH'], excl)
    o0, o1 = endpoints(t, c['ORP'], excl)
    if not np.all(np.isfinite([p0, p1, ph0, ph1, o0, o1])):
        return None
    drop_rate = (p0 - p1) / dur_h                                   # 實測壓降速率
    p_abs = p0 + ATM
    co2 = vlg * H_CC_CO2 * y * p_abs * (10 ** (-(ph1 - ph0)) - 1)   # 存進液相（+）的 CO2，kgf/cm² 當量
    h2a, h2b = ph2_eff(o0, ph0), ph2_eff(o1, ph1)
    h2 = vlg * H_CC_H2 * (h2b - h2a) * ATM
    sat = h2a / ((1 - y) * p_abs / ATM)                             # 液相 H2 相對於頭空平衡的飽和度
    # H2 個別計算（Henry，不用 ORP）：液相 H2 跟著頭空 H2 分壓走（準平衡），
    # 頭空組成近似不變（以 1:4 計量比消耗）→ ΔpH2 = y_H2 · ΔP。降壓時液相釋出 → 負值。
    # 若菌把液相 H2 壓在遠低於飽和，實際變化只會更小，所以這是幅度上限。
    h2_henry = vlg * H_CC_H2 * (1 - y) * (p1 - p0)
    return dict(dur_h=dur_h, drop_rate=drop_rate, dpH=ph1 - ph0, dORP=o1 - o0,
                co2_rate=co2 / dur_h, h2_rate=h2 / dur_h, h2_sat=sat,
                h2_rate_x100=100 * abs(h2) / dur_h, h2_henry_rate=h2_henry / dur_h,
                diss_rate=(co2 + h2_henry) / dur_h, consume_rate=drop_rate - (co2 + h2_henry) / dur_h)


def pump_events(c, excl):
    """泵開事件：開泵前一分鐘 → 這次開泵結束，pH、ORP、壓力各變多少。"""
    t, pump = c['t'], c['pump']
    ev = []
    i = 1
    while i < len(t):
        if pump[i] and not pump[i - 1] and t[i] >= excl:
            j = i
            while j + 1 < len(t) and pump[j + 1]:
                j += 1
            a, b = i - 1, min(j + 1, len(t) - 1)
            if np.isfinite(c['pH'][a]) and np.isfinite(c['pH'][b]) and (t[b] - t[a]) <= c['gap'] + 3:
                ev.append((c['P'][b] - c['P'][a], c['pH'][b] - c['pH'][a], c['ORP'][b] - c['ORP'][a]))
            i = j + 1
        else:
            i += 1
    return ev


def boot_median(x, n=4000, seed=0):
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    rng = np.random.default_rng(seed)
    b = np.median(rng.choice(x, (n, len(x))), 1)
    return float(np.median(x)), float(np.percentile(b, 2.5)), float(np.percentile(b, 97.5))


def main():
    os.makedirs(OUT, exist_ok=True)
    C = cycles()
    allorp = np.concatenate([c['ORP'] for c in C])
    allorp = allorp[np.isfinite(allorp)]
    print('循環 %d 個（%s）' % (len(C), '、'.join('%s %d' % (b[0], sum(c['batch'] == b[0] for c in C)) for b in BATCHES)))
    print('ORP 真值範圍 %.0f ~ %.0f mV（Ag/AgCl）；≥ 0 的點 %d 個 → %s'
          % (allorp.min(), allorp.max(), int((allorp >= 0).sum()),
             '全部為負電位，與預期一致' if (allorp < 0).all() else '⚠ 有正值，要查'))
    print('H_cc：CO2 %.3f、H2 %.4f（比值 %.0f 倍）；Nernst %.2f mV/十倍' % (H_CC_CO2, H_CC_H2, H_CC_CO2 / H_CC_H2, NERNST))

    # ── 主結果：排除 60 分、V_L/V_G 1.6、y_CO2 0.20 ──
    main_rows = []
    for c in C:
        r = per_cycle(c, 60, 1.6, 0.20)
        if r:
            main_rows.append(dict(batch=c['batch'], cycle=c['cycle'], t0=c['t0'], **r))
    print('\n══ 主結果（排除補氣後 60 分；V_L/V_G=1.6；y_CO2=0.20），%d 個循環 ══' % len(main_rows))
    print(' %-6s %3s %5s %8s %6s %7s %10s %10s %8s %8s' % ('批次', '#', '小時', '壓降速率', 'ΔpH', 'ΔORP', 'CO2 存入', 'H2 存入', 'CO2 佔%', 'H2 飽和'))
    for r in main_rows:
        print(' %-6s %3d %5.1f %8.4f %+6.3f %+7.1f %+10.5f %+10.7f %+7.1f%% %8.4f'
              % (r['batch'], r['cycle'], r['dur_h'], r['drop_rate'], r['dpH'], r['dORP'],
                 r['co2_rate'], r['h2_rate'], 100 * r['co2_rate'] / r['drop_rate'], r['h2_sat']))
    keys = ('drop_rate', 'dpH', 'dORP', 'co2_rate', 'h2_rate', 'h2_sat', 'h2_rate_x100')
    summ = {k: boot_median([r[k] for r in main_rows]) for k in keys}
    frac_co2 = boot_median([r['co2_rate'] / r['drop_rate'] for r in main_rows])
    frac_h2 = boot_median([r['h2_rate'] / r['drop_rate'] for r in main_rows])
    frac_h2x = boot_median([r['h2_rate_x100'] / r['drop_rate'] for r in main_rows])
    print('\n中位（95% 自助區間）')
    print('  實測壓降速率        %.4f [%.4f, %.4f] kgf/cm²/hr' % summ['drop_rate'])
    print('  ΔpH（循環內）        %+.3f [%+.3f, %+.3f]' % summ['dpH'])
    print('  ΔORP（循環內）       %+.1f [%+.1f, %+.1f] mV' % summ['dORP'])
    print('  CO2 存入液相         %+.5f [%+.5f, %+.5f] kgf/cm²/hr ＝ 壓降的 %+.1f%% [%+.1f, %+.1f]'
          % (summ['co2_rate'] + tuple(100 * np.array(frac_co2))))
    print('  H2 存入液相          %+.7f [%+.7f, %+.7f] kgf/cm²/hr ＝ 壓降的 %+.3f%% [%+.3f, %+.3f]'
          % (summ['h2_rate'] + tuple(100 * np.array(frac_h2))))
    print('  液相 H2 飽和度        %.4f [%.4f, %.4f]（相對於頭空平衡）' % summ['h2_sat'])
    print('  H2 上界（電極低估 100 倍）壓降的 %.2f%% [%.2f, %.2f]' % tuple(100 * np.array(frac_h2x)))

    # ── 個別計算再加總：CO2（pH）＋ H2（Henry）＝ 溶解；壓降 − 溶解 ＝ 消耗 ──
    print('\n══ 個別計算再加總（kgf/cm²/hr；正＝存進液相、讓壓力多降）══')
    print(' %-6s %3s %9s %10s %10s %10s %9s %8s' % ('批次', 'n', '壓降', 'CO2(pH)', 'H2(Henry)', '溶解合計', '消耗', '溶解佔%'))
    per_batch = {}
    for nm in [b[0] for b in BATCHES] + ['全部']:
        r = [x for x in main_rows if nm == '全部' or x['batch'] == nm]
        med = {k: float(np.median([x[k] for x in r])) for k in ('drop_rate', 'co2_rate', 'h2_henry_rate', 'diss_rate', 'consume_rate')}
        med['diss_frac'] = float(np.median([x['diss_rate'] / x['drop_rate'] for x in r]))
        per_batch[nm] = dict(n=len(r), **med)
        print(' %-6s %3d %9.4f %+10.5f %+10.5f %+10.5f %9.4f %+7.1f%%'
              % (nm, len(r), med['drop_rate'], med['co2_rate'], med['h2_henry_rate'], med['diss_rate'],
                 med['consume_rate'], 100 * med['diss_frac']))
    fr = boot_median([x['diss_rate'] / x['drop_rate'] for x in main_rows])
    fh2 = boot_median([x['h2_henry_rate'] / x['drop_rate'] for x in main_rows])
    print('  溶解合計佔壓降 %+.1f%% [%+.1f, %+.1f]；其中 H2 %+.1f%% [%+.1f, %+.1f]'
          % (*(100 * np.array(fr)), *(100 * np.array(fh2))))
    hs = [100 * v * H_CC_H2 * (1 - y) for v in VLG for y in YCO2]
    print('  H2 佔壓降（V_L/V_G × y 掃描）：%.1f%% ~ %.1f%%（皆為負＝釋出）' % (-max(hs), -min(hs)))

    # ── 敏感度：排除窗 × V_L/V_G × y_CO2 ──
    sens = []
    for ex in EXCL:
        for v in VLG:
            for y in YCO2:
                rr = [per_cycle(c, ex, v, y) for c in C]
                rr = [r for r in rr if r]
                f = [r['co2_rate'] / r['drop_rate'] for r in rr]
                g = [r['h2_rate'] / r['drop_rate'] for r in rr]
                sens.append(dict(excl=ex, vlg=v, y_co2=y, n=len(rr), co2_frac=boot_median(f),
                                 h2_frac=boot_median(g)))
    lo = min(s['co2_frac'][1] for s in sens)
    hi = max(s['co2_frac'][2] for s in sens)
    print('\n敏感度（排除 30/60/90 分 × V_L/V_G 1.2/1.6/2.2 × y_CO2 0.15/0.20/0.25，共 %d 組）' % len(sens))
    print('  CO2 存入佔壓降：各組中位 %+.1f%% ~ %+.1f%%；最寬 95%% 區間 [%+.1f%%, %+.1f%%]'
          % (100 * min(s['co2_frac'][0] for s in sens), 100 * max(s['co2_frac'][0] for s in sens), 100 * lo, 100 * hi))
    for ex in EXCL:
        s = [x for x in sens if x['excl'] == ex and x['vlg'] == 1.6 and x['y_co2'] == 0.20][0]
        print('  排除 %2d 分（n=%2d）：CO2 %+.1f%% [%+.1f, %+.1f]　H2 %+.3f%%'
              % (ex, s['n'], *(100 * np.array(s['co2_frac'])), 100 * s['h2_frac'][0]))

    # ── 互相對照：泵開的瞬間，兩個通道是否同向 ──
    print('\n══ 泵開事件：pH（CO2 進液相→降）與 ORP（H2 進液相→更負）是否同時動 ══')
    pe = {}
    for nm, *_ in BATCHES:
        ev = [e for c in C if c['batch'] == nm for e in pump_events(c, 60)]
        if len(ev) < 10:
            continue
        ev = np.array(ev)
        dP, dpH, dO = ev[:, 0], ev[:, 1], ev[:, 2]
        rng = np.random.default_rng(1)
        bs = lambda x: np.percentile([np.mean(rng.choice(x, len(x))) for _ in range(3000)], [2.5, 97.5])
        pe[nm] = dict(n=len(ev), dP=float(dP.mean()), dpH=float(dpH.mean()), dpH_ci=bs(dpH).tolist(),
                      dORP=float(dO.mean()), dORP_ci=bs(dO).tolist(),
                      co2_equiv=float(1.6 * H_CC_CO2 * 0.20 * (1.0 + ATM) * (10 ** (-dpH.mean()) - 1)))
        print('  %-6s n=%4d  壓力 %+.4f  ΔpH %+.4f [%+.4f, %+.4f]  ΔORP %+.1f [%+.1f, %+.1f] mV  → CO2 當量 %+.5f'
              % (nm, len(ev), dP.mean(), dpH.mean(), *pe[nm]['dpH_ci'], dO.mean(), *pe[nm]['dORP_ci'],
                 pe[nm]['co2_equiv']))

    with open(os.path.join(OUT, 'cycles.csv'), 'w', encoding='utf-8') as fh:
        ks = list(main_rows[0])
        fh.write(','.join(ks) + '\n')
        for r in main_rows:
            fh.write(','.join(str(round(r[k], 7)) if isinstance(r[k], float) else str(r[k]) for k in ks) + '\n')
    summary = dict(n_cycles=len(main_rows), orp_range=[float(allorp.min()), float(allorp.max())],
                   orp_all_negative=bool((allorp < 0).all()), H_cc_CO2=H_CC_CO2, H_cc_H2=H_CC_H2,
                   main={k: v for k, v in summ.items()}, co2_frac=frac_co2, h2_frac=frac_h2, h2_frac_x100=frac_h2x,
                   per_batch=per_batch, diss_frac=fr, h2_henry_frac=fh2,
                   sensitivity=sens, pump_events=pe)
    with open(os.path.join(OUT, 'summary.json'), 'w', encoding='utf-8') as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=1)
    plot(main_rows, pe)
    print('\n-> %s' % OUT)


def plot(rows, pe):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei', 'Noto Sans CJK TC', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    col = {'tau1': '#2f6fd0', 'tau5': '#e0703a', 'tau10': '#2aa876'}
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.6))
    for nm in col:
        r = [x for x in rows if x['batch'] == nm]
        if not r:
            continue
        ax[0].scatter([x['drop_rate'] for x in r], [100 * x['co2_rate'] / x['drop_rate'] for x in r],
                      color=col[nm], label=nm, s=34)
        ax[1].scatter([x['dpH'] for x in r], [x['dORP'] for x in r], color=col[nm], label=nm, s=34)
    ax[0].axhline(0, color='#888', lw=0.8)
    ax[0].set_xlabel('實測壓降速率 (kgf/cm²/hr)')
    ax[0].set_ylabel('CO2 存入液相 ／ 壓降 (%)')
    ax[0].set_title('a　pH 通道：CO2 溶解佔壓降幾成')
    ax[0].legend(frameon=False)
    ax[1].axhline(0, color='#888', lw=0.8)
    ax[1].axvline(0, color='#888', lw=0.8)
    ax[1].set_xlabel('循環內 ΔpH')
    ax[1].set_ylabel('循環內 ΔORP (mV)')
    ax[1].set_title('b　每個循環：pH 與 ORP 的淨變化')
    nms = list(pe)
    x = np.arange(len(nms))
    a2 = ax[2].twinx()
    ax[2].bar(x - 0.18, [pe[n]['dpH'] * 1000 for n in nms], 0.34, color='#7b8fb0', label='ΔpH ×1000')
    a2.bar(x + 0.18, [pe[n]['dORP'] for n in nms], 0.34, color='#c9826b', label='ΔORP (mV)')
    ax[2].set_xticks(x, ['%s\n(n=%d)' % (n, pe[n]['n']) for n in nms])
    ax[2].axhline(0, color='#888', lw=0.8)
    ax[2].set_ylabel('ΔpH ×1000（藍）')
    a2.set_ylabel('ΔORP mV（橘）')
    ax[2].set_title('c　泵開一次：兩個通道各動多少')
    for a in ax:
        a.spines[['top', 'right']].set_visible(False)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, 'dissolution_two_channel.png'), dpi=130)


if __name__ == '__main__':
    main()
