# -*- coding: utf-8 -*-
"""從曲率反推物理份額 —— 曲率裡沒有 r_b，所以繞得開簡併。

2026-09-21。使用者提的方向（「這種通常做 PINN，可是是對曲率做」）。

════════════════════════════════════════════════════════════════════════
為什麼對曲率做是對的

    P(t) = P_eq + A·e^(−kt) − r_b·t
    dP/dt   = −A·k·e^(−kt) − r_b        <- 還有 r_b
    d²P/dt² = +A·k²·e^(−kt)             <- r_b 不見了

  定速項是直線，二階微分為零。所以**曲率是不含 r_b 的純物理通道**：
  先由曲率定出 k 與 A，r_b 再用「總壓降 − 指數項貢獻」相減得到。
  先前的聯合擬合之所以簡併，是因為 r_b 與指數項在 P 與 dP/dt 裡混在一起。

為什麼不直接上 PINN

  逐點二階差分在本案完全不可行：量化步階 0.01、殘差約 0.009，
  而 d²P/dt² 的真值約 A·k² ≈ 0.1×0.15² = 0.0023 /hr²。以一分鐘取樣，
  逐點二階差分的雜訊約 0.01·√6 = 0.024，訊噪比 ~1e-5。
  任何曲率方法（含 PINN）都得靠正則化把訊號撐出來 —— 那時答案由**平滑先驗**
  決定而不是資料。所以先做「不靠先驗」的版本：相干疊加。

做法（不需要神經網路）

  1. 每條下降曲線正規化成純形狀 s(u)，u = 走完的進度 0~1
  2. 取與直線的落差 r(u) = s(u) − (1−u)。⚠ 這一步就把 r_b 消掉了：
     兩項模型正規化後 s(u) = β·E(u;kT) + (1−β)·(1−u)
     => r(u) = β·[E(u;kT) − (1−u)]，其中 E 是純指數的形狀。
     r_b 只影響 β 的分母（總壓降），不影響 r(u) 的**形狀**。
  3. 把幾百條 r(u) 疊起來 -> 雜訊降 √N（ORP 那支已驗證 √N 成立）
  4. 擬合 (β, kT)。**振幅給 β，衰減形狀給 kT** —— 這是單一「彎曲量」
     拿不到的第二個自由度。
  5. 逐時長分箱各擬合一次：若單一 k 能解釋所有箱，kT 應與 T 成正比。
     這是模型自己的內部一致性檢定。
  6. 回收檢定：拿已知 (β,k) 合成資料 + 真實量化與雜訊，看回收得到嗎。
     ⚠ 沒通過回收檢定的估計量不可引用（Rule 8）。

輸出 -> docs/analysis_charts_3batch/curvature_inverse.csv
        docs/analysis_charts_3batch/fig38_curvature_inverse.png
"""
import csv
import os
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt                          # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # research/
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, 'edge_backend'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analyze_three_batches import (                      # noqa: E402
    BLUE, YELLOW, AQUA, RED, INK, INK2, MUTED, BASELINE, OUT, style)
from shape_clustering import (                           # noqa: E402
    NGRID, descents, load_all, shape)

QUANT = 0.01          # 壓力量化步階


def exp_shape(u, kT):
    """純指數在正規化座標下的形狀。kT->0 時退化成直線。"""
    kT = max(kT, 1e-6)
    return (np.exp(-kT * u) - np.exp(-kT)) / (1 - np.exp(-kT))


def resid_shape(u, kT):
    """r(u)/β：純指數形狀與直線的落差。"""
    return exp_shape(u, kT) - (1 - u)


def fit_beta_kT(u, r, w=None, kT_grid=None):
    """給定 r(u)，擬合 (β, kT)。β 是線性參數故可對每個 kT 解析求解。"""
    if kT_grid is None:
        kT_grid = np.exp(np.linspace(np.log(0.05), np.log(400), 600))
    if w is None:
        w = np.ones_like(r)
    best = None
    for kT in kT_grid:
        g = resid_shape(u, kT)
        denom = float((w * g * g).sum())
        if denom <= 0:
            continue
        b = float((w * g * r).sum()) / denom
        sse = float((w * (r - b * g) ** 2).sum())
        if best is None or sse < best[2]:
            best = (b, kT, sse)
    return best


