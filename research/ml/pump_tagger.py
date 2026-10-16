# -*- coding: utf-8 -*-
"""方向 3：逐分鐘「泵狀態」標記器（Bi-LSTM vs 因果 LSTM vs 非深度基準 vs 規則）。

2026-10-16。

════════════════════════════════════════════════════════════════════════
為什麼挑「泵」而不是補氣
  補氣用門檻就分得乾淨（升降速率差 60–450 倍），深度學習在那裡沒有工作可做。
  泵不一樣：pump_rhythm.py 證明泵在壓力裡看得見，但**只有逐日平均後**看得見；
  pump_duration_audit.py 記錄了逐小時規則法失敗（tau5 逐小時給中位 36 分，設定 5 分）。
  逐小時知道泵實際跑幾分鐘，是 τ 稽核（現場回報 τ=20 只跑約 10 分）與
  pump_mode_split（每循環自己的啟動分鐘）都需要、卻做不到的事。

標籤從哪來（弱標籤，要講清楚）
  · 泵開／停：逐日分鐘剖面的驟降尖峰→回升尖峰（pump_rhythm.pump_window），
    假設同一天內每小時同一分鐘開泵。這是**日尺度的真相**，不是逐小時的真相；
    tau1 的啟動分鐘在 49/50 間漂移（pump_mode_split 記錄的坑），所以另報 ±1 分容忍。
  · 補氣：單步升幅 > 0.03（規則；本來就分得開）。
  · 無泵期（2026-04-07 以前）：整段標為泵停——這是**負對照**，模型在這裡報泵開＝假警報。
  ⚠ 輸入**不含**「小時內第幾分鐘」。給了它就只會背時刻表，等於把標籤餵回去。

驗證
  留一期間：每次拿掉一個有泵的期間（不同 τ）當測試，其餘訓練；無泵期另切一段當測試。
  指標：逐分鐘 F1（泵開）、啟動分鐘 ±1 命中率、逐小時運轉分鐘的絕對誤差、無泵期假警報。

用法（一律在 Jetson 跑）：
  python3 pump_tagger.py --qa          只做標籤品質檢查（逐日剖面）
  ML_DEVICE=cuda python3 pump_tagger.py
"""
import datetime as dt
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # research/
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'cycles'))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

DATA = os.path.join(HERE, 'Testing_data')
FOLDERS = ['0301-0416_無循環與有循環_5mins', '0417-0427_有循環_10mins_74%',
           '20260727_1min_data', '202607至08最新循環研究']

D = dt.date
# (名稱, 宣稱 τ（None＝無泵）, 起, 迄)
PERIODS = [
    ('nopump', None, D(2026, 3, 1), D(2026, 4, 6)),
    ('tau1', 1, D(2026, 7, 22), D(2026, 7, 26)),
    ('tau5', 5, D(2026, 7, 27), D(2026, 7, 29)),
    ('tau10', 10, D(2026, 7, 30), D(2026, 8, 3)),
]
# ⚠ 2026-10-16 標籤檢查（--qa）發現：資料夾名稱寫「有循環 5mins／10mins」的 4 月期間，
#   逐日剖面**完全沒有**固定分鐘的泵訊號（驟降 z 3–5，與 3 月無泵日 2.5–4 相同；
#   7 月 τ 批是 13–44）。所以 4 月的泵不是「每小時固定分鐘開」，或在壓力裡看不見，
#   不能用日剖面當標籤。改成只套用：用 7 月訓練好的模型去看 4 月與 5–7 月找到什麼。
APPLY = [
    ('apr_5min', D(2026, 4, 7), D(2026, 4, 16)),
    ('apr_10min', D(2026, 4, 17), D(2026, 4, 26)),
    ('may_jul', D(2026, 4, 27), D(2026, 7, 21)),
]
REFILL_RISE = 0.03
SEQ = 180           # 每條序列 3 小時：至少看得到兩次泵脈衝
SEED = int(os.environ.get('PT_SEED', 20261016))     # 換種子重跑看變異
OUT = os.path.join(HERE, 'ml', 'out_pump_tagger', 'seed%d' % SEED)


