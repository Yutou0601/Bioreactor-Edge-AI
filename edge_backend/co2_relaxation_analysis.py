"""
CO2 溶解 / 生物消耗分離 —— 弛豫振盪器分析
==========================================
2026-07-16 產出。這支腳本記錄的是今天唯一通過驗證的分離路徑，以及沿途證偽掉的
兩條死路（都保留在程式碼裡，避免之後有人重蹈覆轍）。

背景：先前所有嘗試（質量守恆、pH 機制方程式+MOGA、進氣劑量迴歸、K-means 分群）
在嚴謹驗證下皆失敗，詳見 docs/日報_2026-07-16.md。本腳本從「封閉窗口的壓力衰減
曲線形狀」重新切入。

--- 發現 1（結構性事實，已驗證）-----------------------------------------
反應槽本質是「固定振幅的弛豫振盪器」：控制器灌到上限(~1.08)，等壓力掉到下限
(~0.71)就自動補氣。實測 56 個封閉窗口：
    起始壓力 中位數 1.080 (IQR 1.050~1.080)
    結束壓力 中位數 0.710 (IQR 0.710~0.720)
    總壓降   中位數 0.360 (IQR 0.338~0.370)  ← 被控制器鎖死，幾乎不帶資訊
    窗口長度 中位數 21.2 hr (範圍 6.4~29.8)  ← 變異 4.7 倍，唯一帶生物資訊的量
「總壓降」是控制器設定值、不是動力學結果；唯一的自由變數是「花多久掉完」。
任何以「壓降大小」為目標的分析都注定失敗——這解釋了先前多次挫敗的共同根因。

--- 死路 1（已證偽，勿重試）---------------------------------------------
單一窗口內擬合 p(t)=pinf+A*exp(-k*t)-B*t，想用「指數(溶解)vs 線性(生物)」的
形狀差異分離。結果：BIC 雖偏好雙分量模型(50/56)，但 k 與 B 的參數相關係數中位數
高達 0.965 —— 兩分量在單一窗口內完全共線、不可辨識(tau 從 59 飄到 25 萬分鐘)。
見 fit_single_window_UNIDENTIFIABLE()。

--- 死路 2（已證偽，勿重試）---------------------------------------------
改用全域共用 k 的剖面似然(profile likelihood)後，k 確實被資料決定
(tau*=425 min，剖面有明確谷底，split-half 370/488 min 重現性尚可)，且逐窗口解出的
A、B 全部 56/56 為正、方向物理合理。**但未通過決定性檢定**：
    corr(B, 平凡基準 總壓降/時間) = +0.816
    B vs ORP | 控制平凡基準 : rho=-0.008, p=0.954  ← B 無任何超出平凡基準的資訊
    平凡基準 vs ORP | 控制 B : rho=+0.509, p=0.0001 ← 平凡基準反而比 B 更好
即：分解出的 B 只是「總壓降/時間」的重新包裝。因總壓降被控制器鎖死(發現1)，
naive rate ≈ 常數/時間，分解等於在拆一個常數。見 profile_k() / decompose_at_k()。

--- 死路 3（已證偽，勿重試）---------------------------------------------
依洪博報告「每小時循環5分鐘，作動時壓力會下降，停止時壓力會回升」，嘗試從
每小時循環的精細結構分離（循環=強制溶解；停止後回升=脫氣，回升的缺口=生物吃掉的）。
  - 週期圖確實在 ~61.6 min 有峰(pH 5.67x 背景)，且**通過濾波器假象檢定**：改變
    高通窗長(121/151/181/241/301)峰位置不動(61.1~61.6)，不隨假象位置 W/3 移動，
    連完全不濾波都還在。→ 頻譜訊號本身可能是真的。
  - **但無法取出波形**：以時鐘分鐘摺疊全是雜訊(因週期是 61.6 而非整 60，控制器
    用自己的計時器、相對時鐘漂移)；改用「逐窗口估相位再對齊」後雖看似出現顯著
    波形(pH 3.88 sigma)，**但代理資料(相位隨機化)檢定 p=0.850** —— 真實資料
    甚至不如雜訊(中位數 4.45)。該波形純屬「用資料估相位再依該相位對齊」的
    程序假象(自我實現)。任何相位對齊分析都必須先過 surrogate 檢定。

--- 發現 3（關鍵限制，直接決定新實驗規格）------------------------------
現有儀器解析度**不足以**解析循環精細結構，這是死路 3 的根因，也是使用者提出的
三個特徵(進氣後未下降/循環開始小幅下降/每次循環後下降量)無法從舊資料萃取的原因：
    pH  感測器解析度 0.0100，循環訊號振幅 ~0.0023  → 訊號僅為解析度的 0.23 倍（低於 1 個 LSB！）
    壓力感測器解析度 0.0100，循環凹陷 ~0.02(洪博報告) → 僅 2 個量化級
    取樣 1 筆/分鐘，循環僅 5 分鐘             → 每次事件只有 5 個點
之所以在頻譜上還隱約看得到，是因為疊加數千筆量化樣本靠 dither 效應能回收次-LSB
訊號；但**逐事件分析所需的解析度根本不存在**。
→ 新實驗若要走「循環精細結構」這條路，必須提升規格：壓力解析度 0.001、
  pH 解析度 0.001、循環事件期間取樣 10 秒/筆。此為可行性前提，不是加分項。

--- 發現 2（目前唯一站得住腳的分離，但 n=1，需新實驗確認）---------------
2026-04-07 資料中存在一次體制轉換（推測為換液，**待洪博確認當天實際操作**），
其後 9 天呈現乾淨的單調恢復曲線：
    週期長度 8.0 → 20.2 hr 單調拉長
    ORP     647 → 583 mV  單調下降
    (窗口長度 vs ORP: rho=-0.768, p=0.0005)
關鍵反證：若變慢是「菌群恢復中」，速率應**越來越快**；實測**越來越慢**，故快速
起始不可能是生物造成的，只能是物理溶解進入未飽和的新鮮液體。

物理框架：穩態下菌群持續消耗溶解態 CO2、使液相維持未飽和，從而驅動溶解，
故穩態「溶解通量 = 生物消耗通量」（同一個通量，本質上不可分離）；換液後液相
遠離飽和，溶解有巨大驅動力、**淨累積**溶解態 CO2，超出穩態的部分即為純物理溶解。
    穩態速率(生物限制通量) = 0.0133 kg/cm²/hr
    恢復期首週期 = 0.0449 (穩態 3.38 倍)，末週期 = 0.0178 (1.34 倍，趨近飽和)
    恢復期總壓降 5.190 → 填充溶解池 2.522 (48.6%) / 生物消耗 2.668 (51.4%)
見 estimate_split_from_transient()。

--- 發現 2 的已知限制（務必連同結果一起報告）---------------------------
1. n=1：僅此一次體制轉換，未重複驗證。
2. 競爭假說未完全排除：「換液帶入新養分→生物爆發→養分耗盡而衰減」同樣預測
   快→慢。目前僅靠「快速期 ORP 最高(647，氧化態，不利產甲烷菌)」這點反對它，
   非決定性證據。要排除需知道 04-07 究竟做了什麼操作。
3. 「穩態＝液相飽和＝溶解通量等於生物通量」這個準穩態假設，無法用現有資料驗證。
4. 04-07 當天原始資料可見 09:24 一次排氣、11:17 一次補氣，但**看不出是否換液**，
   換液屬推測。→ 這是最高優先的待確認事項。

使用方式：
    python co2_relaxation_analysis.py --folder "Testing_data/0301-0416_無循環與有循環_5mins"
"""