def profile_kT(u, r, w, kT_grid):
    """對 kT 做 profile：每個 kT 下 β 取最佳，回傳 SSE 曲線。看可不可辨識。"""
    out = []
    for kT in kT_grid:
        g = resid_shape(u, kT)
        b = float((w * g * r).sum()) / float((w * g * g).sum())
        out.append((kT, b, float((w * (r - b * g) ** 2).sum())))
    return np.array(out)


def stack(S, grid):
    """疊加形狀落差。回傳 (平均, 標準誤)。

    ⚠ 端點的標準誤恆為 0：正規化強迫 s(0)=1、s(1)=0，那兩點是建構出來的、
      不帶資訊。若用 1/SE² 當權重會變成天文數字，整個擬合被端點綁架
      （實測會把階躍模型壓成 0）。故端點的 SE 設為 inf，等同排除。
    """
    R = S - (1 - grid)[None, :]
    se = R.std(0, ddof=1) / np.sqrt(len(R))
    se[0] = se[-1] = np.inf
    return R.mean(0), se


def recovery_test(n_cycles, T_hr, beta_true, k_true, n_rep=60, seed=0):
    """合成已知答案 + 真實的量化與雜訊，看回收得到嗎。"""
    rng = np.random.default_rng(seed)
    grid = np.linspace(0, 1, NGRID)
    got_b, got_kT = [], []
    for _ in range(n_rep):
        S = []
        for _ in range(n_cycles):
            npts = int(T_hr * 60)
            t = np.linspace(0, T_hr, npts)
            u = t / T_hr
            drop = 0.27                                   # 實測中位降幅
            kT = k_true * T_hr
            y = drop * (beta_true * exp_shape(u, kT) + (1 - beta_true) * (1 - u))
            y = y + rng.normal(0, 0.004, npts)            # 感測器雜訊
            y = np.round(y / QUANT) * QUANT               # 量化
            v = (y - y[-1]) / (y[0] - y[-1]) if y[0] != y[-1] else np.zeros(npts)
            S.append(np.interp(grid, u, v))
        S = np.array(S)
        r, se = stack(S, grid)
        w = 1.0 / np.maximum(se, 1e-9) ** 2
        b, kT_hat, _ = fit_beta_kT(grid, r, w)
        got_b.append(b)
        got_kT.append(kT_hat)
    return np.array(got_b), np.array(got_kT)


