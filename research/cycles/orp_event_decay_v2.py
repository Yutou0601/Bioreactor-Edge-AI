# -*- coding: utf-8 -*-
"""ORP 事件回落 v2：拉長時間窗、扣掉 pH 的影響。
════════════════════════════════════════════════════════════════════════

v1（orp_event_decay.py，2026-10-15）：164 個事件，ORP 回升率與壓力下降率無關
（全部 ρ=+0.15、p=0.69；安慰劑 +0.06）。兩個附帶發現：泵開時 ORP 往負掉 15–24 mV；
補氣時 ORP 反而往正跳（τ10 中位 +51 mV）——懷疑是補氣帶進 CO2、pH 下降所致。

v2 的兩個改動：
1. **扣 pH**：H2/H+ 電對的 Nernst 式 E = E0 − (2.303RT/F)·pH − (2.303RT/2F)·log pH2，
   30 °C 時 2.303RT/F = 60.1 mV。所以 E + 60.1·pH 只剩 H2 的項——「pH 校正 ORP」。
   另外從資料估實際的 dE/dpH（電極未必是理想 Nernst），兩種校正都報。
   pH 濾掉 14.00 故障值與 5–9 以外的讀數。
2. **拉長時間窗**：泵事件受限於每小時一次，單事件最長約 55 分；再長就把連續 3 小時
   併成一個區塊——ORP 回升率取 3 個事件的平均，壓力下降用區塊頭尾（皆取泵開前一分鐘）
   相減，變化量有十幾個 0.01 量化階，雜訊比單事件小得多。

每一組（訊號 × 時間窗）都做：Spearman ρ、批次內置換 p、偏相關、事件前安慰劑。
附帶檢驗：pH 校正後，補氣時的 ORP 正跳是否消失（＝v1 的猜測是否成立）。
"""
import datetime as dt
import json
import os
import shutil
import sys

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from multivariate_increments import load4                      # noqa: E402
from regime_changepoints import TD                             # noqa: E402
from pump_rhythm import BATCHES, FOLDER, minute_profile, pump_window   # noqa: E402
from orp_event_decay import slope, spearman, perm_p, continuous, REFILL_RISE   # noqa: E402

OUT = os.path.join(REPO, 'docs', 'analysis', 'orp_event_decay_v2')
WEB = os.path.join(REPO, 'web_frontend', 'dist', 'reports', 'orp_event_decay_v2')
NERNST = 60.1          # mV per pH，30 °C
PRE = 45


def load():
    rows = load4(os.path.join(TD, FOLDER))
    ts = [r[0] for r in rows]
    P = np.array([r[1] for r in rows]); O = np.array([r[2] for r in rows])
    pH = np.array([r[3] for r in rows], float)
    bad = (pH < 5) | (pH > 9)
    pH[bad] = np.nan
    # 故障點用前後線性內插（只補短洞；長洞留 NaN，該事件會被排除）
    idx = np.arange(len(pH)); ok = ~np.isnan(pH)
    pH_f = np.interp(idx, idx[ok], pH[ok])
    gaps = np.convolve(~ok, np.ones(5), 'same') >= 5           # 連續 ≥5 筆壞的不補
    pH_f[gaps] = np.nan
    h = np.array([(t - ts[0]).total_seconds() / 3600 for t in ts])
    return ts, h, P, O, pH_f, int(bad.sum())


def empirical_slope(O, pH, ts, batches):
    """各批 dORP/dpH：用一階差分（扣掉慢漂移）做穩健迴歸，只取 pH 有變化的分鐘。"""
    out = {}
    for nm, tau, d0, d1 in batches:
        m = np.array([d0 <= t.date() <= d1 for t in ts])
        dO, dp = np.diff(O[m]), np.diff(pH[m])
        ok = np.isfinite(dO) & np.isfinite(dp) & (np.abs(dp) > 1e-9) & (np.abs(dO) < 30)
        if ok.sum() < 30:
            continue
        x, y = dp[ok], dO[ok]
        # Theil–Sen（對突波穩健）：取成對斜率中位數的近似——隨機抽樣
        rng = np.random.default_rng(1)
        i = rng.integers(0, len(x), 20000); j = rng.integers(0, len(x), 20000)
        d = x[i] - x[j]; s = (y[i] - y[j])[np.abs(d) > 1e-9] / d[np.abs(d) > 1e-9]
        out[nm] = {'slope_mV_per_pH': float(np.median(s)), 'n_minutes': int(ok.sum())}
    return out


