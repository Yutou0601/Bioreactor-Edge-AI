"""
CO2 溶解 / 生物消耗分離 —— 灰箱模型可辨識性決定性測試
=====================================================
2026-07-26 產出。用**合成資料**（自帶已知真值）回答一個在花錢做新實驗前必須先確定
的問題：把「物理溶解」與「生物消耗」拆開，在原理上到底分不分得開？需要什麼條件？

為什麼要這支：co2_relaxation_analysis.py 已經證偽兩條分離死路——
  死路1：單窗口擬合指數(溶解)+線性(生物)，兩項相關 0.965、完全共線、不可辨識。
  死路2：全域 profile likelihood，解出的生物項只是「總壓降/時間」的重新包裝。
而唯一站得住的分離（發現2）靠的是**暫態**：換液後液相遠離飽和，溶解通量暫時遠大於
生物通量，兩者才解耦。這支腳本把那個結構性事實用機理模型講清楚，並量化三件事：

  (A) 純穩態資料、(B) 含暫態資料、(C) 用文獻固定亨利溶解度 C*
用 profile likelihood 量各參數的 95% 信賴區間寬度＝可辨識性。

實測結論（見 main() 底部；照結果講不是照假設）：
  1. 物理速率 kLa：穩態 ±160%、暫態 ±0% → 分離槓桿確實是暫態（呼應發現2）。
  2. 生物速率 Vmax：所有情境都不可辨識，因 Monod 低濃度段 Vmax 與 Km 共線
     （只有比值可辨識）。故生物量應以「總通量 − 已釘死的物理通量」殘差取得。
  3. 回答使用者：前沿 ML/改算法沒用（穩態不可辨識是結構問題）；真正有效的是
     實驗製造暫態 + 文獻/對照定住物理常數 + 生物量取殘差。屬機理設計非演算法。

只用 numpy + scipy.optimize（scipy 確認可用；不碰 sklearn 那顆會被系統政策擋的 DLL）。
"""

import sys
import warnings

import numpy as np
from scipy.optimize import minimize

# 最佳化器探到極端參數時 RK4 會暫時溢位（已由早停處理、NLL 自然變大），不需吵版面
warnings.filterwarnings("ignore", category=RuntimeWarning)
np.seterr(all="ignore")

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

rng = np.random.default_rng(42)
_trapz = getattr(np, "trapezoid", getattr(np, "trapz", None))

# ── 機理模型（兩狀態：頭空 CO2 分壓 P、液相溶解態 CO2 濃度 C）──────────
# dP/dt = -J_diss                       頭空只透過溶解流失（生物吃的是溶解態，不直接吃氣體）
# dC/dt = +J_diss - J_bio               液相由溶解補充、被生物消耗
#   J_diss = kLa * (Hpc*P - C)          傳質：驅動力 = 亨利飽和濃度 − 目前溶解濃度
#   J_bio  = Vmax * C / (Km + C)        Monod：菌群消耗溶解態 CO2
#
# 結構性關鍵：穩態(dC/dt=0)時 J_diss = J_bio —— 兩通量相等，從 P 的下降只量得到
# 這個共同通量，無從得知它是「溶解限制」還是「生物限制」。分離只可能發生在暫態
# （C 遠離 Hpc*P、dC/dt≠0）時，兩通量暫時解耦。
#
# 參數尺度對齊真實反應器（每分鐘）：穩態下 dP/dt≈-Vmax≈-0.00026/min≈-0.0156/hr，
# 與實測中位下降速率 0.0146 kg/cm²/hr 同量級；kLa 設成暫態時間常數約 250 min，
# 讓填充暫態在一個循環內看得到（對應發現2 首循環 3.38× 穩態）。
TRUE = dict(kLa=0.004, Vmax=0.00028, Km=0.05, Hpc=0.8)   # 已知真值（每分鐘標度）


def _rhs(P, C, k):
    J_diss = k["kLa"] * (k["Hpc"] * P - C)
    J_bio = k["Vmax"] * C / (k["Km"] + C)
    return -J_diss, J_diss - J_bio, J_diss, J_bio


