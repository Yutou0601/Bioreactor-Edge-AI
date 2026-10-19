# -*- coding: utf-8 -*-
"""循環內每分鐘的溶解進出：以泵週期折疊，pH 換 CO2 進出，再拿壓力對帳。

2026-10-18。承 dissolution_two_channel.py（每循環淨量：CO2 −6.8%、H2 −2.4%）。
淨量只看頭尾；這支看一小時之內，泵開、泵停時氣體怎麼進出液相。

════════════════════════════════════════════════════════════════════════
做法（不用 PINN，模型越少越好）
  1. 折疊：泵每小時固定在同一分開（τ 分鐘），把每批幾百個小時疊到 0–59 分鐘的同一軸
     （0＝開泵那一分）。pH 每分鐘只會跳 0 或 ±0.01，單看沒意義；疊幾百次後，平均
     每分鐘變化就有解析度（與 ORP 相干疊加同一招）。
  2. pH → CO2 進出（同 dissolution_two_channel，鹼度固定 → CO2(aq) ∝ [H⁺]）：
         每分鐘存入液相（頭空壓力當量）＝ −(V_L/V_G)·H_cc,CO2·pCO2·ln10·dpH
  3. 壓力對帳：每分鐘頭空壓降 −dP ＝ 消耗 ＋ 存入液相（CO2＋H2＋其他）
         扣掉 CO2 之後剩下的「殘差」＝ 消耗 ＋ H2 進出 ＋ 其他
     殘差若變平，代表泵造成的壓力起伏就是 CO2 溶解；若仍跟著泵跳，剩下的是 H2 進出、
     量測假象（泵吸氣口的動壓、氣泡滯留），或 H2 傳質受限時「跟著泵走的消耗」。
     ⚠ 實測（2026-10-18）：CO2 只解釋泵開多出壓降的 19–30%；停泵那一分鐘壓力瞬間回升
     ~0.009 kgf/cm²、pH 沒有對應釋出 → 那個回升不是 CO2，較像動壓／滯留假象。
  4. 不確定度：以「小時」為單位自助抽樣（同一小時內的分鐘不獨立）。
限制
  · H2 每分鐘的進出量不到（ORP 不跟 H2 走，見 dissolution_two_channel），只能從殘差間接看
  · V_L/V_G=1.6、y_CO2=0.20 同前（未經設備方確認）；兩者只把 CO2 曲線整條等比縮放，不改形狀
  · 排除補氣後 60 分鐘
輸出 -> docs/analysis/dissolution_per_minute/（summary.json、per_minute.csv、png）
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import dissolution_two_channel as D                                # noqa: E402

OUT = os.path.join(REPO, 'docs', 'analysis', 'dissolution_per_minute')
EXCL = 60
VLG, Y_CO2 = 1.6, 0.20
NB = 3000


def fold(cs):
    """回傳每個「小時區塊」的 (60,) 每分鐘 dpH、dP（缺的是 NaN）。區塊從開泵那一分起算。"""
    blocks = []
    for c in cs:
        t, ph, P, phase = c['t'], c['pH'], c['P'], c['phase']
        cur = None
        for j in range(1, len(t)):
            if t[j] < EXCL:
                continue
            if phase[j] == 0 or cur is None:
                if cur is not None:
                    blocks.append(cur)
                cur = (np.full(60, np.nan), np.full(60, np.nan))
            ok = 0.5 < t[j] - t[j - 1] < 1.5 and P[j] - P[j - 1] <= 0.03 \
                and np.isfinite(ph[j]) and np.isfinite(ph[j - 1])
            if ok:
                cur[0][phase[j]] = ph[j] - ph[j - 1]
                cur[1][phase[j]] = P[j] - P[j - 1]
        if cur is not None:
            blocks.append(cur)
    dph = np.array([b[0] for b in blocks])
    dp = np.array([b[1] for b in blocks])
    keep = np.isfinite(dph).sum(1) >= 50          # 不完整的小時（循環頭尾）不要
    return dph[keep], dp[keep]


def boot(M, n=NB, seed=0):
    """以小時為單位抽樣，回傳每分鐘平均與 95% 區間 (3, 60)。"""
    rng = np.random.default_rng(seed)
    mean = np.nanmean(M, 0)
    bs = np.array([np.nanmean(M[rng.integers(0, len(M), len(M))], 0) for _ in range(n)])
    return mean, np.percentile(bs, 2.5, 0), np.percentile(bs, 97.5, 0)


def main():
    os.makedirs(OUT, exist_ok=True)
    C = D.cycles()
    res = {}
    rows = []
    for nm, tau, *_ in D.BATCHES:
        cs = [c for c in C if c['batch'] == nm]
        gap = cs[0]['gap']
        dph, dp = fold(cs)
        p_abs = float(np.nanmedian(np.concatenate([c['P'] for c in cs]))) + D.ATM
        k_co2 = -VLG * D.H_CC_CO2 * Y_CO2 * p_abs * np.log(10)       # dpH → 存入液相（kgf/cm²）
        co2 = k_co2 * dph                                            # 每分鐘存入（＋）
        drop = -dp                                                   # 每分鐘壓降（＋）
        resid = drop - co2                                           # 消耗＋H2＋其他
        m_drop, m_co2, m_res = boot(drop), boot(co2, seed=1), boot(resid, seed=2)
        on = np.arange(60) < gap
        # 泵開與泵停的平均（×60 → kgf/cm²/hr）；殘差的起伏有沒有被 CO2 拉平
        rng = np.random.default_rng(3)
        def onoff(M):
            ok = np.isfinite(M[:, on]).any(1)                            # 泵開那幾分全缺的小時不算
            v = np.nanmean(M[ok][:, on], 1) - np.nanmean(M[ok][:, ~on], 1)   # 每個小時：泵開比泵停多降多少
            b = [np.mean(v[rng.integers(0, len(v), len(v))]) for _ in range(NB)]
            return float(np.mean(v)) * 60, float(np.percentile(b, 2.5)) * 60, float(np.percentile(b, 97.5)) * 60
        d_drop, d_co2, d_res = onoff(drop), onoff(co2), onoff(resid)
        expl = d_co2[0] / d_drop[0] if d_drop[0] else np.nan
        # 一小時內累積：泵開時存進去多少、之後放出來多少。每個小時先累加再抽樣，
        # 區間才包含「60 分鐘雜訊一路累加」的隨機漫步（不先算區間會把漫步誤當成訊號）
        filled = np.where(np.isfinite(co2), co2, np.nanmean(co2, 0))
        m_cum = boot(np.cumsum(filled, 1), seed=4)
        cum = m_cum[0]
        res[nm] = dict(tau=tau, gap=int(gap), n_hours=int(len(dph)), p_abs=p_abs,
                       drop_rate=float(np.nanmean(drop)) * 60, co2_net_rate=float(np.nanmean(co2)) * 60,
                       pump_minus_idle={'drop': d_drop, 'co2': d_co2, 'residual': d_res},
                       co2_explains_pump_excess=float(expl),
                       co2_peak_stored=float(cum.max() - cum[0] + m_co2[0][0]), co2_peak_minute=int(cum.argmax()),
                       co2_end_of_hour=float(cum[-1]))
        print('\n══ %s（泵每小時開 %d 分；%d 個完整小時）══' % (nm, gap, len(dph)))
        print('  平均壓降 %.4f、CO2 淨存入 %+.4f kgf/cm²/hr' % (res[nm]['drop_rate'], res[nm]['co2_net_rate']))
        print('  泵開比泵停多降（kgf/cm²/hr）：壓力 %+.4f [%+.4f, %+.4f]' % d_drop)
        print('                                 CO2  %+.4f [%+.4f, %+.4f]' % d_co2)
        print('                                 殘差 %+.4f [%+.4f, %+.4f]' % d_res)
        print('  → CO2 解釋泵開多出來的壓降 %.0f%%' % (100 * expl))
        print('  一小時內 CO2 累積存入：最高 %+.5f（第 %d 分），到下次開泵前 %+.5f kgf/cm²'
              % (res[nm]['co2_peak_stored'], res[nm]['co2_peak_minute'], res[nm]['co2_end_of_hour']))
        for mm in sorted({0, gap - 1, gap, 15, 30, 59}):
            print('    第 %2d 分累積 %+.5f [%+.5f, %+.5f]' % (mm, m_cum[0][mm], m_cum[1][mm], m_cum[2][mm]))
        res[nm]['cum_ci'] = {int(mm): [float(m_cum[i][mm]) for i in range(3)] for mm in range(60)}
        for m in range(60):
            rows.append(dict(batch=nm, minute=m, pump=int(on[m]),
                             drop=m_drop[0][m] * 60, drop_lo=m_drop[1][m] * 60, drop_hi=m_drop[2][m] * 60,
                             co2=m_co2[0][m] * 60, co2_lo=m_co2[1][m] * 60, co2_hi=m_co2[2][m] * 60,
                             resid=m_res[0][m] * 60, resid_lo=m_res[1][m] * 60, resid_hi=m_res[2][m] * 60,
                             cum=m_cum[0][m], cum_lo=m_cum[1][m], cum_hi=m_cum[2][m]))
    with open(os.path.join(OUT, 'per_minute.csv'), 'w', encoding='utf-8') as fh:
        ks = list(rows[0])
        fh.write(','.join(ks) + '\n')
        for r in rows:
            fh.write(','.join(('%.6g' % r[k]) if isinstance(r[k], float) else str(r[k]) for k in ks) + '\n')
    with open(os.path.join(OUT, 'summary.json'), 'w', encoding='utf-8') as fh:
        json.dump(dict(excl_min=EXCL, vlg=VLG, y_co2=Y_CO2, batches=res), fh, ensure_ascii=False, indent=1)
    plot(rows, res)
    print('\n-> %s' % OUT)


def plot(rows, res):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei', 'Noto Sans CJK TC', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    nms = list(res)
    fig, ax = plt.subplots(2, len(nms), figsize=(5.2 * len(nms), 7.4), sharex=True)
    for i, nm in enumerate(nms):
        r = [x for x in rows if x['batch'] == nm]
        m = np.array([x['minute'] for x in r])
        g = res[nm]['gap']
        a = ax[0, i]
        a.axvspan(-0.5, g - 0.5, color='#e8d9a8', alpha=0.5, lw=0)
        for k, col, lab in (('drop', '#555555', '頭空壓降（總）'), ('co2', '#2f6fd0', 'CO2 存入液相（pH）'),
                            ('resid', '#d0602f', '殘差＝消耗＋H2＋其他')):
            y = np.array([x[k] for x in r])
            a.plot(m, y, color=col, lw=1.6, label=lab)
            a.fill_between(m, [x[k + '_lo'] for x in r], [x[k + '_hi'] for x in r], color=col, alpha=0.15, lw=0)
        a.axhline(0, color='#999', lw=0.7)
        a.set_title('%s：每分鐘速率（泵開 %d 分，n=%d 小時）' % (nm, g, res[nm]['n_hours']))
        a.set_ylabel('kgf/cm²/hr（正＝頭空減少）')
        if i == 0:
            a.legend(frameon=False, fontsize=8)
        b = ax[1, i]
        b.axvspan(-0.5, g - 0.5, color='#e8d9a8', alpha=0.5, lw=0)
        b.plot(m, [x['cum'] * 1000 for x in r], color='#2f6fd0', lw=1.8)
        b.fill_between(m, [x['cum_lo'] * 1000 for x in r], [x['cum_hi'] * 1000 for x in r],
                       color='#2f6fd0', alpha=0.15, lw=0, label='95% 區間（含累加雜訊）')
        b.legend(frameon=False, fontsize=8, loc='lower left')
        b.axhline(0, color='#999', lw=0.7)
        b.set_title('液相 CO2 累積存入（一小時內）')
        b.set_ylabel('×10⁻³ kgf/cm²')
        b.set_xlabel('距開泵（分鐘）')
    for a in ax.flat:
        a.spines[['top', 'right']].set_visible(False)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, 'dissolution_per_minute.png'), dpi=130)


if __name__ == '__main__':
    main()
