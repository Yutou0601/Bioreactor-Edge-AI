# -*- coding: utf-8 -*-
"""泵開／泵停兩模式拆分：泵停期的壓降速率是什麼、它跟 r_b 比起來如何。

2026-09-17。承 pump_rhythm.py（泵運轉時間＝τ、壓降集中在泵開期）。

════════════════════════════════════════════════════════════════════════
要回答的三個問題

  Q1  泵停期（每小時 60−τ 分鐘、無泵驅動質傳）的壓降速率 r_off 是多少？
      它是全案第一個不靠模擬校準、近似「純生物＋殘餘溶解」的窗口。
      跟論文 r_b = 0.0125 [0.0112, 0.0139] 比，落在哪邊？

  Q2  r_off 在循環內隨壓力變嗎？
        平坦（不隨 P 變）→ 零階，像生物
        隨 (P − P_end) 線性 → 一階，像殘餘物理溶解
      這是最簡版的 switched 模型：泵開／泵停各一條「速率 vs 壓力」直線。

  Q3  泵停那一分鐘的「回升」是假象嗎？
      泵運轉可能改變感測器處的液柱或動壓，泵停就彈回來。若是假象，回升幅度
      應與壓力無關、且與泵開驟降配對。看回升 vs 壓力的斜率。

════════════════════════════════════════════════════════════════════════
⚠ 解讀前提（務必連同結果一起讀）

  泵停期的壓降 = kLa_off × (溶解度缺口)。缺口由生物消耗造成，但若 kLa_off
  太小，氣相看到的速率會被質傳限住、低於 r_b；生物欠下的缺口會在下一次泵開時
  一次補上（併入泵開驟降）。所以 r_off 是 r_b 的**下界**，等於 r_b 只在
  「泵停期的殘餘質傳足以跟上生物」時成立。Q2 的平坦性是判斷這件事的線索。

  三批 τ／菌齡／飽和完全共線（見 three_batch_tau_experiment），批間差異
  不一定是 τ 造成的。

輸出 -> docs/analysis_charts_3batch/pump_mode_split_hours.csv
"""
import csv
import datetime as dt
import glob
import os
import sys

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # research/
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, 'edge_backend'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pump_rhythm import BATCHES, FOLDER, minute_profile, pump_window  # noqa: E402

OUT = os.path.join(REPO, 'docs', 'analysis_charts_3batch')
RB_PAPER = (0.0125, 0.0112, 0.0139)     # 定版 r_b 與 95% 區間（去重後 207 段）
REFILL_RISE = 0.03


def load():
    from core.cycle_store import read_series_full
    d = os.path.join(REPO, 'research', 'Testing_data', FOLDER)
    got = read_series_full(sorted(glob.glob(os.path.join(d, '*.csv'))))
    if got is None:
        raise SystemExit('讀不到資料：%s' % d)
    ts, h, p, *_ = got
    return ts, np.asarray(h), np.asarray(p)


def descents(h, p, min_pts=3):
    """以補氣（單步跳升 > 0.03）為界切下降段（同 detail_tables.descents）。"""
    segs, valley, start = [], p[0], 0
    for i in range(1, len(p)):
        if h[i] - h[i - 1] > 1.0 or p[i] - valley > REFILL_RISE:
            if i - 1 > start:
                segs.append((start, i - 1))
            start, valley = i, p[i]
        elif p[i] < valley:
            valley = p[i]
    segs.append((start, len(p) - 1))
    return [(s, e) for s, e in segs if e > s + min_pts and p[s] > p[e]]


def lin_r2(t, y):
    A = np.vstack([t, np.ones_like(t)]).T
    c, *_ = np.linalg.lstsq(A, y, rcond=None)
    r = y - A @ c
    st = float(((y - y.mean()) ** 2).sum())
    return -float(c[0]), (float('nan') if st <= 0 else 1 - float(r @ r) / st)


