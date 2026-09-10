
# -*- coding: utf-8 -*-
"""資料集 C：條件一致的循環（供全部主結果共用）。
════════════════════════════════════════════════════════════════════════

先前所有主結果都跑在 collect() 的全部 351 個循環上。實測發現那是
**跨異質條件合併**的：橫跨 2025–2026、三種循環時間、有無循環兩種運轉
模式，以及兩種進氣比例。逐來源的中位 r_b 由 −0.031 到 +0.020 不等。

C 的排除準則**全部可事前查證，且不看結果**：

  1. `0109-0123_H2_1CO2_1`
     檔名載明 H2:CO2 = 1:1，與本文所述之 4:1 化學計量比不符。
     進氣比例不同，壓力下降中物理與生物的比例即不同，不可混同。

  2. `0301-0416_無循環與有循環_5mins`
     檔名載明該期間**含無循環時段**。本文 §3 敘述液體持續循環，
     無循環時段的 kLa 完全不同（歷史分析：有循環 kLa 為 2.4 倍）。

  3. `0417-0427_有循環_10mins_74%`
     該批中位 r_b = −0.031，即「生物製造壓力」，物理上不可能。
     屬資料品質問題，非表現不佳。

⚠ **不得再以「表現差」為由排除任何批次。** 依結果篩資料會使其後所有
  p 值與信賴區間失效，且審稿人只要問「準則何時訂定」即可拆穿。
  若設備方確認某批為試機或條件不同，那是新的事前理由，需另行記錄。

用法：
    from dataset_c import collect_c
    cycles = collect_c()          # 與 residual_structure.collect() 同介面
"""
import hashlib
import sys

import numpy as np

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from residual_structure import collect                            # noqa: E402

EXCLUDE = {
    '0109-0123_H2_1CO2_1':
        '檔名載明 H2:CO2 = 1:1，與 4:1 化學計量比不符',
    '0301-0416_無循環與有循環_5mins':
        '檔名載明含無循環時段，kLa 與有循環時期不同',
    '0417-0427_有循環_10mins_74%':
        '該批中位 r_b 為負（生物製造壓力），物理上不可能',
}


def _fingerprint(y):
    """壓力序列的內容指紋（量化到 0.01 階，避開浮點誤差）。"""
    a = np.round(np.asarray(y, dtype=float) / 0.01).astype(np.int64)
    return hashlib.md5(a.tobytes()).hexdigest()


def collect_c(verbose=False):
    """回傳條件一致、且**去重**的循環，介面與 collect() 相同。

    ⚠ 2026-08-24 補上去重。`Testing_data` 底下 351 個 CSV 只有 251 個
      相異內容——同一批原始記錄檔被複製到多個資料夾（`data`、
      `20260727_1min_data`、`202607至08最新循環研究` 三者互相涵蓋，
      連 MD5 都相同）。不去重的話**同一段物理下降會被當成 2~3 個獨立
      觀測**：段數灌水 13%，且 bootstrap 會低估抽樣誤差，因為重複的
      副本不帶任何新資訊。

      去重以壓力序列的內容為準，不以檔名或資料夾為準（同一天的檔在不同
      資料夾裡檔名相同，但也可能有截斷版本，長度不同就是不同段）。
      保留排序後第一次出現的那一份，故結果與列舉順序無關。
    """
    allc = collect()
    kept = [(t, x, y) for t, x, y in allc if t not in EXCLUDE]
    out, seen = [], set()
    for tag, x, y in kept:
        f = _fingerprint(y)
        if f in seen:
            continue
        seen.add(f)
        out.append((tag, x, y))
    if verbose:
        print('資料集 C：%d → %d（排除）→ %d（去重）個循環'
              % (len(allc), len(kept), len(out)))
        for k, why in EXCLUDE.items():
            n = sum(1 for t, _, _ in allc if t == k)
            print('   排除 %-38s n=%-3d  %s' % (k, n, why))
        print('   去重     移除 %d 段重複計數的同一下降'
              % (len(kept) - len(out)))
    return out


if __name__ == '__main__':
    collect_c(verbose=True)