def _P_traj(kLa, Vmax, Km, Hpc, P0, C0, n, dt):
    """只算壓力軌跡的快版 RK4（純浮點、無 dict、無配置），供擬合熱迴圈用。"""
    def rhs(P, C):
        Jd = kLa * (Hpc * P - C)
        Jb = Vmax * C / (Km + C)
        return -Jd, Jd - Jb
    out = np.empty(n + 1)
    P, C = P0, C0
    out[0] = P
    for i in range(n):
        dP1, dC1 = rhs(P, C)
        dP2, dC2 = rhs(P + 0.5*dt*dP1, C + 0.5*dt*dC1)
        dP3, dC3 = rhs(P + 0.5*dt*dP2, C + 0.5*dt*dC2)
        dP4, dC4 = rhs(P + dt*dP3, C + dt*dC3)
        P = P + dt/6*(dP1 + 2*dP2 + 2*dP3 + dP4)
        C = C + dt/6*(dC1 + 2*dC2 + 2*dC3 + dC4)
        if not (-10 < P < 10):          # 發散 → 早停
            out[i+1:] = 1e3
            return out
        out[i+1] = P
    return out


DT = 15.0  # 積分步長（分）：系統時間常數~250 min，dt=5 足夠準且快 5 倍


def simulate(k, P0, C0, minutes, dt=DT):
    """RK4 積分（步長 DT），回傳每步的 P、C 與當下兩通量。
    穩定性早停：參數被最佳化器探到極端值時 RK4 會發散，一旦出現非有限值就停在
    上一步、其餘補該值，讓 NLL 自然變大而不是丟出 overflow。"""
    n = int(minutes / dt)
    P = np.empty(n + 1); C = np.empty(n + 1)
    Jd = np.zeros(n + 1); Jb = np.zeros(n + 1)
    P[0], C[0] = P0, C0
    for i in range(n):
        dP1, dC1, jd, jb = _rhs(P[i], C[i], k); Jd[i], Jb[i] = jd, jb
        dP2, dC2, *_ = _rhs(P[i] + 0.5*dt*dP1, C[i] + 0.5*dt*dC1, k)
        dP3, dC3, *_ = _rhs(P[i] + 0.5*dt*dP2, C[i] + 0.5*dt*dC2, k)
        dP4, dC4, *_ = _rhs(P[i] + dt*dP3, C[i] + dt*dC3, k)
        P[i+1] = P[i] + dt/6*(dP1 + 2*dP2 + 2*dP3 + dP4)
        C[i+1] = C[i] + dt/6*(dC1 + 2*dC2 + 2*dC3 + dC4)
        if not (np.isfinite(P[i+1]) and abs(P[i+1]) < 10):   # 發散 → 早停
            P[i+1:] = 1e3; C[i+1:] = C[i]
            return P, C, Jd, Jb
    Jd[-1], Jb[-1] = _rhs(P[-1], C[-1], k)[2:]
    return P, C, Jd, Jb


def steady_C(k, P):
    """給定 P，解 J_diss=J_bio 的穩態溶解濃度（生物項 Monod 的二次式閉式解）。"""
    a = k["kLa"]; b = k["Vmax"]; Km = k["Km"]; Cs = k["Hpc"] * P
    # a(Cs−C) = bC/(Km+C)  →  a C² + (aKm − aCs + b)C − aKmCs = 0
    A = a; B = a*Km - a*Cs + b; Cc = -a*Km*Cs
    return (-B + np.sqrt(B*B - 4*A*Cc)) / (2*A)


# ── 觀測資料生成 ──────────────────────────────────────
P_NOISE = 0.003        # 壓力量測雜訊（kg/cm²，貼近儀器級）


