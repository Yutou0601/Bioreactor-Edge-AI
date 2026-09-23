
# -*- coding: utf-8 -*-
"""重運算節點：跑在 Jetson Orin NX 16 GB 上的常駐核心。

    python -m compute_node.server            （從 edge_backend/ 底下跑）
    REACTOR_COMPUTE_PORT=8100                （預設 8100）

為什麼有這支
------------
監控電腦是 4 GB 的 Windows 機器，常駐核心的預算是 60 MB，所以那台上的分析
模組一律開**短命子行程**：跑完作業系統把記憶體收回，代價是每次都要重付
import 的錢（xgboost +119.5 MB、scipy +69.6 MB，還有幾秒到幾十秒的載入時間）。

Orin 有 16 GB，那個取捨不成立了。這支服務在啟動時就把三個模組的分析程式
**全部 import 進來並且熱著**，之後每次呼叫都是純運算。這就是「重運算搬回
核心」——只是搬回的是 Orin 上的核心，不是監控電腦上的。

兩台的分工
----------
    監控電腦 (Windows, 4 GB)              Jetson Orin NX (Linux, 16 GB)
    ├─ 記錄程式寫 CSV                      └─ 本服務（常駐、套件熱著、吃得到 GPU）
    ├─ csv_watcher / API / 前端                 modules/*/run.py:compute_row()
    ├─ core 精簡核心（仍守 60 MB）
    └─ module_runner ──── HTTP ──────────→ POST /run/<name>
                     ←── 結果列 JSON ────

⚠ 本服務**不寫資料庫**。結果以 JSON 回給監控電腦，由那邊的核心寫進它自己的
  mod_* 表。這台上面就算有 reactor.db 也沒有人會去看它——真要在這裡寫，
  現場只會看到「結果一直是舊的」而且兩邊都不報錯。

⚠ 三個模組的分析檔**都叫 analysis.py**。常駐 import 的話，第二個
  `import analysis` 會直接拿到 sys.modules 裡第一個的快取，於是 greybox 會
  拿 covariate 的程式去算，不報錯、結果是錯的。子行程模式下沒這個問題（每個
  行程各自獨立），是搬成常駐才冒出來的。這裡用 _swap_analysis() 處理：
  每個模組的 analysis 以唯一名稱載入，呼叫期間才暫時掛到 'analysis' 這個名字。
"""
import importlib.util
import json
import os
import sys
import threading
import time
import traceback

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # edge_backend/
if HERE not in sys.path:
    sys.path.insert(0, HERE)
MODULES_DIR = os.path.join(HERE, 'modules')

PORT = int(os.environ.get('REACTOR_COMPUTE_PORT') or 8100)

# 一次只跑一個模組。與監控電腦核心的 _run_lock 同樣的理由，外加這裡的
# _swap_analysis 需要獨佔 sys.modules['analysis']。
_call_lock = threading.Lock()

_loaded = {}          # name -> {'cfg':…, 'run':…, 'analysis':…, 'error':…}


