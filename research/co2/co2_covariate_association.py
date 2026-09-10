"""
每循環共變數關聯分析 —— 進氣前 ORP → 下降速率 / 斜率平緩化
===========================================================
2026-07-26 產出。這支不做機理分離（那需要暫態，見 co2_greybox_identifiability.py），
而是回答一個務實、且是核心的問題：

    「斜率平緩化」到底是生物（產甲烷稀釋 CO2）還是物理（溶解趨近飽和）造成的？

判斷方式：看平緩化是否隨「菌群成熟度」變動。菌群成熟度用**進氣前 ORP**代理
（系統逐循環自動記錄）。若控制了循環時間 n 之後，平緩化仍與進氣前 ORP 顯著相關，
則平緩化帶生物成因；若只與物理因素（n、壓力區間）相關而與菌態無關，則屬物理。

吃的是系統匯出的「每循環特徵」CSV（/experiment/export/cycles）。

**統計上的誠實處理**：同一批次內的多個循環是偽重複（同一菌群狀態），不是獨立樣本。
故所有回歸都用「以批次分群的叢集穩健標準誤」(cluster-robust SE)，把有效樣本數
降到接近批次數而非循環數——否則 p 值會過度樂觀。另同時報「批次平均後」的回歸
當交叉檢查。只用 numpy + scipy.stats（不碰 sklearn 那顆會被系統政策擋的 DLL）。
"""

import argparse
import sys

import numpy as np
import pandas as pd
from scipy import stats

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# CSV 中文表頭 → 內部鍵（對應 experiment_report.CYCLE_COLUMNS）
HEADER_MAP = {
    "批次": "run_id", "循環時間(每時幾分)": "n_minutes", "週期序": "cycle",
    "起始時間": "start", "時長(hr)": "duration_hr", "壓力起": "pressure_start",
    "壓力末": "pressure_end", "下降速率(kg/cm²/hr)": "drop_rate",
    "早段斜率": "slope_early", "晚段斜率": "slope_late",
    "平緩化(早-晚·疑產甲烷)": "flattening", "進氣前ORP(菌群共變數)": "pre_injection_orp",
    "ORP崩落": "orp_crash", "資料完整性": "quality",
}