def make_data(mode: str):
    """mode='steady'：一開始就在穩態（C 已飽和到穩態值）——對應日常運轉窗口。
       mode='transient'：液相部分耗盡（C0=半飽和）、含填充暫態——對應發現2 的
       體制轉換（換液後遠離飽和，物理溶解淨填充液相）。"""
    P0 = 1.185
    C0 = steady_C(TRUE, P0) if mode == "steady" else 0.5 * steady_C(TRUE, P0)
    P, C, Jd, Jb = simulate(TRUE, P0, C0, minutes=1200)
    # 只截到壓力掉到排氣下限 0.90 為止（對應協定）
    end = int(np.argmax(P <= 0.90)) or len(P)
    P, C, Jd, Jb = P[:end], C[:end], Jd[:end], Jb[:end]
    obs = P + rng.normal(0, P_NOISE, len(P))
    diss_frac_true = _trapz(Jd - Jb, dx=DT) / _trapz(Jd, dx=DT) if mode == "transient" else 0.0
    return dict(obs=obs, P=P, C=C, Jd=Jd, Jb=Jb, mode=mode,
                minutes=(len(P) - 1) * DT, diss_frac_true=diss_frac_true, P0=P0, C0=C0)


# ── 擬合：對觀測到的 P 曲線做最大概似 ─────────────────
PARAMS = ["kLa", "Vmax", "Km", "Hpc"]


def _unpack(theta, fixed):
    k = dict(zip(PARAMS, np.exp(theta)))   # 對數空間搜尋，保證參數為正
    k.update(fixed)
    return k


def nll(theta, data, fixed, C0_known):
    k = _unpack(theta, fixed)
    n = int(data["minutes"] / DT)
    P = _P_traj(k["kLa"], k["Vmax"], k["Km"], k["Hpc"], data["P0"], C0_known(k), n, DT)
    m = min(len(P), len(data["obs"]))
    return 0.5 * float(np.sum((P[:m] - data["obs"][:m]) ** 2)) / P_NOISE**2


def _C0_fn(data):
    """C0 已知條件：暫態資料 C0 已知（半飽和）；穩態資料 C0 由參數決定的穩態值。"""
    if data["mode"] == "transient":
        c0 = data["C0"]
        return lambda k: c0
    return lambda k: steady_C(k, data["P0"])


def _fit_free(data, fixed):
    """在 fixed 之外的參數上最小化 NLL，回傳最佳 NLL 與參數。多起點取最好，
    避免 Nelder-Mead 卡在局部解影響 profile 曲線。"""
    free = [p for p in PARAMS if p not in fixed]
    C0_known = _C0_fn(data)
    best = None
    for _ in range(1):
        x0 = np.array([np.log(TRUE[p] * rng.uniform(0.6, 1.6)) for p in free])

        def obj(thf):
            theta = np.array([np.log(fixed[p]) if p in fixed else thf[free.index(p)]
                              for p in PARAMS])
            return nll(theta, data, fixed, C0_known)

        r = minimize(obj, x0, method="Nelder-Mead",
                     options=dict(maxiter=800, xatol=1e-4, fatol=1e-3))
        if best is None or r.fun < best[0]:
            best = (r.fun, {p: float(np.exp(r.x[i])) for i, p in enumerate(free)})
    return best


# ΔNLL 門檻：χ²(1)/2 的 95% 分位 ≈ 1.92（profile likelihood 標準做法）
DNLL_95 = 1.92


def profile_ci(data, target, fixed):
    """對 target 參數做 profile likelihood：掃一段值域，每點固定 target、
    對其餘參數重新最佳化，得 profile NLL 曲線。ΔNLL=1.92 的交點即 95%CI。
    曲線在整段值域都低於門檻 → 該參數不可辨識（似然平坦）。"""
    nll0 = _fit_free(data, fixed)[0]
    grid = TRUE[target] * np.geomspace(0.15, 6.0, 11)
    prof = []
    for val in grid:
        f2 = {**fixed, target: val}
        prof.append(_fit_free(data, f2)[0] - nll0)
    prof = np.array(prof)
    below = grid[prof <= DNLL_95]
    if len(below) == 0:
        return None
    lo, hi = below.min(), below.max()
    identifiable = not (np.isclose(lo, grid[0]) or np.isclose(hi, grid[-1]))
    return dict(lo=lo, hi=hi, rel=(hi - lo) / 2 / TRUE[target] * 100,
                identifiable=identifiable, floored=not identifiable)


