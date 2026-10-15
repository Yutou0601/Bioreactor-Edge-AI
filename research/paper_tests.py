# -*- coding: utf-8 -*-
"""論文 Algorithm 2／3 的可重跑版本（Jetson 背景工作與介面「論文檢定」分頁用）。
════════════════════════════════════════════════════════════════════════

**預設設定逐位元重現論文**：資料、亂數種子、呼叫順序全部照原腳本——
  Algorithm 2 ＝ degeneracy_matched.main() 的 B0／B1／B2（NREP=25，種子 112358）
  Algorithm 3 ＝ figures/fig_results_new.fig_null()（DRAWS=41）
重現與否由 --verify 對照原腳本的函式直接檢查，不靠看起來差不多。

⚠ 以「程式」為準，不是論文正文。2026-10-15 對照發現兩處論文與程式不符：
  1. Algorithm 3 正文寫 60 次抽樣，程式是 DRAWS = 41；報告的 p = 0.024 = 1/42
     是 41 次的結果，所以是**正文寫錯**。
  2. Algorithm 2 虛擬碼對模擬資料呼叫「Algorithm 1」（含曲率篩選），程式直接
     fit_LE、**不篩**；Algorithm 3 的程式反而有篩。
⚠ 亂數：fig_results_new 宣告了 RNG(20260824) 但**沒用到**——它的 AR(1) 是從
  degeneracy_matched 匯入的 ar1，用那邊的 RNG(112358)，而且是匯入後的全新狀態。
  這裡照實際行為做，兩個演算法各自從一個全新的 default_rng(112358) 開始。

兩個可切換的修正（預設都關，關的時候＝論文）：
  --exact-time     每段時間軸以該段起點整數秒重算。論文時間軸是「資料夾第一筆
                   起算的小時數」相減，帶 1e-14 誤差，正好第 180 秒的那一筆
                   可能被 SKIP_MIN 的 >= 掐掉（見 edge_backend/core/cycle_store.py）
  --drop-k-edge    排除 k̂ 落在網格端點（0.01／2.99）的段：殘差在網格內沒有
                   內部極小，資料約束不了 k，r̂_b 吸收了物理項

資料來源：
  --dataset paper  論文的資料集 C（Testing_data，去重後 207 段左右）
  --dataset stream Jetson 資料庫裡串流切出的循環（--db、--station）

用法：
  python paper_tests.py --algo both --json out.json
  python paper_tests.py --verify                 # 確認預設設定與原腳本逐位元相同
  python paper_tests.py --run-id 3 --db reactor.db   # 背景工作：結果寫回資料庫
"""
import argparse
import json
import os
import sqlite3
import sys
import time
import traceback
from datetime import datetime

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ⚠ simulator_check 在**被匯入的當下**就把 sys.argv[1] 讀成 TRIM_MIN（float）。
#   本檔帶命令列參數（--verify 等）執行時會當場 ValueError；就算是數字也會被
#   誤當成裁切分鐘數。原腳本平常不帶參數跑，TRIM_MIN=0，所以匯入時把 argv 藏起來。
_argv, sys.argv = sys.argv, sys.argv[:1]
try:
    from simulator_check import fit_LE, QUANT, KGRID              # noqa: E402
    from rb_recovery_study import curvature                       # noqa: E402
finally:
    sys.argv = _argv

CURV_MIN = 0.45
SEED = 112358

# 論文定稿（2026-08-24 去重版）之後才放進 Testing_data 的資料夾。
# ⚠ 2026-10-15 實測：不排除這三批，資料集 C 篩選後是 209 段而不是論文的 207 段——
#   多出的 2 段全部來自 0825-0831（另兩批循環過密，被洗管線日規則整天剔除）。
#   這三批是 2026-09-11 才歸檔進來的自動化測試，而且 0825-0831 檔名載明「氫氣不夠、
#   暫停進氣」，與論文的 4:1 連續進氣條件不同——依 dataset_c 的規矩（事前可查證的
#   條件差異）本來就不該混入。所以「論文原樣」＝排除這三批。
POST_PAPER = {
    '0813_補氣0.15kg_自動化測試',
    '0817_補氣0.2kg_自動化測試',
    '0825-0831_氫氣不夠暫停進氣__自動化測試',
}
K_LO, K_HI = float(KGRID[0]), float(KGRID[-1])


