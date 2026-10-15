
# -*- coding: utf-8 -*-
"""部署自我檢查：裝完／更新完，先確認這台機器真的能跑，再啟動。

    python selfcheck.py            檢查
    python selfcheck.py --quiet    只在失敗時印東西

離 system_test.py 的分工：
  system_test  在**開發機**上驗「程式對不對」（34 項，要有測試資料，跑幾分鐘）
  selfcheck    在**現場機**上驗「這台裝好了沒」（幾秒，不需要測試資料）

⚠ 兩台機器檢查的東西**不一樣**，而且有幾項是相反的。本檔依
  REACTOR_PROFILE 分流：

      monitor（4 GB Windows）  要有前端 dist、要有 CSV 資料夾、核心要瘦
      compute（Orin NX 16 GB） 這三項全部不適用——那台沒有前端、不讀 CSV、
                               而且重量級套件**本來就該**是熱著的

  2026-10-08 加上 compute 分支之前，在 Orin 上跑這支會在「前端 dist/」與
  「資料夾存在」兩項亮紅燈，而那兩項在那台機器上根本不該存在；
  同時「核心相依乾淨」會是綠的，但那台如果核心真的乾淨，代表套件沒裝起來，
  是**壞掉**而不是正常。照著紅綠燈修會把機器修壞。

⚠ monitor 模式下這支自己不可以載入 torch/pandas。它跑在 60 MB 預算的機器上，
  而且它的工作就是確認核心夠瘦——自己胖了就沒有意義。
  compute 模式下也一樣不載入 torch（只查有沒有裝），因為 import torch 要好
  幾秒，而且真正要驗的是 CUDA，那要另外跑一行指令（見下）。
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


def has(mod):
    """套件在不在，不實際 import（避免把重量級套件拉進這支行程）。"""
    import importlib.util
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


# ── 0 這台是什麼角色 ────────────────────────────────────────
# ⚠ 先決定角色再檢查。profile() 對拼錯的值會直接 SystemExit，
#   這正是我們要的——與其默默當成 monitor，不如在這裡就停。
try:
    from core import config
    PROFILE = config.profile()
except SystemExit:
    raise
except Exception as e:                                       # noqa: BLE001
    print('\n★ 讀不到站台設定：%s: %s' % (type(e).__name__, e))
    sys.exit(1)

print('\n部署自我檢查（角色：%s）' % PROFILE)
IS_COMPUTE = PROFILE == 'compute'

# ── 1 Python ────────────────────────────────────────────────
v = sys.version_info
check('Python 版本', v >= (3, 9),
      '%d.%d.%d' % (v.major, v.minor, v.micro))

# ── 2 必要套件 ──────────────────────────────────────────────
need = [('fastapi', 'API 框架'), ('uvicorn', 'HTTP 伺服器'),
        ('numpy', '估計器')]
if IS_COMPUTE:
    # 這台的工作就是把重的東西熱著，所以它們是**必要**的，不是違規的。
    need += [('scipy', 'covariate'),
             ('pandas', 'covariate'),
             ('sklearn', 'ch4_attribution'),
             ('joblib', '模型序列化')]
for mod, why in need:
    try:
        __import__(mod)
        check('套件 %s' % mod, True, why)
    except ImportError as e:
        check('套件 %s' % mod, False,
              '缺少（%s）— 請跑 %s' % (e, 'install_jetson.sh' if IS_COMPUTE
                                      else 'install.bat'))

if IS_COMPUTE:
    # xgboost 沒有也能跑（ch4_attribution 會退回 GA+Ridge），但結果較差，
    # 而且 aarch64 常常要自己編譯，很容易裝失敗卻沒人發現 -> 列為警告。
    check('套件 xgboost', has('xgboost'),
          '有' if has('xgboost')
          else '缺少 — ch4_attribution 會退回 GA+Ridge（能跑，結果較差）',
          fatal=False)
    # ⚠ 不要在這裡 import torch：要花好幾秒，而且真正要驗的是 CUDA。
    check('套件 torch', has('torch'),
          '有 — 請另外跑：python -c "import torch; print(torch.cuda.is_available())"'
          if has('torch')
          else '未安裝 — 目前三個模組都用不到，不擋上線', fatal=False)

# ── 3 前端 ──────────────────────────────────────────────────
# compute 那台不出網頁，沒有 dist 是正常的。
if not IS_COMPUTE:
    dist = os.path.join(os.path.dirname(HERE), 'web_frontend', 'dist')
    idx = os.path.join(dist, 'index.html')
    check('前端 dist/', os.path.isfile(idx),
          idx if os.path.isfile(idx)
          else '找不到 index.html —— 網頁會 404（pack 沒解全 or dist 沒進版控）')

# ── 4 站台設定（monitor 最重要的一項）───────────────────────
try:
    has_env = os.path.exists(config.ENV_PATH)
    check('.env 存在', has_env,
          config.ENV_PATH if has_env else '用內建預設——請確認路徑是否適用本機',
          fatal=False)

    if IS_COMPUTE:
        # ⚠ compute 這台不讀 CSV。它反而不該設 REACTOR_COMPUTE_URL——
        #   設了代表有人把 monitor 的 .env 直接複製過來，那會讓這台去呼叫
        #   它自己（或呼叫 monitor），形成迴圈或整條鏈靜默錯位。
        u = config.compute_url()
        check('沒有誤設 REACTOR_COMPUTE_URL', not u,
              '未設（正確）' if not u
              else '★ 設成 %s ——這是 monitor 專用的。compute 這台設了會指向'
                   '自己或繞回去，請從 .env 移除' % u)
    else:
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

# ── 5 資料庫可寫（只有 monitor）─────────────────────────────
# ⚠ compute 那台**不寫資料庫**（compute_node/server.py 的設計）。
#   在那台上建一個 reactor.db 只會讓人以為結果有存下來。
if not IS_COMPUTE:
    try:
        from core import cycle_store as cs
        con = cs.connect()
        con.execute('SELECT COUNT(*) FROM cycle').fetchone()
        con.close()
        check('資料庫可讀寫', True, cs.DB_PATH)
    except Exception as e:                                   # noqa: BLE001
        check('資料庫可讀寫', False, '%s: %s' % (type(e).__name__, e))

# ── 6 埠沒被占用 ────────────────────────────────────────────
import socket                                                  # noqa: E402
if IS_COMPUTE:
    port = int(config.get('REACTOR_COMPUTE_PORT') or 8100)
else:
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

# ── 7 記憶體守門 / 模組可載入 ───────────────────────────────
if IS_COMPUTE:
    # 這台的檢查方向**相反**：要確認三個模組真的載得起來。
    # ⚠ 只檢查檔案與宣告，不實際 import analysis——那要吃掉幾百 MB 又要幾秒，
    #   而且三個模組的分析檔都叫 analysis.py，順序一錯就會互相覆蓋
    #   （見 compute_node/server.py 的 _swap_analysis）。真正的載入由
    #   server.py 啟動時做，它會把每個模組的狀態印出來。
    import json
    mdir = os.path.join(HERE, 'modules')
    names = sorted(d for d in os.listdir(mdir)
                   if os.path.isdir(os.path.join(mdir, d))
                   and not d.startswith('__'))
    check('找得到模組', len(names) >= 1, '%d 個：%s' % (len(names), ', '.join(names)))
    for n in names:
        rp = os.path.join(mdir, n, 'run.py')
        jp = os.path.join(mdir, n, 'module.json')
        if not os.path.isfile(rp):
            check('模組 %s' % n, False, '缺 run.py')
            continue
        src = open(rp, encoding='utf-8', errors='replace').read()
        # ⚠ 沒有 compute_row 的模組只能在監控電腦上開子行程跑，
        #   送到這台會失敗。這是最容易漏掉的一種「裝好了但不會動」。
        ok_fn = 'def compute_row' in src
        detail = 'compute_row ✓' if ok_fn else \
            '★ 沒有 compute_row()——這個模組不能在重運算節點上跑'
        if os.path.isfile(jp):
            try:
                json.load(open(jp, encoding='utf-8'))
            except Exception as e:                           # noqa: BLE001
                ok_fn, detail = False, 'module.json 壞了：%s' % e
        check('模組 %s' % n, ok_fn, detail)

    # 這是 Jetson 嗎？不是的話很多假設（CUDA、nvpmodel、swap）都不成立。
    l4t = '/etc/nv_tegra_release'
    check('是 Jetson（L4T）', os.path.exists(l4t),
          open(l4t, encoding='utf-8', errors='replace').read().strip()[:60]
          if os.path.exists(l4t)
          else '找不到 %s —— 這台不是 Jetson，CUDA 與 nvpmodel 的步驟不適用' % l4t,
          fatal=False)

    # swap：xgboost 若要從原始碼編譯，記憶體不夠會被 OOM killer 砍掉，
    # 而且錯誤訊息常常只是「Killed」，很難看出是記憶體問題。
    try:
        mi = dict()
        for line in open('/proc/meminfo', encoding='utf-8'):
            k, _, rest = line.partition(':')
            mi[k.strip()] = rest.strip()
        sw = int(mi.get('SwapTotal', '0 kB').split()[0]) / 1048576.0
        check('swap', sw >= 4.0, '%.1f GB%s'
              % (sw, '' if sw >= 4.0 else ' —— 編 xgboost 建議 >= 4 GB'),
              fatal=False)
    except Exception:                                        # noqa: BLE001
        pass
else:
    # ⚠ 這支自己不該把重量級套件拉進來。真要載入 main 才知道核心乾不乾淨，
    #   但那會拖慢啟動；這裡只確認「到目前為止」沒有人在 core 裡偷 import。
    heavy = [m for m in ('torch', 'pandas', 'sklearn', 'scipy', 'xgboost')
             if m in sys.modules]
    check('核心相依乾淨', not heavy,
          ('★ 載入了 ' + ', '.join(heavy)) if heavy else 'numpy only')

    # 設了重運算節點的話，順手確認連得到。連不到不擋啟動（模組才會失敗），
    # 但要現在就講，不要等到排程跑起來才在紀錄裡看到。
    u = config.compute_url()
    if u:
        import urllib.request
        try:
            with urllib.request.urlopen(u.rstrip('/') + '/health', timeout=3) as r:
                import json as _json
                hj = _json.loads(r.read().decode('utf-8'))
            # ⚠ /health 回的欄位叫 role（不是 profile）。對錯欄位的話這裡
            #   永遠是紅的，而服務其實是好的。
            check('重運算節點', hj.get('role') == 'compute',
                  '%s（角色 %s，RSS %s MB）'
                  % (u, hj.get('role'), hj.get('rss_mb')), fatal=False)
        except Exception as e:                               # noqa: BLE001
            check('重運算節點', False,
                  '連不到 %s（%s）——模組會失敗，不會退回本機跑'
                  % (u, type(e).__name__), fatal=False)

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