import argparse
import sys

import numpy as np
import pandas as pd
from scipy import stats

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import co2_separation_analysis as sep

SMOOTH_MIN = 30          # 壓力解析度僅 0.01，先滾動平均壓掉量化雜訊
MIN_WINDOW_ROWS = 200
MIN_DROP = 0.05
INTAKE_JUMP = 0.03       # 反應槽壓力單步跳升超過此值 = 補氣事件


def extract_closed_windows(df: pd.DataFrame) -> list:
    """切出「兩次補氣之間、無新氣體注入」的封閉窗口。在這種窗口內反應槽近似封閉
    系統，壓力單調下降只來自溶解與生物消耗，是唯一能談分離的乾淨區段。"""
    df = df.sort_values('timestamp').reset_index(drop=True)
    rp = df['reactor_pressure'].values.astype(float)
    bounds = np.concatenate([[0], np.where(np.diff(rp, prepend=rp[0]) > INTAKE_JUMP)[0], [len(df) - 1]])

    windows = []
    for a, b in zip(bounds[:-1], bounds[1:]):
        seg = df.iloc[a + 1:b]                       # 跳過補氣那一筆
        if len(seg) < MIN_WINDOW_ROWS:
            continue
        p = seg['reactor_pressure'].values.astype(float)
        if p[0] - p[-1] < MIN_DROP:
            continue
        ps = pd.Series(p).rolling(SMOOTH_MIN, center=True, min_periods=SMOOTH_MIN // 2).mean().values
        ok = ~np.isnan(ps)
        windows.append((np.arange(len(p), dtype=float)[ok], ps[ok], seg))
    return windows


def summarize_oscillator(windows: list) -> pd.DataFrame:
    """發現 1：驗證反應槽是固定振幅弛豫振盪器（總壓降被控制器鎖死）。"""
    rows = []
    for t, y, seg in windows:
        p = seg['reactor_pressure'].values.astype(float)
        rows.append({
            'start':    seg['timestamp'].iloc[0],
            'p_start':  p[0],
            'p_end':    p[-1],
            'drop_kg':  p[0] - p[-1],
            'dur_hr':   len(seg) / 60.0,
            'rate':     (p[0] - p[-1]) / (len(seg) / 60.0),
            'orp_mean': float(np.nanmean(seg['ORP (mV)'].values.astype(float))),
        })
    return pd.DataFrame(rows).sort_values('start').reset_index(drop=True)


def profile_k(windows: list, ks=None) -> tuple:
    """死路 2：全域共用 k 的剖面似然。對固定 k，模型 p=pinf+A*exp(-k t)-B*t 對
    (pinf,A,B) 是線性的，可逐窗口 OLS 解析求解，故能精確掃描 k 並看出它是否
    真的被資料決定（谷底 vs 平坦）。k 之所以要全域共用：它是反應槽的傳質係數，
    是物理性質，同一批循環設定下沒有理由每個窗口不同；不共用就會與 B 共線。"""
    if ks is None:
        ks = np.geomspace(1e-5, 1e-1, 200)

    def rss_at(k):
        tot = 0.0
        for t, y, _ in windows:
            X = np.column_stack([np.ones_like(t), np.exp(-k * t), -t])
            beta, *_ = np.linalg.lstsq(X, y, rcond=None)
            tot += float(np.sum((y - X @ beta) ** 2))
        return tot

    rss = np.array([rss_at(k) for k in ks])
    return ks[np.argmin(rss)], ks, rss


def decompose_at_k(windows: list, k: float) -> pd.DataFrame:
    """死路 2 的逐窗口分解結果。保留供重現，但**不要拿來當結論**：B 已證實
    無超出 naive rate 的資訊（見檔頭）。"""
    rows = []
    for t, y, seg in windows:
        X = np.column_stack([np.ones_like(t), np.exp(-k * t), -t])
        (pinf, A, B), *_ = np.linalg.lstsq(X, y, rcond=None)
        T = t[-1]
        rows.append({
            'start':      seg['timestamp'].iloc[0],
            'A':          A,
            'B':          B,
            'diss_total': A * (1 - np.exp(-k * T)),
            'bio_total':  B * T,
            'total_drop': y[0] - y[-1],
            'dur_hr':     len(seg) / 60.0,
            'orp_mean':   float(np.nanmean(seg['ORP (mV)'].values.astype(float))),
        })
    return pd.DataFrame(rows)


def _partial_spearman(x, y, z):
    """控制 z 後 x,y 的偏相關（秩迴歸殘差法）。這是揭穿死路 2 的關鍵工具：
    任何新指標都必須證明自己帶有「平凡基準」以外的資訊。"""
    xr, yr, zr = stats.rankdata(x), stats.rankdata(y), stats.rankdata(z)
    Z = np.column_stack([np.ones_like(zr), zr])
    rx = xr - Z @ np.linalg.lstsq(Z, xr, rcond=None)[0]
    ry = yr - Z @ np.linalg.lstsq(Z, yr, rcond=None)[0]
    return stats.pearsonr(rx, ry)


def decisive_test(dec: pd.DataFrame) -> None:
    """決定性檢定：分解出的 B 是否真的優於平凡基準（總壓降/時間）。
    死路 2 就是敗在這裡。任何未來的新方法都應該先過這一關。"""
    naive = dec.total_drop / dec.dur_hr
    print(f"  corr(B, naive rate)              = {dec.B.corr(naive):+.3f}")
    rho, p = _partial_spearman(dec.B.values, dec.orp_mean.values, naive.values)
    print(f"  B vs ORP | 控制 naive rate       : rho={rho:+.3f} p={p:.4f}"
          f"  {'← B 帶有額外資訊' if p < 0.05 else '← B 無額外資訊（方法失敗）'}")
    rho, p = _partial_spearman(naive.values, dec.orp_mean.values, dec.B.values)
    print(f"  naive rate vs ORP | 控制 B       : rho={rho:+.3f} p={p:.4f}"
          f"  {'← 平凡基準反而更好' if p < 0.05 else ''}")


def estimate_split_from_transient(osc: pd.DataFrame,
                                   ss_start='2026-03-20', ss_end='2026-04-07',
                                   rec_start='2026-04-07', rec_end='2026-04-15 23:59',
                                   ss_min_dur_hr=20.0) -> dict:
    """發現 2：用 04-07 體制轉換這個「天然實驗」估算溶解 vs 生物。

    邏輯：穩態下液相已飽和，菌群消耗溶解態 CO2 驅動溶解，兩者是同一通量
    （不可分離），此通量即為穩態速率。換液後液相遠離飽和，溶解淨累積，
    超出穩態速率的部分即為純物理溶解填充溶解池的量。
    """
    ss = osc[(osc.start >= ss_start) & (osc.start < ss_end) & (osc.dur_hr > ss_min_dur_hr)]
    if len(ss) < 3:
        raise ValueError(f"穩態基準窗口不足 (n={len(ss)})")
    ss_rate = float(ss.rate.median())

    rec = osc[(osc.start >= rec_start) & (osc.start <= rec_end)].copy()
    if len(rec) < 3:
        raise ValueError(f"恢復期窗口不足 (n={len(rec)})")
    rec['excess_rate'] = rec.rate - ss_rate
    rec['excess_amt'] = rec.excess_rate * rec.dur_hr

    pool = float(rec.excess_amt.sum())
    total = float(rec.drop_kg.sum()) if 'drop_kg' in rec else float((rec.rate * rec.dur_hr).sum())
    return {
        'ss_rate': ss_rate, 'ss_n': len(ss),
        'rec': rec, 'rec_n': len(rec),
        'total_drop': total,
        'dissolution_pool': pool, 'dissolution_frac': pool / total,
        'biological': total - pool, 'biological_frac': 1 - pool / total,
        'first_ratio': float(rec.rate.iloc[0] / ss_rate),
        'last_ratio': float(rec.rate.iloc[-1] / ss_rate),
    }


def main():
    ap = argparse.ArgumentParser(description="CO2 溶解/生物消耗分離：弛豫振盪器分析")
    ap.add_argument('--folder', default='Testing_data/0301-0416_無循環與有循環_5mins')
    ap.add_argument('--run-deadends', action='store_true',
                    help="一併重跑兩條已證偽的死路（預設跳過，見檔頭說明）")
    args = ap.parse_args()
    pd.set_option('display.width', 200)

    df = sep.load_folder_combined(args.folder)
    windows = extract_closed_windows(df)
    print(f"封閉窗口數: {len(windows)}\n")

    osc = summarize_oscillator(windows)
    print("=== 發現 1：反應槽是固定振幅弛豫振盪器 ===")
    print(osc[['p_start', 'p_end', 'drop_kg', 'dur_hr']].describe().round(3).to_string())
    print(f"\n  總壓降被控制器鎖死 (IQR {osc.drop_kg.quantile(.25):.3f}~{osc.drop_kg.quantile(.75):.3f})，"
          f"窗口長度變異 {osc.dur_hr.max()/osc.dur_hr.min():.1f} 倍 ← 資訊在時間裡，不在壓降裡")

    if args.run_deadends:
        print("\n=== 死路 2 重現：全域 k 剖面似然 + 決定性檢定 ===")
        k_star, ks, rss = profile_k(windows)
        print(f"  k* = {k_star:.6f} /min  → tau = {1/k_star:.1f} min ({1/k_star/60:.2f} hr)")
        print(f"  剖面 RSS: 最佳 {rss.min():.4f} vs 兩端 {rss[0]:.4f}/{rss[-1]:.4f} → k 有被資料決定")
        dec = decompose_at_k(windows, k_star)
        print(f"  A>0 的窗口 {(dec.A>0).sum()}/{len(dec)}，B>0 的窗口 {(dec.B>0).sum()}/{len(dec)}（方向皆合理）")
        print("  但決定性檢定：")
        decisive_test(dec)
        print("  → 結論：分解無效，B 只是 naive rate 的重新包裝。")

    print("\n=== 發現 2：用 04-07 體制轉換估算溶解 vs 生物 ===")
    try:
        res = estimate_split_from_transient(osc)
    except ValueError as e:
        print(f"  無法估算：{e}")
        return
    print(f"  穩態基準 (n={res['ss_n']}): {res['ss_rate']:.5f} kg/cm²/hr  ← 溶解通量=生物通量，不可分離")
    print(f"  恢復期 (n={res['rec_n']}): 首週期為穩態 {res['first_ratio']:.2f} 倍 → 末週期 {res['last_ratio']:.2f} 倍")
    print()
    print(res['rec'][['start', 'dur_hr', 'rate', 'excess_rate', 'excess_amt', 'orp_mean']].round(4).to_string(index=False))
    print()
    print(f"  恢復期總壓降     = {res['total_drop']:.3f} kg/cm²")
    print(f"  ├ 填充溶解池(物理) = {res['dissolution_pool']:.3f} ({res['dissolution_frac']:.1%})")
    print(f"  └ 生物消耗        = {res['biological']:.3f} ({res['biological_frac']:.1%})")

    rho, p = stats.spearmanr(res['rec'].dur_hr, res['rec'].orp_mean)
    print(f"\n  恢復期 窗口長度 vs ORP: rho={rho:+.3f} p={p:.4f}")
    print("  關鍵反證：若變慢是菌群恢復中，速率應越來越快；實測越來越慢，"
          "故快速起始非生物所致。")
    print("\n  ⚠ 限制：n=1、換液屬推測、準穩態假設未驗證。詳見檔頭「發現 2 的已知限制」。")


if __name__ == '__main__':
    main()