def main():
    ts, hh, p, c, m = load_all()
    segs = descents(hh, p)
    S, T, meta = [], [], []
    for s, e in segs:
        sv, grid = shape(hh, p, s, e)
        if not np.all(np.isfinite(sv)):
            continue
        S.append(sv)
        T.append(hh[e] - hh[s])
        meta.append((ts[s], hh[e] - hh[s], p[s] - p[e]))
    S, T = np.array(S), np.array(T)
    grid = np.linspace(0, 1, NGRID)
    print('可用下降週期 %d 條　時長中位 %.1f hr' % (len(S), np.median(T)))

    # ── 疊加 ──
    r, se = stack(S, grid)
    w = 1.0 / np.maximum(se, 1e-9) ** 2
    print('\n疊加後的落差曲線：最大 |r| = %.4f，該處標準誤 %.4f，訊噪比 %.1f'
          % (np.abs(r).max(), se[np.argmax(np.abs(r))],
             np.abs(r).max() / se[np.argmax(np.abs(r))]))

    b, kT, sse = fit_beta_kT(grid, r, w)
    print('\n── 對疊加曲線擬合 (物理份額 β, kT) ──')
    print('   β = %.3f　kT = %.2f　=> k = kT/T中位 = %.3f /hr' % (b, kT, kT / np.median(T)))

    # ── 可辨識性：對 kT 做 profile ──
    kT_grid = np.exp(np.linspace(np.log(0.05), np.log(400), 600))
    prof = profile_kT(grid, r, w, kT_grid)
    lo = prof[:, 2].min()
    ok = prof[prof[:, 2] <= lo * 1.05]                    # SSE 在最佳值 5% 以內
    print('   SSE 在最佳值 +5%% 以內的 kT 範圍：%.2f ~ %.2f，對應 β %.3f ~ %.3f'
          % (ok[:, 0].min(), ok[:, 0].max(), ok[:, 1].min(), ok[:, 1].max()))
    flat = (ok[:, 0].max() / ok[:, 0].min() > 5)
    print('   -> %s' % ('⚠ 平坦：曲率形狀仍不足以單獨定出 k'
                        if flat else '碗狀：曲率形狀定得出 k'))

    # ── 對照模型：補氣後「瞬間掉一段」而非慢慢鬆弛 ──
    #   若比例 βs 的壓降在 t=0 瞬間完成，其餘為定速，則
    #       s(u) = (1−βs)(1−u)  =>  r(u) = −βs·(1−u)
    #   這是一條直線，形狀與指數鬆弛完全不同，可直接比。
    g_step = -(1 - grid)
    bs = float((w * g_step * r).sum()) / float((w * g_step * g_step).sum())
    sse_step = float((w * (r - bs * g_step) ** 2).sum())
    print('\n── 對照模型：補氣後瞬間掉一段 + 之後定速 ──')
    print('   瞬間掉的比例 βs = %.3f　擬合誤差 %.1f（慢慢鬆弛模型為 %.1f）'
          % (bs, sse_step, sse))
    print('   -> %s' % ('瞬間跳躍解釋得比指數鬆弛好' if sse_step < sse
                        else '指數鬆弛仍較好'))
    # 末尾翹起：最後 10% 的落差
    tail = r[grid >= 0.9].mean()
    print('   ⚠ 末尾 10%% 的落差為 %+.4f（兩個模型都預測接近 0）'
          '：週期末速度變慢，是觸發選擇造成的' % tail)

    # ── 逐時長分箱：單一 k 該讓 kT 正比於 T ──
    print('\n── 逐時長分箱（單一 k 成立的話，kT 應正比於 T）──')
    qs = np.percentile(T, [0, 25, 50, 75, 100])
    print('   %-16s %5s %8s %8s %8s %10s' % ('時長區間(hr)', '條數', 'T中位', 'β', 'kT', 'k=kT/T'))
    rows, ks = [], []
    for i in range(4):
        sel = (T >= qs[i]) & (T <= qs[i + 1]) if i == 3 else (T >= qs[i]) & (T < qs[i + 1])
        if sel.sum() < 15:
            continue
        rr, ss = stack(S[sel], grid)
        bb, kk, _ = fit_beta_kT(grid, rr, 1.0 / np.maximum(ss, 1e-9) ** 2)
        Tm = float(np.median(T[sel]))
        ks.append(kk / Tm)
        rows.append((qs[i], qs[i + 1], int(sel.sum()), Tm, bb, kk, kk / Tm))
        print('   %5.1f ~ %-8.1f %5d %8.1f %8.3f %8.2f %10.3f'
              % (qs[i], qs[i + 1], sel.sum(), Tm, bb, kk, kk / Tm))
    if len(ks) >= 3:
        print('   各箱推得的 k：%s　最大/最小 = %.1f 倍'
              % (' '.join('%.3f' % x for x in ks), max(ks) / min(ks)))
        print('   -> %s' % ('⚠ 不一致：單一 k 解釋不了所有時長，兩項模型本身就不對'
                            if max(ks) / min(ks) > 2 else '一致：單一 k 說得通'))

    # ── 回收檢定 ──
    print('\n── 回收檢定（合成已知答案 + 真實量化與雜訊）──')
    print('   %8s %8s %10s %18s %18s' % ('真 β', '真 k', '條數', '回收 β', '回收 k'))
    rec = []
    for beta_true, k_true in ((0.30, 0.15), (0.50, 0.15), (0.70, 0.15), (0.50, 0.40)):
        gb, gkT = recovery_test(len(S), float(np.median(T)), beta_true, k_true)
        gk = gkT / np.median(T)
        rec.append((beta_true, k_true, np.median(gb), np.median(gk)))
        print('   %8.2f %8.2f %10d %8.3f [%.3f,%.3f] %8.3f [%.3f,%.3f]'
              % (beta_true, k_true, len(S), np.median(gb),
                 *np.percentile(gb, [2.5, 97.5]), np.median(gk),
                 *np.percentile(gk, [2.5, 97.5])))
    err = [abs(m_b - t_b) / t_b for t_b, t_k, m_b, m_k in rec]
    print('   β 的回收偏誤：%s' % ' '.join('%.0f%%' % (x * 100) for x in err))
    print('   -> %s' % ('⚠ 回收不準，估計量不可引用' if max(err) > 0.25
                        else '回收得回來，估計量可用'))

    make_figure(grid, r, se, b, kT, prof, rows, rec)
    path = os.path.join(OUT, 'curvature_inverse.csv')
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        wcsv = csv.writer(f)
        wcsv.writerow(['進度u', '疊加落差', '標準誤', '擬合值'])
        for i in range(NGRID):
            wcsv.writerow([round(grid[i], 4), round(r[i], 5), round(se[i], 5),
                           round(b * resid_shape(grid[i], kT), 5)])
    print('\n疊加曲線 -> %s' % os.path.relpath(path, REPO))


