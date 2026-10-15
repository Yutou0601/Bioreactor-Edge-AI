# -*- coding: utf-8 -*-
"""ORP 事件回落速率 vs 壓力下降速率：ORP 的回落是不是「H2 被甲烷菌吃掉」？
════════════════════════════════════════════════════════════════════════

假說（使用者 2026-10-15）：H2 溶進液相 → ORP 變負（更還原）；嗜氫甲烷菌吃掉 H2
→ ORP 回升。反應器裡只有嗜氫甲烷菌，所以 ORP 回升的快慢若反映 H2 被消耗的快慢，
就應該跟同一段時間的壓力下降速率（生物消耗的一部分）同向。

做法（逐事件，不疊加平均——疊加看的是平均形狀，看不到事件間的快慢差異）：
  事件：補氣（壓力單步跳升 > 0.03）與泵啟動（各批每小時泵開的那一分鐘）
  每個事件：
    ORP 極值   事件後 0–10 分內最負的點（ORP 已還原負號，load4 處理）
    ORP 回升率 極值後的時間窗內 ORP 的線性斜率（mV/分，正＝往氧化方向回升）
    壓力下降率 同一時間窗內反應槽壓力的線性斜率（kgf/cm²/hr，下降記為正）
    時間窗     [極值+5, 事件+45] 分；泵事件另外跳過泵運轉的 τ+3 分（避開驟降與回升）
  檢定：
    1. Spearman ρ(ORP 回升率, 壓力下降率)，置換在「批次×事件類型」內打亂
    2. 偏相關：扣掉事件時的壓力水準、距上次補氣小時數、事件前 ORP 基線（秩迴歸殘差）
    3. 安慰劑：在事件「之前」[-45, -10] 分做完全一樣的計算。事件後的相關若不比安慰劑強，
       就只是兩個訊號共同漂移，不是事件後 H2 被消耗
⚠ 解讀限制寫在報告裡：ORP 回升也可能來自 H2 逸散回氣相（物理），不只生物消耗；
  而壓力下降同時含物理溶解。正相關是「相容」不是「證明」。

輸出：docs/analysis/orp_event_decay/（CSV、summary.json、圖、index.html），
      並複製到 web_frontend/dist/reports/orp_event_decay/ 讓網頁直接看。
"""
import datetime as dt
import json
import os
import shutil
import sys

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # research/
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from multivariate_increments import load4                      # noqa: E402
from regime_changepoints import TD                             # noqa: E402
from pump_rhythm import BATCHES, FOLDER, minute_profile, pump_window   # noqa: E402

OUT = os.path.join(REPO, 'docs', 'analysis', 'orp_event_decay')
WEB = os.path.join(REPO, 'web_frontend', 'dist', 'reports', 'orp_event_decay')
REFILL_RISE = 0.03
PRE, POST = 45, 45
RNG = np.random.default_rng(20261015)
N_PERM = 5000


def slope(x, y):
    x = np.asarray(x, float); y = np.asarray(y, float)
    if len(x) < 5 or np.ptp(x) == 0:
        return np.nan
    return float(np.polyfit(x, y, 1)[0])


def ranks(a):
    return np.argsort(np.argsort(a)).astype(float)


def spearman(a, b):
    return float(np.corrcoef(ranks(a), ranks(b))[0, 1])


def perm_p(a, b, strata, n=N_PERM, partial_X=None):
    """雙尾置換 p。strata 內打亂 b。partial_X 給了就先對秩做線性殘差（偏相關）。"""
    ra, rb = ranks(a), ranks(b)
    if partial_X is not None:
        X = np.column_stack([np.ones(len(a))] + [ranks(c) for c in partial_X.T])
        ra = ra - X @ np.linalg.lstsq(X, ra, rcond=None)[0]
        rb = rb - X @ np.linalg.lstsq(X, rb, rcond=None)[0]
    obs = float(np.corrcoef(ra, rb)[0, 1])
    groups = [np.flatnonzero(strata == s) for s in np.unique(strata)]
    cnt = 0
    for _ in range(n):
        rp = rb.copy()
        for g in groups:
            rp[g] = rb[RNG.permutation(g)]
        if abs(np.corrcoef(ra, rp)[0, 1]) >= abs(obs):
            cnt += 1
    return obs, (cnt + 1) / (n + 1)