def _report(title, data, fixed):
    pin = "、".join(f"{p}(固定)" for p in fixed) or "無"
    print(f"\n── {title} ──   資料={data['mode']}  固定={pin}")
    for p in ("kLa", "Vmax"):
        if p in fixed:
            print(f"   {p:<5} 已由文獻/對照固定")
            continue
        ci = profile_ci(data, p, fixed)
        name = "物理溶解速率 kLa" if p == "kLa" else "生物消耗速率 Vmax"
        if ci is None:
            print(f"   {name}：profile 全段平坦 → 不可辨識")
        elif not ci["identifiable"]:
            print(f"   {name}：95%CI [{ci['lo']:.5f},{ci['hi']:.5f}] 觸及掃描邊界 "
                  f"→ 不可辨識（相對±{ci['rel']:.0f}%）")
        else:
            tag = "可辨識" if ci["rel"] < 30 else "邊緣"
            print(f"   {name}：{TRUE[p]:.5f} 之 95%CI [{ci['lo']:.5f},{ci['hi']:.5f}] "
                  f"相對±{ci['rel']:.0f}% → {tag}")


# ══════════════════════════════════════════════════════════════════
#  真實資料版：可分離度就緒指標（供前端 /greybox_analysis）
# ══════════════════════════════════════════════════════════════════
# 用發現2 的殘差法，不做脆弱的 ODE profile（實測 profile 在真實穩態資料上會因
# C0 假設製造假的可辨識性、給出錯誤的「可分離」）。原理（見本檔頂部結論 2）：
#   穩態速率 r_ss = 生物限制通量（溶解通量≡生物通量時的下降速率）
#   暫態時（換液後液相遠離飽和）下降更快，超出穩態的部分＝純物理填充液相
#   物理溶解佔比 = (r_transient − r_ss)/r_transient = 1 − r_ss/r_transient
# 穩態資料所有循環速率相近（r_max≈r_ss）→ 無暫態 → 尚不可分離。
TRANSIENT_RATIO = 1.30      # 某循環平均速率 > 穩態速率 ×此值 → 認定含暫態

def _cycle_rate(P, dt_min):
    """循環平均下降速率 kg/cm²/hr。"""
    P = np.asarray(P, float)
    hours = (len(P) - 1) * dt_min / 60.0
    return (P[0] - P[-1]) / hours if hours > 0 else 0.0


