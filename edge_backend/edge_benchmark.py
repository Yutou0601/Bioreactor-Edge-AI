# -*- coding: utf-8 -*-
"""邊緣算力預算量測：同一支腳本在 x86 與 Jetson 上跑，結果可直接對比。

── 為何要量這個 ───────────────────────────────────────────
本研究的核心發現是：未校準的參數估計會產生 p=2.6e-12 的假結果，
必須以參數自助法校準才可信。但校準的算力需求遠高於估計本身——
這正是邊緣裝置的核心兩難：算力有限，但不能把未校準的參數往上送。

本檔量測管線各階段的實際成本，作為邊緣部署的算力預算依據。

── 量測項目 ───────────────────────────────────────────────
  S1 循環偵測（串流 vs 批次）      每筆延遲、兩者結果是否一致
  S2 每循環特徵抽取                每循環延遲
  S3 聯合擬合（單次估計）          延遲
  S4 自助校準（可信度的代價）      延遲、與 S3 的倍率
  S5 最佳化器取捨                  局部法 vs 差分演化：速度 vs 可重現性
  S6 記憶體足跡                    峰值 RSS

── 用法 ───────────────────────────────────────────────────
  python edge_benchmark.py                # 完整
  python edge_benchmark.py --quick        # 減少重複次數（Jetson 上先試跑）
  python edge_benchmark.py --nboot 50     # 自訂自助次數

輸出 -> docs/analysis_charts_3batch/edge_benchmark_<platform>.json
"""
import argparse
import json
import os
import platform
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


# ══════════════════════════════════════════════════════════
def platform_info():
    info = dict(system=platform.system(), machine=platform.machine(),
                processor=platform.processor() or 'n/a',
                python=platform.python_version(),
                cpu_count=os.cpu_count())
    # Jetson 偵測
    for p in ('/etc/nv_tegra_release', '/proc/device-tree/model'):
        try:
            with open(p) as f:
                info['jetson'] = f.read().strip().replace('\x00', '')
                break
        except Exception:
            pass
    info.setdefault('jetson', None)
    info['label'] = ('jetson' if info['jetson'] else
                     f"{info['system']}-{info['machine']}")
    try:
        import numpy as _np
        info['numpy'] = _np.__version__
    except Exception:
        pass
    # GPU（僅供記錄：本管線為 scipy 最佳化，不使用 GPU）
    info['gpu'] = None
    try:
        import torch
        if torch.cuda.is_available():
            info['gpu'] = torch.cuda.get_device_name(0)
            info['label'] += '-' + info['gpu'].split()[-1]
    except Exception:
        pass
    return info


def peak_rss_mb():
    """峰值記憶體 (MB)。Linux/Jetson 用 resource，Windows 退回 psutil/ctypes。"""
    try:
        import resource
        v = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return round(v / 1024 if sys.platform != 'darwin' else v / 1024 / 1024, 1)
    except Exception:
        pass
    try:
        import psutil
        return round(psutil.Process().memory_info().rss / 1024 / 1024, 1)
    except Exception:
        pass
    if sys.platform == 'win32':
        try:
            import ctypes
            from ctypes import wintypes

            class PMC(ctypes.Structure):
                _fields_ = [('cb', wintypes.DWORD),
                            ('PageFaultCount', wintypes.DWORD),
                            ('PeakWorkingSetSize', ctypes.c_size_t),
                            ('WorkingSetSize', ctypes.c_size_t),
                            ('QuotaPeakPagedPoolUsage', ctypes.c_size_t),
                            ('QuotaPagedPoolUsage', ctypes.c_size_t),
                            ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t),
                            ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                            ('PagefileUsage', ctypes.c_size_t),
                            ('PeakPagefileUsage', ctypes.c_size_t)]
            k32 = ctypes.windll.kernel32
            k32.GetCurrentProcess.restype = wintypes.HANDLE
            fn = k32.K32GetProcessMemoryInfo
            fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
            fn.restype = wintypes.BOOL
            c = PMC()
            c.cb = ctypes.sizeof(c)
            if fn(k32.GetCurrentProcess(), ctypes.byref(c), c.cb):
                return round(c.PeakWorkingSetSize / 1024 / 1024, 1)
            return None
        except Exception:
            return None
    return None


