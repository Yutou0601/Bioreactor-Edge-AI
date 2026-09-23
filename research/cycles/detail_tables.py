
# -*- coding: utf-8 -*-
"""2026-09-12 明細版日報的全部表格（資料與呈現分離）。

⚠ 每個表都由 `data_X()` 回傳結構化資料（標題、表頭、列、註腳），
  `render_text()` 負責印成等寬文字，Word 版則由
  `docs/build/build_daily_0912_detail.py` 用同一份資料建真正的 Word 表格。

  **兩個輸出共用同一份計算**——先前在 cond_of 上被「兩份會漂移的複製品」
  咬過一次，不再重蹈。

用法：
    python detail_tables.py            全部表
    python detail_tables.py A C        指定表
"""
import datetime as dt
import glob
import os
import sys
from collections import defaultdict

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # research/
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, 'edge_backend'))

ATM = 1.033
VHEAD = 1.00          # 頭空＝液面以上的氣體空間（總容積 1.99 L 的約一半，
                      # 由兩支壓力計互相反推得到）
R_GAS = 8.314462618
KGF_PA = 98066.5

TAU_DIR = '202607至08最新循環研究'
AUTO_DIR = '0825-0831_氫氣不夠暫停進氣__自動化測試'

BATCHES = [
    ('tau1', 1, dt.date(2026, 7, 22), dt.date(2026, 7, 26)),
    ('tau5', 5, dt.date(2026, 7, 27), dt.date(2026, 7, 29)),
    ('tau10', 10, dt.date(2026, 7, 30), dt.date(2026, 8, 3)),
]

_CACHE = {}


# ── 共用工具 ──────────────────────────────────────────────────────
def load(folder):
    if folder in _CACHE:
        return _CACHE[folder]
    from core.cycle_store import read_series_full
    d = os.path.join(REPO, 'research', 'Testing_data', folder)
    got = read_series_full(sorted(glob.glob(os.path.join(d, '*.csv'))))
    if got is None:
        raise SystemExit('讀不到：%s' % d)
    ts, h, p, temp, co2, ch4 = got
    f = lambda v: np.array([x if x is not None else 0.0 for x in v])
    _CACHE[folder] = (ts, np.asarray(h), np.asarray(p), f(co2), f(ch4))
    return _CACHE[folder]


def descents(h, p, min_pts=3):
    """以補氣（單步跳升 > 0.03）為界切下降段。

    ⚠ 消耗量一律用「段首 − 段尾」。不可用所有負差加總——感測器 ±0.01 的
      抖動一小時就累出 0.11，而實測速率只有 0.03（2026-09-11 週報的逐日
      消耗欄就是這樣灌水四倍的）。
    """
    segs, valley, start = [], p[0], 0
    for i in range(1, len(p)):
        if h[i] - h[i - 1] > 1.0 or p[i] - valley > 0.03:
            if i - 1 > start:
                segs.append((start, i - 1))
            start, valley = i, p[i]
        elif p[i] < valley:
            valley = p[i]
    segs.append((start, len(p) - 1))
    return [(s, e) for s, e in segs if e > s + min_pts and p[s] > p[e]]


def fit(t, y):
    """最小平方斜率與 R²（下降為正）。"""
    if len(t) < 3 or t[-1] == t[0]:
        return None, None
    A = np.vstack([t, np.ones_like(t)]).T
    c, *_ = np.linalg.lstsq(A, y, rcond=None)
    r = y - A @ c
    ss, st = float(r @ r), float(((y - y.mean()) ** 2).sum())
    return -float(c[0]), (None if st <= 0 else 1 - ss / st)


def sub(ts, h, p, co2, ch4, d0, d1):
    ix = np.flatnonzero(np.array([d0 <= t.date() <= d1 for t in ts]))
    return ([ts[i] for i in ix], h[ix] - h[ix[0]], p[ix], co2[ix], ch4[ix])


