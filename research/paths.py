
# -*- coding: utf-8 -*-
"""研究腳本共用的路徑解析。

⚠ 為什麼需要這支：2026-09-10 把 100 多支研究腳本從 `edge_backend/` 搬到
  `research/` 之後，那些腳本裡的 `os.path.join(HERE, 'Testing_data')` 全部
  指錯地方——HERE 從 edge_backend/ 變成了 research/ 或 research/<主題>/。
  system_test 第 2 項（線上 vs 離線估計器逐段比對）當場就紅了。

  當時可以逐檔改成寫死新路徑，但那會在下一次搬動時再壞一次，而且監控電腦
  上的資料夾位置與開發機不一定相同。所以改成**依序去找**：找得到就用。

用法：

    from paths import testing_data
    DATA = os.path.join(testing_data(), '202607至08最新循環研究')

⚠ 資料本身不進版控（115 MB，且是洪博的實驗原始資料）。找不到時丟出的
  例外訊息會列出找過哪些位置，不要改成靜默回傳 None——靜默失敗會讓分析
  跑出「0 個循環」然後照常印出結論。
"""
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)

# 依序嘗試。第一個是 2026-09-10 之後的正式位置，第二個是搬動前的舊位置
# （監控電腦或別人的 clone 可能還沒更新）。
_CANDIDATES = (
    os.path.join(_HERE, 'Testing_data'),
    os.path.join(_REPO, 'edge_backend', 'Testing_data'),
)


def testing_data():
    """回傳 Testing_data 的絕對路徑。找不到就丟例外，不靜默。"""
    for p in _CANDIDATES:
        if os.path.isdir(p):
            return p
    raise FileNotFoundError(
        '找不到 Testing_data。找過：\n  ' + '\n  '.join(_CANDIDATES) +
        '\n（這份資料不進版控，需要另外取得並放到第一個位置）')


def research_root():
    """research/ 本身——葉腳本要回頭找共用模組時用。"""
    return _HERE
