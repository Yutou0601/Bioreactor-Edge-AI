
# -*- coding: utf-8 -*-
"""2026-09-12 明細版日報的圖。

⚠ 圖說一律用白話，直接回答會議問的問題，不用行話。
  被明確要求拿掉的說法：「單調上升」「相干疊加」「泵窗」「估計量」
  「訊噪比」「包絡線」「τ 槓桿」。這些是分析過程的詞，不是設備方要看的答案。

  會議問的是：
    · 一段時間能轉換多少氣體（1hr / 2hr / 3hr）
    · 1.2 掉到 1.1 這段，用掉多少 CO2
    · 3–4 小時排一次氣可不可行
    · 排 0.16 才看得到 CH4 最高濃度

⚠ 資料取自 research/cycles/detail_tables.py，與表格共用同一份計算。
⚠ 中文字型沒有下標字元與負號，一律寫 CH4／CO2 並設 unicode_minus=False。
⚠ 標註一律加白底框，否則落在線上就讀不出來。

輸出 → docs/reports/fig_daily_0912/
"""
import os
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt                                    # noqa: E402
import numpy as np                                                 # noqa: E402

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # docs/
REPO = os.path.dirname(HERE)
OUT = os.path.join(HERE, 'reports', 'fig_daily_0912')
sys.path.insert(0, os.path.join(REPO, 'research', 'cycles'))
sys.path.insert(0, os.path.join(REPO, 'edge_backend'))

import detail_tables as DT                                         # noqa: E402

COL = {'tau1': '#2E7D32', 'tau5': '#EF6C00', 'tau10': '#1565C0'}
VHEAD, R_GAS, KGF_PA = 1.00, 8.314462618, 98066.5


# ⚠ y 軸標籤裡不可出現「體」字。matplotlib 把字串轉 90 度時，
#   這個字會被畫成約六成大小並偏移，看起來像兩字疊在一起（已踩過）。
#   橫排正常，所以標題、圖例、標註照用無妨；只有 set_ylabel / supylabel 要避。
def style():
    plt.rcParams.update({
        'font.sans-serif': ['Microsoft JhengHei', 'Microsoft YaHei',
                            'SimHei', 'DejaVu Sans'],
        'axes.unicode_minus': False,
        'font.size': 10, 'axes.labelsize': 10.5, 'axes.titlesize': 11.5,
        'xtick.labelsize': 9, 'ytick.labelsize': 9, 'legend.fontsize': 9,
        'axes.grid': True, 'grid.alpha': 0.25, 'grid.linewidth': 0.6,
        'axes.spines.top': False, 'axes.spines.right': False,
        'figure.dpi': 110,
    })


def box(c):
    return dict(boxstyle='round,pad=0.34', fc='white', ec=c, alpha=0.93, lw=0.8)


def ml(dp):
    return dp * KGF_PA * VHEAD * 1e-3 / (R_GAS * 303.15) * 22400


def stacked_profile():
    """13 個循環對齊後的平均壓降曲線（每 30 分一格）。"""
    ts, h, p, co2, ch4 = DT.load(DT.TAU_DIR)
    t2, h2, p2, _, _ = DT.sub(ts, h, p, co2, ch4, *DT.BATCHES[2][2:])
    segs = DT.descents(h2, p2)
    reg = [(s, e) for s, e in segs
           if 5.0 <= h2[e] - h2[s] <= 8.5 and 0.20 <= p2[s] - p2[e] <= 0.30]
    G = np.arange(0, 6.01, 0.5)
    M = np.array([np.interp(G, h2[s:e + 1] - h2[s], p2[s:e + 1] - p2[s])
                  for s, e in reg])
    return G, -M.mean(axis=0), M.std(axis=0, ddof=1) / np.sqrt(len(M)), reg, h2, p2