def continuous(ts, a, b):
    """索引 a..b 每一步都約一分鐘（40–80 秒）。"""
    if a < 0 or b >= len(ts):
        return False
    d = np.diff([t.timestamp() for t in ts[a:b + 1]])
    return bool(np.all((d > 40) & (d < 80)))


def measure(ts, P, O, i, skip, refills):
    """事件 i 的量測；回傳 dict 或 None（資料不連續、窗內有補氣等）。"""
    if not continuous(ts, i - PRE, i + POST):
        return None
    if any(i < r <= i + POST for r in refills) or any(i - PRE <= r < i for r in refills):
        return None
    base = float(np.mean(O[i - 10:i]))
    k = int(np.argmin(O[i:i + 11])) + i                     # 事件後最負的點
    a = max(k + 5, i + skip)
    b = i + POST
    if b - a < 10:
        return None
    m = np.arange(a, b + 1) - i
    orp_rec = slope(m, O[a:b + 1])                           # mV/分，正＝回升
    p_dec = -slope(m / 60.0, P[a:b + 1])                     # kgf/cm²/hr，下降為正
    # 安慰劑：事件前同長度
    pa, pb = i - PRE, i - 10
    pm = np.arange(pa, pb + 1) - i
    plc_orp = slope(pm, O[pa:pb + 1])
    plc_p = -slope(pm / 60.0, P[pa:pb + 1])
    return dict(orp_jump=float(O[k] - base), orp_base=base, orp_recovery=orp_rec,
                p_decline=p_dec, p_level=float(P[i]), placebo_orp=plc_orp, placebo_p=plc_p,
                window=f'{a - i}..{b - i}')