def event_rows(ts, h, P, Os, refills, kind, i, tau, post):
    """單一事件在訊號 Os（dict 名稱→陣列）上的量測。"""
    if not continuous(ts, i - PRE, i + post):
        return None
    if any(i - PRE <= r <= i + post for r in refills if r != i):
        return None
    skip = tau + 3 if kind == 'pump' else 5
    res = {}
    for name, O in Os.items():
        seg = O[i - 10:i + 11]
        if np.isnan(seg).any() or np.isnan(O[i:i + post + 1]).any():
            return None
        base = float(np.mean(O[i - 10:i]))
        k = int(np.argmin(O[i:i + 11])) + i
        a = max(k + 5, i + skip); b = i + post
        if b - a < 10:
            return None
        m = np.arange(a, b + 1) - i
        res[name] = dict(jump=float(O[k] - base), jump_max=float(np.max(O[i:i + 11]) - base),
                         recovery=slope(m, O[a:b + 1]),
                         placebo=slope(np.arange(i - PRE, i - 9) - i, O[i - PRE:i - 9]))
        res['p_decline'] = -slope(m / 60.0, P[a:b + 1])
        res['placebo_p'] = -slope((np.arange(i - PRE, i - 9) - i) / 60.0, P[i - PRE:i - 9])
    res['p_level'] = float(P[i])
    return res


def stats(sel, sig):
    a = np.array([e[sig]['recovery'] for e in sel]); b = np.array([e['p_decline'] for e in sel])
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 8:
        return {'n': int(ok.sum()), 'note': '事件太少'}
    sel = [e for e, o in zip(sel, ok) if o]; a, b = a[ok], b[ok]
    strata = np.array([e['batch'] for e in sel])
    rho, p = perm_p(a, b, strata)
    X = np.column_stack([[e['p_level'] for e in sel], [e.get('hr_since_refill', 0) for e in sel]])
    prho, pp = perm_p(a, b, strata, partial_X=X)
    pa = np.array([e[sig]['placebo'] for e in sel]); pb = np.array([e['placebo_p'] for e in sel])
    k = np.isfinite(pa) & np.isfinite(pb)
    plc, plcp = perm_p(pa[k], pb[k], strata[k]) if k.sum() >= 8 else (float('nan'), float('nan'))
    return {'n': len(sel), 'rho': rho, 'p': p, 'partial_rho': prho, 'partial_p': pp,
            'placebo_rho': plc, 'placebo_p': plcp}


