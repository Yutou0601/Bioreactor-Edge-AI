# -*- coding: utf-8 -*-
"""Jetson 硬體狀態：溫度、電源軌（電壓／電流／功率）、CPU／GPU 使用率與頻率、
記憶體、風扇、電源模式。介面「系統狀態 → Jetson 硬體」用。

資料來源全部是 sysfs／procfs，不開子行程（tegrastats 要常駐一個子行程，而且
有些欄位要 root）。路徑是 2026-10-15 在本機（Orin NX Super、L4T R36.4.3）實測：
    溫度   /sys/class/thermal/thermal_zone*/{type,temp}       cpu/gpu/cv0-2/soc0-2/tj
    電源軌 hwmon name=ina3221：in{1,2,3}_{label,input}、curr{1,2,3}_input
           VDD_IN（總輸入）、VDD_CPU_GPU_CV、VDD_SOC
    GPU    /sys/devices/platform/bus@0/17000000.gpu/load（千分比）
           /sys/class/devfreq/17000000.gpu/{cur,max}_freq
    風扇   hwmon name=pwmfan：pwm1（0–255）；hwmon name=pwm_tach：rpm
⚠ 不是 Jetson（例如 Windows 監控電腦）就回報 available=False，不起取樣執行緒。
⚠ 只准標準函式庫。
"""
import glob
import os
import subprocess
import threading
import time
from collections import deque
from datetime import datetime

