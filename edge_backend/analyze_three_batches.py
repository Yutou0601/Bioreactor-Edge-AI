# -*- coding: utf-8 -*-
"""1/5/10min 三批次循環時間槓桿分析（2026-07-22 → 2026-08-03）。

對應簡報 P9/P10 的解方：kLa 隨循環時間 tau 改變、rb 不隨 tau 改變，
故以 Peq'(tau) 對 1/kLa(tau) 作圖，截距 = Peq（物理飽和壓）、斜率 = -rb（生物消耗率）。

沿用 2026-07-27 修正後的資料規則：
  * 壓力欄位對調：記錄標籤「混合槽壓力」才是真正的反應槽壓力
  * 記錄中斷門檻 30 分鐘（5 分鐘過嚴）
  * 下降段量到段內谷底，上升邊歸還下一循環

輸出 → docs/analysis_charts_3batch/
"""
import glob
import os
import re
import sys

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import rcParams
from scipy import optimize, stats

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'Testing_data', '202607至08最新循環研究')
OUT = os.path.abspath(os.path.join(HERE, '..', 'docs', 'analysis_charts_3batch'))
os.makedirs(OUT, exist_ok=True)

# 批次區間取自實驗參數批次表（進氣後基準 → 排氣前）
BATCHES = {
    '1.1 (1min)':  ('2026-07-22 14:48:37', '2026-07-27 09:17:43', 1.0),
    '2.1 (5min)':  ('2026-07-27 09:25:13', '2026-07-30 09:07:00', 5.0),
    '3.1 (10min)': ('2026-07-30 09:13:00', '2026-08-03 09:11:00', 10.0),
}

# 排氣峰值以「現場目測」為基準（實驗參數批次表）；感測器讀值僅供佐證。
# 依 2026-07-27 日報：氣相 CO2/CH4 感測器需透過排氣才讀得到，且捕捉不到真峰值，
# 99.98% 讀數為無效拖尾，故不得作為證據，只用來與目測互相印證。
# p_start/ch4_initial 取自批次表「進氣後基準」欄（CH4 為洗管線後讀值，屬前一批殘留）；
# p_vent 取自「排氣前」欄的反應槽壓力；ch4/co2 為排氣後當下峰值的現場目測。
VENT_VISUAL = {
    '1.1 (1min)':  dict(ch4=31.64, co2=21.0, p_vent=1.085,
                        p_start=1.179, ch4_initial=9.50, co2_initial=20.40),
    '2.1 (5min)':  dict(ch4=34.84, co2=21.3, p_vent=1.014,
                        p_start=1.191, ch4_initial=8.56, co2_initial=20.90),
    '3.1 (10min)': dict(ch4=43.04, co2=20.0, p_vent=0.962,
                        p_start=1.165, ch4_initial=8.41, co2_initial=21.50),
}

GAP_MIN = 30.0      # 記錄中斷門檻（分鐘）
RISE = 0.03         # 補氣上升邊判定（kg/cm²）
MIN_HR = 2.0
DROP_RANGE = (0.15, 0.35)   # 正常循環壓降區間；區間外視為人為介入／排氣

BLUE, RED, AQUA, YELLOW = '#2a78d6', '#e34948', '#1baf7a', '#eda100'
SURFACE, INK, INK2, MUTED = '#fcfcfb', '#0b0b0b', '#52514e', '#898781'
GRID, BASELINE = '#e1e0d9', '#c3c2b7'
BCOL = {'1.1 (1min)': BLUE, '2.1 (5min)': YELLOW, '3.1 (10min)': AQUA}

rcParams.update({
    'font.family': 'Microsoft JhengHei', 'axes.unicode_minus': False,
    'figure.facecolor': SURFACE, 'axes.facecolor': SURFACE,
    'savefig.facecolor': SURFACE, 'text.color': INK,
    'axes.labelcolor': INK2, 'xtick.color': MUTED, 'ytick.color': MUTED,
    'axes.edgecolor': BASELINE, 'grid.color': GRID,
    'font.size': 10, 'axes.titlesize': 11,
    'savefig.dpi': 200, 'savefig.bbox': 'tight',
})


def style(ax, title=None, xlabel=None, ylabel=None):
    if title:
        ax.set_title(title, color=INK, fontweight='bold', loc='left', pad=10)
    if xlabel:
        ax.set_xlabel(xlabel)
    if ylabel:
        ax.set_ylabel(ylabel)
    ax.grid(True, linewidth=0.6, alpha=0.9)
    ax.set_axisbelow(True)
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
    return ax


# ══════════════════════════════════════════════════════════
# 1. 讀檔（標籤文字格式，含壓力欄位對調）
# ══════════════════════════════════════════════════════════
PAT = re.compile(
    r'\[(\d{4})-(\d{2})-(\d{2})-(\d{2}):(\d{2}):(\d{2})\]\s*'
    r'ORP=(-?[\d.]+)mV.*?反應器壓力=(-?[\d.]+)kg.*?酸鹼值=pH\s*(-?[\d.]+).*?'
    r'溫度=(-?[\d.]+).*?混合槽壓力=(-?[\d.]+)kg.*?CO2濃度=(-?[\d.]+)%.*?CH4濃度=(-?[\d.]+)%')