def ml(dp):
    return dp * KGF_PA * VHEAD * 1e-3 / (R_GAS * 303.15) * 22400


def minute_profile(t2, h2, p2):
    """依「小時內第幾分鐘」疊加每分鐘壓降。回傳 (平均, 標準誤, 筆數)。"""
    by = [[] for _ in range(60)]
    for j in range(1, len(t2)):
        dtr = h2[j] - h2[j - 1]
        if not (0.008 < dtr < 0.03) or p2[j] - p2[j - 1] > 0.03:
            continue
        by[t2[j].minute].append(p2[j - 1] - p2[j])
    return (np.array([np.mean(v) if len(v) > 5 else 0.0 for v in by]),
            np.array([np.std(v, ddof=1) / np.sqrt(len(v)) if len(v) > 2 else 0.0
                      for v in by]),
            np.array([len(v) for v in by]))


def pump_window(mu):
    """泵在跑的那幾分鐘＝從壓力猛掉的那一分鐘，到壓力回彈的那一分鐘。

    ⚠ 不可用門檻法：開泵尖峰是平均的 23 倍，會把 SD／MAD 撐大，4×MAD 只
      抓得到 2 分鐘而實際是 10 分鐘。
    """
    on, off = int(np.argmax(mu)), int(np.argmin(mu))
    return on, off, (off - on) % 60


# ── 各表的資料 ────────────────────────────────────────────────────
def data_A():
    ts, h, p, co2, ch4 = load(TAU_DIR)
    t2, h2, p2, _, _ = sub(ts, h, p, co2, ch4, *BATCHES[2][2:])
    segs = descents(h2, p2)
    rows = []
    for k, (s, e) in enumerate(segs, 1):
        t = h2[s:e + 1] - h2[s]
        y = p2[s:e + 1]
        sl, r2 = fit(t, y)
        dur, drop = float(t[-1]), float(y[0] - y[-1])
        auto = 5.0 <= dur <= 8.5 and 0.20 <= drop <= 0.30
        rows.append([str(k), t2[s].strftime('%m-%d %H:%M'),
                     t2[e].strftime('%m-%d %H:%M'), '%.1f' % dur,
                     '%.2f' % y[0], '%.2f' % y[-1], '%.3f' % drop,
                     '%.4f' % (drop / dur), '%.4f' % sl, '%.3f' % r2,
                     str(e - s + 1), '自動循環' if auto else '★人工排氣'])
    reg = [(s, e) for s, e in segs
           if 5.0 <= h2[e] - h2[s] <= 8.5 and 0.20 <= p2[s] - p2[e] <= 0.30]
    amp = np.array([p2[s] - p2[e] for s, e in reg])
    dur = np.array([h2[e] - h2[s] for s, e in reg])
    return {
        'title': '表 A　τ=10 批次：每一段下降的完整明細',
        'header': ['#', '起始時刻', '結束時刻', '時長hr', '起壓', '迄壓',
                   '總降', '平均速率', '斜率', 'R²', '筆數', '判定'],
        'rows': rows,
        'widths': [8, 26, 26, 16, 14, 14, 16, 20, 18, 14, 14, 22],
        'foot': ('自動循環 %d 段：降幅 %.3f ± %.3f　時長 %.2f ± %.2f hr　'
                 '速率 %.4f ± %.4f kg/cm²/hr'
                 % (len(reg), amp.mean(), amp.std(ddof=1), dur.mean(),
                    dur.std(ddof=1), (amp / dur).mean(),
                    (amp / dur).std(ddof=1))),
    }


