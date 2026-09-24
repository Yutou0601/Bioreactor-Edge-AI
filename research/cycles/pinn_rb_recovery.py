# -*- coding: utf-8 -*-
"""PINN 反推隨時間變動的生物速率 r_b(t) —— 先問它撈不撈得回來。

2026-09-21。使用者要求：用 PINN 更新 P(t) 的計算模式，反推生物活性。

════════════════════════════════════════════════════════════════════════
為什麼這個方向本身是對的

  現行模型 P = P_eq + A·e^(−kt) − r_b·t 假設 r_b 是**常數**。已證實不成立
  （H2 會耗盡；且把生物當定速時，真物理份額 0% 會被曲率法報成 100%）。
  讓 r_b 變成時間的函數是正確的修正方向。

⚠ 但這一改會讓可辨識性變差，不是變好

  物理式是    dP/dt = −kLa·(P − P_eq) − r_b(t)
  若 r_b(t) 完全自由，它可以吸收**任何**殘差 —— 對任何壓力軌跡都能完美擬合，
  而且有無限多組 (kLa, P_eq, r_b(t)) 給出一模一樣的 P(t)。
  所以 PINN 的輸出不是由資料決定，是由**平滑先驗的強度 λ** 決定。

  網路本身不是問題，先驗才是。這一檔就是要把「答案有多依賴先驗」量出來。

三件事

  一、回收檢定：用已知的 r_b(t) 合成資料（含真實的量化 0.01 與雜訊），
      看 PINN 撈不撈得回來。撈不回來就不必往下做（Rule 8）。
  二、先驗敏感度：同一批資料，只改 λ，看反推出的 r_b(t) 變多少。
      若換個 λ 就換個答案，那結論是先驗的、不是資料的。
  三、真實資料：跑一批真的，並與上面兩項對照解讀。

輸出 -> docs/analysis_charts_3batch/pinn_rb_recovery.csv
        docs/analysis_charts_3batch/fig42_pinn_rb.png
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

import torch                                             # noqa: E402
import torch.nn as nn                                    # noqa: E402

from analyze_three_batches import (                      # noqa: E402
    BLUE, YELLOW, AQUA, RED, INK, INK2, MUTED, BASELINE, OUT, style)

torch.manual_seed(0)
QUANT = 0.01          # 壓力量化步階
NOISE = 0.004         # 感測器雜訊
LAMBDAS = (0.01, 0.1, 1.0, 10.0)


class MLP(nn.Module):
    def __init__(self, out_positive=False, width=48, depth=3):
        super().__init__()
        layers, d = [], 1
        for _ in range(depth):
            layers += [nn.Linear(d, width), nn.Tanh()]
            d = width
        layers += [nn.Linear(d, 1)]
        self.net = nn.Sequential(*layers)
        self.pos = out_positive

    def forward(self, t):
        y = self.net(t)
        return nn.functional.softplus(y) if self.pos else y


def train_pinn(t_obs, p_obs, T, lam=1.0, iters=4000, verbose=False, holdout=None,
               seed=None, return_models=False, refine=400, rb_target=None):
    """P̂(t) 與 r̂_b(t) 兩個網路；物理殘差 dP/dt + kLa(P−P_eq) + r_b = 0。

    kLa 與 P_eq 是可學的純量。r_b 以 softplus 保證非負（生物不會製造氣體）。
    holdout 給索引時，那些點不參與資料項，用來做交叉驗證挑 λ。

    ⚠ 2026-09-23 修正：只跑 Adam 4000 步**沒有收斂**（擬合 RMSE 0.030，
      而雜訊下限只有 0.005，差了六倍），先前據此得到的回收數字是「沒訓練完」
      的假象，不是方法的性質。改成 Adam 之後再接 LBFGS（strong-Wolfe 線搜尋）
      把它推到底：RMSE 降到 0.0052 ≈ 雜訊下限，kLa 也從 0.32 回到 1.44（真值 1.40）。
      refine=0 可關掉，用來重現舊行為。
    """
    tt = torch.tensor(t_obs / T, dtype=torch.float32).view(-1, 1)
    pp = torch.tensor(p_obs, dtype=torch.float32).view(-1, 1)
    p0, p1 = float(p_obs[0]), float(p_obs[-1])
    if holdout is not None:
        mask = np.ones(len(t_obs), bool)
        mask[holdout] = False
        fit_idx = torch.tensor(np.flatnonzero(mask), dtype=torch.long)
        ho_idx = torch.tensor(np.asarray(holdout), dtype=torch.long)

    if seed is not None:
        torch.manual_seed(seed)
    fP = MLP()
    fR = MLP(out_positive=True)
    log_kLa = nn.Parameter(torch.tensor(0.0))            # kLa = exp(·)，單位 1/T
    peq = nn.Parameter(torch.tensor(p1 - 0.2))
    opt = torch.optim.Adam(list(fP.parameters()) + list(fR.parameters())
                           + [log_kLa, peq], lr=3e-3)

    tc = tt.clone().requires_grad_(True)
    sc = (p0 - p1 + 1e-9) ** 2

    def losses():
        P = fP(tc)
        dP = torch.autograd.grad(P, tc, torch.ones_like(P), create_graph=True)[0]
        rb = fR(tc)
        phys = dP + torch.exp(log_kLa) * (P - peq) + rb
        if holdout is None:
            loss_data = ((fP(tt) - pp) ** 2).mean() / sc
        else:
            loss_data = ((fP(tt[fit_idx]) - pp[fit_idx]) ** 2).mean() / sc
        loss_phys = (phys ** 2).mean() / sc
        # 平滑先驗：懲罰 r_b 的變化率
        drb = torch.autograd.grad(rb, tc, torch.ones_like(rb), create_graph=True)[0]
        loss_sm = (drb ** 2).mean() / sc
        if rb_target is not None:
            # 剖面用：把 r_b 的平均值釘在指定值，其餘參數自由重新擬合。
            # 若資料真的能決定 r_b，釘錯位置時擬合誤差就會變差。
            # 併進 loss_phys（權重為 1），不要放進 loss_sm 否則會被 λ 縮放。
            loss_phys = loss_phys + 1e4 * (rb.mean() - rb_target * T) ** 2 / sc
        return loss_data, loss_phys, loss_sm

    for it in range(iters):
        opt.zero_grad()
        loss_data, loss_phys, loss_sm = losses()
        (loss_data + loss_phys + lam * loss_sm).backward()
        opt.step()
        if verbose and it % 1000 == 0:
            print('      it %4d  資料 %.2e  物理 %.2e  平滑 %.2e'
                  % (it, loss_data.item(), loss_phys.item(), loss_sm.item()))

    if refine:
        # 二階收尾：Adam 只把解帶到附近，這一步才真的走到底
        opt2 = torch.optim.LBFGS(
            list(fP.parameters()) + list(fR.parameters()) + [log_kLa, peq],
            max_iter=refine, history_size=50, tolerance_grad=1e-12,
            tolerance_change=1e-14, line_search_fn='strong_wolfe')

        def closure():
            opt2.zero_grad()
            a, b, c = losses()
            loss = a + b + lam * c
            loss.backward()
            return loss

        opt2.step(closure)
        if verbose:
            a, b, c = losses()
            print('      LBFGS 後  資料 %.2e  物理 %.2e  平滑 %.2e'
                  % (a.item(), b.item(), c.item()))

    with torch.no_grad():
        grid = torch.linspace(0, 1, 60).view(-1, 1)
        rb_hat = fR(grid).numpy().ravel() / T            # 換回每小時
        p_hat = fP(grid).numpy().ravel()
        cv = (float(((fP(tt[ho_idx]) - pp[ho_idx]) ** 2).mean())
              if holdout is not None else float('nan'))
        kla = float(torch.exp(log_kLa).detach()) / T
        pe = float(peq.detach())
        rmse = float(torch.sqrt(((fP(tt) - pp) ** 2).mean()))
    if return_models:
        # 給「特徵圖／關聯性分析」用：需要網路本身與學到的純量
        return dict(grid=grid.numpy().ravel(), rb=rb_hat, p=p_hat, kla=kla,
                    peq=pe, cv=cv, rmse=rmse, fP=fP, fR=fR, T=T)
    return grid.numpy().ravel(), rb_hat, p_hat, kla, pe, cv


def synth(T, npts, rb_fun, kLa, peq, p_start, seed=0):
    """以顯式尤拉積分合成：dP/dt = −kLa(P−Peq) − r_b(t)。"""
    rng = np.random.default_rng(seed)
    t = np.linspace(0, T, npts)
    dt = t[1] - t[0]
    P = np.empty(npts)
    P[0] = p_start
    for i in range(1, npts):
        P[i] = P[i - 1] + dt * (-kLa * (P[i - 1] - peq) - rb_fun(t[i - 1]))
    obs = np.round((P + rng.normal(0, NOISE, npts)) / QUANT) * QUANT
    return t, P, obs


def main():
    T, NP = 6.0, 360                                     # 6 小時、一分鐘一筆
    kLa_true, peq_true, p0 = 1.4, 0.75, 1.17
    # 真值：生物速率在週期內衰減一半（H2 耗盡的樣子）
    rb_true = lambda tt: 0.012 * np.exp(-0.7 * tt / T * 3)

    print('══ 一　回收檢定：已知 r_b(t)，PINN 撈不撈得回來 ══')
    t, P, obs = synth(T, NP, rb_true, kLa_true, peq_true, p0)
    print('   真值　kLa %.2f /hr　P_eq %.2f　r_b(0) %.4f -> r_b(T) %.4f'
          % (kLa_true, peq_true, rb_true(0), rb_true(T)))
    floor = np.sqrt(NOISE ** 2 + QUANT ** 2 / 12)
    print('   擬合誤差的理論下限（雜訊＋量化）%.4f —— 低於這個就是在擬合雜訊' % floor)
    rec = {}
    for lam in LAMBDAS:
        r = train_pinn(t, obs, T, lam=lam, return_models=True)
        g, rb_hat, kla, pe = r['grid'], r['rb'], r['kla'], r['peq']
        rec[lam] = (g, rb_hat, kla, pe)
        tru = rb_true(g * T)
        err = np.abs(rb_hat - tru).mean() / tru.mean()
        print('   λ=%-6.2f  回收 r_b(0)=%.4f r_b(T)=%.4f  平均相對誤差 %5.0f%%'
              '  kLa %.2f  P_eq %.4f  擬合 RMSE %.4f'
              % (lam, rb_hat[0], rb_hat[-1], err * 100, kla, pe, r['rmse']))

    best = min(rec, key=lambda L: np.abs(rec[L][1] - rb_true(rec[L][0] * T)).mean())
    print('   -> 最好的 λ=%.2f；但 λ 是我們選的，真實資料上沒有已知答案可以選' % best)

    print('\n══ 一之三　為什麼撈不回來：一個可以用紙筆證明的簡併 ══')
    print('   r_b 若是常數，物理式可以原封不動改寫成')
    print('     dP/dt = −kLa·(P − P_eq) − r_b  ≡  −kLa·(P − [P_eq − r_b/kLa])')
    print('   兩邊是**同一條曲線**，殘差完全為零。也就是說「有生物在等速吃氣」')
    print('   與「平衡壓力低一點、完全沒有生物」在壓力軌跡上是同一件事。')
    print('   可被辨識的只有組合 A = P_eq − r̄_b/kLa，不是 r_b 本身。')
    A_true = peq_true - rb_true(np.linspace(0, T, 60)).mean() / kLa_true
    print('   真值的 A = %.3f − %.5f/%.2f = %.4f'
          % (peq_true, rb_true(np.linspace(0, T, 60)).mean(), kLa_true, A_true))
    print('   檢驗：每個解算出的 A 應該都落在這個值上，不論它把 r_b 擺在哪裡')
    for lam in LAMBDAS:
        g, rb_hat, kla, pe = rec[lam]
        A = pe - rb_hat.mean() / kla
        print('   λ=%-6.2f  P_eq %.4f − r̄_b/kLa %.4f ＝ A %.4f（差真值 %+.4f，'
              '量化步階的 %.0f%%）'
              % (lam, pe, rb_hat.mean() / kla, A, A - A_true,
                 abs(A - A_true) / QUANT * 100))
    print('   -> 這就是為什麼 r_b 一律塌到 0：它被 P_eq 吸收掉了，')
    print('      而資料對 A 有意見、對 r_b 沒有。')

    print('\n══ 一之二　能不能用交叉驗證挑出正確的 λ ══')
    print('   留出 20% 的時間點不參與擬合，比較在留出點上的預測誤差。')
    rng = np.random.default_rng(0)
    ho = rng.choice(len(t), size=int(len(t) * 0.2), replace=False)
    cvs = {}
    for lam in LAMBDAS:
        g, rb_hat, _, _, _, cv = train_pinn(t, obs, T, lam=lam, holdout=ho)
        tru = rb_true(g * T)
        err = np.abs(rb_hat - tru).mean() / tru.mean()
        cvs[lam] = (cv, err)
        print('   λ=%-6.2f  留出點預測誤差 %.3e　（對應的 r_b 真實誤差 %3.0f%%）'
              % (lam, cv, err * 100))
    pick = min(cvs, key=lambda L: cvs[L][0])
    truth = min(cvs, key=lambda L: cvs[L][1])
    print('   交叉驗證挑到 λ=%.2f；真正最好的是 λ=%.2f' % (pick, truth))
    print('   -> %s'
          % ('交叉驗證挑對了，這條路可行' if pick == truth else
             '⚠ 交叉驗證挑錯：r_b(t) 自由時 P 的擬合品質幾乎與 λ 無關，留出誤差分辨不出來'))

    print('\n══ 二　先驗敏感度：同一批資料，只改 λ ══')
    lo = rec[min(LAMBDAS)][1]
    hi = rec[max(LAMBDAS)][1]
    print('   λ 從 %.2f 到 %.1f：r_b 平均值 %.4f -> %.4f（差 %.0f%%）'
          % (min(LAMBDAS), max(LAMBDAS), lo.mean(), hi.mean(),
             abs(hi.mean() - lo.mean()) / lo.mean() * 100))
    print('   r_b 的「週期內衰減幅度」%.0f%% -> %.0f%%'
          % ((1 - lo[-1] / lo[0]) * 100, (1 - hi[-1] / hi[0]) * 100))

    print('\n══ 三　真實資料（τ=10 批的一個代表性循環）══')
    real = load_one_real_cycle()
    if real is None:
        print('   讀不到真實循環，跳過')
        real_out = None
    else:
        tr, pr = real
        Tr = float(tr[-1])
        real_out = {}
        for lam in LAMBDAS:
            g, rb_hat, p_hat, kla, pe, _ = train_pinn(tr, pr, Tr, lam=lam)
            real_out[lam] = (g, rb_hat, kla, pe)
            print('   λ=%-6.2f  r_b 平均 %.4f（%.4f -> %.4f）  kLa %.2f  P_eq %.2f'
                  % (lam, rb_hat.mean(), rb_hat[0], rb_hat[-1], kla, pe))
        a = real_out[min(LAMBDAS)][1].mean()
        b = real_out[max(LAMBDAS)][1].mean()
        print('   -> 只改先驗強度，r_b 平均值就差 %.0f%%' % (abs(b - a) / a * 100))

    make_figure(t, obs, rb_true, rec, real, real_out, T)
    path = os.path.join(OUT, 'pinn_rb_recovery.csv')
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['資料', 'lambda', '進度u', 'r_b真值', 'r_b回收'])
        for lam in LAMBDAS:
            g, rb_hat, _, _ = rec[lam]
            for i in range(len(g)):
                w.writerow(['合成', lam, round(float(g[i]), 4),
                            round(float(rb_true(g[i] * T)), 6), round(float(rb_hat[i]), 6)])
        if real_out:
            for lam in LAMBDAS:
                g, rb_hat, _, _ = real_out[lam]
                for i in range(len(g)):
                    w.writerow(['真實', lam, round(float(g[i]), 4), '',
                                round(float(rb_hat[i]), 6)])
    print('\n逐點明細 -> %s' % os.path.relpath(path, REPO))


def load_one_real_cycle():
    """τ=10 批裡一個中位長度的規律循環。"""
    try:
        import pump_mode_split as M
        ts, h, p = M.load()
        for nm, tau, d0, d1 in M.BATCHES:
            if nm != 'tau10':
                continue
            B = M.analyse_batch(ts, h, p, nm, tau, d0, d1)
            c = B['reg'][4]
            s, e = c['s'], c['e']
            t = B['h2'][s:e + 1] - B['h2'][s]
            return t, B['p2'][s:e + 1]
    except Exception as exc:
        print('   （讀取失敗：%s）' % exc)
    return None


def make_figure(t, obs, rb_true, rec, real, real_out, T):
    COLS = [BLUE, AQUA, YELLOW, RED]
    fig, axes = plt.subplots(1, 3, figsize=(14.8, 4.7), gridspec_kw={'wspace': 0.3})

    ax = axes[0]
    ax.plot(t, obs, color=MUTED, lw=0.8, label='合成的觀測（含量化與雜訊）')
    ax.legend(loc='upper right', fontsize=9, frameon=False)
    ax.text(0.03, 0.06, '這條是「答案已知」的假資料：\n'
                        '生物速率設定成週期內衰減一半。',
            transform=ax.transAxes, fontsize=9, color=INK2, ha='left', va='bottom')
    _lo, _hi = ax.get_ylim()
    ax.set_ylim(_lo - (_hi - _lo) * 0.32, _hi)   # 下方留給說明文字
    style(ax, 'a　拿來做回收檢定的資料', '小時', '壓力 (kg/cm²)')

    ax = axes[1]
    g = rec[LAMBDAS[0]][0]
    ax.plot(g, rb_true(g * T), color=INK, lw=2.8, ls='--', label='真正的答案', zorder=6)
    for c, lam in zip(COLS, LAMBDAS):
        ax.plot(g, rec[lam][1], color=c, lw=1.8, label='PINN（平滑強度 λ=%g）' % lam)
    ax.legend(loc='upper right', fontsize=8.5, frameon=False)
    ax.text(0.03, 0.06, '幾條彩色線離黑虛線多遠，\n就是這個方法錯多少。',
            transform=ax.transAxes, fontsize=9, color=INK2, ha='left', va='bottom')
    _lo, _hi = ax.get_ylim()
    ax.set_ylim(_lo - (_hi - _lo) * 0.22, _hi)
    style(ax, 'b　PINN 撈回來的生物速率 vs 真正的答案', '一個週期走完的進度',
          '生物速率 (kg/cm²/hr)')

    ax = axes[2]
    if real_out:
        for c, lam in zip(COLS, LAMBDAS):
            g2, rb2, _, _ = real_out[lam]
            ax.plot(g2, rb2, color=c, lw=2, label='λ=%g' % lam)
        ax.legend(loc='upper right', fontsize=9, frameon=False)
        a = real_out[min(LAMBDAS)][1].mean()
        b = real_out[max(LAMBDAS)][1].mean()
        ax.text(0.03, 0.06, '同一批真實資料，只改平滑強度，\n'
                            '算出來的生物速率平均值就差 %.0f%%。\n'
                            '也就是答案大半由我們的設定決定。' % (abs(b - a) / a * 100),
                transform=ax.transAxes, fontsize=9, color=INK2, ha='left', va='bottom')
    _lo, _hi = ax.get_ylim()
    ax.set_ylim(_lo - (_hi - _lo) * 0.42, _hi)
    style(ax, 'c　同一批真實資料，只改一個設定', '一個週期走完的進度',
          '生物速率 (kg/cm²/hr)')

    out = os.path.join(OUT, 'fig42_pinn_rb.png')
    fig.savefig(out)
    plt.close(fig)
    print('\n圖 -> %s' % os.path.relpath(out, REPO))


if __name__ == '__main__':
    main()