def load_txt(path):
    rows = []
    with open(path, encoding='utf-8-sig') as f:
        for line in f:
            m = PAT.search(line)
            if not m:
                continue
            g = m.groups()
            rows.append((
                pd.Timestamp(f'{g[0]}-{g[1]}-{g[2]} {g[3]}:{g[4]}:{g[5]}'),
                float(g[6]),      # ORP
                float(g[10]),     # 反應槽壓力（記錄標籤誤寫為「混合槽壓力」）
                float(g[7]),      # 混合槽壓力（記錄標籤誤寫為「反應器壓力」）
                float(g[8]), float(g[9]), float(g[11]), float(g[12])))
    return pd.DataFrame(rows, columns=['ts', 'orp', 'p_reactor', 'p_mix',
                                       'ph', 'temp', 'co2', 'ch4'])


def load_all():
    dfs = [load_txt(p) for p in sorted(glob.glob(os.path.join(DATA, '*.txt')))]
    df = pd.concat(dfs, ignore_index=True).sort_values('ts')
    return df.drop_duplicates('ts').reset_index(drop=True)


# ══════════════════════════════════════════════════════════
# 2. 循環偵測
# ══════════════════════════════════════════════════════════
def split_segments(s):
    gap = s.ts.diff().dt.total_seconds() / 60
    brk = np.where(gap.values > GAP_MIN)[0]
    idx = np.concatenate([[0], brk, [len(s)]])
    return [s.iloc[a:b].reset_index(drop=True)
            for a, b in zip(idx[:-1], idx[1:]) if b - a > 10]


def find_cycles(s):
    """回傳 [(cycle_df, pre_refill_row), ...]，下降段終點為谷底。"""
    out = []
    for seg in split_segments(s):
        p = seg.p_reactor.values
        rises = np.where(np.diff(p) > RISE)[0]
        if len(rises) == 0:
            continue
        events, cur = [], [rises[0]]
        for i in rises[1:]:
            if i - cur[-1] <= 20:          # 20 分鐘內視為同一次補氣（容緩升）
                cur.append(i)
            else:
                events.append(cur)
                cur = [i]
        events.append(cur)
        tops = [e[-1] + 1 for e in events]
        starts = [e[0] for e in events]

        for k, top in enumerate(tops):
            end = starts[k + 1] if k + 1 < len(starts) else len(p) - 1
            if end - top < 30:
                continue
            sub = seg.iloc[top:end + 1]
            valley = int(np.argmin(sub.p_reactor.values))
            if valley < 30:
                continue
            cyc = sub.iloc[:valley + 1].reset_index(drop=True)
            hrs = (cyc.ts.iloc[-1] - cyc.ts.iloc[0]).total_seconds() / 3600
            if hrs < MIN_HR:
                continue
            out.append((cyc, seg.iloc[max(0, starts[k] - 1)]))
    return out


# ══════════════════════════════════════════════════════════
# 3. 擬合
# ══════════════════════════════════════════════════════════
def model(t, k, peq, p0):
    return peq + (p0 - peq) * np.exp(-k * t)


def cyc_ts(c):
    return ((c.ts - c.ts.iloc[0]).dt.total_seconds().values / 3600,
            c.p_reactor.values.astype(float))


def fit_single(cyc):
    t, p = cyc_ts(cyc)
    try:
        popt, _ = optimize.curve_fit(
            model, t, p, p0=[0.05, 0.6, p[0]],
            bounds=([1e-4, 0.0, p[0] - 0.1], [5.0, max(p[-1], 1e-3), p[0] + 0.1]),
            maxfev=20000)
    except Exception:
        return np.nan, np.nan, np.nan
    r2 = 1 - (p - model(t, *popt)).var() / p.var()
    return popt[0], popt[1], r2


def pooled_sse(cycs, k, peq):
    """共用 (k, Peq)、每循環自己的 P0 的總平方誤差。"""
    s = 0.0
    for c in cycs:
        t, p = cyc_ts(c)
        s += float(np.sum((p - model(t, k, peq, p[0])) ** 2))
    return s


def pooled_fit(cycs, peq_fixed=None):
    if peq_fixed is None:
        r = optimize.minimize(lambda x: pooled_sse(cycs, x[0], x[1]), [0.05, 0.6],
                              method='Nelder-Mead',
                              options=dict(maxiter=20000, xatol=1e-9, fatol=1e-13))
        k, peq, sse = r.x[0], r.x[1], r.fun
    else:
        r = optimize.minimize_scalar(lambda k: pooled_sse(cycs, k, peq_fixed),
                                     bounds=(1e-4, 5), method='bounded')
        k, peq, sse = r.x, peq_fixed, r.fun
    n = sum(len(c) for c in cycs)
    return k, peq, sse, n


def profile_ci(cycs, best_sse, n, npar=2, level=0.95):
    """以 F 檢定近似的 Peq' 信賴區間（profile likelihood 門檻）。"""
    thr = best_sse * (1 + npar / (n - npar) * stats.f.ppf(level, npar, n - npar))
    grid = np.linspace(0.0, 0.98, 197)
    sse = np.array([pooled_fit(cycs, peq_fixed=q)[2] for q in grid])
    ok = grid[sse <= thr]
    lo, hi = (ok.min(), ok.max()) if len(ok) else (np.nan, np.nan)
    return grid, sse, thr, lo, hi