def regular_cycles(ts, h, p):
    """規律的自動循環：≥4 hr、降幅 ≥0.10、直線 R² ≥0.9、迄壓 ≥0.7（排除人工排氣）。"""
    out = []
    for s, e in descents(h, p):
        t = h[s:e + 1] - h[s]
        y = p[s:e + 1]
        dur, drop = float(t[-1]), float(y[0] - y[-1])
        sl, r2 = lin_r2(t, y)
        ok = dur >= 4.0 and drop >= 0.10 and r2 >= 0.9 and y[-1] >= 0.7
        out.append(dict(s=s, e=e, dur=dur, drop=drop, r2=r2, ok=ok,
                        t0=ts[s], t1=ts[e], p0=float(y[0]), p1=float(y[-1])))
    return out


GUARD = 2      # 安靜期頭尾各留幾分鐘不算 r_off：回升可能多延續一分鐘、
               # 泵啟動時刻可能提早一分鐘（tau1 實測第 49/50 分都有）


def label_minutes(ts, h, p, s, e, on, gap):
    """把段內每個相鄰一分鐘的壓降標成 spike / on / rebound / edge / off。

    回傳 list of (minute_of_hour, clock_hour_key, drop, p_mid, label, 安靜期位置)。
    """
    rows = []
    for j in range(s + 1, e + 1):
        dtr = h[j] - h[j - 1]
        if not (0.008 < dtr < 0.03) or p[j] - p[j - 1] > REFILL_RISE:
            continue
        m = ts[j].minute
        k = (m - on) % 60
        if k == 0:
            lab = 'spike'
        elif k < gap:
            lab = 'on'
        elif k == gap:
            lab = 'rebound'
        elif k <= gap + GUARD or k >= 60 - GUARD:
            lab = 'edge'
        else:
            lab = 'off'
        rows.append((m, ts[j].strftime('%m-%d %H'), p[j - 1] - p[j],
                     0.5 * (p[j - 1] + p[j]), lab, k - gap - 1))
    return rows


def ols(x, y):
    """y = a + b x；回傳 a, b, se_b。"""
    x, y = np.asarray(x, float), np.asarray(y, float)
    n = len(x)
    if n < 3:
        return float('nan'), float('nan'), float('nan')
    X = np.vstack([np.ones(n), x]).T
    c, *_ = np.linalg.lstsq(X, y, rcond=None)
    r = y - X @ c
    s2 = float(r @ r) / (n - 2)
    cov = s2 * np.linalg.inv(X.T @ X)
    return float(c[0]), float(c[1]), float(np.sqrt(cov[1, 1]))


def perm_slope_p(x, y, n_iter=4000, seed=0):
    x, y = np.asarray(x, float), np.asarray(y, float)
    _, b, _ = ols(x, y)
    rng = np.random.default_rng(seed)
    hit = 0
    for _ in range(n_iter):
        _, bb, _ = ols(x, rng.permutation(y))
        if abs(bb) >= abs(b):
            hit += 1
    return hit / n_iter


def cluster_boot(hours, fn, n_iter=2000, seed=0):
    """以循環為叢集做 bootstrap；fn(list_of_hours) -> 純量或 tuple。"""
    by_cyc = {}
    for hr in hours:
        by_cyc.setdefault(hr['cyc'], []).append(hr)
    keys = list(by_cyc)
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n_iter):
        pick = rng.choice(len(keys), len(keys), replace=True)
        sample = [x for i in pick for x in by_cyc[keys[i]]]
        try:
            vals.append(fn(sample))
        except Exception:
            continue
    return np.array(vals, float)


def two_mode_solution(hours):
    """泵開／泵停各一條「速率 vs 壓力」直線，若 r_b 與 P_eq 兩模式共享則：
         α_on  = r_b − β_on  P_eq
         α_off = r_b − β_off P_eq
       ⇒ P_eq = (α_off − α_on)/(β_on − β_off)，r_b = α_off + β_off P_eq。
    """
    P = [x['P'] for x in hours]
    a_on, b_on, _ = ols(P, [x['r_on'] for x in hours])
    a_off, b_off, _ = ols(P, [x['r_off'] for x in hours])
    peq = (a_off - a_on) / (b_on - b_off)
    rb = a_off + b_off * peq
    return rb, peq