def blocks(ev, n=3):
    """同批、時間上連續（相隔約 1 小時）的泵事件每 n 個併成一個區塊。"""
    out, cur = [], []
    for e in ev:
        if cur and (e['batch'] != cur[-1]['batch'] or abs((e['_t'] - cur[-1]['_t']).total_seconds() - 3600) > 180):
            cur = []
        cur.append(e)
        if len(cur) == n:
            out.append(cur); cur = []
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    ts, h, P, O, pH, n_bad = load()
    refills = [i for i in range(1, len(P)) if P[i] - P[i - 1] > REFILL_RISE]
    emp = empirical_slope(O, pH, ts, BATCHES)
    Os = {'raw': O, 'nernst': O + NERNST * pH}
    for nm, v in emp.items():                               # 各批用自己的實測斜率
        pass
    emp_all = float(np.median([v['slope_mV_per_pH'] for v in emp.values()])) if emp else -NERNST
    Os['empirical'] = O - emp_all * pH                      # 實測斜率（負值）校正

    results, examples = {}, {}
    for post in (45, 55):
        evs = []
        for nm, tau, d0, d1 in BATCHES:
            mu, _s, _n = minute_profile(ts, h, P, d0, d1)
            on, off, gap = pump_window(mu)
            for i, t in enumerate(ts):
                if not (d0 <= t.date() <= d1):
                    continue
                kind = 'pump' if (t.minute == on and (i == 0 or ts[i - 1].minute != on)) else (
                    'refill' if i in set(refills) else None)
                if kind is None:
                    continue
                r = event_rows(ts, h, P, Os, refills, kind, i, tau, post)
                if r:
                    last = max([x for x in refills if x < i], default=None)
                    r.update(batch=nm, tau=tau, kind=kind, _t=t,
                             hr_since_refill=float(h[i] - h[last]) if last is not None else 0.0)
                    evs.append(r)
        for kind in ('pump', 'refill'):
            sel = [e for e in evs if e['kind'] == kind]
            for sig in Os:
                results['%s|%d分|%s' % (kind, post, sig)] = stats(sel, sig)
        examples[post] = evs

    # 3 小時區塊（泵事件，用 55 分窗的事件）
    pumps = [e for e in examples[55] if e['kind'] == 'pump']
    blk = blocks(sorted(pumps, key=lambda e: e['_t']))
    bl = []
    for b in blk:
        i0 = ts.index(b[0]['_t']); i1 = ts.index(b[-1]['_t'])
        i1e = i1 + 55
        dp = (P[i0 - 1] - P[min(i1e, len(P) - 1)]) / ((h[min(i1e, len(P) - 1)] - h[i0 - 1]))
        row = {'batch': b[0]['batch'], 'p_decline': float(dp), 'p_level': b[0]['p_level'],
               'hr_since_refill': b[0]['hr_since_refill'], 'placebo_p': float(np.mean([e['placebo_p'] for e in b]))}
        for sig in Os:
            row[sig] = {'recovery': float(np.mean([e[sig]['recovery'] for e in b])),
                        'placebo': float(np.mean([e[sig]['placebo'] for e in b]))}
        bl.append(row)
    for sig in Os:
        results['pump|3小時區塊|%s' % sig] = stats(bl, sig)

    # 補氣時的 ORP 跳動：原始 vs pH 校正（驗證「正跳是 pH 造成的」）
    jumps = {}
    for sig in Os:
        vals = [e[sig]['jump_max'] if sig == 'raw' else e[sig]['jump'] for e in examples[55] if e['kind'] == 'refill']
        allj = [(e[sig]['jump'], e[sig]['jump_max']) for e in examples[55] if e['kind'] == 'refill']
        jumps[sig] = {'n': len(allj),
                      'median_most_negative': float(np.median([a for a, _ in allj])) if allj else None,
                      'median_most_positive': float(np.median([b for _, b in allj])) if allj else None}
    pump_jumps = {sig: float(np.median([e[sig]['jump'] for e in examples[55] if e['kind'] == 'pump']))
                  for sig in Os}

    summary = {'generated': dt.datetime.now().isoformat(sep=' ', timespec='seconds'),
               'data': FOLDER, 'nernst_mV_per_pH': NERNST, 'empirical_slope': emp,
               'empirical_slope_used': emp_all, 'ph_bad_points_removed': n_bad,
               'n_blocks': len(bl), 'results': results, 'refill_jumps': jumps, 'pump_jump_median': pump_jumps}
    with open(os.path.join(OUT, 'summary.json'), 'w', encoding='utf-8') as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=1)

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams['font.family'] = 'DejaVu Sans'
    col = {'tau1': '#2a78d6', 'tau5': '#eb6834', 'tau10': '#1baf7a'}
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.4))
    for j, sig in enumerate(('raw', 'nernst')):
        for nm, *_ in BATCHES:
            s = [r for r in bl if r['batch'] == nm]
            ax[j].scatter([r['p_decline'] for r in s], [r[sig]['recovery'] for r in s], s=22, alpha=.8, color=col[nm], label=nm)
        st = results['pump|3小時區塊|%s' % sig]
        ax[j].set_title('3-h blocks, ORP %s: rho=%.2f p=%.3f' % ('raw' if sig == 'raw' else 'pH-corrected (Nernst)',
                                                               st.get('rho', np.nan), st.get('p', np.nan)), fontsize=10)
        ax[j].set_xlabel('pressure decline over block (kgf/cm2/hr)'); ax[j].set_ylabel('mean ORP recovery (mV/min)')
        ax[j].axhline(0, color='#999', lw=.6); ax[j].legend(fontsize=8)
    for nm, *_ in BATCHES:
        for sig, ls in (('raw', '--'), ('nernst', '-')):
            curves = []
            for e in examples[55]:
                if e['batch'] != nm or e['kind'] != 'refill':
                    continue
                i = ts.index(e['_t'])
                seg = Os[sig][i - 15:i + 56] - np.mean(Os[sig][i - 10:i])
                if not np.isnan(seg).any():
                    curves.append(seg)
            if curves:
                ax[2].plot(np.arange(-15, 56), np.mean(curves, 0), ls, color=col[nm], lw=1.4,
                           label='%s refill %s (n=%d)' % (nm, sig, len(curves)))
    ax[2].axvline(0, color='#999', lw=.6); ax[2].set_xlabel('minutes from refill'); ax[2].set_ylabel('ORP - baseline (mV)')
    ax[2].set_title('Refill: raw (dashed) vs pH-corrected (solid)', fontsize=10); ax[2].legend(fontsize=7)
    fig.tight_layout(); fig.savefig(os.path.join(OUT, 'orp_event_decay_v2.png'), dpi=130)

    write_html(summary)
    os.makedirs(WEB, exist_ok=True)
    for f in ('index.html', 'orp_event_decay_v2.png', 'summary.json'):
        shutil.copy(os.path.join(OUT, f), os.path.join(WEB, f))
    print(json.dumps({k: v for k, v in summary.items() if k != 'results'}, ensure_ascii=False, indent=1))
    for k, v in results.items():
        print('%-28s n=%-4s rho=%+.3f p=%.3f  partial p=%.3f  placebo rho=%+.3f'
              % (k, v.get('n'), v.get('rho', np.nan), v.get('p', np.nan), v.get('partial_p', np.nan), v.get('placebo_rho', np.nan)))