# ══════════════════════════════════════════════════════════
# 資料
# ══════════════════════════════════════════════════════════
def load_all():
    """四個資料夾合併、依時刻去重（資料夾之間有重疊，見 duplicate_raw_files）。"""
    from multivariate_increments import load4
    seen = {}
    for f in FOLDERS:
        for ts, p, orp, ph in load4(os.path.join(DATA, f)):
            seen.setdefault(ts, (p, orp, ph))
    ts = sorted(seen)
    arr = np.array([seen[t] for t in ts], dtype=float)
    return np.array(ts), arr[:, 0], arr[:, 1], arr[:, 2]


def increments(ts, p, orp, ph):
    """逐分鐘增量。只有與前一筆相隔約一分鐘才算，否則記為斷點（gap=1、增量 0）。"""
    sec = np.array([(t - ts[0]).total_seconds() for t in ts])
    d = np.diff(sec, prepend=sec[0] - 60)
    ok = (d > 30) & (d < 90)
    dp = np.where(ok, np.diff(p, prepend=p[0]), 0.0)
    dorp = np.where(ok, np.diff(orp, prepend=orp[0]), 0.0)
    dph = np.where(ok, np.diff(ph, prepend=ph[0]), 0.0)
    refill = ok & (dp > REFILL_RISE)
    return dp, dorp, dph, ~ok, refill


def day_window(ts, dp, ok, refill, day):
    """該日的分鐘剖面 → (開泵分, 停泵分, 運轉分, 尖峰大小, 筆數)。"""
    m = np.array([t.date() == day for t in ts]) & ok & ~refill
    if m.sum() < 600:
        return None
    mins = np.array([t.minute for t in ts[m]])
    drop = -dp[m]
    mu = np.array([drop[mins == i].mean() if (mins == i).sum() > 5 else 0.0 for i in range(60)])
    on, off = int(np.argmax(mu)), int(np.argmin(mu))
    base = np.median(mu)
    mad = np.median(np.abs(mu - base)) + 1e-9
    return dict(on=on, off=off, run=(off - on) % 60, spike=float((mu[on] - base) / mad),
                rise=float((base - mu[off]) / mad), n=int(m.sum()))