# ── 圖 1　放著不動，幾小時會掉多少、換算成多少氣體 ────────────────
def fig_howmuch():
    G, mu, se, reg, h2, p2 = stacked_profile()
    P0 = 1.17
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9.6, 4.3))

    a1.errorbar(G, P0 - mu, yerr=se, fmt='o-', color='#1565C0', lw=2.2, ms=5,
                capsize=3)
    a1.axhline(1.10, color='#C62828', ls='--', lw=1.5)
    t10 = float(np.interp(0.10, mu, G))
    a1.plot([t10], [1.10], 'o', color='#C62828', ms=10, zorder=5)
    a1.annotate('會議說的「掉到 1.1」\n實際約 %.1f 小時就到' % t10,
                xy=(t10, 1.10), xytext=(2.5, 1.135), fontsize=9.5,
                color='#C62828', fontweight='bold', bbox=box('#C62828'),
                arrowprops=dict(arrowstyle='->', color='#C62828', lw=1.2))
    a1.set_xlabel('放著不動，經過幾小時')
    a1.set_ylabel('反應器壓力（kg/cm²）')
    a1.set_title('（a）壓力掉到哪裡', fontsize=10.5)
    a1.set_ylim(0.90, 1.20)

    hrs = [1, 2, 3, 4, 5, 6]
    used = [ml(mu[int(x / 0.5)]) for x in hrs]
    co2u = [ml(mu[int(x / 0.5)] * 0.25) for x in hrs]
    w = 0.38
    xs = np.arange(len(hrs))
    a2.bar(xs - w / 2, used, w, color='#546E7A', label='總共用掉的氣體')
    a2.bar(xs + w / 2, co2u, w, color='#2E7D32', label='其中的 CO2（最多）')
    for i, (u, c) in enumerate(zip(used, co2u)):
        a2.text(i - w / 2, u + 4, '%.0f' % u, ha='center', fontsize=9)
        a2.text(i + w / 2, c + 4, '%.0f' % c, ha='center', fontsize=9,
                color='#2E7D32')
    a2.set_xticks(xs)
    a2.set_xticklabels(['%d hr' % x for x in hrs])
    a2.set_xlabel('放著不動的時間')
    a2.set_ylabel('用掉多少（mL）')          # 不可寫「氣體」，見檔頭 style() 上方的警語
    a2.set_title('（b）這段時間用掉多少氣體', fontsize=10.5)
    a2.legend(loc='upper left', framealpha=0.95)
    a2.set_ylim(0, 268)
    # ⚠ 說明框不可放右上——那裡是最高的兩根長條與它們的數字標籤（第一版
    #   就壓住了「177」）。放左側，長條較矮的地方。
    a2.text(-0.42, 148,
            'CO2 + 4H2 → CH4：\n每 4 分氣體只換到 1 分甲烷，\n'
            '所以 CO2 最多是總量的四分之一',
            fontsize=9, color='#2E7D32', ha='left', bbox=box('#2E7D32'))
    fig.suptitle('圖 1　反應器放著不動時，多久會用掉多少氣體'
                 '（10 分鐘循環那一批，13 個循環的平均）', fontsize=12, y=1.00)
    fig.tight_layout()
    return fig, 'fig1_多久用掉多少氣體'


# ── 圖 2　壓力不是平均往下掉，是泵一開才掉 ───────────────────────
def fig_when():
    ts, h, p, co2, ch4 = DT.load(DT.TAU_DIR)
    fig, axes = plt.subplots(3, 1, figsize=(9.2, 7.2), sharex=True)
    for ax, (nm, tau, d0, d1) in zip(axes, DT.BATCHES):
        t2, h2, p2, _, _ = DT.sub(ts, h, p, co2, ch4, d0, d1)
        mu, se, n = DT.minute_profile(t2, h2, p2)
        on, off, gap = DT.pump_window(mu)
        ax.axvspan(on, off, color=COL[nm], alpha=0.14, zorder=0)
        ax.errorbar(np.arange(60), mu, yerr=se, fmt='o-', color=COL[nm],
                    lw=1.3, ms=3.2, capsize=2, elinewidth=0.8)
        ax.axhline(0, color='#888', lw=0.8)
        # ⚠ 這裡不要放三行的 y 軸標籤。旋轉 90° 後三行會互相壓在一起
        #   （已踩過，「這一分鐘／掉了多少／(kg/cm²)」糊成一團）。
        #   三個子圖的單位相同，改用整張圖共用的 supylabel，一行寫完。
        ax.set_title('設定為每小時循環 %d 分鐘　→　資料上看到的就是 %d 分鐘'
                     '（第 %d 分到第 %d 分）' % (tau, gap, on, off),
                     loc='left', fontsize=10.5)
        ax.annotate('循環泵開始跑', xy=(on, mu[on]),
                    xytext=(on + 6, mu[on] * 0.9), fontsize=9,
                    color=COL[nm], fontweight='bold', bbox=box(COL[nm]),
                    arrowprops=dict(arrowstyle='->', color=COL[nm], lw=1.1))
        ax.annotate('泵停了，壓力回彈', xy=(off, mu[off]),
                    xytext=(off + 6, mu[off] * 1.7), fontsize=9,
                    color='#C62828', fontweight='bold', bbox=box('#C62828'),
                    arrowprops=dict(arrowstyle='->', color='#C62828', lw=1.1))
    axes[0].text(30, axes[0].get_ylim()[1] * 0.55,
                 '陰影以外的時間，壓力幾乎不動',
                 fontsize=9.5, color='#555', bbox=box('#999'))
    axes[-1].set_xlabel('一個小時裡的第幾分鐘')
    axes[-1].set_xlim(-1, 60)
    fig.supylabel('這一分鐘壓力掉了多少（kg/cm²）', fontsize=10.5)
    fig.suptitle('圖 2　壓力不是慢慢平均往下掉——是循環泵一開才掉',
                 fontsize=12, y=0.995)
    fig.tight_layout()
    return fig, 'fig2_壓力什麼時候掉'