def analyse_batch(ts, h, p, nm, tau, d0, d1):
    """一批的完整拆分。回傳 dict；main() 印表、fig_pump_mode_split.py 畫圖都用它。"""
    ix = np.flatnonzero(np.array([d0 <= t.date() <= d1 for t in ts]))
    t2 = [ts[i] for i in ix]
    h2, p2 = h[ix] - h[ix[0]], p[ix]

    mu, se, n = minute_profile(ts, h, p, d0, d1)
    on, off, gap = pump_window(mu)
    cycs = regular_cycles(t2, h2, p2)
    reg = [c for c in cycs if c['ok']]

    per_cyc, onset_minutes, hours_all, quiet_all, rows_by_cyc = [], [], [], [], {}
    for ci, c in enumerate(reg):
        # 該循環自己的驟降尖峰在第幾分：若與批次剖面差 ≤1 分就用它自己的
        #（tau1 有循環在第 49 分啟動而非第 50 分，用批次值會把驟降漏進安靜期）
        fold = np.zeros(60)
        cnt = np.zeros(60)
        for j in range(c['s'] + 1, c['e'] + 1):
            if 0.008 < h2[j] - h2[j - 1] < 0.03 and p2[j] - p2[j - 1] <= REFILL_RISE:
                fold[t2[j].minute] += p2[j - 1] - p2[j]
                cnt[t2[j].minute] += 1
        if not cnt.any():
            continue
        with np.errstate(invalid='ignore'):
            on_c = int(np.nanargmax(np.where(cnt > 0, fold / cnt, np.nan)))
        onset_minutes.append(on_c)
        if min((on_c - on) % 60, (on - on_c) % 60) > 1:
            on_c = on
        rows = label_minutes(t2, h2, p2, c['s'], c['e'], on_c, gap)
        if not rows:
            continue
        rows_by_cyc[ci + 1] = (on_c, rows)

        tot = {k: 0.0 for k in ('spike', 'on', 'rebound', 'edge', 'off')}
        cntl = {k: 0 for k in tot}
        for _, _, d, _, lab, _ in rows:
            tot[lab] += d
            cntl[lab] += 1
        drop_all = sum(tot.values())
        n_on = cntl['spike'] + cntl['on']
        r_on = (tot['spike'] + tot['on']) / (n_on / 60.0) if n_on else float('nan')
        r_off = tot['off'] / (cntl['off'] / 60.0) if cntl['off'] else float('nan')
        n_quiet = cntl['off'] + cntl['rebound'] + cntl['edge']
        r_off_net = (tot['off'] + tot['rebound'] + tot['edge']) / (n_quiet / 60.0)
        per_cyc.append(dict(
            i=ci + 1, dur=c['dur'], drop=c['drop'], p0=c['p0'], p1=c['p1'],
            share_on=(tot['spike'] + tot['on']) / drop_all if drop_all else float('nan'),
            r_on=r_on, r_off=r_off, r_off_net=r_off_net,
            spike=tot['spike'] / cntl['spike'] if cntl['spike'] else float('nan'),
            rebound=tot['rebound'] / cntl['rebound'] if cntl['rebound'] else float('nan'),
            n_events=cntl['spike'], tot=tot, cntl=cntl))

        # ── 每整點小時：供「速率 vs 壓力」迴歸 ───────────────────
        by_hour = {}
        for m, hk, d, pm, lab, kq in rows:
            by_hour.setdefault(hk, []).append((m, d, pm, lab))
            if lab in ('off', 'edge'):
                quiet_all.append((kq, d, ci + 1, lab))
        for hk, v in by_hour.items():
            if len(v) < 55:                       # 只用完整覆蓋的小時
                continue
            labs = [x[3] for x in v]
            if 'spike' not in labs or 'rebound' not in labs:
                continue
            d_on = sum(x[1] for x in v if x[3] in ('spike', 'on'))
            n_on_h = sum(1 for x in v if x[3] in ('spike', 'on'))
            d_off = sum(x[1] for x in v if x[3] == 'off')
            n_off_h = sum(1 for x in v if x[3] == 'off')
            hours_all.append(dict(
                batch=nm, cyc=ci + 1, hour=hk,
                P=float(np.mean([x[2] for x in v])),
                r_on=d_on / (n_on_h / 60.0),
                r_off=d_off / (n_off_h / 60.0),
                spike=[x[1] for x in v if x[3] == 'spike'][0],
                rebound=[x[1] for x in v if x[3] == 'rebound'][0],
                d_total=sum(x[1] for x in v)))

    return dict(nm=nm, tau=tau, t2=t2, h2=h2, p2=p2, mu=mu, on=on, off=off, gap=gap,
                cycs=cycs, reg=reg, per_cyc=per_cyc, onset_minutes=onset_minutes,
                hours=hours_all, quiet=quiet_all, rows_by_cyc=rows_by_cyc)