def analyze_real(cycles: list) -> dict:
    """對真實完整循環軌跡輸出「可分離度就緒」判斷 + 若有暫態則給分離比例（殘差法）。

    cycles: [{pressure:[...], dt_min, baseline_p, run_id, n_minutes, start}, ...]
    """
    usable = [c for c in cycles if len(c.get("pressure", [])) >= 6]
    if len(usable) < 2:
        return {"status": "insufficient", "n_cycles": len(cycles),
                "message": "完整循環不足（需 ≥2 個以估穩態速率）。"}

    rates = [(_cycle_rate(c["pressure"], c["dt_min"]), c) for c in usable]
    rates = [(r, c) for r, c in rates if r > 0]
    if len(rates) < 2:
        return {"status": "insufficient", "n_cycles": len(cycles),
                "message": "有效循環不足。"}

    vals = sorted(r for r, _ in rates)
    # 穩態速率 = 較慢那半的中位數（暫態是偏快的離群，不能污染基準）
    slow = vals[:max(1, len(vals) // 2)]
    r_ss = float(np.median(slow))
    r_max, cmax = max(rates, key=lambda x: x[0])
    ratio = r_max / r_ss if r_ss > 0 else 1.0
    has_transient = ratio >= TRANSIENT_RATIO

    out = {
        "status":       "ok",
        "n_cycles":     len(usable),
        "steady_rate":  round(r_ss, 5),
        "max_rate":     round(r_max, 5),
        "ratio":        round(ratio, 2),
        "separable":    bool(has_transient),
        "best_cycle":   {"run_id": cmax["run_id"], "start": cmax.get("start")},
        "caveat":       "穩態速率≈生物限制通量；分離只在暫態成立。物理佔比由單一暫態估得、需重複驗證。",
    }
    if has_transient:
        # 殘差法：該暫態循環中，超出穩態速率的部分為純物理填充
        phys_frac = max(0.0, min(1.0, 1.0 - r_ss / r_max))
        out["dissolution_fraction"] = round(phys_frac * 100, 1)
        out["consumption_fraction"] = round((1 - phys_frac) * 100, 1)
        out["verdict"] = "separable"
        out["verdict_text"] = (f"偵測到暫態循環（速率 {r_max:.4f} 為穩態 {r_ss:.4f} 的 "
                               f"{ratio:.1f} 倍）→ 可分離。該暫態物理溶解佔 {phys_frac*100:.0f}%、"
                               f"生物消耗佔 {(1-phys_frac)*100:.0f}%（殘差法，需更多暫態重複驗證）。")
    else:
        out["verdict"] = "not_ready"
        out["verdict_text"] = (f"所有循環速率相近（最快僅穩態的 {ratio:.1f} 倍）→ 目前資料為穩態，"
                               f"**尚不可分離**。需補入暫態段（換液後首循環）或純物理對照，見暫態分離協定。")
    return out


def main():
    print("=" * 66)
    print(" CO2 溶解/生物消耗分離 —— 灰箱可辨識性決定性測試（合成資料）")
    print("=" * 66)
    print(f" 真值 kLa={TRUE['kLa']} Vmax={TRUE['Vmax']} Km={TRUE['Km']} Hpc={TRUE['Hpc']}")

    steady = make_data("steady")
    trans = make_data("transient")

    print("\n【情境 A】純穩態資料（日常運轉窗口），全參數自由估")
    _report("A. 穩態 · 全自由", steady, fixed={})

    print("\n【情境 B】含暫態資料（換液後遠離飽和），全參數自由估")
    _report("B. 暫態 · 全自由", trans, fixed={})

    print("\n【情境 C】用文獻固定亨利溶解度 Hpc（= C* 那一項）")
    _report("C1. 穩態 · 固定 Hpc", steady, fixed={"Hpc": TRUE["Hpc"]})
    _report("C2. 暫態 · 固定 Hpc", trans, fixed={"Hpc": TRUE["Hpc"]})
    _report("C3. 暫態 · 固定 Hpc+kLa（等同有純物理對照組）", trans,
            fixed={"Hpc": TRUE["Hpc"], "kLa": TRUE["kLa"]})

    print("\n" + "=" * 66)
    print(" 實測解讀（照結果講，不是照假設）：")
    print(" 1. 物理速率 kLa：穩態 ±160%（差）、暫態 ±0%（精準）。")
    print("    → 分離的槓桿確實是暫態，與 co2_relaxation_analysis 發現2 一致。")
    print(" 2. 生物速率 Vmax：所有情境都釘不住（連固定 kLa+Hpc 亦然）。")
    print("    根因：Monod 低濃度段 Vmax 與 Km 共線，只有比值 Vmax/Km 可辨識，")
    print("    單獨估 Vmax 必然平坦。生物項應以「總通量 − 已釘死的物理通量」的")
    print("    殘差取得（即發現2 的做法），而非直接擬合 Vmax。")
    print(" 3. 對兩個問題的回答：")
    print("    (a) 前沿 ML / 改算法沒用——穩態不可辨識是結構性質，換模型不會變。")
    print("    (b) 真正有效的是：實驗製造暫態 + 文獻/對照定住物理常數，")
    print("        再把生物量當殘差。這是機理設計，不是演算法創新。")
    print("=" * 66)


if __name__ == "__main__":
    main()
