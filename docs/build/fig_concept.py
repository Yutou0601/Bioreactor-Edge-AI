
# -*- coding: utf-8 -*-
"""簡報用的三張「一眼看懂」概念圖。

每張都回答一個問題，而且都是真的算出來的，不是示意畫的：

  A 為什麼分不開   兩組 r_b 差 2.5 倍的擬合疊在一起，肉眼完全重合
  B 篩選在做什麼   曲率 c 的幾何意義：前半段掉了整段的幾成
  C 校準是什麼     拿已知答案的合成循環量回收表現 —— 就是拿砝碼校磅秤

⚠ 圖 C 是本腳本現場跑的回收模擬，用來說明「校準」這個動作的道理；
  它不是論文 §5 的定版校準數字（那一套跑在真實循環的配對條件上）。
  圖上已標明這一點，簡報頁也照樣寫。
"""
import os
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei', 'DFKai-SB']
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['font.size'] = 11
plt.rcParams['mathtext.fontset'] = 'dejavusans'   # 對數軸的負號需要它

# ⚠ 2026-09-10 本檔從 docs/ 搬到 docs/build/。HERE 仍然要指 docs/，
#   否則產生的文件會掉進 build/ 裡。
OUT = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), 'paper_figures')
BLUE, RED, GREY = '#1F6FB5', '#C0392B', '#666666'
INK_T = '#1A1A1A'
DT = 1.0 / 60.0                       # 每分鐘一筆
QUANT = 0.01                          # 壓力量化階


def model(t, peq, a, k, rb):
    return peq + a * np.exp(-k * t) - rb * t


def profile_fit(t, y, kgrid, rb_fixed=None):
    """對 k 掃描；給定 k（與 r_b）時模型對 (Peq, A) 是線性的。

    回傳 (rb, k, rss)。rb_fixed 不為 None 時把 r_b 釘住只擬合其餘項。
    """
    best = (None, None, np.inf)
    for k in kgrid:
        e = np.exp(-k * t)
        if rb_fixed is None:
            X = np.column_stack([np.ones_like(t), e, -t])
        else:
            X = np.column_stack([np.ones_like(t), e])
        yy = y if rb_fixed is None else y + rb_fixed * t
        coef, *_ = np.linalg.lstsq(X, yy, rcond=None)
        rss = float(np.sum((X @ coef - yy) ** 2))
        if rss < best[2]:
            rb = float(coef[2]) if rb_fixed is None else rb_fixed
            best = (rb, float(k), rss)
    return best


# ── A：為什麼分不開 ────────────────────────────────────────
def fig_degeneracy():
    T = 13.0
    t = np.arange(0, T, DT)
    truth = dict(peq=0.63, a=0.54, k=0.050, rb=0.0125)
    y = model(t, **truth)

    kgrid = np.linspace(0.005, 0.60, 400)
    rb_alt = truth['rb'] / 2.5                     # 蓄意差 2.5 倍
    _, k_alt, rss_alt = profile_fit(t, y, kgrid, rb_fixed=rb_alt)
    e = np.exp(-k_alt * t)
    X = np.column_stack([np.ones_like(t), e])
    coef, *_ = np.linalg.lstsq(X, y + rb_alt * t, rcond=None)
    y_alt = model(t, coef[0], coef[1], k_alt, rb_alt)
    rss_true = float(np.sum((y - y) ** 2))
    amp = y[0] - y[-1]
    dmax = float(np.max(np.abs(y - y_alt)))

    # ── 三格：把兩個分量拆開看 → 分開差很多，加起來一模一樣 ──
    peq2, a2 = float(coef[0]), float(coef[1])
    cases = [('情況甲', truth['a'], truth['k'], truth['rb'], BLUE),
             ('情況乙', a2, k_alt, rb_alt, BLUE)]

    fig, ax = plt.subplots(1, 3, figsize=(14.4, 4.3))
    for j, (name, A, k, rb, _) in enumerate(cases):
        phys = A * (1 - np.exp(-k * t))            # 物理累積下降
        bio = rb * t                               # 生物累積下降
        tot = phys[-1] + bio[-1]
        # ⚠ 標籤要放在各自色帶的中線上——用 t 的 65% 處實際取值，
        #   不要用比例硬湊，否則窄的那條帶會把字擠到帶外。
        i = int(0.65 * t.size)
        ax[j].fill_between(t, 0, phys, color='#7FB3D9', alpha=0.85,
                           label='物理：CO2 溶進水裡')
        ax[j].fill_between(t, phys, phys + bio, color='#E8836F',
                           alpha=0.9, label='生物：被菌吃掉')
        ax[j].plot(t, phys + bio, lw=2.4, color='#243B53')
        ax[j].set_ylim(0, 0.46)
        ax[j].set_xlabel('補氣後經過時間（hr）')
        ax[j].set_title(f'{name}：生物佔 {bio[-1]/tot*100:.0f}%',
                        fontweight='bold',
                        color=(RED if j else INK_T))
        ax[j].grid(alpha=0.2)
        ax[j].text(t[i], phys[i] + bio[i] / 2, f'生物\n{bio[-1]:.3f}',
                   fontsize=11.5, color='#7B1E10', fontweight='bold',
                   ha='center', va='center')
        ax[j].text(t[i], phys[i] / 2, f'物理\n{phys[-1]:.3f}',
                   fontsize=11.5, color='#123A57', fontweight='bold',
                   ha='center', va='center')
        if j == 0:
            ax[j].set_ylabel('壓力已經掉了多少（kg/cm²）')
            ax[j].legend(loc='upper left', framealpha=0.95, fontsize=10)

    ax[2].plot(t, y, lw=5.0, color=BLUE, alpha=0.55, label='情況甲的總壓力')
    ax[2].plot(t, y_alt, lw=1.8, color=RED, ls='--',
               label='情況乙的總壓力')
    ax[2].step(t[::45], np.round(y[::45] / QUANT) * QUANT, where='post',
               color='#243B53', lw=1.0, alpha=0.75,
               label='壓力計實際寫下的數字')
    ax[2].set_xlabel('補氣後經過時間（hr）')
    ax[2].set_ylabel('反應槽壓力（kg/cm²）')
    ax[2].set_title('但壓力計看到的完全一樣', fontweight='bold', color=RED)
    ax[2].legend(loc='upper right', framealpha=0.95, fontsize=9.5)
    ax[2].grid(alpha=0.25)
    ax[2].text(0.04, 0.06,
               '兩條線最大差 %.4f\n只有一個刻度（0.01）的 %.0f%%\n'
               '→ 感測器根本記不出差別'
               % (dmax, dmax / QUANT * 100),
               transform=ax[2].transAxes, fontsize=10.5, color=RED,
               va='bottom',
               bbox=dict(fc='white', ec=RED, alpha=0.92, lw=0.9))

    fig.suptitle('分開看差很多，加起來一模一樣　'
                 '——　就像「10 元」可以是 7+3，也可以是 3+7',
                 fontsize=13.5, fontweight='bold')
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    p = os.path.join(OUT, 'figQ1_why_hard.png')
    fig.savefig(p, dpi=180); plt.close(fig)
    print(f'A 分不開：最大差 {dmax:.5f} = 振幅的 {dmax/amp*100:.2f}%，'
          f'替代解的 k = {k_alt:.4f}  → {os.path.basename(p)}')