def write_html(s):
    R = s['results']
    SIG = {'raw': '原始 ORP', 'nernst': 'pH 校正（Nernst 60.1 mV/pH）', 'empirical': 'pH 校正（實測斜率）'}
    rows = ''
    for key, v in R.items():
        kind, win, sig = key.split('|')
        kind = {'pump': '泵啟動', 'refill': '補氣'}[kind]
        if 'rho' not in v:
            rows += '<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td colspan="6">%s</td></tr>' % (kind, win, SIG[sig], v.get('n'), v.get('note', ''))
            continue
        sig_ok = v['p'] < 0.05 and v['partial_p'] < 0.05 and abs(v['rho']) > abs(v['placebo_rho']) + 0.1
        rows += ('<tr%s><td>%s</td><td>%s</td><td>%s</td><td>%d</td><td>%+.3f</td><td>%.3f</td><td>%+.3f</td><td>%.3f</td><td>%+.3f</td><td>%s</td></tr>'
                 % (' class="hit"' if sig_ok else '', kind, win, SIG[sig], v['n'], v['rho'], v['p'], v['partial_rho'],
                    v['partial_p'], v['placebo_rho'], '✓ 事件特定且顯著' if sig_ok else '—'))
    hits = [k for k, v in R.items() if 'rho' in v and v['p'] < 0.05 and v['partial_p'] < 0.05 and abs(v['rho']) > abs(v['placebo_rho']) + 0.1]
    if hits:
        verdict = ('<b>有組合達到「事件特定且顯著」</b>：%s。拉長時間窗或扣掉 pH 後才出現的話，表示 v1 的虛無結果部分來自雜訊或 pH 干擾。'
                   '⚠ 這裡同時看了 %d 組，有一組 p&lt;0.05 的機率本來就不低，要看它是否在相鄰設定（例如 55 分與 3 小時）都一致。'
                   % ('、'.join(hits), len(R)))
    else:
        verdict = ('<b>拉長時間窗、扣掉 pH 之後，仍沒有任何組合達到「事件特定且顯著」。</b>'
                   'ORP 回升快慢與壓力下降快慢，在這批資料裡看不出關聯——與 v1 一致，也與 2026-09-21「ORP 反映料位／操作、不是活性計」的結論一致。')
    j = s['refill_jumps']; pj = s['pump_jump_median']
    emp = ''.join('<li>%s：%.1f mV/pH（%d 分鐘）</li>' % (k, v['slope_mV_per_pH'], v['n_minutes']) for k, v in s['empirical_slope'].items())
    jump_tbl = ''.join('<tr><td>%s</td><td>%d</td><td>%+.1f</td><td>%+.1f</td><td>%+.1f</td></tr>'
                       % (SIG[k], v['n'], v['median_most_positive'] or 0, v['median_most_negative'] or 0, pj[k]) for k, v in j.items())
    html = f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ORP 事件回落 v2</title><style>