def build_labels(ts, dp, gap, refill, verbose=True):
    """回傳 y（0 泵停、1 泵開、2 補氣、-1 不用）、期間編號、每日標籤表。"""
    ok = ~gap
    y = np.full(len(ts), -1, int)
    pid = np.full(len(ts), -1, int)
    dates = np.array([t.date() for t in ts])
    mins = np.array([t.minute for t in ts])
    table = []
    for k, (name, tau, d0, d1) in enumerate(PERIODS):
        day = d0
        while day <= d1:
            sel = dates == day
            if sel.sum() == 0:
                day += dt.timedelta(days=1)
                continue
            w = day_window(ts, dp, ok, refill, day)
            row = dict(period=name, day=str(day), tau=tau, **(w or {}))
            use = w is not None
            if tau is not None and use:
                # 日剖面的運轉分鐘與宣稱 τ 差太多 → 那天的標籤不可信，不用
                use = abs(w['run'] - tau) <= max(1, tau // 2)
            row['used'] = bool(use)
            table.append(row)
            if use:
                pid[sel] = k
                if tau is None:
                    y[sel] = 0
                else:
                    on_ = ((mins[sel] - w['on']) % 60) < w['run']
                    y[sel] = on_.astype(int)
                y[sel & refill] = 2
                y[sel & gap] = -1
            day += dt.timedelta(days=1)
    if verbose:
        print('%-10s %-11s %4s %4s %4s %4s %7s %7s %6s %s' %
              ('期間', '日', 'τ', '開', '停', '運轉', '驟降z', '回升z', '筆數', '採用'))
        for r in table:
            if 'on' not in r:
                print('%-10s %-11s %4s   資料不足' % (r['period'], r['day'], r['tau']))
                continue
            print('%-10s %-11s %4s %4d %4d %4d %7.1f %7.1f %6d %s' % (
                r['period'], r['day'], r['tau'], r['on'], r['off'], r['run'],
                r['spike'], r['rise'], r['n'], '✓' if r['used'] else '✗'))
    return y, pid, table


# ══════════════════════════════════════════════════════════
# 特徵與序列
# ══════════════════════════════════════════════════════════
def features(dp, dorp, dph, gap, channels='all'):
    """逐分鐘輸入。用穩健尺度（MAD）標準化，避免泵尖峰撐大尺度。"""
    def rz(x):
        s = 1.4826 * np.median(np.abs(x - np.median(x))) + 1e-9
        return np.clip((x - np.median(x)) / s, -50, 50)
    cols = [rz(dp)]
    if channels == 'all':
        cols += [rz(dorp), rz(dph)]
    cols.append(gap.astype(float))
    return np.stack(cols, 1).astype(np.float32)


def make_seqs(X, y, idx_mask, stride):
    """在 idx_mask 為真的連續區域內切長度 SEQ 的序列。"""
    starts = []
    i, n = 0, len(X)
    while i + SEQ <= n:
        if idx_mask[i:i + SEQ].all():
            starts.append(i)
            i += stride
        else:
            i += 1
    if not starts:
        return np.zeros((0, SEQ, X.shape[1]), np.float32), np.zeros((0, SEQ), int), []
    S = np.stack([X[s:s + SEQ] for s in starts])
    Y = np.stack([y[s:s + SEQ] for s in starts])
    return S, Y, starts


# ══════════════════════════════════════════════════════════
# 模型
# ══════════════════════════════════════════════════════════
def train_lstm(Str, Ytr, bidir, epochs=40, hid=32, device='cpu', seed=SEED):
    import torch
    import torch.nn as nn
    torch.manual_seed(seed)

    class Tagger(nn.Module):
        def __init__(self):
            super().__init__()
            self.lstm = nn.LSTM(Str.shape[2], hid, num_layers=2, batch_first=True,
                                bidirectional=bidir, dropout=0.1)
            self.head = nn.Linear(hid * (2 if bidir else 1), 3)

        def forward(self, x):
            return self.head(self.lstm(x)[0])

    dev = torch.device(device)
    net = Tagger().to(dev)
    X = torch.tensor(Str, device=dev)
    Y = torch.tensor(Ytr, device=dev, dtype=torch.long)
    # 類別權重：泵開只佔 2–17% 的分鐘
    cnt = np.bincount(Ytr[Ytr >= 0].ravel(), minlength=3).astype(float)
    wt = torch.tensor(cnt.sum() / (3 * np.maximum(cnt, 1)), dtype=torch.float32, device=dev)
    lossf = nn.CrossEntropyLoss(weight=wt, ignore_index=-1)
    opt = torch.optim.Adam(net.parameters(), lr=3e-3)
    n = len(X)
    for ep in range(epochs):
        net.train()
        perm = torch.randperm(n).to(dev)
        for i in range(0, n, 64):
            b = perm[i:i + 64]
            opt.zero_grad()
            out = net(X[b])
            loss = lossf(out.reshape(-1, 3), Y[b].reshape(-1))
            loss.backward()
            opt.step()
    net.eval()
    return net


def predict_lstm(net, X, mask, device='cpu'):
    """整段（非重疊、長度 SEQ）預測；序列頭尾各 30 分鐘的預測較差，用重疊視窗中段覆蓋。"""
    import torch
    n = len(X)
    prob = np.zeros((n, 3))
    cnt = np.zeros(n)
    step = SEQ // 2
    with torch.no_grad():
        for s in range(0, max(n - SEQ, 0) + 1, step):
            if not mask[s:s + SEQ].any():
                continue
            xb = torch.tensor(X[s:s + SEQ][None], device=torch.device(device))
            pr = torch.softmax(net(xb), -1)[0].cpu().numpy()
            # 只取中段（頭尾 30 分鐘權重低）
            w = np.ones(SEQ)
            w[:30] = 0.2
            w[-30:] = 0.2
            prob[s:s + SEQ] += pr * w[:, None]
            cnt[s:s + SEQ] += w
    prob /= np.maximum(cnt, 1e-9)[:, None]
    return prob


def window_feats(X, k=10):
    """非深度基準：前後各 k 分鐘的特徵攤平（與 Bi-LSTM 一樣看得到未來）。"""
    n, c = X.shape
    pad = np.pad(X, ((k, k), (0, 0)))
    return np.concatenate([pad[i:i + n] for i in range(2 * k + 1)], 1)


def rule_per_hour(dp, ts, mask):
    """規則基準：每個時鐘小時內，最大驟降分→最大回升分＝泵窗（逐小時版的 pump_window）。"""
    pred = np.zeros(len(dp), int)
    hours = np.array([t.replace(minute=0, second=0) for t in ts])
    idx = np.flatnonzero(mask)
    if not len(idx):
        return pred
    hk = hours[idx]
    bounds = np.flatnonzero(np.r_[True, hk[1:] != hk[:-1], True])
    for a, b in zip(bounds[:-1], bounds[1:]):
        ii = idx[a:b]
        if len(ii) < 50:
            continue
        x = -dp[ii]
        on, off = int(np.argmax(x)), int(np.argmin(x))
        if off > on:
            pred[ii[on:off]] = 1
        else:
            pred[ii[on:]] = 1
    return pred


# ══════════════════════════════════════════════════════════
# 指標
# ══════════════════════════════════════════════════════════
def metrics(pred, y, ts, mask):
    """pred：0/1（泵開）。y：真標籤。只算 mask 內、y∈{0,1} 的分鐘。"""
    m = mask & (y >= 0) & (y != 2)
    t, p = (y[m] == 1), (pred[m] == 1)
    tp, fp, fn = (t & p).sum(), (~t & p).sum(), (t & ~p).sum()
    f1 = 2 * tp / max(2 * tp + fp + fn, 1)
    # 逐小時運轉分鐘：以真標籤的開泵分 − 20 為每「泵小時」起點，避免泵窗被時鐘整點切開
    hours = {}
    mi = np.flatnonzero(m)
    for i in mi:
        key = (ts[i] - dt.timedelta(minutes=20)).replace(minute=0, second=0)
        h = hours.setdefault(key, [0, 0, [], []])
        h[0] += int(y[i] == 1)
        h[1] += int(pred[i] == 1)
        if y[i] == 1 and (i == 0 or y[i - 1] != 1):
            h[2].append(i)
        if pred[i] == 1 and (i == 0 or pred[i - 1] != 1):
            h[3].append(i)
    full = list(hours.values())
    err = [abs(v[1] - v[0]) for v in full]
    hit = []
    for v in full:
        if v[2]:
            hit.append(any(abs(a - b) <= 1 for a in v[2] for b in v[3]))
    fa = sum(1 for v in full if v[0] == 0 and v[1] > 0)
    n0 = sum(1 for v in full if v[0] == 0)
    return dict(f1=float(f1), mae_run=float(np.mean(err)) if err else float('nan'),
                med_run_pred=float(np.median([v[1] for v in full if v[0] > 0])) if any(v[0] > 0 for v in full) else float('nan'),
                med_run_true=float(np.median([v[0] for v in full if v[0] > 0])) if any(v[0] > 0 for v in full) else float('nan'),
                onset_hit=float(np.mean(hit)) if hit else float('nan'),
                false_alarm_hours=f'{fa}/{n0}' if n0 else '—', n_hours=len(full))


def summarize_days(ts, pred, mask):
    """逐日：有偵測到泵的小時比例、運轉分鐘中位、最常見的開泵分鐘與其佔比。"""
    out = []
    dates = np.array([t.date() for t in ts])
    for d in sorted(set(dates[mask])):
        sel = mask & (dates == d)
        ii = np.flatnonzero(sel)
        if len(ii) < 600:
            continue
        hrs = {}
        for i in ii:
            k = ts[i].hour
            h = hrs.setdefault(k, [0, []])
            h[0] += int(pred[i])
            if pred[i] and (i == 0 or not pred[i - 1]):
                h[1].append(ts[i].minute)
        runs = [v[0] for v in hrs.values() if v[0] > 0]
        onsets = [m for v in hrs.values() for m in v[1]]
        mode = int(np.bincount(onsets, minlength=60).argmax()) if onsets else None
        share = (np.mean([abs(m - mode) <= 1 or abs(m - mode) >= 59 for m in onsets])
                 if onsets else 0.0)
        out.append(dict(day=str(d), hours=len(hrs), hours_with_pump=len(runs),
                        med_run=float(np.median(runs)) if runs else 0.0,
                        onset_mode=mode, onset_mode_share=float(share)))
    return out


def apply_unlabeled(ts, dp, dorp, dph, gap, refill, y, pid, device):
    """用全部有標籤的資料訓練最終 Bi-LSTM，套到沒有可信標籤的期間。

    ⚠ 這是探索，不是驗證：沒有真相可比。判讀看兩件事——
      (1) 偵測到的開泵分鐘是否集中在同一分（＝有固定時刻表）；
      (2) 無泵期（3 月）的同一張表當對照，報出來的量就是這個模型的雜訊底。
    """
    X = features(dp, dorp, dph, gap, 'all')
    lab = pid >= 0
    S, Y, _ = make_seqs(X, y, lab, stride=30)
    net = train_lstm(S, Y, bidir=True, device=device)
    dates = np.array([t.date() for t in ts])
    res = {}
    groups = [(n, a, b) for n, a, b in APPLY]
    groups += [('ref_nopump', PERIODS[0][2], PERIODS[0][3])]
    groups += [('ref_' + n, a, b) for n, tau, a, b in PERIODS if tau is not None]
    for name, a, b in groups:
        m = (dates >= a) & (dates <= b) & ~gap
        if not m.any():
            continue
        prob = predict_lstm(net, X, m, device)
        pred = (prob.argmax(1) == 1) & m
        days = summarize_days(ts, pred, m)
        res[name] = days
        hw = [d['hours_with_pump'] / max(d['hours'], 1) for d in days]
        sh = [d['onset_mode_share'] for d in days]
        rn = [d['med_run'] for d in days if d['hours_with_pump']]
        print('  %-14s %3d 天　有泵小時比例 中位 %.2f　運轉中位 %4.1f 分　開泵分鐘集中度 中位 %.2f'
              % (name, len(days), np.median(hw) if hw else 0, np.median(rn) if rn else 0,
                 np.median(sh) if sh else 0))
    return res


# ══════════════════════════════════════════════════════════
def main():
    qa = '--qa' in sys.argv
    device = os.environ.get('ML_DEVICE', 'cpu')
    t0 = time.time()
    ts, p, orp, ph = load_all()
    print('讀入 %d 筆　%s ~ %s（%.1f 秒）' % (len(ts), ts[0], ts[-1], time.time() - t0))
    dp, dorp, dph, gap, refill = increments(ts, p, orp, ph)
    y, pid, table = build_labels(ts, dp, gap, refill)
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, 'label_table.json'), 'w', encoding='utf-8') as f:
        json.dump(table, f, ensure_ascii=False, indent=1)
    if qa:
        return

    # 無泵期切兩半：前半訓練、後半當負對照測試（避免負對照被模型看過）
    k_off = [k for k, P in enumerate(PERIODS) if P[1] is None][0]
    off_idx = np.flatnonzero(pid == k_off)
    off_test = np.zeros(len(ts), bool)
    off_test[off_idx[len(off_idx) // 2:]] = True

    results = []
    for kt, (name, tau, d0, d1) in enumerate(PERIODS):
        if tau is None:
            continue
        test = (pid == kt)
        if test.sum() == 0:
            continue
        train = (pid >= 0) & ~test & ~off_test
        print('\n══ 留出 %s（τ=%d）：訓練 %d 分鐘、測試 %d 分鐘 ══' % (name, tau, train.sum(), test.sum()))
        for chans in ('all', 'pressure'):
            X = features(dp, dorp, dph, gap, chans)
            Str, Ytr, _ = make_seqs(X, y, train, stride=30)
            row = dict(heldout=name, tau=tau, channels=chans)
            for model in ('BiLSTM', 'LSTM'):
                t1 = time.time()
                net = train_lstm(Str, Ytr, bidir=(model == 'BiLSTM'), device=device)
                prob_t = predict_lstm(net, X, test, device)
                prob_o = predict_lstm(net, X, off_test, device)
                pred_t = (prob_t.argmax(1) == 1).astype(int)
                pred_o = (prob_o.argmax(1) == 1).astype(int)
                mt = metrics(pred_t, y, ts, test)
                fa_min = float(pred_o[off_test & (y == 0)].mean()) if (off_test & (y == 0)).any() else float('nan')
                row[model] = dict(**mt, nopump_fa_minute_rate=fa_min, sec=round(time.time() - t1, 1))
                print('  %-6s %-8s F1 %.3f　啟動±1 %.2f　運轉 真%.0f/估%.0f 分　|誤差| %.1f　無泵期假警報 %.4f　%.0f 秒'
                      % (model, chans, mt['f1'], mt['onset_hit'], mt['med_run_true'], mt['med_run_pred'],
                         mt['mae_run'], fa_min, time.time() - t1))
            if chans == 'all':
                # 非深度基準：梯度提升（前後 10 分鐘視窗）
                from sklearn.ensemble import HistGradientBoostingClassifier
                W = window_feats(X)
                tr = train & (y >= 0)
                clf = HistGradientBoostingClassifier(max_iter=300, class_weight='balanced',
                                                     random_state=0).fit(W[tr], y[tr])
                pg_t = (clf.predict(W) == 1).astype(int)
                mt = metrics(pg_t, y, ts, test)
                fa_min = float(pg_t[off_test & (y == 0)].mean())
                row['GBM'] = dict(**mt, nopump_fa_minute_rate=fa_min)
                print('  %-6s %-8s F1 %.3f　啟動±1 %.2f　運轉 真%.0f/估%.0f 分　|誤差| %.1f　無泵期假警報 %.4f'
                      % ('GBM', chans, mt['f1'], mt['onset_hit'], mt['med_run_true'], mt['med_run_pred'],
                         mt['mae_run'], fa_min))
                # 規則基準
                pr = rule_per_hour(dp, ts, test & ~gap & ~refill)
                po = rule_per_hour(dp, ts, off_test & ~gap & ~refill)
                mt = metrics(pr, y, ts, test)
                fa_min = float(po[off_test & (y == 0)].mean())
                row['rule'] = dict(**mt, nopump_fa_minute_rate=fa_min)
                print('  %-6s %-8s F1 %.3f　啟動±1 %.2f　運轉 真%.0f/估%.0f 分　|誤差| %.1f　無泵期假警報 %.4f'
                      % ('規則', '壓力', mt['f1'], mt['onset_hit'], mt['med_run_true'], mt['med_run_pred'],
                         mt['mae_run'], fa_min))
            results.append(row)
    print('\n══ 套用到沒有可信標籤的期間（探索）══')
    applied = apply_unlabeled(ts, dp, dorp, dph, gap, refill, y, pid, device)
    with open(os.path.join(OUT, 'results.json'), 'w', encoding='utf-8') as f:
        json.dump(dict(device=device, seed=SEED, seq=SEQ, results=results, applied=applied),
                  f, ensure_ascii=False, indent=1, default=str)
    print('\n完成，%.0f 秒。結果 -> %s' % (time.time() - t0, OUT))


if __name__ == '__main__':
    main()