SAMPLE_SEC = 10
HISTORY = deque(maxlen=24 * 3600 // SAMPLE_SEC)       # 24 小時
_lock = threading.Lock()
_thread = None
_stop = threading.Event()
_prev_cpu = None
_static = None


def _read(path, cast=str):
    try:
        with open(path) as fh:
            return cast(fh.read().strip())
    except (OSError, ValueError):
        return None


def available():
    return os.path.isfile('/etc/nv_tegra_release') and os.path.isdir('/sys/class/thermal')


def _hwmon(name):
    for h in glob.glob('/sys/class/hwmon/hwmon*'):
        if _read(os.path.join(h, 'name')) == name:
            return h
    return None


def static_info():
    """開機後不會變的：型號、L4T、電源模式、核心數。只查一次。"""
    global _static
    if _static is not None:
        return _static
    mode = None
    try:
        out = subprocess.run(['nvpmodel', '-q'], capture_output=True, text=True, timeout=5).stdout
        for ln in out.splitlines():
            if 'Power Mode' in ln:
                mode = ln.split(':', 1)[1].strip()
    except (OSError, subprocess.SubprocessError):
        pass
    # 溫控門檻一律從驅動讀，不自己訂（設備的安全範圍不該由介面決定）。
    # 2026-10-15 本機：cpu/gpu/cv/soc 為 passive 70 與 99、critical 104.5 °C；
    # tj 為 active 35/74/95（風扇加速）與 critical 104.5。
    trips = {}
    for z in glob.glob('/sys/class/thermal/thermal_zone*'):
        name = (_read(os.path.join(z, 'type')) or '').replace('-thermal', '')
        pts = []
        for p in glob.glob(os.path.join(z, 'trip_point_*_temp')):
            v = _read(p, int)
            typ = _read(p[:-5] + '_type')
            if v is not None and typ:
                pts.append({'type': typ, 'temp': v / 1000.0})
        if name and pts:
            trips[name] = sorted(pts, key=lambda d: d['temp'])
    passive = sorted({p['temp'] for ps in trips.values() for p in ps if p['type'] == 'passive'})
    critical = sorted({p['temp'] for ps in trips.values() for p in ps if p['type'] == 'critical'})
    _static = {
        'trips': trips,
        # 給介面的燈號：第一個被動降頻點、主要降頻點、關機點
        'throttle_first_c': passive[0] if passive else None,
        'throttle_main_c': passive[-1] if passive else None,
        'critical_c': critical[0] if critical else None,
        'model': (_read('/proc/device-tree/model') or '').replace('\x00', ''),
        'l4t': (_read('/etc/nv_tegra_release') or '').split(',')[0:2],
        'power_mode': mode,
        'cpu_count': os.cpu_count(),
        'gpu_max_mhz': (_read('/sys/class/devfreq/17000000.gpu/max_freq', int) or 0) / 1e6,
    }
    return _static


def _cpu_util():
    """各核使用率（%），由 /proc/stat 兩次讀數的差算。第一次呼叫回 None。"""
    global _prev_cpu
    cur = {}
    try:
        with open('/proc/stat') as fh:
            for ln in fh:
                if ln.startswith('cpu') and ln[3].isdigit():
                    p = ln.split()
                    v = list(map(int, p[1:9]))
                    idle = v[3] + v[4]
                    cur[p[0]] = (sum(v), idle)
    except OSError:
        return None
    prev, _prev_cpu = _prev_cpu, cur
    if not prev:
        return None
    out = []
    for k in sorted(cur, key=lambda s: int(s[3:])):
        if k not in prev:
            out.append(None)
            continue
        dt, di = cur[k][0] - prev[k][0], cur[k][1] - prev[k][1]
        out.append(round(100.0 * (1 - di / dt), 1) if dt > 0 else 0.0)
    return out


def sample():
    """一筆快照。欄位缺就是 None，不要編預設值。"""
    temps = {}
    for z in glob.glob('/sys/class/thermal/thermal_zone*'):
        t = _read(os.path.join(z, 'type'))
        v = _read(os.path.join(z, 'temp'), int)
        if t and v is not None and v > -40000:
            temps[t.replace('-thermal', '')] = round(v / 1000.0, 1)

    rails = {}
    h = _hwmon('ina3221')
    if h:
        for lab in glob.glob(os.path.join(h, 'in*_label')):
            i = os.path.basename(lab)[2:-6]
            name = _read(lab)
            mv = _read(os.path.join(h, 'in%s_input' % i), int)
            ma = _read(os.path.join(h, 'curr%s_input' % i), int)
            if name and name.startswith('VDD') and mv is not None and ma is not None:
                rails[name] = {'v': round(mv / 1000.0, 3), 'a': round(ma / 1000.0, 3),
                               'w': round(mv * ma / 1e6, 3)}

    freqs = [(_read('/sys/devices/system/cpu/cpu%d/cpufreq/scaling_cur_freq' % c, int) or 0) / 1000.0
             for c in range(os.cpu_count() or 0)]
    util = _cpu_util()

    mem = {}
    try:
        with open('/proc/meminfo') as fh:
            for ln in fh:
                k, v = ln.split(':', 1)
                mem[k] = int(v.split()[0])           # kB
    except OSError:
        pass
    fan_h, tach_h = _hwmon('pwmfan'), _hwmon('pwm_tach')
    pwm = _read(os.path.join(fan_h, 'pwm1'), int) if fan_h else None
    st = os.statvfs('/')
    load1 = (_read('/proc/loadavg') or '0').split()[0]

    return {
        'ts': datetime.now().isoformat(sep=' ', timespec='seconds'),
        'temps': temps,
        'rails': rails,
        'cpu_util': util,
        'cpu_util_avg': round(sum(util) / len(util), 1) if util else None,
        'cpu_mhz': [round(f) for f in freqs],
        'gpu_util': (_read('/sys/devices/platform/bus@0/17000000.gpu/load', int) or 0) / 10.0,
        'gpu_mhz': round((_read('/sys/class/devfreq/17000000.gpu/cur_freq', int) or 0) / 1e6),
        'ram_used_gb': round((mem.get('MemTotal', 0) - mem.get('MemAvailable', 0)) / 1048576, 2),
        'ram_total_gb': round(mem.get('MemTotal', 0) / 1048576, 2),
        'swap_used_gb': round((mem.get('SwapTotal', 0) - mem.get('SwapFree', 0)) / 1048576, 2),
        'fan_pct': None if pwm is None else round(pwm / 255 * 100),
        'fan_rpm': _read(os.path.join(tach_h, 'rpm'), int) if tach_h else None,
        'disk_used_gb': round((st.f_blocks - st.f_bfree) * st.f_frsize / 1e9, 1),
        'disk_total_gb': round(st.f_blocks * st.f_frsize / 1e9, 1),
        'load1': float(load1),
        'uptime_hr': round(float((_read('/proc/uptime') or '0').split()[0]) / 3600, 2),
    }


def _loop():
    _cpu_util()                                   # 先讀一次，下一筆才有差可算
    while not _stop.wait(SAMPLE_SEC):
        try:
            s = sample()
            with _lock:
                HISTORY.append(s)
        except Exception as e:                    # noqa: BLE001  取樣失敗不能讓執行緒死掉
            print('[jetson_hw] 取樣失敗：%s: %s' % (type(e).__name__, e))


def start():
    global _thread
    if not available() or (_thread and _thread.is_alive()):
        return False
    static_info()
    _stop.clear()
    _thread = threading.Thread(target=_loop, name='jetson_hw', daemon=True)
    _thread.start()
    return True


def stop():
    _stop.set()


def status():
    if not available():
        return {'available': False, 'reason': '這台不是 Jetson（找不到 /etc/nv_tegra_release）'}
    with _lock:
        last = HISTORY[-1] if HISTORY else None
    return {'available': True, 'static': static_info(), 'now': last or sample(),
            'sample_sec': SAMPLE_SEC, 'n_history': len(HISTORY)}


def history(minutes=60):
    """最近 N 分鐘的時間序列（欄位攤平，前端直接畫）。"""
    with _lock:
        rows = list(HISTORY)
    if minutes:
        rows = rows[-max(1, int(minutes * 60 / SAMPLE_SEC)):]
    def col(f):
        return [f(r) for r in rows]
    t = lambda r, k: r['temps'].get(k)
    rail = lambda r, k: (r['rails'].get(k) or {}).get('w')
    return {
        'ts': col(lambda r: r['ts']),
        'temp_cpu': col(lambda r: t(r, 'cpu')),
        'temp_gpu': col(lambda r: t(r, 'gpu')),
        'temp_cv': col(lambda r: max([v for k, v in r['temps'].items() if k.startswith('cv')], default=None)),
        'temp_soc': col(lambda r: max([v for k, v in r['temps'].items() if k.startswith('soc')], default=None)),
        'temp_tj': col(lambda r: t(r, 'tj')),
        'w_in': col(lambda r: rail(r, 'VDD_IN')),
        'w_cpu_gpu_cv': col(lambda r: rail(r, 'VDD_CPU_GPU_CV')),
        'w_soc': col(lambda r: rail(r, 'VDD_SOC')),
        'v_in': col(lambda r: (r['rails'].get('VDD_IN') or {}).get('v')),
        'cpu': col(lambda r: r['cpu_util_avg']),
        'gpu': col(lambda r: r['gpu_util']),
        'ram': col(lambda r: r['ram_used_gb']),
        'fan_rpm': col(lambda r: r['fan_rpm']),
    }