def main():
    ts, h, p = load()
    print('讀入 %d 筆　%s ~ %s\n' % (len(ts), ts[0].date(), ts[-1].date()))
    os.makedirs(OUT, exist_ok=True)
    csv_rows = []
    summary = {}

    for nm, tau, d0, d1 in BATCHES:
        print('═' * 72)
        print('%s（宣稱 τ = %d 分/時）　%s ~ %s' % (nm, tau, d0, d1))
        B = analyse_batch(ts, h, p, nm, tau, d0, d1)
        on, off, gap = B['on'], B['off'], B['gap']
        cycs, reg, per_cyc = B['cycs'], B['reg'], B['per_cyc']
        onset_minutes, hours_all = B['onset_minutes'], B['hours']
        quiet_all = [q for q in B['quiet'] if q[3] == 'off']
        csv_rows += hours_all
        print('   泵窗：第 %d 分驟降 → 第 %d 分回升，運轉 %d 分' % (on, off, gap))
        print('   下降段 %d，規律循環 %d（其餘：%s）'
              % (len(cycs), len(reg),
                 '、'.join('%.1fhr/降%.2f/R²%.2f' % (c['dur'], c['drop'], c['r2'])
                           for c in cycs if not c['ok']) or '無'))

        if not per_cyc:
            print('   （沒有可用循環）')
            continue

        print('\n   ── 每循環（速率單位 kg/cm²/hr；r_off 只算安靜分鐘，不含回升分鐘）──')
        print('   %3s %6s %6s %6s  %6s %7s %7s %8s %8s %8s'
              % ('#', '時長', '起壓', '迄壓', '泵開佔', 'r_on', 'r_off', 'r_off淨',
                 '驟降/次', '回升/次'))
        for c in per_cyc:
            print('   %3d %6.1f %6.2f %6.2f  %5.0f%% %7.4f %7.4f %8.4f %+8.4f %+8.4f'
                  % (c['i'], c['dur'], c['p0'], c['p1'], c['share_on'] * 100,
                     c['r_on'], c['r_off'], c['r_off_net'], c['spike'], c['rebound']))

        med = lambda k: float(np.median([c[k] for c in per_cyc]))
        q = lambda k, qq: float(np.percentile([c[k] for c in per_cyc], qq))
        print('\n   中位　泵開佔 %.0f%%　r_on %.4f　r_off %.4f [%.4f, %.4f]　r_off淨 %.4f'
              % (med('share_on') * 100, med('r_on'), med('r_off'),
                 q('r_off', 25), q('r_off', 75), med('r_off_net')))
        print('   各循環自己的驟降尖峰分鐘：%s（批次剖面為第 %d 分）'
              % (sorted(set(onset_minutes)), on))
        lo, hi = RB_PAPER[1], RB_PAPER[2]
        pos = ('落在論文區間內' if lo <= med('r_off') <= hi
               else ('低於論文區間' if med('r_off') < lo else '高於論文區間'))
        print('   對照論文 r_b = %.4f [%.4f, %.4f]：r_off 中位 %.4f → %s'
              % (RB_PAPER[0], lo, hi, med('r_off'), pos))

        # ── Q2：r_off 隨壓力變嗎（每小時，叢集＝循環）──────────────────
        if len(hours_all) >= 6:
            P = [x['P'] for x in hours_all]
            print('\n   ── Q2　速率 vs 壓力（%d 個完整小時，%d 個循環）──'
                  % (len(hours_all), len(set(x['cyc'] for x in hours_all))))
            for key, name in (('r_off', '泵停 r_off'), ('r_on', '泵開 r_on'),
                              ('spike', '驟降尖峰'), ('rebound', '回升')):
                y = [x[key] for x in hours_all]
                a, b, seb = ols(P, y)
                pv = perm_slope_p(P, y)
                span = (max(P) - min(P)) * b
                print('   %-10s 截距 %+.4f　斜率 %+.4f /kg·cm⁻²（跨本批壓力範圍變動 %+.4f）'
                      '　p = %.3f%s'
                      % (name, a, b, span, pv,
                         '  ← 隨壓力變' if pv < 0.05 else '  ← 平坦'))
            # 相對變化：壓力從最高到最低，r_off 變了幾成
            a, b, _ = ols(P, [x['r_off'] for x in hours_all])
            hiP, loP = max(P), min(P)
            if a + b * hiP:
                print('   r_off 在 P=%.2f 為 %.4f，在 P=%.2f 為 %.4f（相對變化 %+.0f%%）'
                      % (hiP, a + b * hiP, loP, a + b * loP,
                         ((a + b * loP) / (a + b * hiP) - 1) * 100))

            # ── 兩模式共享 r_b、P_eq 的解（探索性）──────────────────
            rb, peq = two_mode_solution(hours_all)
            bs = cluster_boot(hours_all, two_mode_solution)
            bs = bs[np.isfinite(bs).all(axis=1)]
            print('\n   ── 兩模式聯立解（探索性；假設 r_b 在兩模式相同，見檔頭前提）──')
            print('   r_b = %+.4f　P_eq = %.3f' % (rb, peq))
            if len(bs):
                print('   叢集 bootstrap 95%%：r_b [%+.4f, %+.4f]　P_eq [%.2f, %.2f]'
                      % (np.percentile(bs[:, 0], 2.5), np.percentile(bs[:, 0], 97.5),
                         np.percentile(bs[:, 1], 2.5), np.percentile(bs[:, 1], 97.5)))
            # ── Q3：回升配對驟降 ─────────────────────────────────────
            sp = np.array([x['spike'] for x in hours_all])
            rb_ = np.array([x['rebound'] for x in hours_all])
            print('\n   ── Q3　回升 vs 驟降（假象檢查）──')
            print('   驟降/次 %.4f ± %.4f　回升/次 %+.4f ± %.4f　|回升|/驟降 = %.2f'
                  % (sp.mean(), sp.std(ddof=1), rb_.mean(), rb_.std(ddof=1),
                     -rb_.mean() / sp.mean() if sp.mean() else float('nan')))
            r = np.corrcoef(sp, rb_)[0, 1]
            print('   逐小時 驟降 vs 回升 相關 %+.2f（假象若成立應為強負相關且回升不隨 P 變）' % r)

        # ── Q4：安靜期內是加速還是減速 ────────────────────────────
        #   生物欠的缺口在安靜期線性累積、由小 kLa_off 漏出 → 速率隨時間「加速」
        #   泵停後殘餘溶解／回升假象消退 → 速率隨時間「減速」
        if quiet_all:
            kq = np.array([x[0] for x in quiet_all], float)
            dq = np.array([x[1] for x in quiet_all], float)
            nq = int(kq.max()) + 1
            thirds = [(0, nq // 3), (nq // 3, 2 * nq // 3), (2 * nq // 3, nq)]
            print('\n   ── Q4　安靜期內的速率剖面（%d 分鐘安靜期，%d 筆逐分鐘壓降）──'
                  % (nq, len(kq)))
            for lo_, hi_ in thirds:
                sel = (kq >= lo_) & (kq < hi_)
                print('   第 %2d–%2d 分：%+.5f ± %.5f /min（×60 = %+.4f /hr）'
                      % (lo_ + 1, hi_, dq[sel].mean(), dq[sel].std(ddof=1) / np.sqrt(sel.sum()),
                         dq[sel].mean() * 60))
            a, b, seb = ols(kq, dq)
            pv = perm_slope_p(kq, dq, n_iter=2000)
            print('   逐分鐘壓降 vs 安靜期位置：斜率 %+.2e /min²　p = %.3f → %s'
                  % (b, pv, ('加速（像缺口漏出）' if b > 0 else '減速（像殘餘溶解／消退）')
                     if pv < 0.05 else '看不出趨勢'))
            summary_q4 = (b, pv)
        else:
            summary_q4 = (float('nan'), float('nan'))

        summary[nm] = dict(tau=tau, n=len(per_cyc), share=med('share_on'),
                           r_on=med('r_on'), r_off=med('r_off'),
                           r_off_net=med('r_off_net'),
                           # 包絡速率＝每循環速率的中位（與日報表 F 同義）。
                           # 不可用「中位降幅÷中位時長」，那是比值的比，差 2~4%。
                           env=float(np.median([c['drop'] / c['dur'] for c in per_cyc])))
        print()

    # ── 跨批總表 ──────────────────────────────────────────────────
    print('═' * 72)
    print('跨批總表（中位；速率 kg/cm²/hr）')
    print('%-7s %4s %4s %7s %8s %8s %9s %10s'
          % ('批次', 'τ', '循環', '泵開佔', '包絡速率', 'r_on', 'r_off', 'r_off/r_b'))
    for nm, s in summary.items():
        print('%-7s %4d %4d %6.0f%% %8.4f %8.4f %9.4f %10.2f'
              % (nm, s['tau'], s['n'], s['share'] * 100, s['env'], s['r_on'],
                 s['r_off'], s['r_off'] / RB_PAPER[0]))
    print('論文 r_b = %.4f [%.4f, %.4f]；尾段斜率 0.0177；化學計量反推 0.016~0.029'
          % RB_PAPER)

    # ── Q2 合併：批內去均值後 r_off vs P（三批 175 小時一起）──
    if csv_rows:
        Pd, Yd = [], []
        for nm in summary:
            rows_b = [r for r in csv_rows if r['batch'] == nm]
            mP = np.mean([r['P'] for r in rows_b])
            mY = np.mean([r['r_off'] for r in rows_b])
            Pd += [r['P'] - mP for r in rows_b]
            Yd += [r['r_off'] - mY for r in rows_b]
        a, b, seb = ols(Pd, Yd)
        pv = perm_slope_p(Pd, Yd)
        print('\nQ2 合併（批內去均值，%d 小時）：r_off 對 P 斜率 %+.4f ± %.4f /kg·cm⁻²　p = %.3f'
              % (len(Pd), b, seb, pv))
        print('   壓力掉 0.25（一個循環）對應 r_off 變 %+.4f，佔 r_b 的 %+.0f%%'
              % (-0.25 * b, -0.25 * b / RB_PAPER[0] * 100))

    path = os.path.join(OUT, 'pump_mode_split_hours.csv')
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(csv_rows[0].keys()))
        w.writeheader()
        w.writerows(csv_rows)
    print('\n每小時明細 -> %s（%d 列）' % (os.path.relpath(path, REPO), len(csv_rows)))


if __name__ == '__main__':
    main()
