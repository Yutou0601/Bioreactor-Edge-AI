"""
用 NSGA-II 多目標啟發式演算法，從連續、可信的 pH／壓力訊號去反推
CO2 溶解速率 r_d(t) 與生物消耗速率 r_b(t) 的相對大小，不依賴 CO2%/CH4%
感測器讀數（2026-07-16 跟洪博確認：CH4 產出緩慢、人工排氣時機不準、
分析儀取樣管路本身還有延遲拖尾，讀數不可信，不能當標籤用）。

⚠ 2026-07-16 依洪博研究報告修正：本檔的 pH 機制假設是**單向**的（pH 只反映溶解），
   這是錯的。洪博報告明確記載：「pH 會先**酸**變化，應該是 CO2 溶入液體中，再經
   菌種反應後會往**鹼**變化」——pH 是**雙向**訊號：溶解→酸、生物消耗→鹼。
   這解釋了為何本檔所有 pH 相關的擬合都測不出東西（把雙向訊號當單向線性代理）。
   新實驗資料進來後，pH 模型應改為雙向形式，勿沿用本檔的單向假設。

機制假設（**已知有誤，見上方修正**）：
  - pH 下降主要來自 CO2 溶入水中酸化，H2 短時間內幾乎不溶、不貢獻 pH 變化
    （AHPD 文獻普遍觀察一致：pH 隨壓力上升下降，因 CO2 過量溶解）。
    2026-07-16 修正：pH 定義是 -log[H+]，本身已是對數尺度，直接用 pH 差值
    線性代表溶解量在數學上只有小變化時才成立；改用 [H+] 濃度本身
    （= 10^(-pH)）的變化量當代理，才是真正線性對應「濃度」變化：
        r_d(t) = k_ph * h_slope(t)，h(t) = 10^(-ph_smooth(t))
  - 氣相總消耗速率 = 溶解 + 生物反應對氣相的淨效應：
        -pressure_slope(t) = r_d(t) + coef * r_b(t)
        → r_b(t) = ( -pressure_slope(t) - r_d(t) ) / coef

2026-07-16 第一版只用「r_d 非負」「r_b 非負」當兩個目標，結果退化：coef 只是
把 r_b 整體等比例縮放，不改變正負號，所以 GA 會鑽漏洞把 coef 推到邊界把
違反量除小，不是真的找到有意義的解；同理 r_d 正負只取決於 pH 斜率正負號，
跟 k_ph 大小無關。相關係數、正負號比例這類目標對純縮放（coef、m_orp 這種
只影響量級不影響形狀的參數）不敏感，所以 coef 這種「只決定量級」的參數
本質上無法只靠訊號形狀去反推校正，只能取化學計量比的候選值（3/4/5）分別
測，不當自由變數。真正該搜索的是 k_ph（決定 r_d、r_b 這兩條時間序列的
「形狀」怎麼從壓力斜率跟 pH 斜率的組合中被分出來）。

第二版改用 ORP 斜率（平滑過）當獨立第三方訊號校正 k_ph：依照舊研究相位
定義，Phase 1（ORP 斜率急降）對應嗜氫甲烷菌消耗 H2/CO2 最活躍的時候，
所以生物消耗速率應該跟「ORP 下降的快慢」正相關：
        r_b_orp_proxy(t) ∝ -orp_slope(t)
兩個目標：
  1. r_b(t)（由壓力+pH 模型算出）違反非負的比例——最小化
  2. r_b(t) 跟 -orp_slope(t) 的相關係數之負值（1 − corr）——最小化，
     也就是要求由壓力+pH 反推出的生物消耗速率，形狀要盡量吻合 ORP 這個
     獨立訊號描述的生物活躍程度
這兩個目標都是 k_ph 的非平凡函數（前者決定 r_b 的正負號分布，後者決定
r_b(t) 這條曲線的形狀），不會被參數縮放鑽漏洞，才是真正有意義的多目標
權衡，交給 NSGA-II 找 Pareto front，不加權合成單一數字硬解。coef 固定用
3/4/5 分別跑，當敏感度分析，不放進決策變數。

**已知限制（2026-07-16 自我檢討，尚未解決，留給新實驗資料驗證）**：
目標 2（跟 ORP 相關性）完全由「壓力＋pH」這組訊號自己算出來，沒有任何
外部獨立標籤可以驗證——如果最佳解落在 k_ph≈0（pH 幾乎不貢獻），相關性
其實主要是「壓力本身跟 ORP 相關」這個早就預期的關係，不代表真的驗證了
溶解/消耗的分離是否正確。程式會額外印出 k_ph=0（純壓力 baseline）的
相關係數，方便直接比對「加入 pH 之後有沒有真的比 baseline 更好」，但
這只能排除「更差」，不能證明「更對」——真正的驗證仍要等新實驗的短窗口
真值資料。

使用方式：
    python co2_moga_calibration.py --folder "Testing_data/0301-0416_無循環與有循環_5mins"
    python co2_moga_calibration.py --folder "..." --pop 60 --gen 80
"""