# ── 與原腳本相同的小工具（帶明確的 rng，不靠模組全域狀態） ─────────────
def sp(a, b):
    """Spearman ρ（與 degeneracy_matched.sp 相同）。"""
    ra = np.argsort(np.argsort(np.asarray(a, float))).astype(float)
    rb_ = np.argsort(np.argsort(np.asarray(b, float))).astype(float)
    return float(np.corrcoef(ra, rb_)[0, 1])


def ar1(rng, n, sd, phi):
    """與 degeneracy_matched.ar1 相同的抽法與順序（先整條創新項，再 z[0]）。"""
    e = rng.normal(0, sd*np.sqrt(max(1-phi**2, 1e-6)), n)
    z = np.empty(n); z[0] = rng.normal(0, sd)
    for i in range(1, n):
        z[i] = phi*z[i-1]+e[i]
    return z


def fit_phys(t, y):
    """r_b ≡ 0 的兩參數擬合（與 fig_results_new.fit_phys 相同；用 KGRID，與它一致）。"""
    best = None
    for k in KGRID:
        A = np.vstack([np.exp(-k * t), np.ones_like(t)]).T
        c, *_ = np.linalg.lstsq(A, y, rcond=None)
        r = y - A @ c
        s = float(r @ r)
        if best is None or s < best[0]:
            best = (s, c, k, r)
    s, c, k, r = best
    return dict(amp=c[0], peq=c[1], k=k, resid=r,
                sd=np.sqrt(s / max(len(t) - 3, 1)))


def k_at_edge(k):
    return k <= K_LO + 1e-9 or k >= K_HI - 1e-9


# ── 資料 ───────────────────────────────────────────────────────────────
def collect_paper(exact_time=False, snapshot=True):
    """資料集 C。snapshot=False、exact_time=False 時與 dataset_c.collect_c() 逐位元相同
    （--verify 檢查）；snapshot=True 另外排除論文之後才加入的資料夾（POST_PAPER）。

    結構照抄 residual_structure.collect()＋dataset_c 的排除與去重，唯一差別是
    exact_time 時每段的 t 改由時間戳對段起點重算。
    """
    import glob
    from regime_changepoints import TD
    from multivariate_increments import load4
    from clean_and_form import seg_clean, SKIP_MIN
    from dataset_c import EXCLUDE, _fingerprint

    folders = []
    for d in sorted(os.listdir(TD)):
        p = os.path.join(TD, d)
        if not os.path.isdir(p):
            continue
        if glob.glob(os.path.join(p, '*.csv')):
            folders.append((p, d))
        for s in sorted(os.listdir(p)):
            spth = os.path.join(p, s)
            if os.path.isdir(spth) and glob.glob(os.path.join(spth, '*.csv')):
                folders.append((spth, f'{d}/{s}'))
    allc = []
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
            if exact_time:
                t = np.array([(ts[i]-ts[a]).total_seconds()/3600 for i in range(a, b+1)])
            else:
                t = h[a:b+1]-h[a]
            sel = t >= SKIP_MIN
            if sel.sum() < 20:
                continue
            allc.append((tag, t[sel]-t[sel][0], P[a:b+1][sel]))
    kept = [(t, x, y) for t, x, y in allc if t not in EXCLUDE
            and not (snapshot and t.split('/')[0] in POST_PAPER)]
    out, seen = [], set()
    for tag, x, y in kept:
        f = _fingerprint(y)
        if f in seen:
            continue
        seen.add(f)
        out.append((tag, x, y))
    return out