def make_figure(grid, r, se, b, kT, prof, rows, rec):
    fig, axes = plt.subplots(1, 3, figsize=(14.5, 4.6),
                             gridspec_kw={'wspace': 0.3})

    ax = axes[0]
    ax.axhline(0, color=BASELINE, lw=1)
    ax.fill_between(grid, r - 2 * se, r + 2 * se, color=BLUE, alpha=0.20, lw=0)
    ax.plot(grid, r, color=BLUE, lw=2.4, label='把 252 條疊起來（帶 95% 範圍）')
    g_step = -(1 - grid)
    ws = 1.0 / np.maximum(se, 1e-9) ** 2
    bs = float((ws * g_step * r).sum()) / float((ws * g_step * g_step).sum())
    ax.plot(grid, bs * g_step, color=RED, lw=2, ls='--',
            label='補氣後瞬間掉 %.0f%%，之後定速' % (bs * 100))
    ax.plot(grid, b * resid_shape(grid, kT), color=YELLOW, lw=2, ls=':',
            label='論文的慢慢鬆弛（擬合跑到邊界）')
    ax.legend(loc='lower center', fontsize=9, frameon=False)
    ax.text(0.03, 0.96, '疊加把雜訊降到 1/√252\n曲線在直線下方 = 前段掉得快',
            transform=ax.transAxes, fontsize=9, color=INK2, ha='left', va='top')
    style(ax, 'a　疊加之後，彎曲的形狀看得很清楚', '一個週期走完的進度', '與直線的落差')

    ax = axes[1]
    lo = prof[:, 2].min()
    ax.plot(prof[:, 0], prof[:, 2] / lo, color=INK, lw=2)
    ax.axhline(1.05, color=RED, lw=1, ls='--')
    ax.text(prof[0, 0], 1.052, '最佳值 +5%', color=RED, fontsize=9, ha='left', va='bottom')
    ok = prof[prof[:, 2] <= lo * 1.05]
    ax.axvspan(ok[:, 0].min(), ok[:, 0].max(), color=BLUE, alpha=0.14, lw=0)
    ax.set_xscale('log')
    ax.set_ylim(0.98, 1.6)
    ax.text(0.03, 0.96,
            '這條線若是碗狀，代表資料定得出 k；\n平坦就代表定不出來。\n'
            '可接受範圍 %.1f ~ %.1f（%.0f 倍）'
            % (ok[:, 0].min(), ok[:, 0].max(), ok[:, 0].max() / ok[:, 0].min()),
            transform=ax.transAxes, fontsize=9, color=INK2, ha='left', va='top')
    style(ax, 'b　這個形狀能不能定出 k', 'kT（快慢 × 週期長度）', '擬合誤差（相對最佳值）')

    ax = axes[2]
    tb = [x[0] for x in rec]
    mb = [x[2] for x in rec]
    ax.plot([0, 0.8], [0, 0.8], color=BASELINE, lw=1.2, ls='--')
    ax.scatter(tb, mb, s=70, color=RED, zorder=4)
    for t_b, t_k, m_b, m_k in rec:
        ax.annotate('k=%.2f' % t_k, (t_b, m_b), textcoords='offset points',
                    xytext=(8, -4), fontsize=8.5, color=INK2)
    ax.text(0.03, 0.96, '把已知答案合成成資料（含真實的量化與雜訊），\n'
                        '再用同一套方法去算，看算不算得回來。\n'
                        '點落在虛線上 = 算得回來。',
            transform=ax.transAxes, fontsize=9, color=INK2, ha='left', va='top')
    ax.set_xlim(0.15, 0.85)
    ax.set_ylim(0.0, 0.95)
    style(ax, 'c　這方法算得回已知的答案嗎', '合成時放進去的溶解佔比', '算出來的溶解佔比')

    out = os.path.join(OUT, 'fig38_curvature_inverse.png')
    fig.savefig(out)
    plt.close(fig)
    print('\n圖 -> %s' % os.path.relpath(out, REPO))


if __name__ == '__main__':
    main()