def timeit(fn, repeats=5, warmup=1):
    for _ in range(warmup):
        fn()
    ts = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        ts.append(time.perf_counter() - t0)
    ts = np.array(ts)
    return dict(mean_s=float(ts.mean()), sd_s=float(ts.std()),
                min_s=float(ts.min()), n=repeats)


# ══════════════════════════════════════════════════════════
def stage1_cycle_detection(df, repeats):
    """S1：循環偵測。批次版 vs 串流版（逐筆餵入）。"""
    from analyze_three_batches import BATCHES, find_cycles
    a, b, _ = BATCHES['3.1 (10min)']
    s = df[(df.ts >= a) & (df.ts <= b)].reset_index(drop=True)
    n_rows = len(s)

    batch = timeit(lambda: find_cycles(s), repeats)
    batch['per_sample_us'] = batch['mean_s'] / n_rows * 1e6
    batch['n_rows'] = n_rows
    batch['n_cycles'] = len(find_cycles(s))

    # 串流版：模擬逐筆到達，每筆只做 O(1) 的狀態更新
    p = s.p_reactor.values.astype(float)

    def streaming():
        peak = p[0]
        valley = p[0]
        n_ref = 0
        for x in p:                      # 每筆 O(1)
            if x > valley + 0.03:
                n_ref += 1
                peak, valley = x, x
            elif x < valley:
                valley = x
        return n_ref
    stream = timeit(streaming, repeats)
    stream['per_sample_us'] = stream['mean_s'] / n_rows * 1e6
    stream['n_refills'] = streaming()
    return dict(batch=batch, streaming=stream)


def stage2_features(cycles, repeats):
    """S2：每循環特徵抽取。"""
    from analyze_new_methods import sweep_segments
    cs = [c for v in cycles.values() for c in v]

    def run():
        return [sweep_segments(c) for c in cs]
    r = timeit(run, repeats)
    r['n_cycles'] = len(cs)
    r['per_cycle_ms'] = r['mean_s'] / len(cs) * 1000
    return r


def stage3_joint_fit(D, repeats):
    """S3：聯合擬合單次估計。"""
    from joint_fit_calibrated import joint
    r = timeit(lambda: joint(D), repeats)
    th = joint(D)
    r['rb'] = float(th[4])
    r['Peq'] = float(th[3])
    return r


def stage4_calibration(D, nboot, repeats=1):
    """S4：自助校準——可信度的代價。"""
    from joint_fit_calibrated import joint, make_null
    th0 = joint(D, with_rb=False)
    rng = np.random.default_rng(0)

    def one():
        return joint(make_null(D, th0, rng))[4]
    unit = timeit(one, repeats=max(repeats, 3))
    total = unit['mean_s'] * nboot
    return dict(per_bootstrap_s=unit['mean_s'], nboot=nboot,
                total_s=total, total_min=total / 60)


def _boot_worker(seed):
    """自助校準的單次工作單元（供多核平行化用，必須是頂層函式）。"""
    import numpy as _np
    from joint_fit_calibrated import joint, make_null, load
    if 'D' not in _BOOT_CACHE:
        _BOOT_CACHE['D'] = load()
    D = _BOOT_CACHE['D']
    if 'th0' not in _BOOT_CACHE:
        _BOOT_CACHE['th0'] = joint(D, with_rb=False)
    th0 = _BOOT_CACHE['th0']
    return float(joint(make_null(D, th0, _np.random.default_rng(seed)))[4])


_BOOT_CACHE = {}


def stage4b_parallel(nboot, workers):
    """S4b：自助校準的多核平行化——本工作負載的正確加速途徑。

    200 次自助彼此獨立（embarrassingly parallel），故隨核數近線性加速。
    注意：此為 scipy 最佳化，GPU 完全用不到。
    """
    from concurrent.futures import ProcessPoolExecutor
    n = max(3 * workers, 24)                  # 任務數需遠大於行程數才量得準
    with ProcessPoolExecutor(max_workers=workers) as ex:
        # 暖機：讓每個行程先載入資料並建好快取，避免啟動開銷混入計時
        t_warm = time.perf_counter()
        list(ex.map(_boot_worker, range(workers)))
        warm_s = time.perf_counter() - t_warm
        # 正式計時
        t0 = time.perf_counter()
        list(ex.map(_boot_worker, range(1000, 1000 + n)))
        dt = time.perf_counter() - t0
    return dict(n_measured=n, workers=workers, total_s=dt,
                per_bootstrap_s=dt / n, warmup_s=warm_s)


