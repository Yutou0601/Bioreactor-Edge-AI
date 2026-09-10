
# -*- coding: utf-8 -*-
"""站台設定：每台機器不同的東西集中在這裡。

開發在筆電、正式跑在監控電腦，兩台的資料夾路徑不一樣。以前這些值散在各支
程式的預設參數裡（例如 csv_watcher 的 DEFAULT_DIR = r'C:\\Users\\BTP\\...'），
結果是：監控電腦上改過的值，下一次 git pull 就被覆蓋回去。

作法：`.env` 放在 edge_backend/ 下，**不進版控**（.gitignore 有擋）。
範本是 .env.example，部署時複製一份改成自己的值。

⚠ 不用 python-dotenv：那是一個為了讀 KEY=VALUE 而加的相依，而監控電腦
  的記憶體預算是 60 MB。這裡 20 行標準庫就夠。

⚠ 環境變數優先於 .env。這樣臨時要覆蓋一個值不必改檔案：
      set REACTOR_DATA_DIR=D:\\test && python main.py
"""
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(HERE, '.env')

_DEFAULTS = {
    # 記錄程式寫出 CSV 的資料夾。csv_watcher 監看它。
    'REACTOR_DATA_DIR': r'C:\Users\BTP\Desktop\data',
    # 後端位址與埠
    'REACTOR_HOST': '127.0.0.1',
    'REACTOR_PORT': '8000',
    # 循環資料庫。留空＝edge_backend/reactor.db
    'REACTOR_DB': '',
    # LSTM 壓力預測：預設關。開啟會讓 CSV 匯入把 torch 拉進常駐行程
    # （實測 RSS 62 → 348 MB），而該預測值前端並不顯示。
    'REACTOR_ENABLE_LSTM': '0',
    # csv_watcher 檢查間隔（秒）
    'REACTOR_POLL_SECONDS': '60',
}

_cache = None


def _parse_env_file(path):
    """讀 KEY=VALUE。忽略空行與 # 開頭；值兩側的引號會去掉。"""
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding='utf-8-sig', errors='replace') as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, _, v = line.partition('=')
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in '"\'':
                v = v[1:-1]
            out[k.strip()] = v
    return out


def load():
    """回傳完整設定。順序：環境變數 > .env > 內建預設。"""
    global _cache
    if _cache is None:
        from_file = _parse_env_file(ENV_PATH)
        _cache = {}
        for k, default in _DEFAULTS.items():
            _cache[k] = os.environ.get(k) or from_file.get(k) or default
    return _cache


def get(key, default=None):
    return load().get(key, default)


def data_dir():
    return get('REACTOR_DATA_DIR')


def api_base():
    return 'http://%s:%s' % (get('REACTOR_HOST'), get('REACTOR_PORT'))


def describe():
    """啟動時印出來，讓人一眼看出這台機器讀的是哪個資料夾。

    ⚠ 這很重要：2026-07-22 記錄靜默中斷 17.5 小時沒人發現。設定印在啟動
      訊息裡，至少「指到錯的資料夾」這種錯會當場看見。
    """
    cfg = load()
    src = '.env' if os.path.exists(ENV_PATH) else '內建預設（沒有 .env）'
    lines = ['[設定] 來源：%s' % src]
    for k in sorted(cfg):
        lines.append('[設定]   %-22s %s' % (k, cfg[k] or '（未設，用預設）'))
    return '\n'.join(lines)