def collect_stream(db, station):
    """Jetson 資料庫裡串流切出的循環 → (tag, t, y)，前處理與論文相同（掐 3 分鐘）。

    時間軸一律以段起點整數秒計（串流本來就是 exact_time，見 cycle_sync）。
    """
    from clean_and_form import SKIP_MIN
    con = sqlite3.connect(db)
    try:
        cyc = con.execute('SELECT ts_start, ts_end FROM cycle WHERE source = ? ORDER BY ts_start',
                          ('stream:%s' % station,)).fetchall()
        out = []
        for a, b in cyc:
            rows = con.execute('SELECT ts, pressure FROM raw_sample WHERE station = ? AND ts >= ?'
                               ' AND ts <= ? ORDER BY ts', (station, a, b)).fetchall()
            if len(rows) < 20:
                continue
            t0 = datetime.fromisoformat(rows[0][0])
            t = np.array([(datetime.fromisoformat(r[0]) - t0).total_seconds()/3600 for r in rows])
            y = np.array([float(r[1]) for r in rows])
            sel = t >= SKIP_MIN
            if sel.sum() < 20:
                continue
            out.append(('stream:%s %s' % (station, a), t[sel]-t[sel][0], y[sel]))
        return out
    finally:
        con.close()


def retained(cycles, drop_k_edge=False):
    """通過曲率預篩的循環與各自的 LE 擬合（＝ fig_results_new.retained）。"""
    rows, n_edge = [], 0
    for tag, t, y in cycles:
        cv = curvature(t, y)
        if not np.isfinite(cv) or cv < CURV_MIN:
            continue
        f = fit_LE(t, y)
        if k_at_edge(f['k']):
            n_edge += 1
            if drop_k_edge:
                continue
        rows.append((tag, t, y, f))
    return rows, n_edge


# ── Algorithm 2：配對基準（＝ degeneracy_matched.main 的計算部分） ────────
def algorithm2(rows, nrep=25, progress=None):
    rng = np.random.default_rng(SEED)
    fits = []
    for tag, t, y, f in rows:
        r = f['resid']
        phi = float(np.corrcoef(r[:-1], r[1:])[0, 1]) if r.std() > 0 else 0.
        fits.append(dict(t=t, k=f['k'], amp=f['amp'], peq=f['peq'], rb=f['rb'],
                         sd=max(f['sd'], QUANT/4), phi=float(np.clip(phi*1.3, 0, 0.98))))
    rb_obs = np.array([f['rb'] for f in fits])
    k_obs = np.array([f['k'] for f in fits])
    rho_obs = sp(rb_obs, k_obs)
    R0 = float(np.median(rb_obs))
    A = np.vstack([np.log(k_obs), np.ones_like(k_obs)]).T
    slope, icpt = np.linalg.lstsq(A, rb_obs, rcond=None)[0]
    sd_rb = float(np.std(rb_obs, ddof=1))

    out = {}
    total, done = 3 * nrep, 0
    for mode in ('B0', 'B1', 'B2'):
        rhos, meds = [], []
        for _ in range(nrep):
            rr, kk = [], []
            for f in fits:
                if mode == 'B0':
                    rb_true = R0
                elif mode == 'B1':
                    rb_true = R0 + rng.normal(0, sd_rb)
                else:
                    rb_true = icpt + slope*np.log(f['k'])
                t = f['t']
                yy = f['peq'] + f['amp']*np.exp(-f['k']*t) - rb_true*t + ar1(rng, len(t), f['sd'], f['phi'])
                g = fit_LE(t, np.round(yy/QUANT)*QUANT)
                rr.append(g['rb']); kk.append(g['k'])
            rhos.append(sp(rr, kk)); meds.append(float(np.median(rr)))
            done += 1
            if progress:
                progress('Algorithm 2 %s' % mode, done / total)
        rhos, meds = np.array(rhos), np.array(meds)
        truth = R0 if mode != 'B2' else float(np.median(icpt + slope*np.log(k_obs)))
        out[mode] = {'rho_mean': float(rhos.mean()), 'rho_sd': float(rhos.std(ddof=1)),
                     'rho_draws': rhos.tolist(), 'median_mean': float(meds.mean()),
                     'truth_median': truth, 'bias_pct': float((meds.mean()/truth - 1) * 100)}
    return {'n': len(fits), 'rho_observed': rho_obs, 'rb_median_observed': R0,
            'slope_log_k': float(slope), 'baselines': out, 'nrep': nrep}