def main():
    os.makedirs(OUT, exist_ok=True)
    rows = load4(os.path.join(TD, FOLDER))
    ts = [r[0] for r in rows]
    P = np.array([r[1] for r in rows]); O = np.array([r[2] for r in rows])
    h = np.array([(t - ts[0]).total_seconds() / 3600 for t in ts])
    refills = [i for i in range(1, len(P)) if P[i] - P[i - 1] > REFILL_RISE]

    events = []
    for nm, tau, d0, d1 in BATCHES:
        mu, _se, _n = minute_profile(ts, h, P, d0, d1)
        on, off, gap = pump_window(mu)
        idx = [i for i, t in enumerate(ts) if d0 <= t.date() <= d1]
        # 泵事件：每小時第 on 分
        for i in idx:
            if ts[i].minute == on and (i == 0 or ts[i - 1].minute != on):
                last_r = max([r for r in refills if r < i], default=None)
                m = measure(ts, P, O, i, tau + 3, refills)
                if m:
                    m.update(batch=nm, tau=tau, kind='pump', ts=ts[i].isoformat(sep=' '),
                             hr_since_refill=(h[i] - h[last_r]) if last_r is not None else np.nan)
                    events.append(m)
        # 補氣事件
        for i in refills:
            if d0 <= ts[i].date() <= d1:
                last_r = max([r for r in refills if r < i], default=None)
                m = measure(ts, P, O, i, 5, refills)
                if m:
                    m.update(batch=nm, tau=tau, kind='refill', ts=ts[i].isoformat(sep=' '),
                             hr_since_refill=(h[i] - h[last_r]) if last_r is not None else np.nan)
                    events.append(m)
        print('%s：泵開於每小時第 %d 分、運轉約 %d 分' % (nm, on, gap))

    import csv
    keys = ['batch', 'tau', 'kind', 'ts', 'orp_base', 'orp_jump', 'orp_recovery', 'p_decline',
            'p_level', 'hr_since_refill', 'placebo_orp', 'placebo_p', 'window']
    with open(os.path.join(OUT, 'events.csv'), 'w', newline='', encoding='utf-8-sig') as fh:
        w = csv.DictWriter(fh, fieldnames=keys); w.writeheader()
        for e in events:
            w.writerow({k: e.get(k) for k in keys})

    summary = {'generated': dt.datetime.now().isoformat(sep=' ', timespec='seconds'),
               'data': FOLDER, 'n_events': len(events), 'groups': []}
    for kind in ('pump', 'refill', 'all'):
        sel = [e for e in events if kind == 'all' or e['kind'] == kind]
        sel = [e for e in sel if np.isfinite(e['orp_recovery']) and np.isfinite(e['p_decline'])]
        if len(sel) < 8:
            summary['groups'].append({'kind': kind, 'n': len(sel), 'note': '事件太少'})
            continue
        a = np.array([e['orp_recovery'] for e in sel]); b = np.array([e['p_decline'] for e in sel])
        strata = np.array([e['batch'] + e['kind'] for e in sel])
        rho, p = perm_p(a, b, strata)
        Xc = np.column_stack([[e['p_level'] for e in sel], [e['orp_base'] for e in sel],
                              [0 if not np.isfinite(e['hr_since_refill']) else e['hr_since_refill'] for e in sel]])
        prho, pp = perm_p(a, b, strata, partial_X=Xc)
        pa_ = np.array([e['placebo_orp'] for e in sel]); pb_ = np.array([e['placebo_p'] for e in sel])
        ok = np.isfinite(pa_) & np.isfinite(pb_)
        plc_rho, plc_p = perm_p(pa_[ok], pb_[ok], strata[ok])
        per_batch = {}
        for nm, *_ in BATCHES:
            s2 = [e for e in sel if e['batch'] == nm]
            if len(s2) >= 6:
                per_batch[nm] = {'n': len(s2), 'rho': spearman([e['orp_recovery'] for e in s2], [e['p_decline'] for e in s2]),
                                 'median_orp_recovery': float(np.median([e['orp_recovery'] for e in s2])),
                                 'median_orp_jump': float(np.median([e['orp_jump'] for e in s2])),
                                 'median_p_decline': float(np.median([e['p_decline'] for e in s2]))}
        summary['groups'].append({'kind': kind, 'n': len(sel), 'rho': rho, 'p': p,
                                  'partial_rho': prho, 'partial_p': pp,
                                  'placebo_rho': plc_rho, 'placebo_p': plc_p, 'per_batch': per_batch})
    with open(os.path.join(OUT, 'summary.json'), 'w', encoding='utf-8') as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=1)

    # ── 圖（英文標籤：Jetson 不一定有中文字型）──
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    col = {'tau1': '#2a78d6', 'tau5': '#eb6834', 'tau10': '#1baf7a'}
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.4))
    for j, kind in enumerate(('pump', 'refill')):
        for nm, *_ in BATCHES:
            s = [e for e in events if e['kind'] == kind and e['batch'] == nm]
            ax[j].scatter([e['p_decline'] for e in s], [e['orp_recovery'] for e in s], s=14, alpha=.7, color=col[nm], label=nm)
        g = next((g for g in summary['groups'] if g['kind'] == kind and 'rho' in g), None)
        ax[j].set_title('%s events: rho=%.2f p=%.3f (placebo rho=%.2f)' % (kind, g['rho'], g['p'], g['placebo_rho']) if g else kind, fontsize=10)
        ax[j].set_xlabel('pressure decline (kgf/cm2/hr)'); ax[j].set_ylabel('ORP recovery (mV/min, + = toward oxidised)')
        ax[j].axhline(0, color='#999', lw=.6); ax[j].legend(fontsize=8)
    # 事件對齊的平均 ORP 曲線
    for nm, *_ in BATCHES:
        for kind, ls in (('pump', '-'), ('refill', '--')):
            curves = []
            for e in events:
                if e['batch'] != nm or e['kind'] != kind:
                    continue
                i = ts.index(dt.datetime.fromisoformat(e['ts']))
                curves.append(O[i - 15:i + POST + 1] - np.mean(O[i - 10:i]))
            if curves:
                ax[2].plot(np.arange(-15, POST + 1), np.mean(curves, 0), ls, color=col[nm], lw=1.4, label='%s %s (n=%d)' % (nm, kind, len(curves)))
    ax[2].axvline(0, color='#999', lw=.6); ax[2].set_xlabel('minutes from event'); ax[2].set_ylabel('ORP - pre-event baseline (mV)')
    ax[2].set_title('Event-aligned mean ORP', fontsize=10); ax[2].legend(fontsize=7)
    fig.tight_layout(); fig.savefig(os.path.join(OUT, 'orp_event_decay.png'), dpi=130)

    write_html(summary)
    os.makedirs(WEB, exist_ok=True)
    for f in ('index.html', 'orp_event_decay.png', 'events.csv', 'summary.json'):
        shutil.copy(os.path.join(OUT, f), os.path.join(WEB, f))
    print(json.dumps(summary, ensure_ascii=False, indent=1)[:3000])