# ── B：篩選在做什麼 ────────────────────────────────────────
def fig_screen():
    T = 13.0
    t = np.arange(0, T + DT, DT)
    cases = [(0.0, '筆直下降', RED, '兩項分不開 → 丟掉'),
             (0.030, '略為彎曲', '#E8912B', '勉強 → 丟掉'),
             (0.075, '明顯彎曲', BLUE, '指數項現形 → 留下')]

    fig, ax = plt.subplots(figsize=(10.6, 4.4))
    for k, name, col, verdict in cases:
        if k == 0:
            y = 1.17 - (1.17 - 0.93) * t / T
        else:
            a = (1.17 - 0.93) / (1 - np.exp(-k * T))
            y = 0.93 - a * np.exp(-k * T) + a * np.exp(-k * t)
        c = (y[0] - y[len(y) // 2]) / (y[0] - y[-1])
        ax.plot(t, y, lw=2.6, color=col,
                label=f'{name}：c = {c:.2f}　{verdict}')
        ax.plot([T / 2], [y[len(y) // 2]], 'o', color=col, ms=7)

    ax.axvline(T / 2, color=GREY, ls=':', lw=1.2)
    ax.annotate('整段的正中間', xy=(T / 2, 1.155), xytext=(T / 2 + 0.6, 1.16),
                fontsize=10, color=GREY)
    ax.set_xlabel('補氣後經過時間（hr）')
    ax.set_ylabel('反應槽壓力（kg/cm²）')
    ax.set_title('c ＝ 前半段掉了多少 ÷ 整段掉了多少　'
                 '（筆直下降恰好 0.5，愈彎愈大，門檻 0.45）',
                 fontweight='bold')
    ax.legend(loc='lower left', framealpha=0.95)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    p = os.path.join(OUT, 'figQ2_screen.png')
    fig.savefig(p, dpi=180); plt.close(fig)
    print(f'B 篩選 → {os.path.basename(p)}')


# ── C：校準是什麼 ──────────────────────────────────────────
EXCLUDE = {'0109-0123_H2_1CO2_1', '0301-0416_無循環與有循環_5mins',
           '0417-0427_有循環_10mins_74%'}


def real_conditions():
    """讀出資料集 C 每個真實循環的擬合條件——校準必須配對到這些條件。

    這正是論文 Algorithm 2 的作法：沿用該段自己的 k、時長、振幅與殘差
    尺度，只把真實的 r_b 換掉。用隨便設的參數校出來的是別人的偏差。
    """
    import csv
    p = os.path.join(os.path.dirname(OUT), 'analysis_charts_3batch',
                     'rb_per_cycle.csv')
    out = []
    with open(p, encoding='utf-8-sig') as fh:
        for r in csv.DictReader(fh):
            if r['folder'] in EXCLUDE:
                continue
            T, k = float(r['dur_hr']), float(r['k'])
            amp = float(r['total_rate']) * T
            if not (2.0 < T < 40.0 and k > 0 and amp > 0.05):
                continue
            out.append((T, k, amp, float(r['rmse'])))
    return out


def fig_calibration():
    """對已知真值的合成循環跑同一條流程，看量出來的值偏多少。"""
    rng = np.random.default_rng(20260815)
    phi = 0.27
    cond = real_conditions()
    kgrid = np.arange(0.01, 3.001, 0.02)      # 同 Algorithm 1 的網格
    truths = np.array([0.006, 0.008, 0.010, 0.012, 0.014, 0.016, 0.018])
    ncyc = 60

    med, lo, hi, iqr = [], [], [], []
    for rb0 in truths:
        got = []
        for _ in range(ncyc):
            T, k, amp, sig = cond[rng.integers(len(cond))]
            t = np.arange(0, T, DT)
            a = (amp - rb0 * T) / (1 - np.exp(-k * T))
            y = model(t, 0.63, a, k, rb0)
            n = np.zeros_like(t)                       # AR(1) 雜訊
            w = rng.normal(0, sig * np.sqrt(1 - phi ** 2), t.size)
            for i in range(1, t.size):
                n[i] = phi * n[i - 1] + w[i]
            y = np.round((y + n) / QUANT) * QUANT      # 量化到 0.01
            c = (y[0] - y[t.size // 2]) / (y[0] - y[-1])
            if c < 0.45:                               # 同一道預篩
                continue
            rb, _, _ = profile_fit(t, y, kgrid)
            got.append(rb)
        g = np.array(got)
        med.append(np.median(g))
        # 帶狀畫的是「中位數本身」的拔靴精度——那才是我們實際使用的量。
        # 逐循環的散布大上一個量級（見下方註記），畫出來會衝出圖外，
        # 而且會讓人誤以為單一循環可以讀，那正是論文明講不可以的事。
        bm = np.median(g[np.random.default_rng(7).integers(
            0, g.size, size=(2000, g.size))], axis=1)
        lo.append(np.percentile(bm, 2.5))
        hi.append(np.percentile(bm, 97.5))
        iqr.append((np.percentile(g, 75) - np.percentile(g, 25)))
    med = np.array(med); lo = np.array(lo); hi = np.array(hi)

    fig, ax = plt.subplots(figsize=(7.4, 5.6))
    lim = [0.004, 0.020]
    ax.plot(lim, lim, ls='--', lw=1.6, color=GREY,
            label='理想：量到的 = 真的')
    ax.fill_between(truths, lo, hi, color=BLUE, alpha=0.30,
                    label='中位數的 95% 拔靴範圍')
    ax.plot(truths, med, 'o-', lw=2.4, ms=7, color=BLUE,
            label='流程量出的中位')

    # 回推示範：實測 0.0128 沿校準曲線回到真值軸
    obs = 0.01283
    est = float(np.interp(obs, med, truths))
    ax.plot([lim[0], est], [obs, obs], color=RED, lw=1.8, ls=':')
    ax.plot([est, est], [obs, lim[0]], color=RED, lw=1.8, ls=':')
    ax.plot([est], [obs], '*', ms=17, color=RED, zorder=5)
    ax.annotate(f'實測讀數 {obs:.4f}\n沿曲線回推 → {est:.4f}',
                xy=(est, obs), xytext=(0.006, 0.0163), fontsize=10.5,
                color=RED,
                arrowprops=dict(arrowstyle='->', color=RED, lw=1.4),
                bbox=dict(fc='white', ec=RED, alpha=0.92, lw=0.9))

    ax.set_xlim(lim); ax.set_ylim(lim)
    ax.set_xlabel('我們設定的真實速率（已知答案）')
    ax.set_ylabel('整條流程量出來的速率')
    ax.set_title('拿砝碼校磅秤：先量已知的，再回推未知的',
                 fontweight='bold')
    ax.legend(loc='lower right', framealpha=0.95, fontsize=10)
    ax.grid(alpha=0.25)
    spread = float(np.median(iqr))
    prec = float(np.median(np.array(hi) - np.array(lo)))
    ax.text(0.03, 0.965,
            '每個真值 %d 段合成循環，沿用真實循環的時長、k、振幅與\n'
            '殘差尺度，走完全相同的切／篩／估\n'
            '逐段的四分位距約 %.4f，是中位數精度的 %.0f 倍\n'
            '—— 所以只有聚合值可用' % (ncyc, spread, spread / prec),
            transform=ax.transAxes, fontsize=8.5, color=GREY, va='top')
    fig.tight_layout()
    p = os.path.join(OUT, 'figQ3_calibration.png')
    fig.savefig(p, dpi=180); plt.close(fig)
    print(f'C 校準：實測 {obs:.5f} 回推 {est:.5f} '
          f'（{(est/obs-1)*100:+.1f}%）  → {os.path.basename(p)}')


# ── D：為什麼用中位數而不是平均 ────────────────────────────
def fig_percycle():
    """資料集 C 全部 280 段的逐循環估計值分布（真實資料，非模擬）。

    這張圖同時說明兩件事：中位數穩、平均被尾巴拖走；以及逐循環的值
    為什麼不能單獨拿來用。
    """
    import csv
    p = os.path.join(os.path.dirname(OUT), 'analysis_charts_3batch',
                     'rb_per_cycle.csv')
    v = [float(r['rb']) for r in
         csv.DictReader(open(p, encoding='utf-8-sig'))
         if r['folder'] not in EXCLUDE]
    a = np.array(v)
    med, mean = float(np.median(a)), float(a.mean())
    lo, hi = -0.02, 0.06
    out_lo, out_hi = int((a < lo).sum()), int((a > hi).sum())

    fig, ax = plt.subplots(figsize=(10.4, 4.4))
    ax.hist(np.clip(a, lo, hi), bins=64, color=BLUE, alpha=0.75,
            edgecolor='white', lw=0.4)
    ax.axvline(med, color=RED, lw=2.6,
               label=f'中位數 {med:.4f}　← 我們用這個')
    ax.axvline(mean, color='#E8912B', lw=2.2, ls='--',
               label=f'平均 {mean:.4f}　（被尾巴拖高 '
                     f'{(mean/med-1)*100:.0f}%）')
    ax.axvline(0, color=GREY, lw=1.0, ls=':')
    ax.set_xlim(lo, hi)
    ax.set_xlabel('單一補氣段算出的生物速率（kg/cm²/hr）')
    ax.set_ylabel('循環數')
    ax.set_title(f'資料集 C 全部 {a.size} 個補氣段的估計值', fontweight='bold')
    ax.legend(loc='upper right', framealpha=0.95)
    ax.grid(alpha=0.22, axis='y')
    ax.text(0.015, 0.62,
            '負值 %.0f%%（物理上不可能）\n'
            '超出左界 %d 段、右界 %d 段\n'
            '最小 %.2f、最大 %.2f\n'
            '→ 單一段讀不得，只有聚合值可用'
            % ((a < 0).mean() * 100, out_lo, out_hi, a.min(), a.max()),
            transform=ax.transAxes, fontsize=9.5, color=RED, va='top',
            bbox=dict(fc='white', ec=RED, alpha=0.92, lw=0.8))
    fig.tight_layout()
    q = os.path.join(OUT, 'figQ4_percycle.png')
    fig.savefig(q, dpi=180); plt.close(fig)
    print(f'D 逐循環：{a.size} 段，中位 {med:.5f}，平均 {mean:.5f} '
          f'（+{(mean/med-1)*100:.0f}%） → {os.path.basename(q)}')


# ── E：部署預算 ────────────────────────────────────────────
def fig_budget():
    """為什麼整條流程只能用 NumPy 寫：瓶頸是函式庫體積，不是演算法。"""
    names = ['本文流程\n（純 NumPy）', '加上 SciPy', '完整科學堆疊\n'
             '（SciPy+pandas）']
    size = [27, 62, 129]
    budget = 60

    fig, ax = plt.subplots(figsize=(7.0, 4.2))
    cols = [BLUE if s <= budget else RED for s in size]
    b = ax.bar(names, size, color=cols, width=0.58)
    ax.axhline(budget, color='#E8912B', lw=2.2, ls='--')
    ax.text(2.48, budget + 3, f'監控電腦可用預算 {budget} MB',
            color='#E8912B', fontsize=10.5, ha='right', fontweight='bold')
    for r, s in zip(b, size):
        ax.text(r.get_x() + r.get_width() / 2, s + 3, f'{s} MB',
                ha='center', fontsize=11, fontweight='bold',
                color=(BLUE if s <= budget else RED))
    ax.set_ylabel('安裝後佔用（MB）')
    ax.set_ylim(0, 150)
    ax.set_title('瓶頸是函式庫體積，不是演算法成本', fontweight='bold')
    ax.grid(alpha=0.22, axis='y')
    fig.tight_layout()
    q = os.path.join(OUT, 'figQ5_budget.png')
    fig.savefig(q, dpi=180); plt.close(fig)
    print(f'E 預算 → {os.path.basename(q)}')


# ── F：感測器的刻度有多粗 ──────────────────────────────────
def fig_ladder():
    """把「31 格 / 15 格 / 不到 1 格」畫成看得見的刻度。"""
    fig, ax = plt.subplots(figsize=(8.2, 4.6))
    items = [('整段\n掉了多少', 0.31, '#7FB3D9'),
             ('其中要測的\n生物那一份', 0.15, '#E8836F'),
             ('每一筆讀數的\n雜訊', 0.0065, '#9AA5B1')]
    for i, (name, v, col) in enumerate(items):
        ax.bar(i, v, width=0.5, color=col, edgecolor='#243B53', lw=0.8)
        ax.text(i, v + 0.012, '%.4f' % v if v < 0.02 else '%.2f' % v,
                ha='center', fontsize=12, fontweight='bold')
        ax.text(i, v / 2, '%.0f 格' % round(v / QUANT) if v >= QUANT
                else '不到 1 格', ha='center', va='center', fontsize=13,
                fontweight='bold', color='white')
    for g in np.arange(0, 0.33, QUANT):        # 感測器的刻度
        ax.axhline(g, color=GREY, lw=0.5, alpha=0.45)
    ax.set_xticks(range(3))
    ax.set_xticklabels([n for n, _, _ in items], fontsize=11)
    ax.set_ylabel('壓力（kg/cm²）')
    ax.set_ylim(0, 0.35)
    ax.set_title('橫線就是感測器的刻度（每格 0.01）', fontweight='bold')
    ax.text(0.98, 0.96,
            '要測的東西有 15 格高\n雜訊連 1 格都不到\n'
            '→ 訊號夠大，難的不在雜訊',
            transform=ax.transAxes, fontsize=10.5, color=RED, va='top',
            ha='right', bbox=dict(fc='white', ec=RED, alpha=0.92, lw=0.9))
    fig.tight_layout()
    q = os.path.join(OUT, 'figQ6_ladder.png')
    fig.savefig(q, dpi=180); plt.close(fig)
    print('F 刻度 → figQ6_ladder.png')


# ── G：ORP 三分組 ─────────────────────────────────────────
def fig_orp():
    fig, ax = plt.subplots(figsize=(7.6, 4.4))
    names = ['最低\n三分之一', '中間\n三分之一', '最高\n三分之一']
    vals = [0.0099, 0.0134, 0.0152]
    b = ax.bar(names, vals, width=0.55,
               color=['#B8CCE0', '#6FA8D0', BLUE], edgecolor='#243B53',
               lw=0.8)
    for r, v in zip(b, vals):
        ax.text(r.get_x() + r.get_width() / 2, v + 0.0004, '%.4f' % v,
                ha='center', fontsize=12.5, fontweight='bold', color=BLUE)
    ax.annotate('', xy=(2, 0.0152), xytext=(0, 0.0099),
                arrowprops=dict(arrowstyle='<->', color=RED, lw=2.0))
    ax.text(1.0, 0.0163, '菌越活躍，量到的速率越高（跨度 54%）',
            ha='center', fontsize=12, color=RED, fontweight='bold')
    ax.set_ylabel('該組的生物速率（kg/cm²/hr）')
    ax.set_ylim(0, 0.019)
    ax.set_xlabel('依 ORP 活躍度分成三組（ORP 完全沒有進入計算）')
    ax.set_title('用一個完全沒被用到的訊號去對答案', fontweight='bold')
    ax.grid(alpha=0.22, axis='y')
    fig.tight_layout()
    q = os.path.join(OUT, 'figQ7_orp.png')
    fig.savefig(q, dpi=180); plt.close(fig)
    print('G ORP → figQ7_orp.png')


# ── H：AUC 量尺 ───────────────────────────────────────────
def fig_auc():
    fig, ax = plt.subplots(figsize=(8.6, 3.4))
    ax.axhline(0, color=GREY, lw=2.5)
    for x, lab, col, dy in [(0.5, '完全分不出\n真假', '#2E8B57', -1),
                            (0.968, '白雜訊\n0.968', RED, 1),
                            (0.832, 'AR(1)\n0.832', '#E8912B', -1),
                            (0.695, '定版\n0.695', BLUE, 1),
                            (1.0, '一眼看穿', RED, -1)]:
        ax.plot([x], [0], 'o', ms=13, color=col, zorder=4)
        ax.annotate(lab, xy=(x, 0), xytext=(x, 0.42 * dy),
                    ha='center', va='center', fontsize=11.5, color=col,
                    fontweight='bold',
                    arrowprops=dict(arrowstyle='-', color=col, lw=1.2))
    ax.set_xlim(0.44, 1.06); ax.set_ylim(-0.85, 0.85)
    ax.set_yticks([]); ax.set_xticks([0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
    ax.set_xlabel('分類器分辨真假資料的能力 AUC')
    ax.set_title('模擬器越像真的，這個數字越靠左', fontweight='bold')
    for sp in ('left', 'right', 'top'):
        ax.spines[sp].set_visible(False)
    fig.tight_layout()
    q = os.path.join(OUT, 'figQ8_auc.png')
    fig.savefig(q, dpi=180); plt.close(fig)
    print('H AUC → figQ8_auc.png')


# ── I：結果與誤差來源 ─────────────────────────────────────
def fig_interval():
    fig, ax = plt.subplots(1, 2, figsize=(11.0, 3.6),
                           gridspec_kw={'width_ratios': [1.5, 1]})
    ax[0].errorbar([0.01256], [0], xerr=[[0.00135], [0.00165]], fmt='o',
                   ms=15, color=RED, ecolor=RED, elinewidth=3.0, capsize=10,
                   capthick=3.0)
    ax[0].axvline(0, color=GREY, lw=1.2, ls=':')
    ax[0].text(0.01256, 0.30, '0.0126', ha='center', fontsize=15,
               fontweight='bold', color=RED)
    ax[0].text(0.01121, -0.34, '0.0112', ha='center', fontsize=11,
               color=GREY)
    ax[0].text(0.01421, -0.34, '0.0142', ha='center', fontsize=11,
               color=GREY)
    ax[0].text(0.0002, 0.30, '零', fontsize=11, color=GREY)
    ax[0].set_xlim(-0.0008, 0.0175); ax[0].set_ylim(-0.75, 0.75)
    ax[0].set_yticks([])
    ax[0].set_xlabel('生物速率（kg/cm²/hr）')
    ax[0].set_title('結果落在哪裡，離零有多遠', fontweight='bold')
    for sp in ('left', 'right', 'top'):
        ax[0].spines[sp].set_visible(False)

    ax[1].barh([1], [5.5], color='#7FB3D9', edgecolor='#243B53', lw=0.8)
    ax[1].barh([0], [5.1], color='#E8836F', edgecolor='#243B53', lw=0.8)
    ax[1].barh([-1], [11.9], color=RED, alpha=0.85,
               edgecolor='#243B53', lw=0.8)
    for y, v, lab in [(1, 5.5, '量得更久會變小'),
                      (0, 5.1, '量再久也不會變小'), (-1, 11.9, '合起來')]:
        ax[1].text(v + 0.4, y, '±%.1f%%　%s' % (v, lab), va='center',
                   fontsize=10.5)
    ax[1].set_yticks([1, 0, -1])
    ax[1].set_yticklabels(['抽樣', '系統', '總計'], fontsize=12)
    ax[1].set_xlim(0, 22); ax[1].set_xticks([])
    ax[1].set_title('誤差從哪裡來', fontweight='bold')
    for sp in ('right', 'top', 'bottom'):
        ax[1].spines[sp].set_visible(False)
    fig.tight_layout()
    q = os.path.join(OUT, 'figQ9_interval.png')
    fig.savefig(q, dpi=180); plt.close(fig)
    print('I 區間 → figQ9_interval.png')


# ── J：r_b 在化學上是什麼 ─────────────────────────────────
def fig_chem():
    """壓力為什麼會掉：五個氣體分子進去，只有一個出來。

    水是液態，不回到氣相，所以淨少四個 —— 這就是壓力下降的來源，
    也是 r_b 這個「壓力速率」背後的化學意義。
    """
    from matplotlib.patches import Circle, FancyArrow

    fig, ax = plt.subplots(figsize=(11.6, 3.4))

    def mol(x, y, lab, fc, ec, r=0.42, alpha=1.0, txt='white'):
        ax.add_patch(Circle((x, y), r, facecolor=fc, edgecolor=ec,
                            lw=1.6, alpha=alpha, zorder=3))
        ax.text(x, y, lab, ha='center', va='center', fontsize=11.5,
                fontweight='bold', color=txt, zorder=4)

    # 反應前：1 個 CO2 + 4 個 H2 ＝ 5 個氣體分子
    mol(0.8, 1.0, r'$\mathrm{CO_2}$', '#1F6FB5', '#123A57')
    for i in range(4):
        mol(1.95 + i * 0.95, 1.0, r'$\mathrm{H_2}$', '#7FB3D9', '#123A57',
            txt='#123A57')
    ax.text(2.85, 2.05, '反應前：5 個氣體分子', ha='center', fontsize=13,
            fontweight='bold', color='#123A57')

    ax.add_patch(FancyArrow(6.15, 1.0, 1.15, 0, width=0.10,
                            head_width=0.34, head_length=0.36,
                            facecolor='#243B53', edgecolor='none',
                            zorder=3))
    ax.text(6.75, 1.52, '嗜氫甲烷菌', ha='center', fontsize=11.5,
            color='#243B53', fontweight='bold')

    # 反應後：1 個 CH4（氣體）＋ 2 個 H2O（液態，不佔氣相）
    mol(8.0, 1.0, r'$\mathrm{CH_4}$', '#C0392B', '#7B1E10')
    for i in range(2):
        mol(9.15 + i * 0.95, 1.0, r'$\mathrm{H_2O}$', '#E4E7EB',
            '#9AA5B1', alpha=0.95, txt='#6B6B6B')
    ax.text(8.0, 2.05, '反應後：1 個氣體分子', ha='center', fontsize=13,
            fontweight='bold', color='#7B1E10')
    ax.text(9.62, 0.28, '水是液態，不回到氣相', ha='center', fontsize=10,
            color=GREY)

    ax.text(5.5, -0.42,
            '淨少 4 個氣體分子　→　壓力下降　→　'
            'r$_b$ 量到的就是這件事的速度',
            ha='center', fontsize=13.5, fontweight='bold', color=RED)
    ax.set_xlim(0, 11.0); ax.set_ylim(-0.85, 2.5)
    ax.axis('off')
    ax.set_title(r'$\mathrm{CO_2 + 4H_2 \rightarrow CH_4 + 2H_2O}$'
                 '　（4:1 預混就是照這個比例配的）',
                 fontsize=14, fontweight='bold')
    fig.tight_layout()
    q = os.path.join(OUT, 'figQ10_chemistry.png')
    fig.savefig(q, dpi=180); plt.close(fig)
    print('J 化學 → figQ10_chemistry.png')


# ── K：ORP 怎麼分組（真實資料） ───────────────────────────
def fig_orp_groups():
    """資料集 C 的 280 段，依每段的氧化還原變化量切成三組。

    ⚠ 沒有沿用既有的 fig6 / fig12：那兩張的圖說寫的是「ORP 反映 H2 分壓」
      的 Nernst 解讀，該解讀已經收回（ORP 同時受 pH 與溶解 CO2 影響，
      是活躍度指標而非氫氣計）。圖檔裡的文字改不掉，只能重畫。
    """
    import csv
    p = os.path.join(os.path.dirname(OUT), 'analysis_charts_3batch',
                     'rb_per_cycle.csv')
    rows = [r for r in csv.DictReader(open(p, encoding='utf-8-sig'))
            if r['folder'] not in EXCLUDE]
    d = np.array([float(r['dORP']) for r in rows])
    rb = np.array([float(r['rb']) for r in rows])
    q1, q2 = np.percentile(d, [100 / 3, 200 / 3])
    lo, hi = -320.0, 220.0
    groups = [('還原力最弱', d <= q1, '#B8CCE0'),
              ('中間', (d > q1) & (d <= q2), '#6FA8D0'),
              ('還原力最強', d > q2, BLUE)]

    fig, ax = plt.subplots(figsize=(10.8, 4.2))
    bins = np.linspace(lo, hi, 56)
    for name, m, col in groups:
        ax.hist(np.clip(d[m], lo, hi), bins=bins, color=col, alpha=0.9,
                edgecolor='white', lw=0.4,
                label='%s（%d 段，r$_b$ 中位 %.4f）'
                      % (name, m.sum(), np.median(rb[m])))
    for q in (q1, q2):
        ax.axvline(q, color=RED, lw=2.0, ls='--')
        ax.text(q, ax.get_ylim()[1] * 0.97, ' %.0f mV' % q, color=RED,
                fontsize=10.5, va='top', fontweight='bold')
    ax.set_xlim(lo, hi)
    ax.set_xlabel('每個補氣段的氧化還原變化量（mV，記錄器的原始讀數）')
    ax.set_ylabel('循環數')
    ax.set_title('280 個補氣段依氧化還原變化量切成三等分（紅線為切點）',
                 fontweight='bold')
    ax.legend(loc='upper right', framealpha=0.95, fontsize=10)
    ax.grid(alpha=0.22, axis='y')
    ax.text(0.015, 0.96,
            '每組段數幾乎相同（95 / 93 / 92）\n'
            '切點事先由三分位決定，不是看結果挑的',
            transform=ax.transAxes, fontsize=9.5, color=GREY, va='top')
    fig.tight_layout()
    q = os.path.join(OUT, 'figQ11_orp_groups.png')
    fig.savefig(q, dpi=180); plt.close(fig)
    print('K ORP 分組：切點 %.0f / %.0f mV，各組 r_b 中位 %s'
          % (q1, q2, ['%.4f' % np.median(rb[m]) for _, m, _ in groups]))


# ── L：ρ 是什麼，為什麼 0.814 不能直接讀 ─────────────────
def fig_rho_meaning():
    """兩種假設的真值各跑一次，看算出來的兩個估計值會不會連動。

    ⚠ 兩格都是模擬，真值由我們指定，所以可以直接比。不放實測散布：
      實測的相關要在篩選後的 239 段上算，而篩選需要原始軌跡，
      本圖的資料來源（逐循環擬合表）沒有那個欄位。硬拿全部 280 段
      算會得到 0.57，與論文報的 0.814 不是同一件事，並列只會誤導。
    """
    rng = np.random.default_rng(20260816)
    phi = 0.27
    cond = real_conditions()
    kgrid = np.arange(0.01, 3.001, 0.02)
    kmed = float(np.median([c[1] for c in cond]))
    R0, ncyc = 0.0126, 110

    def run(beta):
        got_rb, got_k = [], []
        for _ in range(ncyc):
            T, k, amp, sig = cond[rng.integers(len(cond))]
            rb0 = R0 * (k / kmed) ** beta          # 真值隨 k 變的強度
            a = (amp - rb0 * T) / (1 - np.exp(-k * T))
            if a <= 0:
                continue
            t = np.arange(0, T, DT)
            y = model(t, 0.63, a, k, rb0)
            n = np.zeros_like(t)
            w = rng.normal(0, sig * np.sqrt(1 - phi ** 2), t.size)
            for i in range(1, t.size):
                n[i] = phi * n[i - 1] + w[i]
            y = np.round((y + n) / QUANT) * QUANT
            c = (y[0] - y[t.size // 2]) / (y[0] - y[-1])
            if c < 0.45:
                continue
            rbh, kh, _ = profile_fit(t, y, kgrid)
            got_rb.append(rbh); got_k.append(kh)
        return np.array(got_rb), np.array(got_k)

    def spearman(a, b):
        ra, rb_ = np.argsort(np.argsort(a)), np.argsort(np.argsort(b))
        return float(np.corrcoef(ra, rb_)[0, 1])

    fig, ax = plt.subplots(1, 2, figsize=(11.6, 4.4), sharey=True)
    ylo, yhi = -0.012, 0.055
    for j, (beta, title, col) in enumerate(
            [(0.0, '假設一：真值完全不變', '#6FA8D0'),
             (0.5, '假設二：真值隨 k 上升', BLUE)]):
        rbh, kh = run(beta)
        r = spearman(rbh, kh)
        out = int(((rbh < ylo) | (rbh > yhi)).sum())
        ax[j].scatter(kh, np.clip(rbh, ylo, yhi), s=30, color=col,
                      edgecolor='#123A57', lw=0.5, alpha=0.8)
        # ⚠ 散布圖上看不出秩相關，必須畫分箱中位線，趨勢才會現形
        edges = np.quantile(kh, np.linspace(0, 1, 6))
        bx, by = [], []
        for e0, e1 in zip(edges[:-1], edges[1:]):
            m = (kh >= e0) & (kh <= e1)
            if m.sum() >= 3:
                bx.append(np.median(kh[m])); by.append(np.median(rbh[m]))
        ax[j].plot(bx, by, 'o-', color='#243B53', lw=2.6, ms=8,
                   zorder=5, label='每五分之一 k 的中位')
        ax[j].set_xscale('log')
        ax[j].set_xticks([0.01, 0.1, 1.0])
        ax[j].set_xticklabels(['0.01', '0.1', '1'])   # 避免對數軸負號破字
        ax[j].set_ylim(ylo, yhi)
        ax[j].set_xlabel('算出的鬆弛常數 k（1/hr）')
        ax[j].set_title('%s\n兩者的連動程度 ρ = %.2f' % (title, r),
                        fontweight='bold',
                        color=(RED if j == 0 else INK_T))
        ax[j].grid(alpha=0.22)
        ax[j].legend(loc='upper left', fontsize=10, framealpha=0.95)
        if out:
            ax[j].text(0.98, 0.03, '另有 %d 點超出範圍' % out,
                       transform=ax[j].transAxes, fontsize=9,
                       color=GREY, ha='right')
        if j == 0:
            ax[j].set_ylabel('算出的生物速率 r$_b$')
        print('   β=%.1f → n=%d, ρ=%.3f' % (beta, len(rbh), r))
    fig.suptitle('每一點是一個補氣段：橫軸與縱軸都是「算出來的」，'
                 '看它們會不會一起大一起小', fontsize=13, fontweight='bold')
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    q = os.path.join(OUT, 'figQ12_rho.png')
    fig.savefig(q, dpi=180); plt.close(fig)
    print('L rho → figQ12_rho.png')


if __name__ == '__main__':
    fig_degeneracy()
    fig_screen()
    fig_calibration()
    fig_percycle()
    fig_budget()


# ── M：虛無是什麼（Algorithm 3 的視覺化） ─────────────────
def fig_null():
    """把「純物理虛無」畫出來：它長什麼樣，以及流程讀它會算出什麼。

    左：r_b 強制為零所生成的一段紀錄——「完全沒有生物」該長的樣子。
    右：讓完全相同的流程去讀這種紀錄，算出來的 r_b 分布，
        以及實測中位數的位置。兩者差兩個數量級。
    """
    rng = np.random.default_rng(20260818)
    cond = real_conditions()
    kgrid = np.arange(0.01, 3.001, 0.02)
    phi, got = 0.27, []
    demo = None
    for _ in range(120):
        T, k, amp, sig = cond[rng.integers(len(cond))]
        a = amp / (1 - np.exp(-k * T))          # r_b 恆為 0
        t = np.arange(0, T, DT)
        y = model(t, 0.63, a, k, 0.0)
        n = np.zeros_like(t)
        w = rng.normal(0, sig * np.sqrt(1 - phi ** 2), t.size)
        for i in range(1, t.size):
            n[i] = phi * n[i - 1] + w[i]
        yq = np.round((y + n) / QUANT) * QUANT
        c = (yq[0] - yq[t.size // 2]) / (yq[0] - yq[-1])
        if c < 0.45:
            continue
        rbh, _, _ = profile_fit(t, yq, kgrid)
        got.append(rbh)
        if demo is None and 8 < T < 16:
            demo = (t, y, yq)
    g = np.array(got)
    obs = 0.01283

    fig, ax = plt.subplots(1, 2, figsize=(11.8, 4.2),
                           gridspec_kw={'width_ratios': [1, 1.15]})
    t, y, yq = demo
    ax[0].step(t, yq, where='post', color='#243B53', lw=1.0,
               label='壓力計會寫下的數字')
    ax[0].plot(t, y, color=BLUE, lw=2.6, label='真相：只有物理，生物 = 0')
    ax[0].set_xlabel('補氣後經過時間（hr）')
    ax[0].set_ylabel('反應槽壓力（kg/cm²）')
    ax[0].set_title('虛無長這樣：完全沒有生物的一段', fontweight='bold')
    ax[0].legend(loc='upper right', framealpha=0.95, fontsize=10)
    ax[0].grid(alpha=0.25)

    ax[1].hist(g, bins=26, color='#7FB3D9', edgecolor='white', lw=0.5)
    ax[1].axvline(float(np.median(g)), color=BLUE, lw=2.4,
                  label='虛無算出的中位 %.5f' % np.median(g))
    ax[1].axvline(obs, color=RED, lw=3.0,
                  label='實測中位 %.4f' % obs)
    ax[1].set_xlim(-0.004, 0.015)
    ax[1].set_xlabel('流程算出的生物速率 r$_b$')
    ax[1].set_ylabel('段數')
    ax[1].set_title('讓流程去讀虛無，它算出什麼', fontweight='bold',
                    color=RED)
    ax[1].legend(loc='upper center', framealpha=0.95, fontsize=10)
    ax[1].grid(alpha=0.22, axis='y')
    ax[1].text(0.97, 0.55,
               '流程沒有無中生有\n虛無與實測差兩個數量級\n置換檢定 p = 0.024',
               transform=ax[1].transAxes, fontsize=10.5, color=RED,
               ha='right', va='top',
               bbox=dict(fc='white', ec=RED, alpha=0.93, lw=0.9))
    fig.tight_layout()
    q = os.path.join(OUT, 'figQ13_null.png')
    fig.savefig(q, dpi=180); plt.close(fig)
    print('M 虛無：n=%d，中位 %.6f，實測 %.5f → figQ13_null.png'
          % (g.size, np.median(g), obs))