# ── 圖 3　循環開得越久，氣體用得越快 ─────────────────────────────
def fig_tau():
    ts, h, p, co2, ch4 = DT.load(DT.TAU_DIR)
    taus, rates, names = [], [], []
    for nm, tau, d0, d1 in DT.BATCHES:
        t2, h2, p2, _, _ = DT.sub(ts, h, p, co2, ch4, d0, d1)
        segs = DT.descents(h2, p2)
        amp = np.array([p2[s] - p2[e] for s, e in segs])
        dur = np.array([h2[e] - h2[s] for s, e in segs])
        taus.append(tau)
        rates.append(float(np.median(amp / dur)))
        names.append(nm)
    fig, ax = plt.subplots(figsize=(8.2, 4.2))
    perday = [ml(r) * 24 for r in rates]
    bars = ax.bar([str(t) for t in taus], perday,
                  color=[COL[n] for n in names], width=0.5)
    for b, v, r in zip(bars, perday, rates):
        ax.text(b.get_x() + b.get_width() / 2, v + 8,
                '%.0f mL/天\n(%.4f kg/cm²/hr)' % (v, r),
                ha='center', fontsize=9.5, fontweight='bold')
    ax.set_xlabel('設定：每小時循環幾分鐘')
    ax.set_ylabel('一天用掉多少（mL）')
    ax.set_ylim(0, max(perday) * 1.38)
    ax.set_title('圖 3　循環泵開得越久，氣體用得越快')
    ax.text(0.06, max(perday) * 1.13,
            '循環 10 分鐘比循環 1 分鐘多用掉一倍以上的氣體。\n'
            '泵在跑的時候氣體才會進到水裡，所以泵開多久直接決定用掉多少。',
            fontsize=9.5, color='#333', bbox=box('#999'))
    fig.tight_layout()
    return fig, 'fig3_循環時間與用氣量'


# ── 圖 4　用掉多少 CO2：四種算法的差別 ───────────────────────────
def fig_est():
    d = DT.data_E()
    ph, cur = {}, None
    for r in d['rows']:
        if r[0]:
            cur = r[0]
            ph[cur] = []
        v = r[6].split('±')
        ph[cur].append((r[4], float(v[0].strip().rstrip('%')),
                        float(v[1].strip().rstrip('%')) if len(v) > 1 else 0.0))
    fig, ax = plt.subplots(figsize=(9.2, 4.3))
    labels = ['單筆端點', '兩端各 6 hr', '兩端各 12 hr', '兩端各 24 hr']
    show = ['只取頭尾各一筆', '頭尾各平均 6 小時', '頭尾各平均 12 小時',
            '頭尾各平均 24 小時']
    cols = ['#90A4AE', '#2E7D32', '#EF6C00', '#C62828']
    xs = np.arange(len(ph))
    w = 0.2
    for j, (lab, sh) in enumerate(zip(labels, show)):
        vals, errs = [], []
        for k in ph:
            m = [x for x in ph[k] if x[0] == lab]
            vals.append(m[0][1] if m else np.nan)
            errs.append(m[0][2] if m else 0.0)
        ax.bar(xs + (j - 1.5) * w, vals, w, yerr=errs, capsize=3,
               color=cols[j], alpha=0.88, label=sh)
    ax.axhline(0, color='#333', lw=1.0)
    ax.axhline(100, color='#1565C0', ls='--', lw=1.4)
    ax.text(2.45, 104, '理論上最多就是 100%', fontsize=9, color='#1565C0',
            ha='right', bbox=box('#1565C0'))
    ax.set_xticks(xs)
    ax.set_xticklabels(['菌長起來\n8/11–8/23', '氫氣用完\n8/24–8/25',
                        '沒有 CO2 可用\n8/26–8/30'])
    ax.set_ylabel('壓力下降裡有多少是菌吃掉的（%）')
    ax.legend(ncol=2, loc='upper left', fontsize=8.8, framealpha=0.95)
    ax.set_ylim(-64, 128)
    ax.annotate('算出負的＝這段時間根本沒有在產甲烷，\n'
                '現有的甲烷正被補進來的新氣體稀釋',
                xy=(2.16, -30), xytext=(1.26, -57), fontsize=9,
                color='#C62828', fontweight='bold', bbox=box('#C62828'),
                arrowprops=dict(arrowstyle='->', color='#C62828', lw=1.2))
    ax.annotate('這段只有 2 天，四種算法差很多，\n不能當數字用',
                xy=(1.19, 70), xytext=(1.28, 103), fontsize=9,
                color='#EF6C00', fontweight='bold', bbox=box('#EF6C00'),
                arrowprops=dict(arrowstyle='->', color='#EF6C00', lw=1.2))
    ax.set_title('圖 4　壓力掉下來的部分，有多少是菌吃掉的')
    fig.tight_layout()
    return fig, 'fig4_多少是菌吃掉的'


def main():
    style()
    os.makedirs(OUT, exist_ok=True)
    for old in os.listdir(OUT):
        if old.endswith('.png'):
            os.remove(os.path.join(OUT, old))
    for fn in (fig_howmuch, fig_when, fig_tau, fig_est):
        fig, name = fn()
        fig.savefig(os.path.join(OUT, name + '.png'), dpi=200,
                    bbox_inches='tight')
        plt.close(fig)
        print('   ✓', name)
    print('輸出 →', OUT)


if __name__ == '__main__':
    main()