def write_html(s):
    def g(kind):
        return next((x for x in s['groups'] if x['kind'] == kind), {})
    def row(kind, label):
        x = g(kind)
        if 'rho' not in x:
            return '<tr><td>%s</td><td colspan="7">%s（n=%s）</td></tr>' % (label, x.get('note', ''), x.get('n'))
        return ('<tr><td>%s</td><td>%d</td><td>%+.3f</td><td>%.4f</td><td>%+.3f</td><td>%.4f</td><td>%+.3f</td><td>%.4f</td></tr>'
                % (label, x['n'], x['rho'], x['p'], x['partial_rho'], x['partial_p'], x['placebo_rho'], x['placebo_p']))
    pb = ''
    for kind in ('pump', 'refill'):
        for nm, v in g(kind).get('per_batch', {}).items():
            pb += ('<tr><td>%s</td><td>%s</td><td>%d</td><td>%+.2f</td><td>%+.2f</td><td>%+.3f</td><td>%.4f</td></tr>'
                   % (kind, nm, v['n'], v['rho'], v['median_orp_jump'], v['median_orp_recovery'], v['median_p_decline']))
    a, pm = g('all'), g('pump')
    verdict = '尚無足夠事件'
    if 'rho' in a:
        stronger = abs(a['rho']) > abs(a['placebo_rho']) + 0.1
        if a['p'] < 0.05 and a['rho'] > 0 and stronger and a['partial_p'] < 0.05:
            verdict = ('<b>相容於假說</b>：事件後 ORP 回升越快，壓力也降得越快，扣掉壓力水準、ORP 基線、距補氣時間後仍顯著，'
                       '且明顯強於事件前的安慰劑。這與「ORP 回升反映 H2 被甲烷菌消耗」一致，但仍無法排除 H2 逸散回氣相（見限制）。')
        elif a['p'] < 0.05 and not stronger:
            verdict = ('<b>不支持事件特定的關聯</b>：相關顯著，但事件前的安慰劑也差不多強——兩個訊號只是一起漂移，'
                       '不是事件後 H2 被消耗造成的。')
        elif a['p'] < 0.05 and a['rho'] < 0:
            verdict = '<b>方向與假說相反</b>：ORP 回升越快，壓力反而降得越慢。'
        else:
            verdict = ('<b>沒有偵測到關聯</b>（p ≥ 0.05）。注意這不等於「沒有關係」：每段時間窗的壓力變化只有幾個 '
                       '0.01 的量化階，速率雜訊很大，檢定力可能不足。')
    html = f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>ORP 事件回落分析</title>