def stage5_optimizer(D, n_local=10, n_de=3):
    """S5：局部法 vs 差分演化——速度與可重現性的取捨。"""
    from scipy import optimize
    from joint_fit_calibrated import traj, BN
    BND = [(1e-3, 3)] * 3 + [(0, 0.95), (0, 0.1)]

    def sse(th):
        v = 0.0
        for i, b in enumerate(BN):
            for t, P in D[b]:
                v += float(np.sum((P - traj(t, P[0], th[i], th[3], th[4])) ** 2))
        return v

    rng = np.random.default_rng(0)
    t0 = time.perf_counter()
    loc = []
    for _ in range(n_local):
        p0 = [rng.uniform(l, h) for l, h in BND]
        r = optimize.minimize(sse, p0, method='L-BFGS-B', bounds=BND)
        r = optimize.minimize(sse, r.x, method='Nelder-Mead', bounds=BND,
                              options=dict(maxiter=20000, fatol=1e-14))
        loc.append((r.fun, r.x[4]))
    t_loc = (time.perf_counter() - t0) / n_local
    loc = np.array(loc)
    best = loc[:, 0].min()
    conv = float((loc[:, 0] < best * 1.001).mean())

    t0 = time.perf_counter()
    de = []
    for s in range(n_de):
        r = optimize.differential_evolution(sse, BND, seed=s, tol=1e-10,
                                            maxiter=300, popsize=18,
                                            polish=True, init='sobol')
        de.append((r.fun, r.x[4]))
    t_de = (time.perf_counter() - t0) / n_de
    de = np.array(de)

    return dict(
        local=dict(mean_s=t_loc, n=n_local, converge_rate=conv,
                   rb_min=float(loc[:, 1].min()), rb_max=float(loc[:, 1].max())),
        de=dict(mean_s=t_de, n=n_de,
                converge_rate=float((de[:, 0] < de[:, 0].min() * 1.001).mean()),
                rb_min=float(de[:, 1].min()), rb_max=float(de[:, 1].max())),
        speed_ratio=t_de / max(t_loc, 1e-9))