def data_B():
    ts, h, p, co2, ch4 = load(TAU_DIR)
    prof, win = {}, {}
    for nm, tau, d0, d1 in BATCHES:
        t2, h2, p2, _, _ = sub(ts, h, p, co2, ch4, d0, d1)
        prof[nm] = minute_profile(t2, h2, p2)
        win[nm] = pump_window(prof[nm][0])
    rows = []
    for i in range(60):
        r = ['%02d' % i]
        for nm, tau, _, _ in BATCHES:
            mu, se, n = prof[nm]
            on, off, gap = win[nm]
            mk = ('開' if i == on else '停' if i == off
                  else '｜' if (i - on) % 60 < gap else '')
            r += ['%+.4f' % mu[i], '%.4f' % se[i], str(n[i]), mk]
        rows.append(r)
    foot = []
    for nm, tau, _, _ in BATCHES:
        mu = prof[nm][0]
        on, off, gap = win[nm]
        w = [(on + k) % 60 for k in range(gap)]
        tot, ws = mu.sum(), sum(mu[i] for i in w)
        r_on = ws / (gap / 60.0)
        r_off = (tot - ws) / ((60 - gap) / 60.0)
        foot.append('%s（設定每小時循環 %d 分）泵在第 %d~%d 分跑＝%d 分鐘；'
                    '這段佔全部壓降的 %.0f%%；'
                    '泵開 %.4f vs 泵停 %.4f＝%.0f 倍'
                    % (nm, tau, on, off, gap, ws / tot * 100, r_on, r_off,
                       r_on / r_off))
    return {
        'title': '表 B　循環泵：小時內逐分鐘的平均壓降（三批對照）',
        'header': ['分', 'tau1 壓降', '±SE', 'n', '', 'tau5 壓降', '±SE', 'n',
                   '', 'tau10 壓降', '±SE', 'n', ''],
        'rows': rows,
        'widths': [8, 17, 14, 11, 8, 17, 14, 11, 8, 17, 14, 11, 8],
        'foot': '\n'.join(foot),
    }


def data_C():
    ts, h, p, co2, ch4 = load(TAU_DIR)
    t2, h2, p2, _, _ = sub(ts, h, p, co2, ch4, *BATCHES[2][2:])
    segs = descents(h2, p2)
    reg = [(s, e) for s, e in segs
           if 5.0 <= h2[e] - h2[s] <= 8.5 and 0.20 <= p2[s] - p2[e] <= 0.30]
    G = np.arange(0, 6.01, 0.5)
    M = np.array([np.interp(G, h2[s:e + 1] - h2[s], p2[s:e + 1] - p2[s])
                  for s, e in reg])
    mu = M.mean(axis=0)
    se = M.std(axis=0, ddof=1) / np.sqrt(len(M))
    d1 = np.diff(mu) / np.diff(G)
    base = -d1.mean()
    rows = []
    for j, g in enumerate(G):
        rows.append(['%.1f' % g, '%+.4f' % mu[j], '%.4f' % se[j],
                     '' if j == 0 else '%.4f' % -d1[j - 1],
                     '' if j == 0 else '%.2f×' % (-d1[j - 1] / base)])
    return {
        'title': '表 C　一個循環裡壓力掉的速度（13 段對齊後平均，每 30 分一格）',
        'header': ['循環內時刻 hr', '平均累計壓降', '標準誤', '區間速率',
                   '相對速率'],
        'rows': rows,
        'widths': [34, 32, 24, 26, 24],
        'foot': 'n = %d 段；全段平均速率 %.4f kg/cm²/hr' % (len(M), base),
    }