def load_cycles(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = df.rename(columns={c: HEADER_MAP.get(c.strip(), c.strip()) for c in df.columns})
    if "n_minutes" in df:      # "1 分" → 1
        df["n_minutes"] = (df["n_minutes"].astype(str)
                           .str.extract(r"([\d.]+)").astype(float))
    for c in ("drop_rate", "flattening", "pre_injection_orp",
              "slope_early", "slope_late", "orp_crash"):
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    # 只保留完整循環（跨斷點的循環平緩化不可信）
    if "quality" in df:
        df = df[df["quality"].astype(str).str.contains("完整", na=False)]
    return df.reset_index(drop=True)


# ── 叢集穩健 OLS（以批次分群）─────────────────────────
def ols_cluster(y, X, groups, names):
    """最小平方 + 以 groups 分群的叢集穩健標準誤（CR1 修正）。
    回傳每個係數的 (估計, 穩健SE, t, 雙尾p)。有效自由度取「群數−參數數」，
    這正是把偽重複折算成獨立樣本的關鍵。"""
    X = np.asarray(X, float); y = np.asarray(y, float)
    n, k = X.shape
    XtX_inv = np.linalg.pinv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    resid = y - X @ beta

    uniq = np.unique(groups)
    G = len(uniq)
    if G < 2:                       # 叢集穩健需至少 2 群，否則無法估群間變異
        return [(nm, beta[i], np.nan, np.nan, np.nan) for i, nm in enumerate(names)], G, 0
    meat = np.zeros((k, k))
    for g in uniq:
        m = groups == g
        Xg = X[m]; ug = resid[m]
        s = Xg.T @ ug
        meat += np.outer(s, s)
    dfc = (G / (G - 1)) * ((n - 1) / (n - k))          # CR1 小樣本修正
    cov = dfc * XtX_inv @ meat @ XtX_inv
    se = np.sqrt(np.clip(np.diag(cov), 0, None))
    dof = max(G - k, 1)                                 # 以群數定自由度
    out = []
    for i, nm in enumerate(names):
        t = beta[i] / se[i] if se[i] > 0 else np.nan
        p = 2 * stats.t.sf(abs(t), dof) if np.isfinite(t) else np.nan
        out.append((nm, beta[i], se[i], t, p))
    return out, G, dof


def _design(df, cols):
    X = np.column_stack([np.ones(len(df))] + [df[c].values for c in cols])
    return X, ["截距"] + cols


def partial_corr(df, x, y, control):
    """x 與 y 在控制 control 後的偏相關（各自對 control 迴歸取殘差再相關）。"""
    d = df[[x, y, control]].dropna()
    if len(d) < 5:
        return np.nan, np.nan, len(d)
    def resid(t):
        A = np.column_stack([np.ones(len(d)), d[control].values])
        b = np.linalg.lstsq(A, d[t].values, rcond=None)[0]
        return d[t].values - A @ b
    rx, ry = resid(x), resid(y)
    if np.std(rx) < 1e-12 or np.std(ry) < 1e-12:
        return np.nan, np.nan, len(d)
    r, p = stats.pearsonr(rx, ry)
    return r, p, len(d)


def _fmt_p(p):
    return "n/a" if not np.isfinite(p) else (f"{p:.4f}" + (" *" if p < 0.05 else ""))


def analyze(df: pd.DataFrame):
    need = {"drop_rate", "flattening", "pre_injection_orp", "n_minutes", "run_id"}
    if not need.issubset(df.columns):
        print(f"[錯誤] CSV 缺欄位：{need - set(df.columns)}")
        return
    r = compute(df)
    if r["status"] != "ok":
        print(f"\n{r['message']}")
        return

    print(f"\n樣本：{r['n_cycles']} 個完整循環，來自 {r['n_batches']} 個批次")
    print("\n── ① 下降速率 ~ 循環時間 n + 進氣前ORP（叢集穩健，以批次分群）──")
    for t in r["rate_model"]:
        print(f"   {t['term']:<18} 係數={t['coef']:+.6g}  穩健SE={t['se']:.3g}  t={t['t']:+.2f}  p={_fmt_p(t['p'])}")
    print(f"   （有效自由度 {r['dof']}，非循環數 {r['n_cycles']}——已折算偽重複）")

    if r["flat_model"]:
        print("\n── ② 斜率平緩化 ~ 循環時間 n + 進氣前ORP（核心判斷）──")
        for t in r["flat_model"]:
            print(f"   {t['term']:<18} 係數={t['coef']:+.6g}  穩健SE={t['se']:.3g}  t={t['t']:+.2f}  p={_fmt_p(t['p'])}")
        pc = r["partial_corr"]
        print(f"   偏相關 平緩化 vs 進氣前ORP | 控制 n：r={pc['r']:+.3f}  p={_fmt_p(pc['p'])}  (n={pc['n']})")
        print(f"\n   ▶ 判讀：{r['verdict_text']}")
        print("     ※ 此判讀強度受批次數限制；批次少時把「無顯著」讀成「證據不足」而非「無關」。")
    else:
        print("\n── ② 斜率平緩化：完整且有平緩化的循環不足，暫略 ──")

    print("\n── ③ 交叉檢查：批次平均後（每批一個獨立點）──")
    for b in r["batch_level"]:
        print(f"   批次層 下降速率 vs {b['label']}：r={b['r']:+.3f}  p={_fmt_p(b['p'])}  (批次數={b['n']})")


def compute(df: pd.DataFrame) -> dict:
    """核心分析，回傳結構化結果（供 CLI 與 API 共用）。不印任何東西。"""
    need = {"drop_rate", "flattening", "pre_injection_orp", "n_minutes", "run_id"}
    if not need.issubset(df.columns):
        return {"status": "error", "message": f"缺欄位：{need - set(df.columns)}"}
    d = df.dropna(subset=["drop_rate", "pre_injection_orp", "n_minutes"]).copy()
    G = int(d["run_id"].nunique())
    # 洪博要的是「每次補氣的 slope → 進氣前 ORP」關係，單一批次幾個循環就能看，
    # 不必等 9 批次。故門檻放寬到「≥3 個完整循環」；n 有變異才納入 n 項、
    # 批次 ≥2 才用叢集穩健標準誤，否則退回一般 OLS。多批次時仍是嚴謹版。
    n_orp = d["pre_injection_orp"].nunique()
    if len(d) < 3 or n_orp < 3:
        return {"status": "insufficient", "n_cycles": int(len(d)), "n_batches": G,
                "message": f"目前可用完整循環 {len(d)} 個（進氣前 ORP 有 {n_orp} 種變異值），"
                           f"至少需 3 個且 ORP 要有變化才能看 slope→ORP 關係。"
                           f"（每次自動補氣才產生一個完整循環；剛開始跑時循環數會慢慢累積。）"}

    def sf(v, nd):     # 安全浮點：非有限值→None（避免 FastAPI JSON 序列化 NaN 失敗）
        return None if v is None or not np.isfinite(v) else round(float(v), nd)

    def terms(rows):
        return [{"term": nm, "coef": sf(b, 8), "se": sf(se, 8),
                 "t": sf(t, 3), "p": sf(p, 4)}
                for nm, b, se, t, p in rows]

    has_n = d["n_minutes"].nunique() >= 2      # 單一批次時 n 無變異，不納入回歸
    cols = (["n_minutes", "pre_injection_orp"] if has_n else ["pre_injection_orp"])
    grp = d["run_id"].values
    X, names = _design(d, cols)
    rate_rows, _, dof = ols_cluster(d["drop_rate"].values, X, grp, names)

    flat_model = partial = verdict = verdict_text = None
    dd = d.dropna(subset=["flattening"])
    if len(dd) >= 3:
        X2, names2 = _design(dd, cols)
        fr, _, _ = ols_cluster(dd["flattening"].values, X2, dd["run_id"].values, names2)
        flat_model = terms(fr)
        p_orp = next((t["p"] for t in flat_model if t["term"] == "pre_injection_orp"), None)
        if has_n:      # 有 n 變異才控制 n；單批次直接看平緩化 vs ORP
            r_pc, p_pc, n_pc = partial_corr(dd, "pre_injection_orp", "flattening", "n_minutes")
        else:
            dpc = dd[["pre_injection_orp", "flattening"]].dropna()
            if len(dpc) >= 3 and dpc["pre_injection_orp"].std() > 1e-9 and dpc["flattening"].std() > 1e-9:
                r_pc, p_pc = stats.pearsonr(dpc["pre_injection_orp"], dpc["flattening"]); n_pc = len(dpc)
            else:
                r_pc = p_pc = float("nan"); n_pc = len(dpc)
        partial = {"r": sf(r_pc, 3), "p": sf(p_pc, 4), "n": int(n_pc)}
        ctrl = "控制 n 後" if has_n else ""
        if p_orp is not None and p_orp < 0.05:
            verdict = "biological"
            verdict_text = f"{ctrl}平緩化仍顯著隨進氣前 ORP 變動 → 平緩化帶生物成因（支持產甲烷稀釋 CO2、使溶解變慢之假說）"
        else:
            verdict = "physical"
            verdict_text = f"{ctrl}平緩化與進氣前 ORP 無顯著關聯 → 傾向物理成因（溶解趨近飽和即可解釋）"

    agg = d.groupby("run_id").agg(n=("n_minutes", "mean"), rate=("drop_rate", "mean"),
                                  orp=("pre_injection_orp", "mean")).reset_index()
    batch_level = []
    for x, lab in [("n", "循環時間 n"), ("orp", "進氣前 ORP")]:
        if agg[x].std() > 1e-9 and agg["rate"].std() > 1e-9:
            rr, pp = stats.pearsonr(agg[x], agg["rate"])
            batch_level.append({"x": x, "label": lab, "r": sf(rr, 3),
                                "p": sf(pp, 4), "n": int(len(agg))})

    # ── 特徵探索（洪博：把補氣次數、pH 也當特徵推推看）─────────────────
    # 對每個可用特徵，報「下降速率(slope)」與「平緩化」的簡單相關。純探索：
    # 補氣壓力固定→每次補氣的 slope 反映消耗快慢；補氣次數＝批次內累積成熟度軸。
    # 單批次為偽重複、未控制其他項，僅供「哪個特徵值得深挖」的方向判斷。
    feature_defs = [("pre_injection_orp", "進氣前 ORP"),
                    ("pre_injection_ph", "進氣前 pH"),
                    ("refill_index", "補氣次數(週期序)")]
    features = []
    for col, lab in feature_defs:
        if col not in d.columns:
            continue
        for ycol, ylab in [("drop_rate", "下降速率slope"), ("flattening", "平緩化")]:
            sub = d[[col, ycol]].dropna()
            if len(sub) >= 3 and sub[col].std() > 1e-9 and sub[ycol].std() > 1e-9:
                rr, pp = stats.pearsonr(sub[col], sub[ycol])
                features.append({"feature": col, "feature_label": lab,
                                 "target": ycol, "target_label": ylab,
                                 "r": sf(rr, 3), "p": sf(pp, 4), "n": int(len(sub))})

    caveats = ["此為關聯分析，找到關聯 ≠ 分離了機制",
               "循環少時「無顯著」應讀為「證據不足」而非「無關」"]
    if G >= 2:
        caveats.insert(0, "同批次多循環為偽重複，已用批次分群叢集穩健標準誤折算檢定力")
    else:
        caveats.insert(0, "⚠ 目前只有 1 個批次：同批循環為偽重複、標準誤偏樂觀，僅供探索；"
                          "累積多批次後才是嚴謹結果")
    if not has_n:
        caveats.append("目前 n（循環時間）無變異，未納入回歸；多個 n 水準後才看得到 n 效應")
    return {"status": "ok", "n_cycles": int(len(d)), "n_batches": G, "dof": int(dof),
            "single_batch": G < 2, "has_n": bool(has_n),
            "rate_model": terms(rate_rows), "flat_model": flat_model,
            "partial_corr": partial, "verdict": verdict, "verdict_text": verdict_text,
            "batch_level": batch_level, "features": features, "caveats": caveats}


def make_demo(bio: bool = True) -> pd.DataFrame:
    """合成每循環資料驗證管線。bio=True：平緩化真的隨菌群成熟(ORP)上升（生物）；
    bio=False：平緩化只隨物理（壓力區間）變、與 ORP 無關。"""
    rng = np.random.default_rng(0)
    rows = []
    for level, n in enumerate([1, 5, 10]):
        for rep in range(3):
            run = f"{level+1}.{rep+1}"
            orp0 = 540 + level * 8 + rep * 2          # 菌齡隨天數(≈level)上升
            for cyc in range(3):
                orp = orp0 + cyc * 3 + rng.normal(0, 1.5)
                rate = 0.013 + 0.0003 * n + 0.00004 * (orp - 540) + rng.normal(0, 0.0005)
                flat = (0.002 + (0.00012 * (orp - 540) if bio else 0.0)
                        + 0.00005 * n + rng.normal(0, 0.0008))
                rows.append(dict(run_id=run, n_minutes=n, cycle=cyc + 1,
                                 drop_rate=round(rate, 5), flattening=round(flat, 5),
                                 pre_injection_orp=round(orp, 1), quality="完整"))
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser(description="每循環共變數關聯分析")
    ap.add_argument("csv", nargs="?", help="每循環特徵 CSV（/experiment/export/cycles）")
    ap.add_argument("--demo", choices=["bio", "phys"],
                    help="用合成資料驗證管線：bio=平緩化含生物成因；phys=純物理")
    args = ap.parse_args()

    print("=" * 62)
    print(" 每循環共變數關聯分析 —— 平緩化是生物還是物理？")
    print("=" * 62)
    if args.demo:
        print(f" [示範模式：{args.demo}] 合成資料，真值已知，用來驗證判讀正確")
        analyze(make_demo(bio=(args.demo == "bio")))
    elif args.csv:
        analyze(load_cycles(args.csv))
    else:
        print(" 用法：python co2_covariate_association.py cycles.csv")
        print("   或：python co2_covariate_association.py --demo bio   （驗證管線）")


if __name__ == "__main__":
    main()