# ── Algorithm 3：純物理虛無（＝ fig_results_new.fig_null 的計算部分） ─────
def algorithm3(rows, draws=41, progress=None):
    rng = np.random.default_rng(SEED)
    observed = float(np.median([f['rb'] for *_, f in rows]))
    phys = []
    for _tag, t, y, _f in rows:
        g = fit_phys(t, y)
        r = g['resid']
        phi = float(np.corrcoef(r[:-1], r[1:])[0, 1]) if r.std() > 0 else 0.
        phys.append((t, g, max(g['sd'], QUANT / 4), float(np.clip(phi * 1.3, 0, .98))))
    meds, n_kept = [], []
    for d in range(draws):
        got = []
        for t, g, sd, phi in phys:
            z = g['peq'] + g['amp'] * np.exp(-g['k'] * t) + ar1(rng, len(t), sd, phi)
            w = np.round(z / QUANT) * QUANT
            if curvature(t, w) < CURV_MIN:
                continue
            got.append(fit_LE(t, w)['rb'])
        if got:
            meds.append(float(np.median(got)))
            n_kept.append(len(got))
        if progress:
            progress('Algorithm 3', (d + 1) / draws)
    meds = np.array(meds)
    p = (1 + int((meds >= observed).sum())) / (1 + len(meds))
    return {'n': len(rows), 'observed_median': observed, 'draws': draws,
            'null_median': float(np.median(meds)), 'null_mean': float(meds.mean()),
            'null_sd': float(meds.std(ddof=1)) if len(meds) > 1 else None,
            'null_max': float(meds.max()), 'p_value': p, 'null_draws': meds.tolist(),
            'cycles_passing_screen_per_draw': n_kept}


def run(dataset='paper', algo='both', exact_time=False, drop_k_edge=False,
        nrep=25, draws=41, db=None, station='BTP-1', progress=None):
    t0 = time.time()
    if dataset in ('paper', 'paper_all'):
        # paper＝論文定稿時的資料快照；paper_all＝目前 Testing_data 的全部（含之後加入的）
        cycles = collect_paper(exact_time=exact_time, snapshot=(dataset == 'paper'))
    else:
        cycles = collect_stream(db, station)
    rows, n_edge = retained(cycles, drop_k_edge=drop_k_edge)
    res = {'params': dict(dataset=dataset, algo=algo, exact_time=exact_time,
                          drop_k_edge=drop_k_edge, nrep=nrep, draws=draws, station=station),
           'n_cycles_total': len(cycles), 'n_retained': len(rows), 'n_k_edge': n_edge,
           'rb_median': float(np.median([f['rb'] for *_, f in rows])) if rows else None,
           'frac_negative': float(np.mean([f['rb'] < 0 for *_, f in rows])) if rows else None}
    if len(rows) < 10:
        res['error'] = '通過篩選的循環只有 %d 段，不足以做檢定（至少 10 段）' % len(rows)
        return res
    if algo in ('2', 'both'):
        res['algorithm2'] = algorithm2(rows, nrep=nrep, progress=progress)
    if algo in ('3', 'both'):
        res['algorithm3'] = algorithm3(rows, draws=draws, progress=progress)
    res['seconds'] = round(time.time() - t0, 1)
    return res


# ── 對照原腳本：預設設定必須逐位元相同 ─────────────────────────────────
def verify():
    from dataset_c import collect_c
    import degeneracy_matched as dm
    ok = True
    a, b = collect_c(), collect_paper(exact_time=False, snapshot=False)
    same = len(a) == len(b) and all(x[0] == y[0] and np.array_equal(x[1], y[1]) and np.array_equal(x[2], y[2])
                                    for x, y in zip(a, b))
    print('資料集 C 與 collect_c() 逐位元相同：%s（%d 段）' % (same, len(a)))
    ok &= same
    # 亂數：本檔的 ar1(rng) 與原腳本的 ar1（模組全域 RNG）在同一種子下序列相同
    dm.RNG = np.random.default_rng(SEED)
    r1 = [dm.ar1(50, 0.01, 0.4) for _ in range(3)]
    rng = np.random.default_rng(SEED)
    r2 = [ar1(rng, 50, 0.01, 0.4) for _ in range(3)]
    s2 = all(np.array_equal(x, y) for x, y in zip(r1, r2))
    print('AR(1) 抽樣序列與 degeneracy_matched.ar1 相同：%s' % s2)
    ok &= s2
    print('結論：%s' % ('✓ 預設設定＝論文' if ok else '✘ 有不一致，不可宣稱重現論文'))
    return ok