def data_D():
    ts, h, p, co2, ch4 = load(AUTO_DIR)
    segs = descents(h, p)
    by = defaultdict(list)
    for i, t in enumerate(ts):
        by[t.date()].append(i)
    rows, prev, total = [], None, 0.0
    for d in sorted(by):
        ix = by[d]
        lo, hi = ix[0], ix[-1]
        cons = sum(p[max(s, lo)] - p[min(e, hi)] for s, e in segs
                   if min(e, hi) > max(s, lo) + 1
                   and p[max(s, lo)] > p[min(e, hi)])
        total += cons
        c = float(np.median(ch4[ix]))
        note = ('★氫氣耗盡' if d.day in (24, 25) else
                '★覆蓋不足' if d.day == 31 else
                '衰退期' if d.day >= 26 else '建立期')
        rows.append([str(d), str(len(ix)), '%.0f%%' % (len(ix) / 14.4),
                     '%.2f~%.2f' % (p[ix].min(), p[ix].max()), '%.2f' % c,
                     '' if prev is None else '%+.1f' % (c - prev),
                     '%.2f' % float(np.median(co2[ix])),
                     str(int((np.diff(p[ix]) > 0.03).sum())),
                     '%.3f' % cons, note])
        prev = c
    return {
        'title': '表 D　自動化批次：逐日明細（2026-08-11 ~ 08-31）',
        'header': ['日期', '筆數', '覆蓋', '壓力 min~max', 'CH4中位',
                   '日變化', 'CO2中位', '補氣', '當日消耗', '備註'],
        'rows': rows,
        'widths': [26, 14, 14, 26, 18, 16, 18, 12, 20, 22],
        'foot': ('當日消耗欄加總 = %.2f kg/cm²，與全期總消耗一致。'
                 '⚠ 2026-09-11 週報該欄用「所有負差加總」計算，把 ±0.01 的'
                 '感測器抖動也算進去，灌水約四倍。' % total),
    }


def data_E():
    ts, h, p, co2, ch4 = load(AUTO_DIR)
    segs = descents(h, p)
    hr = np.floor(h).astype(int)
    PH = [('建立期 8/11–8/23', dt.date(2026, 8, 11), dt.date(2026, 8, 23)),
          ('氫氣耗盡 8/24–8/25', dt.date(2026, 8, 24), dt.date(2026, 8, 25)),
          ('衰退期 8/26–8/30', dt.date(2026, 8, 26), dt.date(2026, 8, 30))]
    rows = []
    for nm, d0, d1 in PH:
        m = np.array([d0 <= t.date() <= d1 for t in ts])
        ix = np.flatnonzero(m)
        lo, hi = ix[0], ix[-1]
        cons = sum(p[max(s, lo)] - p[min(e, hi)] for s, e in segs
                   if s >= lo and e <= hi)
        days = (h[hi] - h[lo]) / 24
        y = []
        for u in sorted(set(hr[m])):
            k = np.flatnonzero((hr == u) & m)
            if len(k) >= 40:
                y.append(float((ch4[k] / 100.0 * (p[k] + ATM)).mean()))
        y = np.array(y)
        est = [('單筆端點', ch4[hi] / 100 * (p[hi] + ATM)
                - ch4[lo] / 100 * (p[lo] + ATM), None)]
        for K in (6, 12, 24):
            if len(y) >= 3 * K:
                g = y[-K:].mean() - y[:K].mean()
                s = np.sqrt(y[-K:].var(ddof=1) / K + y[:K].var(ddof=1) / K)
                est.append(('兩端各 %d hr' % K, g, s))
        for j, (lab, g, s) in enumerate(est):
            rows.append([nm if j == 0 else '',
                         '%.1f' % days if j == 0 else '',
                         '%.2f' % cons if j == 0 else '',
                         '%.1f%%→%.1f%%' % (ch4[lo], ch4[hi]) if j == 0 else '',
                         lab,
                         '%+.4f' % g + ('' if s is None else ' ± %.4f' % s),
                         '%+.0f%%' % (g / cons / 0.25 * 100)
                         + ('' if s is None else ' ± %.0f%%'
                            % (s / cons / 0.25 * 100)),
                         '%.0f' % (ml(g) / days),
                         '← 建議' if lab == '兩端各 6 hr' else ''])
    return {
        'title': '表 E　各階段轉換了多少（四種算法對照）',
        'header': ['期間', '天數', '總消耗', 'CH4 起→迄', '怎麼算',
                   'CH4 產量', '生物份額', 'mL/天', ''],
        'rows': rows,
        'widths': [30, 12, 16, 24, 24, 30, 26, 14, 14],
        'foot': ('化學計量上限 CH4/消耗 ≤ 0.25（生物份額 ≤ 100%）。'
                 '⚠ 份額為負代表該期間沒有甲烷在產生，現有的正被補入氣體'
                 '稀釋。⚠ 氫氣用完那段只有 2 天，四種算法差很多，不要引用。'),
    }


