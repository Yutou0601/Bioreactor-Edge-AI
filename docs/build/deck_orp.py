
# -*- coding: utf-8 -*-
"""補充簡報：2026-08-20 的三項發現。版式沿用同一個模板。

ORP 放第一，因為那是洪博提出疑問、且直接影響論文宣稱的一項。
"""
import os
import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from pptx import Presentation
from pptx.enum.text import PP_ALIGN
from pptx.util import Cm

import build_deck as B
from build_deck import (BLUE, GREY, INK, RED, RULE, W, bullets, caption,
                        chrome, note, page, pic, put, rect, table,
                        textbox)

OUT = os.path.join(B.HERE, 'decks', '補充簡報_ORP與獨立驗證_2026-08-20.pptx')


def cover(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    rect(s, Cm(0.6), Cm(5.6), W - Cm(1.2), Cm(0.05), RULE)
    tf = textbox(s, Cm(2.0), Cm(6.6), W - Cm(4.0), Cm(5.0))
    put(tf, [('2026-08-20 三項發現', 34, True, INK)], first=True,
        space_after=14, align=PP_ALIGN.CENTER)
    put(tf, [('ORP 量到的是什麼 ｜ 甲烷化學計量驗證 ｜ 十分鐘循環的失效',
              17, False, INK)], space_after=14, align=PP_ALIGN.CENTER)
    put(tf, [('第一項直接影響論文宣稱，建議納入本次投稿；'
              '後兩項證據尚未覆核，列為下一階段', 13, False, GREY)],
        align=PP_ALIGN.CENTER)
    rect(s, Cm(0.6), Cm(12.6), W - Cm(1.2), Cm(0.05), RULE)
    chrome(s, B.nextno())


def p1(prs):
    s = page(prs, 'ORP 我們實際量到的是什麼', '洪博的疑問：2 mV 不太可能')
    table(s, Cm(1.4), Cm(3.2), W - Cm(2.8),
          [['項目', '實際情形'],
           ['程式的定義', 'dORP = 該循環末筆讀數 − 首筆讀數（端點差）'],
           ['論文的用詞', 'the redox excursion（擺幅）　← 與實作不符'],
           ['紀錄的範圍', '337 ~ 610 mV，62,640 筆全部為正'],
           ['真實電位', '−610 ~ −337 mV（記錄器只存絕對值）'],
           ['實機表頭', '照片顯示 −585 mV，紀錄裡是 585　← 獨立佐證'],
           ['尺度', 'Nernst 對數；30°C、n=2 每 30 mV 對應濃度比 10 倍']],
          widths=[Cm(7.4), Cm(23.7)], fs=14, hi_rows=(2,))
    note(s, '★ 洪博說的「−600多至−400多」與資料完全吻合。'
            '記憶裡另有「−357 mV vs SHE」，兩者都對 —— '
            '差別在參考電極：表頭讀數對 Ag/AgCl，換算到標準氫電極約 +200 mV。')


def p2(prs):
    s = page(prs, '為什麼會出現「2 mV」', '不是數值錯，是定義把過程丟掉了')
    pic(s, 'figY_orp.png', Cm(2.4), Cm(3.1), Cm(29.0))
    caption(s, Cm(1.2), Cm(12.1), W - Cm(2.4), '-',
            '左：一個真實循環，擺幅 119 mV 但端點差只有 19 mV。'
            '中：全部 62,640 筆的真值分布與文獻最適窗口。'
            '右：控制循環時長前後的秩相關。')
    tf = textbox(s, Cm(1.6), Cm(13.0), W - Cm(3.2), Cm(2.0))
    put(tf, [('• 補氣後急降、週期性起伏、再回升 → ', 15),
             ('端點差只抓到擺幅的 16%', 15, True, RED)], first=True,
        space_after=7)
    put(tf, [('• 洪博一眼看出不合理，正是因為他知道真實擺幅是'
              '幾十到上百 mV', 15, False, GREY)])
    note(s, '★ 這不是統計上的混淆，是量錯了東西 —— '
            '論文說量擺幅，程式量的是端點差。', color=INK)


def p3(prs):
    s = page(prs, 'ORP 檢核還剩下什麼', '有東西留著，但比論文寫的弱')
    table(s, Cm(1.4), Cm(3.2), W - Cm(2.8),
          [['檢定', '值', '判讀'],
           ['dORP 與 r_{b} 的秩相關', '+0.213', '論文 54% 跨度的來源'],
           ['dORP 與循環時長', '−0.231', '循環越長，累積漂移越多'],
           ['控制時長後的偏秩相關', '+0.150', '★ 掉三成，但沒有消失'],
           ['「高活躍」組的時長中位', '8.82 hr', '另兩組是 12.9 hr']],
          widths=[Cm(12.0), Cm(5.6), Cm(13.5)], fs=14, hi_rows=(3,))
    tf = textbox(s, Cm(1.6), Cm(8.4), W - Cm(3.2), Cm(5.0))
    put(tf, [('我曾用 dORP/Δt 正規化得到 +0.040 並判定「主要是長度」'
              '—— 該結論已撤回。', 15, True, RED)], first=True,
        space_after=11)
    put(tf, [('理由：電位是對數尺度，除以時間是對對數量做算術，'
              '只有在 Nernst 成立且濃度呈指數衰減時才合理；而本案 ORP '
              '同時受 H_{2}、pH、溶解 CO_{2} 影響，是混合電位。',
              15, False, GREY)], space_after=11)
    put(tf, [('中位數與秩相關在任何單調變換下不變 → ', 15),
             ('偏秩相關 +0.150 是唯一免於此疑慮的結論', 15, True, BLUE)])
    note(s, '★ 建議的論文改法：用詞由 excursion 改為 net change in redox '
            'potential across each cycle，並加註排序與循環長度部分共線。'
            '合計約 8 mm。')


def p4(prs):
    s = page(prs, '★ 甲烷化學計量驗證 —— 首次獨立於壓力通道',
             '化學計量給出硬上限 0.25，三批全部落在內')
    table(s, Cm(1.4), Cm(3.2), W - Cm(2.8),
          [['批次', '循環', 'n', '下降速率', '峰值 CH_{4}',
            'CH_{4}/消耗', '生物份額'],
           ['1', '1 分', '6', '0.0185 ± 0.0017', '31.64%', '0.2172', '87%'],
           ['2', '5 分', '10', '0.0434 ± 0.0309', '34.84%', '0.1682',
            '67%'],
           ['3', '10 分', '14', '0.0364 ± 0.0045', '43.04%', '0.1928',
            '77%']],
          widths=[Cm(3.0), Cm(3.4), Cm(2.4), Cm(7.6), Cm(5.6), Cm(4.6),
                  Cm(4.5)], fs=13, hi_rows=(1, 2, 3), hi_col=5)
    pic(s, 'figZ_batch_check.png', Cm(6.4), Cm(7.4), Cm(21.0))
    caption(s, Cm(1.4), Cm(14.3), W - Cm(2.8), '-',
            'CH_{4} 生成 ÷ 氣體消耗 = (f_{2}P_{2} − f_{1}P_{1}) ÷ '
            '(下降速率 × 總時數)；兩邊的頭空體積相消，故不需知悉該體積。')
    note(s, '★ 為什麼比論文現有檢核硬：純物理虛無、端點裁切、ORP、C2ST '
            '最終都源自同一支壓力通道或其模擬；這一項用的是分析儀真的'
            '讀到的甲烷，審稿人拿計算機就能複驗。', color=INK)


def p4b(prs):
    s = page(prs, '公式怎麼來的', '頭空體積在比值裡自動相消，所以不需要知道它')
    pic(s, 'figW1_formula.png', Cm(3.9), Cm(3.2), Cm(26.0))
    caption(s, Cm(1.4), Cm(14.0), W - Cm(2.8), '-',
            '左：起點與終點的莫耳盤點。'
            '右：兩邊都帶著同一個 V/(RT)，相除即相消。')
    note(s, '★ 必須用絕對壓（錶壓 + 1.033 kg/cm^{2}）：'
            '分子的 f·P 是分率乘壓力，不是壓力差，偏移不會自動抵消。',
         color=INK)


def p4c(prs):
    s = page(prs, '怎麼從比值反推出速率', '上限 0.25 就是「生物份額 100%」的情形')
    pic(s, 'figW2_inference.png', Cm(3.9), Cm(3.2), Cm(26.0))
    caption(s, Cm(1.4), Cm(14.0), W - Cm(2.8), '-',
            '左：化學計量給出的上限。'
            '右：由實測比值反推 r_{b} 的三個步驟。')
    note(s, '★ 這個檢定會自己抓錯：起點 CH_{4} 若誤設為 0%，'
            '比值變成 0.3164，對應生物份額 127% —— 物理上不可能。'
            '實測 0.2172 落在內，對應 87%。')


def p5(prs):
    s = page(prs, '⚠ 十分鐘循環：估計器的系統性失效',
             '把論文的估計器跑在同三批上，差異歸因於方法')
    table(s, Cm(1.4), Cm(3.2), W - Cm(2.8),
          [['批次', '篩後', '逐段 r_{b} 中位', '四分位', '化學計量', '差'],
           ['1 分', '7', '0.01344', '0.01213 / 0.01485', '0.01610',
            '+20%'],
           ['5 分', '9', '0.01896', '−0.07205 / 0.02259', '0.02920',
            '+54%'],
           ['10 分', '14', '−0.03057', '−0.09977 / 0.01682', '0.02810',
            '—']],
          widths=[Cm(4.0), Cm(3.4), Cm(6.6), Cm(9.0), Cm(4.6), Cm(3.5)],
          fs=14, hi_rows=(3,), hi_col=2)
    tf = textbox(s, Cm(1.6), Cm(8.0), W - Cm(3.2), Cm(5.0))
    put(tf, [('批次 1 是好消息：', 16, True, BLUE),
             ('估計器正常時與獨立化學驗證吻合到 20% 以內。', 16)],
        first=True, space_after=11)
    put(tf, [('批次 3 的中位是負的（物理上不可能），而且 ', 16),
             ('14 個循環全數通過曲率預篩', 16, True, RED)],
        space_after=11)
    put(tf, [('研判：10 分鐘循環質傳強，壓力在循環內就接近平衡而趨緩，'
              '該趨緩被歸給指數項，線性項被推到負值。曲率擋不住，'
              '因為那個彎確實存在。', 15, False, GREY)])
    note(s, '⚠ 資料集 C 的排除清單裡，0417-0427 那批也是 10 分鐘循環、'
            '同樣因中位為負而排除 —— 這是第二個獨立案例，代表它是'
            '高質傳下的系統性失效，不是單一批次的資料問題。')


def p5b(prs):
    s = page(prs, '三批的原始數據', '上排壓力軌跡、下排逐段估計')
    pic(s, 'figZ2_batch_full.png', Cm(4.9), Cm(3.1), Cm(24.0))
    caption(s, Cm(1.4), Cm(15.8), W - Cm(2.8), '-',
            '下排的灰點為逐段估計、藍虛線為該批中位、紅線為化學計量值、'
            '橘點線為論文全資料集中位 0.0126。批次 3 有大量負值。')


def p6(prs):
    s = page(prs, '本次投稿改什麼、不改什麼', '距截稿 11 天')
    table(s, Cm(1.4), Cm(3.2), W - Cm(2.8),
          [['項目', '處置', '理由'],
           ['ORP 用詞與限定', '★ 建議改，約 8 mm',
            '用詞與實作不符，屬事實陳述的修正'],
           ['10 分鐘失效模式', '看洪博的答覆再決定',
            '需先確認該條件下壓力是否提早趨於平衡'],
           ['甲烷化學計量驗證', '不進本篇',
            'n=3、峰值為目測、無誤差量化、未經覆核'],
           ['r_{b} 可能系統性偏低', '不進本篇',
            '三個同向跡象但都有選擇性，需下一階段釐清']],
          widths=[Cm(7.0), Cm(8.4), Cm(15.7)], fs=13, hi_rows=(1,))
    note(s, '★ 下一階段的第一個工作項：化學計量約束的狀態空間模型。'
            '請設備方自即日起，每次排氣記錄五項數值以累積約束點 —— '
            '資料要時間長出來，不必等投稿完再開始。', color=INK)


def main():
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, B.H
    cover(prs)
    for fn in (p1, p2, p3, p4, p4b, p4c, p5, p5b, p6):
        fn(prs)
    prs.save(OUT)
    print('OK', OUT, len(prs.slides._sldIdLst), '頁')


if __name__ == '__main__':
    main()