:root{{color-scheme:dark}} body{{background:#0d0d0d;color:#f0efec;font-family:system-ui,"Microsoft JhengHei",sans-serif;margin:0;padding:16px;line-height:1.6}}
main{{max-width:1150px;margin:0 auto}} .card{{background:#1a1a19;border:1px solid rgba(255,255,255,.1);border-radius:8px;padding:16px;margin:0 0 16px}}
h1{{font-size:1.25rem}} h2{{font-size:1rem;margin:0 0 10px}} p,li{{color:#c3c2b7;font-size:.9rem}} b{{color:#f0efec}}
table{{border-collapse:collapse;width:100%;font-size:.82rem;font-variant-numeric:tabular-nums}} th,td{{padding:5px 8px;border-bottom:1px solid #2c2c2a;text-align:right;white-space:nowrap}}
th{{color:#898781;font-weight:500}} td:nth-child(-n+3),th:nth-child(-n+3){{text-align:left}} tr.hit td{{color:#0ca30c}}
.wrap{{overflow-x:auto}} img{{width:100%;background:#fff;border-radius:6px}} a{{color:#86b6ef}}
</style></head><body><main>
<h1>ORP 事件回落 v2：拉長時間窗、扣掉 pH　<small style="color:#898781;font-size:.8rem">產生於 {s['generated']}（Jetson）· {s['data']}</small></h1>
<div class="card"><h2>結論</h2><p>{verdict}</p></div>
<div class="card"><h2>補氣時 ORP 往正跳，是不是 pH 造成的？</h2><div class="wrap"><table>
<tr><th>訊號</th><th></th><th></th><th>補氣事件</th><th>事件後最正（中位, mV）</th><th>事件後最負（中位, mV）</th><th>泵開後最負（中位, mV）</th></tr>
{''.join('<tr><td>%s</td><td></td><td></td><td>%d</td><td>%+.1f</td><td>%+.1f</td><td>%+.1f</td></tr>' % (SIG[k], v['n'], v['median_most_positive'] or 0, v['median_most_negative'] or 0, pj[k]) for k, v in j.items())}
</table></div><p>若補氣的正跳是 CO2 帶來的酸化，pH 校正後「最正」應明顯變小、「最負」變得更負（H2 進來了）。對照右圖的虛線（原始）與實線（校正）。</p></div>
<div class="card"><h2>ORP 回升率 vs 壓力下降率（每一組都有批次內置換、偏相關、事件前安慰劑）</h2><div class="wrap"><table>
<tr><th>事件</th><th>時間窗</th><th>ORP 訊號</th><th>n</th><th>ρ</th><th>p</th><th>偏相關 ρ</th><th>p</th><th>安慰劑 ρ</th><th>判定</th></tr>{rows}</table></div>
<p>綠色＝p&lt;0.05、偏相關 p&lt;0.05、且比安慰劑強 0.1 以上。3 小時區塊共 {s['n_blocks']} 個（同批連續 3 次泵事件）。</p></div>
<div class="card"><h2>pH 斜率</h2><p>理論（Nernst，30 °C）：−60.1 mV/pH。實測（各批一階差分的 Theil–Sen 斜率）：</p><ul>{emp}</ul>
<p>使用的實測中位斜率：{s['empirical_slope_used']:.1f} mV/pH。濾掉的 pH 故障點：{s['ph_bad_points_removed']} 筆（5–9 以外，含 14.00）。
實測斜率若遠小於 60，代表 ORP 與 pH 的短時變化不是單純的 Nernst 關係（混合電位），Nernst 校正可能過度。</p></div>
<div class="card"><h2>圖</h2><img src="orp_event_decay_v2.png" alt="左、中：3 小時區塊的壓力下降率 vs 平均 ORP 回升率（原始、pH 校正）；右：補氣事件對齊的 ORP，虛線原始、實線 pH 校正"></div>
<div class="card"><h2>限制</h2><ul><li>ORP 回升也可能是 H2 逸散回氣相（物理）；壓力下降含物理溶解。正相關只是「相容」。</li>
<li>這裡一次看了很多組（訊號 × 時間窗 × 事件類型），單一組 p&lt;0.05 不足為證，要看是否跨設定一致。</li>
<li>三批沒有換液，τ、菌齡、液相飽和共線。</li></ul>
<p>v1 報告：<a href="../orp_event_decay/index.html">ORP 事件回落 v1</a>；原始資料：<a href="summary.json">summary.json</a>；程式：research/cycles/orp_event_decay_v2.py</p></div>
</main></body></html>"""
    with open(os.path.join(OUT, 'index.html'), 'w', encoding='utf-8') as fh:
        fh.write(html)


if __name__ == '__main__':
    main()