def data_F():
    from core import ch4_realtime as c4
    ts, h, p, co2, ch4 = load(TAU_DIR)
    rows = []
    for nm, tau, d0, d1 in BATCHES:
        t2, h2, p2, _, m2 = sub(ts, h, p, co2, ch4, d0, d1)
        segs = descents(h2, p2)
        amp = np.array([p2[s] - p2[e] for s, e in segs])
        dur = np.array([h2[e] - h2[s] for s, e in segs])
        mu, _, _ = minute_profile(t2, h2, p2)
        on, off, gap = pump_window(mu)
        w = sum(mu[(on + k) % 60] for k in range(gap))
        pk = c4.find_peaks_np(m2, c4.VENT_PROMINENCE, c4.VENT_MIN_DISTANCE)
        rows.append([nm, str(tau),
                     '%s~%s' % (d0.strftime('%m/%d'), d1.strftime('%m/%d')),
                     '%.1f' % ((d1 - d0).days + 1), str(len(segs)),
                     '%.3f' % np.median(amp), '%.2f' % np.median(dur),
                     '%.4f' % np.median(amp / dur),
                     '%d–%d（%d 分）' % (on, off, gap),
                     '%.0f%%' % (w / mu.sum() * 100), str(len(pk))])
    return {
        'title': '表 F　三批對照：每小時循環幾分鐘，差多少',
        'header': ['批次', 'τ分', '期間', '天數', '段數', '降幅中位',
                   '時長中位', '速率中位', '泵在跑', '佔壓降', 'CH4峰'],
        'rows': rows,
        'widths': [16, 12, 26, 14, 14, 20, 20, 20, 26, 18, 16],
        'foot': ('「泵在跑」＝壓力猛掉那一分鐘到回彈那一分鐘，'
                 '其長度應該等於設定的每小時循環分鐘數。'
                 '⚠ CH4 峰欄顯示可用的濃度錨點極少，三批合計僅 3 個。'),
    }


DATA = {'A': data_A, 'B': data_B, 'C': data_C,
        'D': data_D, 'E': data_E, 'F': data_F}


# ── 文字呈現 ──────────────────────────────────────────────────────
def _w(s):
    """字串的顯示寬度（中文與全形符號算 2）。"""
    return sum(2 if ord(c) > 0x2E7F else 1 for c in str(s))


def render_text(d):
    cells = [d['header']] + d['rows']
    ncol = len(d['header'])
    wid = [max(_w(r[i]) for r in cells) + 2 for i in range(ncol)]
    out = ['【%s】' % d['title'], '']
    for k, row in enumerate(cells):
        line = ''
        for i in range(ncol):
            v = str(row[i])
            line += v + ' ' * (wid[i] - _w(v))
        out.append('  ' + line.rstrip())
        if k == 0:
            out.append('  ' + '-' * (sum(wid) - 2))
    out.append('  ' + '-' * (sum(wid) - 2))
    for ln in d['foot'].split('\n'):
        out.append('  ' + ln)
    return '\n'.join(out)


def main():
    want = [x.upper() for x in sys.argv[1:]] or list(DATA)
    for k in want:
        if k not in DATA:
            print('沒有這張表：%s（可用 %s）' % (k, ' '.join(DATA)))
            continue
        print('=' * 106)
        print(render_text(DATA[k]()))
        print()


if __name__ == '__main__':
    main()