# ══════════════════════════════════════════════════════════
# 4. ORP 生物探針
# ══════════════════════════════════════════════════════════
def orp_features(cyc, pre_orp):
    """補氣後 ORP 崩→回升：崩深（相對補氣前）、回升速率、時間常數 tau。"""
    t = (cyc.ts - cyc.ts.iloc[0]).dt.total_seconds().values / 3600
    o = pd.Series(cyc.orp.values.astype(float)).rolling(
        15, center=True, min_periods=1).mean().values
    head = max(5, min(len(o) // 4, 90))       # 補氣後 1/4 段（上限 90 分）內找崩谷
    j = int(np.argmin(o[:head]))
    depth = float(pre_orp - o[j])
    tr, orr = t[j:] - t[j], o[j:]
    if len(tr) < 30:
        return depth, np.nan, np.nan
    m = tr <= 2.0                              # 回升速率取崩谷後 2 小時線性斜率
    rate = float(np.polyfit(tr[m], orr[m], 1)[0]) if m.sum() > 10 else np.nan
    try:
        popt, _ = optimize.curve_fit(
            lambda t, a, tau, c: c - a * np.exp(-t / tau), tr, orr,
            p0=[max(depth, 5.0), 2.0, float(orr.max())],
            bounds=([0, 0.05, float(orr.min())], [500, 200, float(orr.max()) + 100]),
            maxfev=20000)
        tau = popt[1] if 0.06 < popt[1] < 150 else np.nan
    except Exception:
        tau = np.nan
    return depth, rate, tau


# ══════════════════════════════════════════════════════════
# 5. 統計
# ══════════════════════════════════════════════════════════
def perm_corr(x, y, nperm=20000, seed=0):
    m = np.isfinite(x) & np.isfinite(y)
    x, y = np.asarray(x)[m], np.asarray(y)[m]
    if len(x) < 4:
        return np.nan, np.nan, len(x)
    r = stats.pearsonr(x, y)[0]
    rng = np.random.default_rng(seed)
    null = np.array([stats.pearsonr(x, rng.permutation(y))[0] for _ in range(nperm)])
    return r, float((np.abs(null) >= abs(r)).mean()), len(x)


def ols_cluster(X, y, groups):
    """OLS + 叢集穩健標準誤（CRSE）。回傳 beta, se, 叢集數。"""
    X = np.asarray(X, float)
    y = np.asarray(y, float)
    XtX_inv = np.linalg.pinv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    u = y - X @ beta
    meat = np.zeros((X.shape[1], X.shape[1]))
    gs = np.unique(groups)
    for g in gs:
        m = groups == g
        Xg, ug = X[m], u[m]
        meat += Xg.T @ np.outer(ug, ug) @ Xg
    V = XtX_inv @ meat @ XtX_inv
    return beta, np.sqrt(np.diag(V)), len(gs)


# ══════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════
def main():
    print('載入資料 …')
    df = load_all()
    print(f'  {len(df):,} 筆  {df.ts.min()} → {df.ts.max()}')

    rows, traces, vents = [], {}, []
    for name, (a, b, tau) in BATCHES.items():
        s = df[(df.ts >= a) & (df.ts <= b)].reset_index(drop=True)
        cycles = find_cycles(s)
        for n, (cyc, pre) in enumerate(cycles, 1):
            k, peq, r2 = fit_single(cyc)
            depth, orate, otau = orp_features(cyc, pre.orp)
            hrs = (cyc.ts.iloc[-1] - cyc.ts.iloc[0]).total_seconds() / 3600
            drop = cyc.p_reactor.iloc[0] - cyc.p_reactor.iloc[-1]
            is_last = (n == len(cycles))
            rows.append(dict(
                batch=name, tau_min=tau, cycle=n, start=cyc.ts.iloc[0],
                hours=round(hrs, 3), p0=cyc.p_reactor.iloc[0],
                p_end=cyc.p_reactor.iloc[-1], drop=round(drop, 3),
                drop_rate=drop / hrs, k_single=k, peq_single=peq, r2_single=r2,
                orp_depth=depth, orp_rise_rate=orate, orp_tau=otau,
                pre_orp=pre.orp, pre_ph=pre.ph,
                ph_mean=cyc.ph.mean(), orp_mean=cyc.orp.mean(),
                keep=(DROP_RANGE[0] <= drop <= DROP_RANGE[1]) and not is_last))
            traces[(name, n)] = cyc
        # 排氣事件：目測為基準，感測器峰值僅作佐證
        vis = VENT_VISUAL[name]
        tail = df[(df.ts >= b) & (df.ts <= pd.Timestamp(b) + pd.Timedelta('40min'))]
        rec = dict(batch=name, ch4_visual=vis['ch4'], co2_visual=vis['co2'],
                   ts=None, ch4_sensor=np.nan, co2_sensor=np.nan)
        if len(tail) and tail.ch4.max() > 5:
            i = int(tail.ch4.idxmax())
            rec.update(ts=df.ts[i], ch4_sensor=df.ch4[i], co2_sensor=df.co2[i])
        vents.append(rec)

    F = pd.DataFrame(rows)
    F.to_csv(os.path.join(OUT, 'cycle_features_3batch.csv'),
             index=False, encoding='utf-8-sig')
    K = F[F.keep].reset_index(drop=True)
    print(f'\n循環：全部 {len(F)}，納入分析 {len(K)}'
          f'（排除批次末被排氣終止者與壓降異常者）')
    print(K.groupby('batch').agg(n=('cycle', 'size'), 小時=('hours', 'mean'),
                                 下降速率=('drop_rate', 'mean')).round(4))

    print('\n排氣峰值（基準=現場目測；感測器僅佐證）：')
    V = pd.DataFrame(vents)
    for _, v in V.iterrows():
        s = (f'感測器 CH4={v.ch4_sensor:.2f}% CO2={v.co2_sensor:.1f}% @{v.ts}'
             if pd.notna(v.ch4_sensor) else '感測器未捕捉到峰值')
        print(f'  {v.batch}  目測 CH4={v.ch4_visual:.2f}% CO2={v.co2_visual:.1f}%'
              f'  |  {s}')
    V.to_csv(os.path.join(OUT, 'vent_peaks.csv'), index=False, encoding='utf-8-sig')

    # ── 每批合併擬合 + Peq' profile ──
    print('\n每批合併擬合（共用 k、Peq\'）：')
    P = []
    for name, (_, _, tau) in BATCHES.items():
        cycs = [traces[(name, c)] for c in K[K.batch == name].cycle]
        k, peq, sse, n = pooled_fit(cycs)
        grid, sseg, thr, lo, hi = profile_ci(cycs, sse, n)
        P.append(dict(batch=name, tau=tau, n_cyc=len(cycs), k=k, peq=peq,
                      lo=lo, hi=hi, rmse=np.sqrt(sse / n),
                      grid=grid, sse=sseg, thr=thr,
                      rate=K[K.batch == name].drop_rate.mean()))
        print(f'  {name}: n={len(cycs):2d}  kLa={k:.4f}/hr  '
              f'Peq\'={peq:.4f} [{lo:.3f}, {hi:.3f}]  RMSE={np.sqrt(sse/n):.5f}')
    P = pd.DataFrame(P)

    # ── tau 槓桿線：Peq' vs 1/kLa ──
    x, y = 1 / P.k.values, P.peq.values
    sl, ic, rv, pv, se = stats.linregress(x, y)
    rb, peq_phys = -sl, ic
    print(f'\n循環時間槓桿線 Peq\' = Peq - rb/kLa：')
    print(f'  截距 Peq（物理飽和壓）= {peq_phys:.4f} kg/cm²')
    print(f'  斜率 -rb → rb（生物消耗率）= {rb:.5f} kg/cm²/hr')
    print(f'  R²={rv**2:.4f}  p={pv:.4f}  （n=3 點，僅 1 自由度）')
    print(f'  ※ 5min 與 10min 的 kLa 幾乎相同（{P.k.iloc[1]:.4f} vs {P.k.iloc[2]:.4f}）'
          f'→ 有效相異點僅 2 個')

    # ── 共變數回歸（方法 C）──
    reg = K.dropna(subset=['drop_rate', 'pre_orp']).copy()
    Xm = np.column_stack([np.ones(len(reg)), reg.tau_min.values,
                          reg.pre_orp.values, reg.cycle.values])
    beta, se_c, ncl = ols_cluster(Xm, reg.drop_rate.values, reg.batch.values)
    beta_o, se_o, _ = ols_cluster(Xm, reg.drop_rate.values,
                                  np.arange(len(reg)))     # 一般 OLS 標準誤
    names = ['截距', 'τ 循環時間(物理軸)', '進氣前 ORP(生物軸)', '批次內補氣次數']
    print(f'\n共變數回歸  下降速率 ~ τ + 進氣前ORP + 補氣次數   n={len(reg)}, 叢集={ncl}')
    for nm, b_, s1, s2 in zip(names, beta, se_c, se_o):
        print(f'  {nm:22s} β={b_:+.6f}  CRSE={s1:.6f}  OLS-SE={s2:.6f}')
    print('  ※ 叢集僅 3 個，CRSE 在小叢集數下嚴重低估；下方以置換檢定為準')

    # ── 置換檢定 ──
    print('\n置換檢定（每循環層級）：')
    tests = [
        ('下降速率 vs τ（全部循環）', K.tau_min.values, K.drop_rate.values),
        ('下降速率 vs 補氣次數（全部）', K.cycle.values, K.drop_rate.values),
        ('下降速率 vs 進氣前ORP', K.pre_orp.values, K.drop_rate.values),
        ('ORP回升速率 vs 補氣次數', K.cycle.values, K.orp_rise_rate.values),
        ('進氣前ORP vs 絕對時間(天)',
         (K.start - K.start.min()).dt.total_seconds().values / 86400, K.pre_orp.values),
    ]
    for lab, xx, yy in tests:
        r, p, n = perm_corr(np.asarray(xx, float), np.asarray(yy, float))
        print(f'  {lab:28s} r={r:+.3f}  p_perm={p:.4f}  n={n}')
    for name in BATCHES:
        g = K[K.batch == name]
        r, p, n = perm_corr(g.cycle.values.astype(float), g.drop_rate.values)
        print(f'  [{name}] 下降速率 vs 補氣次數  r={r:+.3f}  p_perm={p:.4f}  n={n}')

    print('\n※ 批次層級檢定的天花板：3 個批次僅 3!=6 種排列 → 最小可能 p = 1/6 = 0.167，'
          '任何「τ 效應」的批次層級檢定在 n=3 批時結構上不可能達 p<0.05')

    make_figures(df, F, K, P, traces, (peq_phys, rb, rv ** 2, pv), reg, beta, se_c, V)
    print(f'\n圖表與資料 → {OUT}')
    return F, K, P


# ══════════════════════════════════════════════════════════
# 圖表
# ══════════════════════════════════════════════════════════
def make_figures(df, F, K, P, traces, lever, reg, beta, se_c, V):
    peq_phys, rb, r2l, pvl = lever

    # ── 圖1：三批壓力軌跡總覽 ──
    fig, axes = plt.subplots(3, 1, figsize=(13, 9))
    for ax, (name, (a, b, tau)) in zip(axes, BATCHES.items()):
        s = df[(df.ts >= a) & (df.ts <= b)]
        ax.plot(s.ts, s.p_reactor, lw=1.0, color=BCOL[name])
        g = F[F.batch == name]
        for _, r in g.iterrows():
            c = traces[(name, r.cycle)]
            ax.axvline(c.ts.iloc[0], color=BASELINE, lw=0.8)
            col = RED if not r.keep else INK2
            ax.scatter([c.ts.iloc[-1]], [c.p_reactor.iloc[-1]], s=22,
                       marker='v', color=col, zorder=5)
        nk = int(g.keep.sum())
        style(ax, f'{name}  循環時間 {tau:.0f} 分/小時  '
                  f'完整循環 {nk} 個（灰線=補氣、▽=谷底、紅▽=排除）',
              None, '反應槽壓力\n(kg/cm²)')
    axes[-1].set_xlabel('時間')
    fig.suptitle('圖1  三批次反應槽壓力軌跡與循環切分（2026-07-22 → 08-03）',
                 fontweight='bold', x=0.09, ha='left', y=0.995)
    fig.text(0, -0.02, '批次區間取自實驗參數批次表的「進氣後基準」與「排氣前」時間戳；'
             '總時數實測 114.47 / 71.67 / 95.95 hr，與表列 114.485 / 71.696 / 95.966 相符。',
             fontsize=8.5, color=INK2)
    fig.tight_layout()
    fig.savefig(f'{OUT}/fig1_three_batch_traces.png')
    plt.close(fig)

    # ── 圖2：每批合併質傳擬合 ──
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.3), sharey=True)
    for ax, (_, row) in zip(axes, P.iterrows()):
        name = row.batch
        for c in K[K.batch == name].cycle:
            cyc = traces[(name, c)]
            t, p = cyc_ts(cyc)
            ax.plot(t, p, lw=0.7, alpha=0.45, color=BCOL[name])
            ax.plot(t, model(t, row.k, row.peq, p[0]), lw=1.6, color=RED, alpha=0.8)
        style(ax, f'{name}\nkLa={row.k:.4f}/hr  Peq\'={row.peq:.3f}  '
                  f'RMSE={row.rmse:.4f}', '補氣後經過時間 (hr)',
              '反應槽壓力 (kg/cm²)' if ax is axes[0] else None)
    fig.suptitle('圖2  每批次「合併擬合」P(t)=Peq\'+(P0-Peq\')·exp(-kLa·t)（細線=實測、紅=擬合）',
                 fontweight='bold', x=0.06, ha='left')
    fig.text(0, -0.06, '合併擬合的理由：單一循環未降到飽和平台（近直線），k 與 Peq 高度相關、'
             '個別循環擬合會把 Peq 打到邊界；整批多循環共用 (k, Peq\') 才使參數收斂。',
             fontsize=8.5, color=INK2)
    fig.tight_layout()
    fig.savefig(f'{OUT}/fig2_pooled_masstransfer_fits.png')
    plt.close(fig)

    # ── 圖3：Peq' 的 profile likelihood ──
    fig, ax = plt.subplots(figsize=(9, 4.6))
    for _, row in P.iterrows():
        rel = (row.sse - row.sse.min()) / row.sse.min() * 100
        ax.plot(row.grid, rel, lw=2, color=BCOL[row.batch],
                label=f'{row.batch}  Peq\'={row.peq:.3f} [{row.lo:.2f}, {row.hi:.2f}]')
        ax.scatter([row.peq], [0], s=45, color=BCOL[row.batch], zorder=5)
    ax.set_ylim(-0.5, 25)
    style(ax, '圖3  Peq\' 的 Profile Likelihood：三批皆呈「碗狀」→ 合併擬合後可辨識',
          '表觀飽和壓 Peq\' (kg/cm²)', 'SSE 相對最小值增加 (%)')
    ax.legend(frameon=False, fontsize=9)
    fig.text(0, -0.05, '對照：07-27 單循環擬合時 Peq 平坦不可辨識（打到邊界）。'
             '合併整批循環後曲線收成碗狀，即簡報方法 A 所要求的可辨識判準。',
             fontsize=8.5, color=INK2)
    fig.savefig(f'{OUT}/fig3_peq_profile_likelihood.png')
    plt.close(fig)

    # ── 圖4：循環時間槓桿線（核心圖）──
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 4.8),
                                   gridspec_kw={'width_ratios': [1, 1.15]})
    ax1.bar(range(3), P.k, color=[BCOL[b] for b in P.batch], width=0.55)
    for i, (k, tau) in enumerate(zip(P.k, P.tau)):
        ax1.annotate(f'{k:.4f}', xy=(i, k), xytext=(0, 4),
                     textcoords='offset points', ha='center',
                     fontsize=10, fontweight='bold', color=INK)
    ax1.set_xticks(range(3))
    ax1.set_xticklabels([f'{t:.0f} 分/小時' for t in P.tau])
    ax1.annotate('1→5 min：kLa 增為 4.2 倍（槓桿有效）', xy=(0.5, 0.175),
                 fontsize=9.5, color=INK, fontweight='bold', ha='center')
    ax1.annotate('5→10 min：幾乎不變（槓桿飽和）', xy=(1.5, 0.168),
                 fontsize=9.5, color=RED, fontweight='bold', ha='center')
    style(ax1, '圖4a  質傳係數 kLa 對循環時間 τ 的響應', '循環時間 τ', 'kLa (1/hr)')
    ax1.set_ylim(0, 0.2)

    x, y = 1 / P.k.values, P.peq.values
    xs = np.linspace(0, x.max() * 1.1, 50)
    ax2.plot(xs, peq_phys - rb * xs, lw=2, ls='--', color=RED)
    for xi, yi, lo, hi, b, t in zip(x, y, P.lo, P.hi, P.batch, P.tau):
        ax2.errorbar([xi], [yi], yerr=[[yi - lo], [hi - yi]], fmt='o', ms=9,
                     color=BCOL[b], ecolor=BCOL[b], elinewidth=1.6, capsize=4)
        ax2.annotate(f'{t:.0f}min', xy=(xi, yi), xytext=(7, 7),
                     textcoords='offset points', fontsize=9.5, fontweight='bold')
    ax2.axhline(peq_phys, color=AQUA, ls=':', lw=1.4)
    ax2.set_ylim(0.55, 0.985)
    ax2.annotate(f'截距 = Peq = {peq_phys:.3f}（物理飽和壓）',
                 xy=(0.5, peq_phys - 0.028), color=AQUA,
                 fontsize=9.5, fontweight='bold')
    ax2.annotate(f'斜率 = -rb\n→ rb = {rb:.4f} kg/cm²/hr\n（生物消耗率，初步值）',
                 xy=(12.5, 0.735), color=RED, fontsize=9.5, fontweight='bold')
    style(ax2, "圖4b  解方：Peq'(τ) 對 1/kLa(τ) 作圖", '1 / kLa(τ)  (hr)',
          "表觀飽和壓 Peq' (kg/cm²)")
    fig.text(0, -0.07,
             f'擬合 R²={r2l:.3f}、p={pvl:.3f}。※ 三點中 5min 與 10min 的 1/kLa 幾乎重合 → '
             '有效相異點僅 2 個，直線無殘差自由度、無法檢驗線性假設；\n'
             'rb 幾乎完全由「1min <-> 5min」單一對比決定，而該對比同時混淆了菌齡與 CO2 累積飽和'
             '（全程未換液），故 rb 僅為初步值，須待無菌／換液對照校準。',
             fontsize=8.5, color=INK2)
    fig.tight_layout()
    fig.savefig(f'{OUT}/fig4_tau_leverage_separation.png')
    plt.close(fig)

    # ── 圖5：下降速率 ──
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 4.4))
    for name in BATCHES:
        g = K[K.batch == name]
        ax1.plot(g.cycle, g.drop_rate, 'o-', ms=5, lw=1.6,
                 color=BCOL[name], label=name)
    style(ax1, '圖5a  下降速率隨批次內補氣次數的變化', '批次內補氣次數（週期序）',
          '下降速率 (kg/cm²/hr)')
    ax1.legend(frameon=False, fontsize=9)

    for name in BATCHES:
        g = K[K.batch == name]
        ax2.scatter(g.start, g.drop_rate, s=42, color=BCOL[name], label=name, zorder=4)
    ax2.set_xlabel('日期')
    r, p, n = perm_corr((K.start - K.start.min()).dt.total_seconds().values / 86400,
                        K.drop_rate.values)
    ax2.annotate(f'全期 r={r:+.3f}  p_perm={p:.3f}  n={n}', xy=(0.03, 0.06),
                 xycoords='axes fraction', fontsize=9.5, color=INK, fontweight='bold')
    style(ax2, '圖5b  沿絕對時間看：τ 切換與菌齡完全共線', None, '下降速率 (kg/cm²/hr)')
    ax2.legend(frameon=False, fontsize=9)
    fig.text(0, -0.06, 'τ 的執行順序為 1min → 5min → 10min，與菌齡、CO2 累積飽和同向遞增，'
             '三者在觀測上不可分；欲分離須穿插執行順序或加對照組。',
             fontsize=8.5, color=INK2)
    fig.tight_layout()
    fig.savefig(f'{OUT}/fig5_droprate_trends.png')
    plt.close(fig)

    # ── 圖6：ORP / pH 生物探針 ──
    fig, axes = plt.subplots(2, 3, figsize=(14, 7), sharex=True)
    for j, name in enumerate(BATCHES):
        g = K[K.batch == name]
        cm = plt.cm.viridis(np.linspace(0, 0.9, max(len(g), 1)))
        for i, c in enumerate(g.cycle):
            cyc = traces[(name, c)]
            tn = np.linspace(0, 1, len(cyc))
            axes[0, j].plot(tn, cyc.orp, lw=0.8, color=cm[i], alpha=0.85)
            axes[1, j].plot(tn, cyc.ph, lw=0.8, color=cm[i], alpha=0.85)
        style(axes[0, j], f'{name}  ORP', None,
              'ORP (mV)' if j == 0 else None)
        style(axes[1, j], f'{name}  pH', '正規化時間 (0補氣 → 1谷底)',
              'pH' if j == 0 else None)
        axes[0, j].set_ylim(230, 700)
        axes[1, j].set_ylim(6.88, 7.08)
    fig.suptitle('圖6  三批次 ORP / pH 循環軌跡（顏色由深到淺 = 批次內由早到晚）',
                 fontweight='bold', x=0.06, ha='left')
    fig.text(0, -0.03, '10min 批的 ORP 整體抬高至 640~660 mV（1min 批約 590），'
             '方向與「還原劑（H2）消耗更完全」一致；pH 三批皆被緩衝壓在 6.93~7.02，訊號幅度極小。',
             fontsize=8.5, color=INK2)
    fig.tight_layout()
    fig.savefig(f'{OUT}/fig6_orp_ph_probes.png')
    plt.close(fig)

    # ── 圖7：相關矩陣 ──
    cols = ['drop_rate', 'hours', 'k_single', 'orp_depth', 'orp_rise_rate',
            'pre_orp', 'pre_ph', 'tau_min', 'cycle']
    labs = ['下降速率', '下降時長', '單循環k', 'ORP崩深', 'ORP回升率',
            '進氣前ORP', '進氣前pH', 'τ循環時間', '補氣次數']
    C = K[cols].corr()
    fig, ax = plt.subplots(figsize=(8.2, 7))
    im = ax.imshow(C.values, cmap='RdBu_r', vmin=-1, vmax=1)
    ax.set_xticks(range(len(labs)), labs, rotation=45, ha='right')
    ax.set_yticks(range(len(labs)), labs)
    for i in range(len(labs)):
        for j in range(len(labs)):
            v = C.values[i, j]
            ax.text(j, i, f'{v:.2f}', ha='center', va='center', fontsize=8.5,
                    color='white' if abs(v) > 0.55 else INK)
    ax.set_title(f'圖7  三批次合併每循環特徵相關矩陣（n={len(K)}）',
                 fontweight='bold', loc='left', pad=10)
    fig.colorbar(im, ax=ax, shrink=0.8)
    fig.text(0, -0.02, '※ τ、補氣次數與絕對時間共線，故任何與時間同向的量彼此都會高相關，'
             '不可逕自解讀為獨立因果。', fontsize=8.5, color=INK2)
    fig.tight_layout()
    fig.savefig(f'{OUT}/fig7_corr_matrix.png')
    plt.close(fig)

    # ── 圖8：共變數回歸係數 ──
    fig, ax = plt.subplots(figsize=(9, 4.2))
    nm = ['τ 循環時間\n(物理軸)', '進氣前 ORP\n(生物軸)', '批次內補氣次數']
    b_, s_ = beta[1:], se_c[1:]
    ax.errorbar(range(3), b_, yerr=1.96 * s_, fmt='o', ms=9, color=BLUE,
                ecolor=BLUE, elinewidth=1.8, capsize=5)
    ax.axhline(0, color=BASELINE, lw=1.4)
    ax.set_xticks(range(3), nm)
    for i, (v, s) in enumerate(zip(b_, s_)):
        ax.annotate(f'β={v:+.5f}\n±{1.96*s:.5f}', xy=(i, v), xytext=(12, 0),
                    textcoords='offset points', fontsize=9, color=INK, va='center')
    style(ax, f'圖8  共變數回歸：下降速率 ~ τ + 進氣前ORP + 補氣次數（n={len(reg)}）',
          None, '係數 (kg/cm²/hr per unit)')
    fig.text(0, -0.06, '誤差棒為 ±1.96×叢集穩健標準誤（叢集=批次）。'
             '※ 叢集僅 3 個，CRSE 的漸近性質在此不成立、區間過窄，'
             '此圖僅呈現效應方向與量級，不作顯著性宣稱。', fontsize=8.5, color=INK2)
    fig.savefig(f'{OUT}/fig8_covariate_regression.png')
    plt.close(fig)

    # ── 圖9：排氣峰值（目測為基準）──
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.3))
    xpos = np.arange(3)
    cols = [BCOL[b] for b in V.batch]
    ax1.bar(xpos, V.ch4_visual, color=cols, width=0.55)
    ax1.plot(xpos, V.ch4_sensor, 'o--', ms=8, color=RED, lw=1.6)
    for i, (a, b_) in enumerate(zip(V.ch4_visual, V.ch4_sensor)):
        ax1.annotate(f'目測 {a:.2f}%', xy=(i, a), xytext=(0, 5),
                     textcoords='offset points', ha='center',
                     fontsize=9.5, fontweight='bold', color=INK)
        if pd.notna(b_):
            ax1.annotate(f'感測 {b_:.2f}%', xy=(i, b_), xytext=(0, -16),
                         textcoords='offset points', ha='center',
                         fontsize=9, color=RED)
    ax1.set_xticks(xpos, [b.split()[1] for b in V.batch])
    style(ax1, '圖9a  排氣峰值 CH4（長條=目測基準、紅點=感測器佐證）',
          '批次（循環時間）', 'CH4 (%)')

    ax2.bar(xpos, V.co2_visual, color=cols, width=0.55)
    ax2.plot(xpos, V.co2_sensor, 'o--', ms=8, color=RED, lw=1.6)
    for i, (a, b_) in enumerate(zip(V.co2_visual, V.co2_sensor)):
        ax2.annotate(f'目測 {a:.1f}%', xy=(i, a), xytext=(0, 5),
                     textcoords='offset points', ha='center',
                     fontsize=9.5, fontweight='bold', color=INK)
        if pd.notna(b_):
            ax2.annotate(f'感測 {b_:.1f}%', xy=(i, b_), xytext=(0, -16),
                         textcoords='offset points', ha='center',
                         fontsize=9, color=RED)
    ax2.set_xticks(xpos, [b.split()[1] for b in V.batch])
    style(ax2, '圖9b  排氣峰值 CO2', '批次（循環時間）', 'CO2 (%)')

    fig.text(0, -0.07,
             'CH4 目測峰值三批單調上升 31.64% → 34.84% → 43.04%，CO2 目測維持 20~21.3%；'
             '感測器讀值在 5min／10min 兩批與目測高度吻合（34.79 / 44.24），\n'
             '1min 批感測器未捕捉到峰值（排氣時讀數仍為 0.39%），正說明氣相感測器「捕捉不到峰值」，'
             '故全案一律以目測為基準。CH4 上升與生物確有作用一致，但 τ 與菌齡共線，不能歸因於循環時間。',
             fontsize=8.5, color=INK2)
    fig.tight_layout()
    fig.savefig(f'{OUT}/fig9_vent_peaks_visual.png')
    plt.close(fig)

    # ── 圖10：預測能力（LOBO-CV：外推到沒看過的 τ）──
    y = K.drop_rate.values
    one = np.ones(len(K))
    tau = K.tau_min.values
    g = K.batch.values
    cand = {'常數（平凡基準）': np.column_stack([one]),
            '線性 ~ τ': np.column_stack([one, tau]),
            '飽和型 ~ 1/τ': np.column_stack([one, 1 / tau])}

    def lobo(X):
        e = {}
        for b_ in np.unique(g):
            m = g != b_
            beta = np.linalg.pinv(X[m]) @ y[m]
            e[b_] = float(np.sqrt(np.mean((y[~m] - X[~m] @ beta) ** 2)))
        return e

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 4.6),
                                   gridspec_kw={'width_ratios': [1.15, 1]})
    w = 0.26
    for i, (nm, X) in enumerate(cand.items()):
        e = lobo(X)
        ax1.bar(np.arange(3) + (i - 1) * w, [e[b] for b in BATCHES], width=w,
                color=[MUTED, RED, AQUA][i], label=nm)
    ax1.set_xticks(range(3), [f'留出 {b.split()[1]}' for b in BATCHES])
    style(ax1, '圖10a  留一批次 CV：預測「沒看過的循環時間」的誤差',
          None, 'LOBO-CV RMSE (kg/cm²/hr)')
    ax1.legend(frameon=False, fontsize=9)
    ax1.set_ylim(0, 0.026)
    ax1.annotate('線性模型（紅）比平凡基準（灰）還差\n→ τ 效應不是線性的',
                 xy=(0.03, 0.90), xycoords='axes fraction',
                 fontsize=9.5, color=RED, fontweight='bold', va='top')

    means = K.groupby('batch').drop_rate.agg(['mean', 'std'])
    xs = np.linspace(0.8, 11, 100)
    Xf = np.column_stack([one, 1 / tau])
    bf = np.linalg.pinv(Xf) @ y
    ax2.plot(xs, bf[0] + bf[1] / xs, lw=2, ls='--', color=RED)
    for b_ in BATCHES:
        t = BATCHES[b_][2]
        ax2.errorbar([t], [means.loc[b_, 'mean']], yerr=[means.loc[b_, 'std']],
                     fmt='o', ms=10, color=BCOL[b_], ecolor=BCOL[b_],
                     elinewidth=1.8, capsize=5)
        ax2.annotate(b_.split()[1], xy=(t, means.loc[b_, 'mean']), xytext=(9, -4),
                     textcoords='offset points', fontsize=9.5, fontweight='bold')
    ax2.annotate(f'下降速率 = {bf[0]:.4f} - {abs(bf[1]):.4f}/τ', xy=(3.4, 0.021),
                 fontsize=10.5, color=RED, fontweight='bold')
    print(f'\n飽和型預測式：下降速率 = {bf[0]:.4f} - {abs(bf[1]):.4f}/τ')
    style(ax2, '圖10b  飽和型 τ 響應（三批平均 ± 標準差）',
          '循環時間 τ (分/小時)', '下降速率 (kg/cm²/hr)')

    fig.text(0, -0.07,
             '飽和型 1/τ 模型在留出任一批次時 RMSE 皆約 0.004（批次間全距約 0.021），'
             '即用兩個循環時間可預測第三個未見過的循環時間；線性 τ 模型則比平凡基準更差。\n'
             '這是本資料最強的可外推結論：預測有效。但預測有效不等於分離有效——'
             '此模型描述的是總氣體移除速率，並未拆出物理／生物份額。',
             fontsize=8.5, color=INK2)
    fig.tight_layout()
    fig.savefig(f'{OUT}/fig10_predictive_validity.png')
    plt.close(fig)

    print('  圖 1–10 完成')


if __name__ == '__main__':
    main()
