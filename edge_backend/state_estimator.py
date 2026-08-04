"""潛在速率貝氏多訊號狀態估計 — 物理溶解 vs 生物消耗之分離框架。

從壓力／ORP／pH 的變化率，估計反應器內二氧化碳去向的兩個潛在速率：
    r_d = 物理溶解率（CO2 溶入液體）
    r_b = 生物消耗率（嗜氫產甲烷 CO2 + 4H2 -> CH4 + 2H2O）

方法：線性高斯觀測模型 + 弱先驗之 MAP／加權最小平方（等價於 Kalman 量測更新）。
每個觀測帶「條件變異數」(state-dependent)：可信的訊號權重高、不可信的自動退場。

觀測模型（符號結構來自物理，量值常數 H 待校準）：
    -dP/dt   = a_P·r_d + b_P·r_b + e_P    壓力：物理與生物皆降壓 → 兩者相加、混合
     dORP/dt = a_O·r_d + b_O·r_b + e_O    ORP ：H2 溶解度極低(亨利常數約為 CO2 的 1/44)
                                          → a_O ≈ 0，ORP 近乎純生物通道（此為分離之命門）
     dpH/dt  = a_H·r_d + b_H·r_b + e_H    pH  ：溶解酸化 a_H<0 / 生物鹼化 b_H>0，反號→方向可分

────────────────────────────────────────────────────────────────────────
★ 嚴謹聲明（務必連同任何輸出一起解讀）
  1. 結構可辨識：觀測矩陣滿秩即可分 r_d,r_b；ORP 提供 a_O≈0 的獨立方程式是關鍵。
  2. 實務可辨識 = 尚未證實：取決於
       (i)  ORP 真的近純生物（a_O≈0）——但 ORP 是「混合電位」，此為近似非事實；
       (ii) 常數 H 已校準（否則僅相對、非絕對）；
       (iii) 線性化成立——Nernst 實為對數非線性，靈敏度隨 [H2] 變。
  3. 分離主張之「否證測試」＝無菌對照：無生物時估計器對 r_b 必須 ≈ 0。
     若無菌卻估到 r_b≠0，代表假設 (i) 被否證、分離失敗（見 abiotic_falsification）。
  → 通過該測試前，輸出應解讀為「結構上可辨識、相對趨勢」，非「已驗證之絕對分離」。
────────────────────────────────────────────────────────────────────────

純 numpy，無 sklearn（部署端 Application Control 政策擋 sklearn DLL）。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Sequence
import numpy as np

# 訊號索引順序
SIGNALS = ("pressure", "orp", "ph")


@dataclass
class ObservationModel:
    """觀測矩陣 H（每列 = 一個訊號的 [對 r_d 係數, 對 r_b 係數]）。

    預設為「符號結構」占位常數；calibrated=False 時輸出僅為相對量。
    校準（無菌對照定 a_H、純 CO2 定 a_H/pH 尺度、純 H2 定 b_O）後設 calibrated=True。
    """
    H: np.ndarray = field(default_factory=lambda: np.array([
        [1.0,  1.0],   # pressure: r_d + r_b
        [0.0,  1.0],   # orp     : ~ r_b        (a_O≈0：H2 低溶解)
        [-1.0, 1.0],   # ph      : -r_d + r_b
    ], dtype=float))
    calibrated: bool = False

    def rows_for(self, active: Sequence[str]) -> np.ndarray:
        idx = [SIGNALS.index(s) for s in active]
        return self.H[idx, :]


@dataclass
class Estimate:
    r_d: float
    r_b: float
    cov: np.ndarray            # 2x2 後驗協方差
    active: tuple              # 用了哪些訊號

    @property
    def sd_rb(self) -> float:
        return float(np.sqrt(self.cov[1, 1]))

    @property
    def sd_rd(self) -> float:
        return float(np.sqrt(self.cov[0, 0]))

    @property
    def max_uncertainty_sd(self) -> float:
        """後驗最大不確定方向之 sd。接近先驗 sd = 該方向不可辨識。"""
        return float(np.sqrt(np.linalg.eigvalsh(self.cov).max()))

    @property
    def phi_physical(self) -> Optional[float]:
        """物理份額 r_d/(r_d+r_b)。僅在 r_d+r_b>0 且非退化時有意義。"""
        tot = self.r_d + self.r_b
        return float(self.r_d / tot) if tot > 1e-9 else None


class StateEstimator:
    """線性高斯 + 弱先驗的貝氏速率估計器。

    prior_sd 大 → 弱先驗：不可辨識方向會呈現 ~prior_sd 之大變異（誠實地標示分不出），
    而非被 pinv 壓成 0。
    """

    def __init__(self, model: Optional[ObservationModel] = None, prior_sd: float = 10.0):
        self.model = model or ObservationModel()
        self.prior_prec = np.eye(2) / float(prior_sd) ** 2
        self.prior_sd = float(prior_sd)

    def estimate(self, obs: dict, sigma: dict) -> Estimate:
        """單點估計。

        obs   : {"pressure": -dP/dt, "orp": dORP/dt, "ph": dpH/dt}（可只給子集）
        sigma : {同鍵: 該觀測之條件標準差}（越不可信越大）
        """
        active = tuple(s for s in SIGNALS if s in obs and obs[s] is not None
                       and np.isfinite(obs[s]))
        if not active:
            cov = np.linalg.inv(self.prior_prec)
            return Estimate(0.0, 0.0, cov, active)
        H = self.model.rows_for(active)
        y = np.array([obs[s] for s in active], float)
        s = np.array([sigma.get(s, 1.0) for s in active], float)
        Rinv = np.diag(1.0 / np.clip(s, 1e-9, None) ** 2)
        prec = H.T @ Rinv @ H + self.prior_prec
        cov = np.linalg.inv(prec)
        mean = cov @ H.T @ Rinv @ y
        return Estimate(float(mean[0]), float(mean[1]), cov, active)

    def identifiability(self, active: Sequence[str]) -> float:
        """資料無關的可辨識性診斷：給定用哪些訊號，最大不確定方向之 sd。
        回傳值接近 prior_sd → 不可辨識；遠小於 → 可辨識。"""
        H = self.model.rows_for(active)
        # 以單位變異數評估「結構」可辨識性（不含資料雜訊尺度）
        prec = H.T @ H + self.prior_prec
        cov = np.linalg.inv(prec)
        return float(np.sqrt(np.linalg.eigvalsh(cov).max()))

    def abiotic_falsification(self, estimates: Sequence[Estimate],
                              tol_sd: float = 2.0) -> dict:
        """否證測試：對無菌批次的估計，檢查 r_b 是否統計上 ≈ 0。

        通過（r_b 與 0 相差 < tol_sd 個後驗 sd）→ 支持「ORP 近純生物」假設；
        未通過 → 假設被否證，分離不成立。
        """
        rbs = np.array([e.r_b for e in estimates], float)
        sds = np.array([e.sd_rb for e in estimates], float)
        zscores = rbs / np.clip(sds, 1e-9, None)
        passed = bool(np.all(np.abs(zscores) < tol_sd))
        return {
            "passed": passed,
            "mean_rb": float(rbs.mean()),
            "max_abs_z": float(np.abs(zscores).max()) if len(zscores) else 0.0,
            "verdict": ("無菌 r_b≈0，支持 ORP 生物專一假設（分離框架未被否證）"
                        if passed else
                        "無菌 r_b 顯著非 0 → ORP 生物專一假設被否證，分離不可信"),
        }


# ─────────────────────────────────────────────────────────────
# 條件變異數：由當下狀態決定各訊號可信度（可被覆寫／校準）
# ─────────────────────────────────────────────────────────────
def default_conditional_sigma(dph: float, dorp: float,
                              ph_resolution: float = 0.01) -> dict:
    """預設條件標準差模型（相對尺度）。

    - 壓力：恆定小（解析度好、恆可信），但它只約束總量。
    - ORP ：中；H2 耗盡時（|dorp| 極小）資訊變少 → 稍加大。
    - pH  ：|dph| 接近量化地板時 → sigma 爆大（近純噪聲，自動退場）。
    """
    sig_p = 0.15
    sig_o = 0.45 * (1.0 + 0.5 / (abs(dorp) + 0.3))
    # pH 訊噪：每步變化相對於解析度；擺幅越接近地板越不可信
    snr_ph = abs(dph) / (ph_resolution + 1e-9)
    sig_h = 1.10 * (1.0 + 2.0 / (snr_ph + 0.5))
    return {"pressure": sig_p, "orp": sig_o, "ph": sig_h}


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    rng = np.random.default_rng(0)
    est = StateEstimator(prior_sd=10.0)

    print("=== 可辨識性診斷（資料無關）===")
    for act in (("pressure",), ("pressure", "orp"), ("pressure", "orp", "ph")):
        print(f"  {'+'.join(act):22s} 最大不確定 sd = {est.identifiability(act):.2f}"
              + ("  ← 接近先驗=不可辨識" if est.identifiability(act) > 5 else ""))

    print("\n=== 合成資料自檢：真值 r_d=1.0, r_b=0.6 ===")
    rd_t, rb_t = 1.0, 0.6
    H = est.model.H
    truth = H @ np.array([rd_t, rb_t])
    # 加雜訊觀測
    obs = {"pressure": truth[0] + rng.normal(0, 0.15),
           "orp": truth[1] + rng.normal(0, 0.45),
           "ph": truth[2] + rng.normal(0, 0.3)}
    sig = default_conditional_sigma(dph=obs["ph"], dorp=obs["orp"])
    e_all = est.estimate(obs, sig)
    e_ponly = est.estimate({"pressure": obs["pressure"]}, sig)
    print(f"  僅壓力    : r_d={e_ponly.r_d:+.2f} r_b={e_ponly.r_b:+.2f}  "
          f"最大不確定 sd={e_ponly.max_uncertainty_sd:.2f}")
    print(f"  三訊號全用: r_d={e_all.r_d:+.2f} r_b={e_all.r_b:+.2f}  "
          f"sd(r_b)={e_all.sd_rb:.2f}  phi_physical={e_all.phi_physical:.2f}")

    print("\n=== 否證測試自檢：無菌(真值 r_b=0) ===")
    ab = []
    for _ in range(8):
        tr = H @ np.array([1.0, 0.0])   # 無生物
        o = {"pressure": tr[0] + rng.normal(0, 0.15),
             "orp": tr[1] + rng.normal(0, 0.45),
             "ph": tr[2] + rng.normal(0, 0.3)}
        ab.append(est.estimate(o, default_conditional_sigma(o["ph"], o["orp"])))
    res = est.abiotic_falsification(ab)
    print(f"  passed={res['passed']}  mean_rb={res['mean_rb']:+.3f}  "
          f"max|z|={res['max_abs_z']:.2f}\n  {res['verdict']}")