import argparse
import sys

import numpy as np
import pandas as pd

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from pymoo.algorithms.moo.nsga2 import NSGA2
from pymoo.core.problem import Problem
from pymoo.operators.crossover.sbx import SBX
from pymoo.operators.mutation.pm import PM
from pymoo.operators.sampling.rnd import FloatRandomSampling
from pymoo.optimize import minimize
from scipy.signal import savgol_filter

import co2_separation_analysis as sep


def prepare_signals(df: pd.DataFrame, smooth_window_min: int = 60, method: str = 'rolling_mean',
                     sg_polyorder: int = 2) -> pd.DataFrame:
    """把壓力/pH/ORP 轉成斜率（單位 /hr），供後續模型使用。

    2026-07-16 加入 method 選項：原本的 60 分鐘滾動平均是比照舊研究宏觀相位
    偵測的設計，用在這裡（要看短期溶解/消耗動態）太鈍，會把細節洗掉——這也是
    第一輪 MOGA 結果顯示 pH 完全沒貢獻的可能原因之一，不一定是機制假設本身
    的問題。改用 Savitzky-Golay 濾波器（`method='savgol'`）直接估斜率
    （scipy `deriv=1`），不用先平滑再差分，保留形狀又比原始訊號乾淨，視窗
    可以開比 60 分鐘小很多（例如舊研究用的 11 分鐘）去保留更多細節。
    """
    df = df.sort_values('timestamp').reset_index(drop=True)
    cols = {'reactor_pressure': 'pressure', '酸鹼值 (pH)': 'ph', 'ORP (mV)': 'orp'}

    if method == 'savgol':
        w = smooth_window_min if smooth_window_min % 2 == 1 else smooth_window_min + 1
        for src, name in cols.items():
            df[f'{name}_smooth'] = savgol_filter(df[src].to_numpy(), window_length=w, polyorder=sg_polyorder)
            df[f'{name}_slope_per_hr'] = savgol_filter(
                df[src].to_numpy(), window_length=w, polyorder=sg_polyorder, deriv=1, delta=1.0) * 60
    elif method == 'rolling_mean':
        for src, name in cols.items():
            df[f'{name}_smooth'] = df[src].rolling(smooth_window_min, min_periods=smooth_window_min // 2).mean()
            df[f'{name}_slope_per_hr'] = df[f'{name}_smooth'].diff() * 60
    else:
        raise ValueError(f"未知的 method：{method}（可選 'rolling_mean' 或 'savgol'）")

    df['h_conc_smooth'] = 10.0 ** (-df['ph_smooth'])   # [H+] 濃度代理，pH 是對數尺度不能直接當線性代理用
    df['h_slope_per_hr'] = -np.log(10.0) * df['h_conc_smooth'] * df['ph_slope_per_hr']  # d(10^-pH)/dt 鏈式法則
    return df.dropna(subset=['pressure_slope_per_hr', 'h_slope_per_hr', 'orp_slope_per_hr']).reset_index(drop=True)


def _r_b(k_ph: float, coef: float, h_slope: np.ndarray, pressure_slope: np.ndarray) -> np.ndarray:
    # h_slope > 0 代表 [H+] 上升（酸化）= 正在溶解，跟 r_d 同向，不用像 ph_slope 那樣反號
    r_d = k_ph * h_slope
    return (-pressure_slope - r_d) / coef


class DissolutionReactionProblem(Problem):
    """決策變數：[k_ph]（coef 為化學計量比候選值，外部固定傳入，不放進搜索
    ——見檔案開頭說明，純縮放參數對這兩個目標都不可辨識）。

    目標 1：r_b(t) 違反非負的比例（物理上不該為負）——最小化
    目標 2：1 − corr(r_b(t), −orp_slope(t))——最小化，也就是要求由壓力+pH
    反推出的生物消耗速率，形狀要盡量吻合 ORP 這個獨立訊號（ORP 下降越快，
    依照舊研究相位定義代表菌群消耗 H2/CO2 越活躍）。
    兩者都是 k_ph 的非平凡函數，才是真正的多目標權衡。
    """

    def __init__(self, h_slope: np.ndarray, pressure_slope: np.ndarray, orp_slope: np.ndarray, coef: float):
        super().__init__(n_var=1, n_obj=2, n_constr=0, xl=np.array([0.0]), xu=np.array([2e8]))
        self.h_slope = h_slope
        self.pressure_slope = pressure_slope
        self.orp_signal = -orp_slope
        self.coef = coef

    def _evaluate(self, X, out, *args, **kwargs):
        n = X.shape[0]
        f1 = np.empty(n)
        f2 = np.empty(n)
        for i in range(n):
            k_ph = X[i, 0]
            r_b = _r_b(k_ph, self.coef, self.h_slope, self.pressure_slope)
            f1[i] = np.mean(r_b < 0)
            corr = np.corrcoef(r_b, self.orp_signal)[0, 1]
            f2[i] = 1.0 - (corr if np.isfinite(corr) else -1.0)
        out["F"] = np.column_stack([f1, f2])


def run_moga(h_slope: np.ndarray, pressure_slope: np.ndarray, orp_slope: np.ndarray, coef: float,
             pop_size: int = 40, n_gen: int = 60, seed: int = 1):
    problem = DissolutionReactionProblem(h_slope, pressure_slope, orp_slope, coef)
    algorithm = NSGA2(
        pop_size=pop_size,
        sampling=FloatRandomSampling(),
        crossover=SBX(prob=0.9, eta=15),
        mutation=PM(eta=20),
        eliminate_duplicates=True,
    )
    res = minimize(problem, algorithm, ('n_gen', n_gen), seed=seed, verbose=False)
    return res


def summarize_pareto_front(res, h_slope: np.ndarray, pressure_slope: np.ndarray,
                            orp_slope: np.ndarray, coef: float) -> pd.DataFrame:
    orp_signal = -orp_slope
    rows = []
    for x, f in zip(res.X, res.F):
        k_ph = float(x[0])
        r_b = _r_b(k_ph, coef, h_slope, pressure_slope)
        corr = np.corrcoef(r_b, orp_signal)[0, 1]
        rows.append({
            'coef':             coef,
            'k_ph':             k_ph,
            'r_b_neg_fraction': round(float(f[0]), 4),
            'corr_with_orp':    round(float(corr), 4),
            'r_b_mean':         round(float(np.mean(r_b)), 6),
        })
    return pd.DataFrame(rows).sort_values('k_ph').drop_duplicates()


def baseline_corr(pressure_slope: np.ndarray, orp_slope: np.ndarray, coef: float) -> float:
    """k_ph=0（完全不採信 pH）時，純壓力反推出的 r_b 跟 ORP 的相關係數。
    拿來檢查目標 2 是不是只是在重新發現「壓力跟 ORP 本來就相關」，不是真的
    驗證了 pH 分離出來的東西有沒有價值——見檔案開頭「已知限制」說明。"""
    r_b0 = _r_b(0.0, coef, np.zeros_like(pressure_slope), pressure_slope)
    return float(np.corrcoef(r_b0, -orp_slope)[0, 1])


def main():
    parser = argparse.ArgumentParser(description="NSGA-II 反推 CO2 溶解/生物消耗速率的相對權重（不用 CO2/CH4 感測器）")
    parser.add_argument('--folder', required=True, help="Testing_data 底下的資料夾路徑")
    parser.add_argument('--smooth-window', type=int, default=60, help="平滑/濾波視窗（分鐘），預設 60")
    parser.add_argument('--smooth-method', choices=['rolling_mean', 'savgol'], default='rolling_mean',
                         help="rolling_mean（預設，宏觀平滑，比照舊研究 Step2）或 savgol（Savitzky-Golay，"
                              "直接估斜率不用先平滑再差分，視窗可以開小一點保留更多細節）")
    parser.add_argument('--sg-polyorder', type=int, default=2, help="savgol 多項式次數，預設 2（比照舊研究）")
    parser.add_argument('--pop', type=int, default=40, help="NSGA-II 族群大小")
    parser.add_argument('--gen', type=int, default=60, help="NSGA-II 世代數")
    parser.add_argument('--coef', default='3,4,5', help="化學計量比候選值，逗號分隔（不放進搜索，見檔案開頭說明）")
    args = parser.parse_args()

    print(f"1. 載入資料夾：{args.folder}")
    combined = sep.load_folder_combined(args.folder)
    print(f"   共 {len(combined):,} 筆原始資料，期間 {combined['timestamp'].iloc[0]} ~ {combined['timestamp'].iloc[-1]}")

    print(f"2. 計算斜率（method={args.smooth_method}, window={args.smooth_window} min）...")
    prepared = prepare_signals(combined, smooth_window_min=args.smooth_window,
                                method=args.smooth_method, sg_polyorder=args.sg_polyorder)
    print(f"   可用資料點：{len(prepared):,}")

    h_slope = prepared['h_slope_per_hr'].to_numpy()
    pressure_slope = prepared['pressure_slope_per_hr'].to_numpy()
    orp_slope = prepared['orp_slope_per_hr'].to_numpy()

    coef_list = [float(c) for c in args.coef.split(',')]
    pd.set_option('display.width', 200)
    all_fronts = []
    for coef in coef_list:
        base = baseline_corr(pressure_slope, orp_slope, coef)
        print(f"\n3. 執行 NSGA-II（coef={coef}, pop={args.pop}, gen={args.gen}）...")
        print(f"   baseline（k_ph=0，純壓力）跟 ORP 的相關係數 = {base:.4f} ← 加入 pH 後要比這個更好才有意義")
        res = run_moga(h_slope, pressure_slope, orp_slope, coef, pop_size=args.pop, n_gen=args.gen)
        front = summarize_pareto_front(res, h_slope, pressure_slope, orp_slope, coef)
        print(f"   Pareto front 共 {len(front)} 組解")
        print(front.to_string(index=False))
        all_fronts.append(front)

    combined_front = pd.concat(all_fronts, ignore_index=True)
    out_path = args.folder.rstrip('/\\') + '/_moga_pareto_front.csv'
    combined_front.to_csv(out_path, index=False, encoding='utf-8-sig')
    print(f"\n已輸出：{out_path}")

    best = combined_front.iloc[combined_front['r_b_neg_fraction'].argsort().iloc[0]]
    print(f"\nr_b 非負違反比例最小的解（僅供參考，不代表唯一正確答案）：")
    print(best)


if __name__ == '__main__':
    main()