# ── 載入 ──────────────────────────────────────────────────────────────
def _load_file(path, unique_name):
    """用唯一名稱從檔案路徑載入一個 Python 模組。"""
    spec = importlib.util.spec_from_file_location(unique_name, path)
    if spec is None or spec.loader is None:
        raise ImportError('載不進來：%s' % path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[unique_name] = mod
    spec.loader.exec_module(mod)
    return mod


def load_all():
    """掃 modules/、把每一個的 analysis.py 與 run.py 載入並熱著。

    ⚠ 個別模組載不起來要記下原因並繼續，不要讓整個服務起不來。少一個模組
      還能跑其他兩個；整台服務掛掉的話監控電腦那邊全部的模組都會失敗。
    """
    out = {}
    if not os.path.isdir(MODULES_DIR):
        return out
    for name in sorted(os.listdir(MODULES_DIR)):
        d = os.path.join(MODULES_DIR, name)
        cfg_path = os.path.join(d, 'module.json')
        if not os.path.isfile(cfg_path):
            continue
        entry = {'dir': d, 'cfg': None, 'run': None, 'analysis': None,
                 'error': None}
        try:
            with open(cfg_path, encoding='utf-8') as fh:
                entry['cfg'] = json.load(fh)
            apath = os.path.join(d, 'analysis.py')
            if os.path.isfile(apath):
                entry['analysis'] = _load_file(
                    apath, 'modcode_%s_analysis' % name)
            rpath = os.path.join(d, entry['cfg'].get('entry') or 'run.py')
            entry['run'] = _load_file(rpath, 'modcode_%s_run' % name)
            if not hasattr(entry['run'], 'compute_row'):
                raise AttributeError(
                    '%s 沒有 compute_row()。遠端模式要的是「純運算、回一列 '
                    'dict」的函式；只有 main() 的話這個模組只能在監控電腦上'
                    '用子行程跑。' % rpath)
        except Exception as e:
            entry['error'] = '%s: %s' % (type(e).__name__, e)
            print('[compute_node] ✘ %s 載入失敗：%s' % (name, entry['error']))
        else:
            print('[compute_node] ✓ %s 已載入並熱著' % name)
        out[name] = entry
    return out


class _swap_analysis:
    """呼叫期間把 sys.modules['analysis'] 指到這個模組自己的那一份。

    run.py 裡寫的是 `from analysis import compute`。三個模組的 analysis.py
    同名，不換的話第二個之後全部拿到第一個的快取。
    """

    def __init__(self, mod):
        self.mod = mod
        self.prev = None
        self.had = False

    def __enter__(self):
        if self.mod is not None:
            self.had = 'analysis' in sys.modules
            self.prev = sys.modules.get('analysis')
            sys.modules['analysis'] = self.mod
        return self

    def __exit__(self, *exc):
        if self.mod is not None:
            if self.had:
                sys.modules['analysis'] = self.prev
            else:
                sys.modules.pop('analysis', None)
        return False


def run_one(name, payload):
    """跑一個模組，回傳 (row, log)。例外往上丟，由 API 層轉成錯誤回應。"""
    entry = _loaded.get(name)
    if entry is None:
        raise KeyError('這個節點上沒有模組 %s' % name)
    if entry.get('error'):
        raise RuntimeError('模組 %s 載入時就壞了：%s' % (name, entry['error']))
    with _call_lock:
        with _swap_analysis(entry['analysis']):
            row = entry['run'].compute_row(payload)
    if not isinstance(row, dict):
        raise TypeError('%s.compute_row() 要回 dict，回的是 %s'
                        % (name, type(row).__name__))
    return row


# ── 健康資訊 ──────────────────────────────────────────────────────────
def _rss_mb():
    """常駐記憶體（MB）。拿不到就回 None，不要為了這個讓 /health 掛掉。"""
    try:
        import resource                                   # Linux / macOS
        kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return round(kb / 1024.0, 1)
    except Exception:
        pass
    try:                                                  # Windows 後備
        import ctypes
        from ctypes import wintypes

        class _PMC(ctypes.Structure):
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

        # ⚠ argtypes/restype 一定要宣告。不宣告的話 64 位元指標會被截成
        #   32 位元，呼叫多半失敗或拿到垃圾值（先前量 RSS 就踩過）。
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        psapi = ctypes.WinDLL('psapi', use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        c = _PMC()
        c.cb = ctypes.sizeof(_PMC)
        if psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(),
                                      ctypes.byref(c), c.cb):
            return round(c.WorkingSetSize / 1048576.0, 1)
    except Exception:
        pass
    return None


def _gpu():
    """torch 看不看得到 CUDA。torch 沒裝不是錯誤——三個模組都不需要它。"""
    t = sys.modules.get('torch')
    if t is None:
        return {'torch': None, 'cuda': False}
    try:
        return {'torch': t.__version__, 'cuda': bool(t.cuda.is_available()),
                'device': (t.cuda.get_device_name(0)
                           if t.cuda.is_available() else None)}
    except Exception as e:
        return {'torch': getattr(t, '__version__', '?'), 'cuda': False,
                'error': str(e)}


def health():
    warm = {}
    for pkg in ('numpy', 'pandas', 'scipy', 'sklearn', 'xgboost', 'torch'):
        m = sys.modules.get(pkg)
        warm[pkg] = getattr(m, '__version__', 'loaded') if m else None
    return {
        'ok': True,
        'role': 'compute',
        'python': sys.version.split()[0],
        'platform': '%s %s' % (sys.platform, os.uname().machine
                               if hasattr(os, 'uname') else ''),
        'rss_mb': _rss_mb(),
        'warm_packages': warm,
        'gpu': _gpu(),
        'modules': {k: (v['error'] or 'ready') for k, v in _loaded.items()},
    }


# ── HTTP ──────────────────────────────────────────────────────────────
def build_app():
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel

    class RunBody(BaseModel):
        input: object = None

    app = FastAPI(title='反應器重運算節點', version='1.0.0')

    @app.get('/health')
    def _health():
        return health()

    @app.get('/modules')
    def _modules():
        return {'modules': [
            {'name': k,
             'title': (v['cfg'] or {}).get('title'),
             'version': (v['cfg'] or {}).get('version'),
             'ready': v['error'] is None,
             'error': v['error']}
            for k, v in sorted(_loaded.items())]}

    @app.post('/run/{name}')
    def _run(name: str, body: RunBody):
        if name not in _loaded:
            raise HTTPException(404, '這個節點上沒有模組 %s' % name)
        t0 = time.time()
        try:
            row = run_one(name, body.input)
        except Exception as e:
            # ⚠ 把 traceback 回給監控電腦。現場的人看的是那台的介面，
            #   不會有人跑來 Orin 上翻 log。
            return {'ok': False,
                    'error': '%s: %s' % (type(e).__name__, e),
                    'traceback': traceback.format_exc()[-3000:],
                    'seconds': round(time.time() - t0, 1)}
        return {'ok': True, 'row': row,
                'seconds': round(time.time() - t0, 1),
                'log': '%s 在重運算節點跑完（套件熱著，未重新 import）' % name}

    return app


def main():
    global _loaded
    print('[compute_node] 載入模組並暖機……')
    t0 = time.time()
    _loaded = load_all()
    print('[compute_node] 暖機完成，耗時 %.1f 秒，RSS %s MB'
          % (time.time() - t0, _rss_mb()))
    g = _gpu()
    print('[compute_node] GPU：torch=%s cuda=%s' % (g.get('torch'), g.get('cuda')))

    import uvicorn
    uvicorn.run(build_app(), host='0.0.0.0', port=PORT, log_level='info')


if __name__ == '__main__':
    main()