def _db_job(run_id, db):
    """背景工作：讀參數、跑、把進度與結果寫回 paper_test_run 那一列。"""
    con = sqlite3.connect(db, timeout=30)

    def upd(**kw):
        cols = ', '.join('%s = ?' % k for k in kw)
        con.execute('UPDATE paper_test_run SET %s WHERE id = ?' % cols, (*kw.values(), run_id))
        con.commit()

    last = [0.0]

    def progress(stage, frac):
        now = time.time()
        if now - last[0] > 2 or frac >= 1:
            last[0] = now
            upd(stage=stage, progress=round(frac, 3))

    try:
        params = json.loads(con.execute('SELECT params FROM paper_test_run WHERE id = ?',
                                        (run_id,)).fetchone()[0])
        upd(status='running', started=datetime.now().isoformat(sep=' ', timespec='seconds'), pid=os.getpid())
        res = run(db=db, progress=progress, **params)
        upd(status='error' if res.get('error') else 'done', result=json.dumps(res),
            finished=datetime.now().isoformat(sep=' ', timespec='seconds'), progress=1.0,
            stage='完成' if not res.get('error') else res['error'])
    except Exception as e:                                  # noqa: BLE001
        upd(status='error', stage='%s: %s' % (type(e).__name__, e), log=traceback.format_exc()[-4000:],
            finished=datetime.now().isoformat(sep=' ', timespec='seconds'))
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser(description='論文 Algorithm 2／3')
    ap.add_argument('--dataset', default='paper', choices=['paper', 'paper_all', 'stream'])
    ap.add_argument('--algo', default='both', choices=['2', '3', 'both'])
    ap.add_argument('--exact-time', action='store_true')
    ap.add_argument('--drop-k-edge', action='store_true')
    ap.add_argument('--nrep', type=int, default=25)
    ap.add_argument('--draws', type=int, default=41)
    ap.add_argument('--db'); ap.add_argument('--station', default='BTP-1')
    ap.add_argument('--json'); ap.add_argument('--verify', action='store_true')
    ap.add_argument('--run-id', type=int)
    a = ap.parse_args()
    if a.verify:
        return 0 if verify() else 1
    if a.run_id is not None:
        _db_job(a.run_id, a.db)
        return 0
    res = run(a.dataset, a.algo, a.exact_time, a.drop_k_edge, a.nrep, a.draws, a.db, a.station,
              progress=lambda s, f: print('\r  %s %3.0f%%' % (s, f * 100), end='', flush=True))
    print()
    brief = {k: v for k, v in res.items() if k not in ('algorithm2', 'algorithm3')}
    print(json.dumps(brief, ensure_ascii=False))
    if 'algorithm2' in res:
        a2 = res['algorithm2']
        print('Algorithm 2：n=%d  實測 ρ=%.3f  中位 %.5f' % (a2['n'], a2['rho_observed'], a2['rb_median_observed']))
        for m, v in a2['baselines'].items():
            print('   %s  ρ %.3f ± %.3f   回收中位 %.5f（偏誤 %+.1f%%）'
                  % (m, v['rho_mean'], v['rho_sd'], v['median_mean'], v['bias_pct']))
    if 'algorithm3' in res:
        a3 = res['algorithm3']
        print('Algorithm 3：n=%d  實測中位 %.5f  虛無中位 %.5f ± %.5f（最大 %.5f）  p = %.3f'
              % (a3['n'], a3['observed_median'], a3['null_median'], a3['null_sd'] or 0, a3['null_max'], a3['p_value']))
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as fh:
            json.dump(res, fh, ensure_ascii=False)
    return 0


if __name__ == '__main__':
    sys.exit(main())
