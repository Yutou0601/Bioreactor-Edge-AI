
# -*- coding: utf-8 -*-
"""部署自我檢查：裝完／更新完，先確認這台機器真的能跑，再啟動。

    python selfcheck.py            檢查
    python selfcheck.py --quiet    只在失敗時印東西

離 system_test.py 的分工：
  system_test  在**開發機**上驗「程式對不對」（34 項，要有測試資料，跑幾分鐘）
  selfcheck    在**現場機**上驗「這台裝好了沒」（幾秒，不需要測試資料）

⚠ 第 4 項是全部裡面最重要的。「資料夾路徑指錯」是最容易發生、又最難察覺的
  部署錯誤——服務會正常啟動、網頁會正常打開、只是永遠沒有資料進來。
  2026-07-22 記錄靜默中斷 17.5 小時無人發現，就是這一類。

⚠ 這支自己不可以載入 torch/pandas。它跑在 60 MB 預算的機器上，而且它的
  工作就是確認核心夠瘦——自己胖了就沒有意義。
"""
import os
import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
QUIET = '--quiet' in sys.argv

OK, BAD, WARN = [], [], []


def check(name, ok, detail='', fatal=True):
    """fatal=False 的項目失敗只警告，不擋啟動。"""
    if ok:
        OK.append(name)
    elif fatal:
        BAD.append((name, detail))
    else:
        WARN.append((name, detail))
    if not QUIET or not ok:
        mark = '[OK]' if ok else ('[★ ]' if fatal else '[! ]')
        print('  %s %-34s %s' % (mark, name, detail))


print('\n部署自我檢查')

# ── 1 Python ────────────────────────────────────────────────
v = sys.version_info
check('Python 版本', v >= (3, 9),
      '%d.%d.%d' % (v.major, v.minor, v.micro))

# ── 2 必要套件 ──────────────────────────────────────────────
for mod, why in (('fastapi', 'API 框架'), ('uvicorn', 'HTTP 伺服器'),
                 ('numpy', '估計器')):
    try:
        __import__(mod)
        check('套件 %s' % mod, True, why)
    except ImportError as e:
        check('套件 %s' % mod, False, '缺少（%s）— 請跑 install.bat' % e)

# ── 3 前端 ──────────────────────────────────────────────────
dist = os.path.join(os.path.dirname(HERE), 'web_frontend', 'dist')
idx = os.path.join(dist, 'index.html')
check('前端 dist/', os.path.isfile(idx),
      idx if os.path.isfile(idx)
      else '找不到 index.html —— 網頁會 404（pack 沒解全 or dist 沒進版控）')

# ── 4 站台設定（最重要）─────────────────────────────────────
try:
    from core import config
    cfg = config.load()
    has_env = os.path.exists(config.ENV_PATH)
    check('.env 存在', has_env,
          config.ENV_PATH if has_env else '用內建預設——請確認路徑是否適用本機',
          fatal=False)

    d = config.data_dir()
    exists = os.path.isdir(d)
    n_csv = 0
    if exists:
        n_csv = len([f for f in os.listdir(d) if f.lower().endswith('.csv')])
    # ⚠ 資料夾不存在＝服務會正常啟動但永遠沒資料。這是致命的。
    check('資料夾存在', exists,
          '%s（%d 個 CSV）' % (d, n_csv) if exists
          else '%s ← 不存在！改 edge_backend/.env 的 REACTOR_DATA_DIR' % d)
    # 資料夾在但沒有 CSV：可能是新機器還沒開始記錄，警告即可
    check('資料夾裡有 CSV', (not exists) or n_csv > 0,
          '%d 個' % n_csv if exists else '（略過）', fatal=False)
except Exception as e:                                       # noqa: BLE001
    check('站台設定', False, '%s: %s' % (type(e).__name__, e))

# ── 5 資料庫可寫 ────────────────────────────────────────────
try:
    from core import cycle_store as cs
    con = cs.connect()
    con.execute('SELECT COUNT(*) FROM cycle').fetchone()
    con.close()
    check('資料庫可讀寫', True, cs.DB_PATH)
except Exception as e:                                       # noqa: BLE001
    check('資料庫可讀寫', False, '%s: %s' % (type(e).__name__, e))

# ── 6 埠沒被占用 ────────────────────────────────────────────
import socket                                                  # noqa: E402
port = int(config.get('REACTOR_PORT') or 8000)
s = socket.socket()
s.settimeout(0.6)
busy = s.connect_ex(('127.0.0.1', port)) == 0
s.close()
# ⚠ 埠被占用多半是「已經有一份在跑」。那不是錯誤，但要講出來，
#   否則會有人開了第二份、然後納悶為什麼改了設定沒有生效。
check('埠 %d 可用' % port, not busy,
      '已經有服務在這個埠上——可能已經啟動過了' if busy else '空著',
      fatal=False)

# ── 7 記憶體守門 ────────────────────────────────────────────
# ⚠ 這支自己不該把重量級套件拉進來。真要載入 main 才知道核心乾不乾淨，
#   但那會拖慢啟動；這裡只確認「到目前為止」沒有人在 core 裡偷 import。
heavy = [m for m in ('torch', 'pandas', 'sklearn', 'scipy', 'xgboost')
         if m in sys.modules]
check('核心相依乾淨', not heavy,
      ('★ 載入了 ' + ', '.join(heavy)) if heavy else 'numpy only')

# ── 總結 ────────────────────────────────────────────────────
print()
if BAD:
    print('★ 有 %d 項不通過，不要啟動：' % len(BAD))
    for n, d in BAD:
        print('   · %s — %s' % (n, d))
    sys.exit(1)
if WARN and not QUIET:
    print('! %d 項提醒（不擋啟動）：' % len(WARN))
    for n, d in WARN:
        print('   · %s — %s' % (n, d))
print('檢查通過（%d 項）。' % len(OK))
sys.exit(0)