# ══════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--quick', action='store_true')
    ap.add_argument('--nboot', type=int, default=200)
    args = ap.parse_args()
    rep = 2 if args.quick else 5

    info = platform_info()
    print('══ 平台 ══')
    for k, v in info.items():
        print(f'   {k}: {v}')

    print('\n載入資料 …')
    from analyze_three_batches import load_all
    from analyze_new_methods import collect
    from joint_fit_calibrated import load
    t0 = time.perf_counter()
    df = load_all()
    t_load = time.perf_counter() - t0
    cycles = collect()
    D = load()
    print(f'   {len(df):,} 筆，載入 {t_load:.1f} s')

    res = dict(platform=info, data=dict(rows=len(df), load_s=t_load))

    print('\n══ S1 循環偵測 ══')
    res['s1'] = stage1_cycle_detection(df, rep)
    b, s = res['s1']['batch'], res['s1']['streaming']
    print(f"   批次版  {b['mean_s']*1000:8.1f} ms  →  {b['per_sample_us']:.2f} us/筆"
          f"  （{b['n_rows']} 筆 → {b['n_cycles']} 循環）")
    print(f"   串流版  {s['mean_s']*1000:8.1f} ms  →  {s['per_sample_us']:.2f} us/筆"
          f"  （偵測到 {s['n_refills']} 次補氣）")
    print(f"   → 串流版足以在 1 分鐘取樣間隔內即時處理"
          f"（餘裕 {60e6/max(s['per_sample_us'],1e-9):,.0f} 倍）")

    print('\n══ S2 每循環特徵抽取 ══')
    res['s2'] = stage2_features(cycles, rep)
    print(f"   {res['s2']['mean_s']*1000:.1f} ms / {res['s2']['n_cycles']} 循環"
          f"  →  {res['s2']['per_cycle_ms']:.2f} ms/循環")

    print('\n══ S3 聯合擬合（單次估計）══')
    res['s3'] = stage3_joint_fit(D, rep)
    print(f"   {res['s3']['mean_s']:.3f} s   rb={res['s3']['rb']:.5f}"
          f"  Peq={res['s3']['Peq']:.4f}")

    print('\n══ S4 自助校準（可信度的代價）══')
    res['s4'] = stage4_calibration(D, args.nboot)
    ratio = res['s4']['per_bootstrap_s'] * args.nboot / max(res['s3']['mean_s'], 1e-9)
    res['s4']['cost_ratio_vs_estimate'] = ratio
    print(f"   單次自助 {res['s4']['per_bootstrap_s']:.3f} s"
          f"  ×  {args.nboot} 次  =  {res['s4']['total_min']:.1f} 分鐘")
    print(f"   → 校準成本是估計本身的 {ratio:.0f} 倍")
    print(f"   → 循環間隔 6~15 hr，故可排在閒置期執行，不影響即時偵測")

    print('\n══ S4b 校準的多核平行化（本負載的正確加速途徑）══')
    nw = max(1, (os.cpu_count() or 2) - 1)
    try:
        par = stage4b_parallel(args.nboot, nw)
        res['s4b'] = par
        speedup = res['s4']['per_bootstrap_s'] / max(par['per_bootstrap_s'], 1e-9)
        res['s4b']['speedup'] = speedup
        res['s4b']['projected_total_min'] = (par['per_bootstrap_s'] *
                                             args.nboot / 60)
        print(f"   {nw} 個工作行程：單次自助 {par['per_bootstrap_s']:.3f} s"
              f"  （單核 {res['s4']['per_bootstrap_s']:.3f} s）")
        print(f"   → 加速 {speedup:.1f}x，{args.nboot} 次校準降為 "
              f"{res['s4b']['projected_total_min']:.1f} 分鐘")
    except Exception as e:
        res['s4b'] = dict(error=str(e))
        print(f'   平行化量測失敗：{e}')
    print(f"   ※ 本負載為 scipy 最佳化，GPU 完全未使用"
          f"（本機 GPU：{info.get('gpu') or '無'}）")
    print(f"   → 此類工作該配的是多核 CPU，不是 GPU")

    print('\n══ S5 最佳化器取捨 ══')
    res['s5'] = stage5_optimizer(D, n_local=6 if args.quick else 10,
                                 n_de=2 if args.quick else 3)
    L, E = res['s5']['local'], res['s5']['de']
    print(f"   局部法   {L['mean_s']:.2f} s/次   收斂率 {L['converge_rate']*100:.0f}%"
          f"   rb 範圍 [{L['rb_min']:.5f}, {L['rb_max']:.5f}]")
    print(f"   差分演化 {E['mean_s']:.2f} s/次   收斂率 {E['converge_rate']*100:.0f}%"
          f"   rb 範圍 [{E['rb_min']:.5f}, {E['rb_max']:.5f}]")
    print(f"   → DE 慢 {res['s5']['speed_ratio']:.0f} 倍，換取無人值守的可重現性")

    res['s6_peak_rss_mb'] = peak_rss_mb()
    print(f"\n══ S6 峰值記憶體 ══\n   {res['s6_peak_rss_mb']} MB"
          if res['s6_peak_rss_mb'] else "\n══ S6 記憶體 ══\n   無法取得")

    out_dir = os.path.abspath(os.path.join(
        os.path.dirname(__file__), '..', 'docs', 'analysis_charts_3batch'))
    os.makedirs(out_dir, exist_ok=True)
    fn = os.path.join(out_dir, f"edge_benchmark_{info['label']}.json")
    with open(fn, 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(f'\n輸出 → {fn}')
    print('\n※ 明天在 Jetson 上執行同一支腳本，會產生 edge_benchmark_jetson.json，')
    print('  兩份 JSON 可直接併表比較 x86 與邊緣裝置的算力預算。')


if __name__ == '__main__':
    main()