<style>
:root{{color-scheme:dark;--bg:#0d0d0d;--s:#1a1a19;--t:#f0efec;--t2:#c3c2b7;--m:#898781;--g:#2c2c2a}}
body{{background:var(--bg);color:var(--t);font-family:system-ui,"Microsoft JhengHei",sans-serif;margin:0;padding:16px;line-height:1.6}}
main{{max-width:1100px;margin:0 auto}} .card{{background:var(--s);border:1px solid rgba(255,255,255,.1);border-radius:8px;padding:16px;margin:0 0 16px}}
h1{{font-size:1.25rem}} h2{{font-size:1rem;margin:0 0 10px}} p,li{{color:var(--t2);font-size:.9rem}}
table{{border-collapse:collapse;width:100%;font-size:.85rem;font-variant-numeric:tabular-nums}} th,td{{padding:5px 8px;border-bottom:1px solid var(--g);text-align:right}}
th{{color:var(--m);font-weight:500}} td:first-child,th:first-child{{text-align:left}} img{{width:100%;background:#fff;border-radius:6px}}
.wrap{{overflow-x:auto}} b{{color:var(--t)}}
</style></head><body><main>
<h1>ORP 事件回落 vs 壓力下降　<small style="color:#898781;font-size:.8rem">產生於 {s['generated']}（Jetson）· 資料 {s['data']} · {s['n_events']} 個事件</small></h1>
<div class="card"><h2>問題</h2><p>反應器裡只有嗜氫甲烷菌。若補氣／泵開讓 H2 溶進液相（ORP 變負），之後 ORP 回升的快慢反映 H2 被甲烷菌吃掉的快慢，
那麼<b>ORP 回升越快的事件，同一段時間的壓力也應該降得越快</b>。逐事件檢查，而不是疊加平均。</p></div>
<div class="card"><h2>結論</h2><p>{verdict}</p></div>
<div class="card"><h2>相關檢定（Spearman；置換在批次×事件類型內打亂，{N_PERM} 次）</h2><div class="wrap"><table>
<tr><th>事件</th><th>n</th><th>ρ</th><th>p</th><th>偏相關 ρ</th><th>p</th><th>安慰劑 ρ（事件前）</th><th>p</th></tr>
{row('pump', '泵啟動')}{row('refill', '補氣')}{row('all', '全部')}</table></div>
<p>偏相關扣掉：事件時的壓力水準、事件前 ORP 基線、距上次補氣的小時數。安慰劑＝事件前 −45～−10 分做同樣計算；事件後的相關要明顯強於它才算事件特定。</p></div>
<div class="card"><h2>各批次</h2><div class="wrap"><table><tr><th>事件</th><th>批次</th><th>n</th><th>ρ</th><th>ORP 跳動中位（mV）</th><th>ORP 回升中位（mV/分）</th><th>壓力下降中位（kgf/cm²/hr）</th></tr>{pb}</table></div>
<p>ORP 已還原為真實負值：跳動為負＝事件後變得更還原（H2 進入），回升為正＝往氧化方向回去。</p></div>
<div class="card"><h2>圖</h2><img src="orp_event_decay.png" alt="左、中：各事件的壓力下降率對 ORP 回升率散佈圖（泵、補氣）；右：事件對齊的平均 ORP 曲線"></div>
<div class="card"><h2>限制（解讀前必讀）</h2><ul>
<li>ORP 回升也可能是 H2 從液相逸散回氣相（物理），不只是被吃掉；壓力下降也含物理溶解。正相關是「相容」，不是「證明」。</li>
<li>鉑電極量到的是混合電位，不是 H2 濃度；不同事件間的電極狀態可能不同。</li>
<li>時間窗約 30–40 分鐘，壓力只變化幾個 0.01 的量化階，速率雜訊大，檢定力有限。</li>
<li>三批 τ 期間沒有換液，τ、菌齡、液相飽和共線；批次差異不能歸因給 τ。</li>
</ul><p>原始資料：<a href="events.csv" style="color:#86b6ef">events.csv</a>、<a href="summary.json" style="color:#86b6ef">summary.json</a>；
程式：research/cycles/orp_event_decay.py</p></div>
</main></body></html>"""
    with open(os.path.join(OUT, 'index.html'), 'w', encoding='utf-8') as fh:
        fh.write(html)


if __name__ == '__main__':
    main()
