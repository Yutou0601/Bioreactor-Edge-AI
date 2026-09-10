
# -*- coding: utf-8 -*-
"""簡報逐頁內容（24 頁）。版式函式取自 build_deck.py，樣式對齊 8 月模板。

兩件事在這一版被特別處理：

1. 第 2 頁不可省略——本版與 8 月版的結論相反（8 月版「r_{b} 未被辨識」，
   本版「恆定真值被排除、速率可回復」）。原因是資料集、估計量、虛無三者
   都換了。不主動說明會被當成前後不一致。

2. 第 7～12 頁是「結果怎麼做出來的」五步驟。依指示以淺顯方式講，
   不放虛擬碼、不放概似函數；每一步都先給一句白話再接上實際數字。
   校準那一步用「拿砝碼校磅秤」講——它就是那件事，而且是全篇的樞紐。
"""
import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Cm, Pt

from build_deck import (BLUE, BOXBG, GREY, H, INK, OUT, RED, RULE, THEAD, nextno,
                        TROW2, W, WHITE, bullets, chrome, note, page, pic,
                        put, rect, table, textbox, caption)


# ── 流程方塊（第 7 頁的五步驟圖） ─────────────────────────────
def stepbox(slide, x, y, w, h, no, title, body, fill=TROW2):
    b = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h)
    b.fill.solid()
    b.fill.fore_color.rgb = fill
    b.line.color.rgb = THEAD
    b.line.width = Pt(1.0)
    b.shadow.inherit = False
    tf = textbox(slide, x + Cm(0.3), y + Cm(0.4), w - Cm(0.6),
                 h - Cm(0.8))
    put(tf, [(no + '　' + title, 16, True, INK)], first=True,
        space_after=6, align=PP_ALIGN.CENTER)
    put(tf, [(body, 12, False, GREY)], align=PP_ALIGN.CENTER)
    return b


def arrow(slide, x, y, w, h=Cm(0.5)):
    a = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, x, y, w, h)
    a.fill.solid()
    a.fill.fore_color.rgb = THEAD
    a.line.fill.background()
    a.shadow.inherit = False
    return a


def sieve(slide, x, y):
    """篩子示意：280 段進去，239 段留下，41 段被擋掉。

    用原生圖形而不是圖檔，字才不會因為縮放而糊掉。
    """
    def box(bx, by, bw, bh, top, bottom, fill, line, fs=15):
        b = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, bx, by,
                                   bw, bh)
        b.fill.solid(); b.fill.fore_color.rgb = fill
        b.line.color.rgb = line; b.line.width = Pt(1.2)
        b.shadow.inherit = False
        tb = textbox(slide, bx + Cm(0.2), by + Cm(0.35), bw - Cm(0.4),
                     bh - Cm(0.6))
        put(tb, [(top, fs + 5, True, line)], first=True, space_after=4,
            align=PP_ALIGN.CENTER)
        put(tb, [(bottom, 12, False, GREY)], align=PP_ALIGN.CENTER)

    box(x, y, Cm(5.0), Cm(2.6), '280 段', '切出來的全部', BOXBG, THEAD)
    arrow(slide, x + Cm(5.1), y + Cm(1.0), Cm(1.1), Cm(0.6))
    box(x + Cm(6.3), y - Cm(0.2), Cm(5.4), Cm(3.0), 'c ≥ 0.45',
        '只看形狀，不必先擬合', TROW2, THEAD)
    arrow(slide, x + Cm(11.8), y + Cm(1.0), Cm(1.1), Cm(0.6))
    box(x + Cm(13.0), y, Cm(5.0), Cm(2.6), '239 段', '彎得夠明顯，留下',
        BOXBG, THEAD)
    tb = textbox(slide, x + Cm(6.0), y + Cm(3.2), Cm(6.0), Cm(1.0))
    put(tb, [('↓ 擋掉 41 段', 14, True, RED)], first=True,
        align=PP_ALIGN.CENTER)


# ── 逐頁 ─────────────────────────────────────────────────────
def cover(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    tf = textbox(s, Cm(2.0), Cm(3.4), W - Cm(4.0), Cm(5.0))
    put(tf, [('閾值觸發循環作為內生弛豫實驗：', 32, True, INK)],
        first=True, space_after=8, align=PP_ALIGN.CENTER)
    put(tf, [('從微正壓循環反應器的量化壓力挖掘生物甲烷化速率', 26, True,
              INK)], space_after=20, align=PP_ALIGN.CENTER)
    put(tf, [('Threshold-Triggered Cycles as Endogenous Relaxation '
              'Experiments: Mining a Biological Methanation Rate from '
              'Quantized Pressure', 15, True, BLUE)], space_after=0,
        align=PP_ALIGN.CENTER)
    rect(s, Cm(6.0), Cm(11.6), W - Cm(12.0), Cm(0.03), GREY)
    tf2 = textbox(s, Cm(2.0), Cm(12.2), W - Cm(4.0), Cm(4.4))
    put(tf2, [('報告人：李承育', 22, False, INK)], first=True,
        space_after=16, align=PP_ALIGN.CENTER)
    put(tf2, [('李承育^{1}　陳俊豪^{1}　洪政源^{2}　黃彥傑^{2}', 14)], space_after=5,
        align=PP_ALIGN.CENTER)
    put(tf2, [('^{1} 國立高雄科技大學 資訊工程系　　'
               '^{2} 金屬工業研究發展中心 光電組', 12, False, GREY)],
        space_after=13, align=PP_ALIGN.CENTER)
    put(tf2, [('ICEA 2026 投稿中｜Springer LNCS｜', 12, False, GREY),
              ('10 頁上限', 12, True, RED),
              ('｜截止 2026-08-31', 12, False, GREY)],
        align=PP_ALIGN.CENTER)
    chrome(s)


def p1b(prs):
    """為什麼要做這件事——資料來源：洪政源計畫簡報。

    先前整份簡報只證明「做得到」，沒說「為什麼要做」。
    """
    s = page(prs, '為什麼要做這件事',
             '傳統厭氧消化有四個階段，本系統只取最後一段')
    steps = [('①', '水解', '複雜有機物\n分解'),
             ('②', '酸形成', '產生揮發性\n脂肪酸'),
             ('③', '產乙酸', '產生氫氣與\n二氧化碳'),
             ('④', '產甲烷', 'CO_{2} + H_{2}\n→ CH_{4}')]
    bw, gap = Cm(6.6), Cm(0.9)
    x0 = Cm(3.4)
    for i, (no, t1, t2) in enumerate(steps):
        x = x0 + i * (bw + gap)
        last = (i == 3)
        b = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, Cm(3.3),
                               bw, Cm(2.9))
        b.fill.solid()
        b.fill.fore_color.rgb = TROW2 if last else BOXBG
        b.line.color.rgb = RED if last else THEAD
        b.line.width = Pt(1.6 if last else 1.0)
        b.shadow.inherit = False
        tb = textbox(s, x + Cm(0.3), Cm(3.65), bw - Cm(0.6), Cm(2.2))
        put(tb, [(no + '　' + t1, 15, True, RED if last else GREY)],
            first=True, space_after=5, align=PP_ALIGN.CENTER)
        put(tb, [(t2, 12, False, GREY)], align=PP_ALIGN.CENTER)
        if i < 3:
            arrow(s, x + bw + Cm(0.08), Cm(4.5), gap - Cm(0.16))
    tf = textbox(s, Cm(1.6), Cm(6.9), W - Cm(3.2), Cm(8.0))
    put(tf, [('本系統直接餵 CO_{2} 與 H_{2}，跳過前三段，'
              '只做第 ④ 段的甲烷化。', 17, True, BLUE)], first=True,
        space_after=16)
    put(tf, [('卡在哪裡：', 16, True, INK),
             ('氣體難溶於水，H_{2} 又比 CO_{2} 更難溶。氣體溶不進去、'
              '又不能連續供應，', 16),
             ('現有的二氧化碳生物甲烷化研究因此都侷限在實驗室批次。',
              16, True, RED)], space_after=14)
    put(tf, [('這台設備的解法：', 16, True, INK),
             ('加微正壓讓氣體留得住，再用泵把沒用完的氣體不斷送回液體，'
              '使反應可以連續進行。', 16)], space_after=14)
    put(tf, [('這篇論文的位置：', 16, True, INK),
             ('設備為了控制壓力，每天自己留下紀錄。', 16),
             ('我們不加任何硬體，只從那些紀錄裡把生物的速率讀出來。',
              16, True, RED)])
    note(s, '資料來源：洪政源，「以生物反應方式進行二氧化碳轉換成甲烷之'
            '微正壓循環控制系統開發」計畫簡報。')


def p3b(prs):
    """兩種「循環」與設備的硬限制——洪博本人最可能被搞混的地方。"""
    s = page(prs, '兩種「循環」不要搞混',
             '同一台機器上同時發生，但完全是兩件事')
    table(s, Cm(1.4), Cm(3.2), W - Cm(2.8),
          [['', '泵的循環', '補氣段（本簡報說的「段」）'],
           ['誰在動', '循環泵抽送氣體', '沒有誰在動，是壓力自然下降'],
           ['何時發生', '固定排程，例如每小時 5 分鐘', '壓力降到下限才補氣'],
           ['長度', '幾分鐘', '中位 10.3 小時'],
           ['在本文的角色', '影響質傳，是實驗條件', '每一段就是一次弛豫實驗']],
          widths=[Cm(6.0), Cm(11.5), Cm(13.6)], fs=14, hi_rows=(4,),
          hi_col=2)
    table(s, Cm(1.4), Cm(9.4), W - Cm(2.8),
          [['設備的硬限制', '數值', '造成的後果'],
           ['反應槽材質', '透明壓克力，耐壓 2 kg/cm^{2}、耐溫 40 度',
            '不能加壓、不能任意開孔'],
           ['最佳反應壓力', '不大於 2 kg/cm^{2}', '操作窗很窄'],
           ['氣體感測器位置', '接在閥 4 之後', '要排氣才讀得到 → 讀數多為過期']],
          widths=[Cm(8.0), Cm(13.6), Cm(9.5)], fs=13, hi_rows=(3,),
          hi_col=2)
    note(s, '★ 這頁的用意：實驗請求裡「觸發改固定時間間隔」指的是'
            '**補氣**改成定時，不是泵 —— 泵本來就是定時的。'
            '　三層分壓為反應物 6、反應菌 1.5、生成物 1 kg/cm^{2}。',
         color=INK)


def p3c(prs):
    """菌是什麼——外行人必問，先前一個字都沒交代。"""
    s = page(prs, '菌是什麼 —— 純化採購的嗜氫甲烷菌',
             '不是汙泥、不是混合菌相，是單一菌種')
    table(s, Cm(1.4), Cm(3.3), Cm(15.0),
          [['分類階層', 'Methanobacterium palustre'],
           ['界', '古菌界 Archaea'],
           ['門', '廣古菌門 Euryarchaeota'],
           ['綱', '甲烷桿菌綱 Methanobacteria'],
           ['目', '甲烷桿菌目 Methanobacteriales'],
           ['科', '甲烷桿菌科 Methanobacteriaceae'],
           ['屬', '甲烷桿菌屬 Methanobacterium'],
           ['種', '沼生甲烷桿菌 M. palustre']],
          widths=[Cm(4.4), Cm(10.6)], fs=13)
    tf = textbox(s, Cm(17.4), Cm(3.5), Cm(15.0), Cm(9.0))
    bullets(tf, ['能把 CO_{2} + H_{2} 轉成甲烷的是「嗜氫甲烷菌」，'
                 '主要有四個屬，均存在於當地環境',
                 '本研究經生物資源保存及研究中心採購',
                 '純菌研究委託中興大學陳老師'], fs=15, gap=12)
    put(tf, [('• 為什麼要用純菌：', 15, True, INK),
             ('提高嗜氫甲烷菌的濃度，', 15),
             ('降低混合菌相中乙酸甲烷菌的比例', 15, True, RED)],
        space_after=12)
    put(tf, [('• 培養基可用 CO_{2} + H_{2} 或甲酸', 15)])
    note(s, '★ 這對本文為什麼重要：菌相單一，代表壓力下降裡的生物那一份'
            '來自同一種代謝途徑，化學計量比 5 進 1 出才站得住。'
            '　資料來源：洪政源計畫簡報。', color=INK)


def p2(prs):
    s = page(prs, '本版與 8 月版的結論相反 —— 先講清楚',
             '不是同一份資料、不是同一個估計量、不是同一個虛無', 2)
    table(s, Cm(1.4), Cm(3.2), W - Cm(2.8),
          [['', '8 月版', '本版'],
           ['資料', '三批次 26 段', '條件一致時期 280 → 篩選 239'],
           ['估計量', '單步聯合擬合', '曲率預篩＋設計配對校準'],
           ['對虛無', 'p = 0.40（失敗）', 'p = 0.024'],
           ['主結論', 'r_{b} 未被辨識', '恆定真值被排除，速率可回復'],
           ['速率', '0.01104', '0.0126 [0.0112, 0.0142]']],
          widths=[Cm(5.2), Cm(11.4), Cm(14.5)], hi_rows=(4, 5), hi_col=2)
    note(s, '為什麼會翻轉：8 月版的設定誤差虛無與當時的估計量共用同一個'
            '單指數模型 —— 虛無偵測不到自己的設定誤差。本版改用逐段'
            '擬合的純物理參照，並另外掃描 k 依賴強度，兩者都不再共用'
            '那個假設。')


def p_map(prs):
    """一頁看懂：什麼問題 → 為什麼這樣做 → 解決了什麼。

    這頁不放任何新資訊，只把後面二十頁排成三欄，讓聽眾先拿到骨架。
    """
    s = page(prs, '一頁看懂 —— 問題、做法、結果',
             '後面每一頁都在填這張表裡的某一格')
    cols = [('什麼問題', RED,
             [('壓力會掉，但有兩個原因',
               '生物把氣體吃掉、CO_{2} 溶進水裡'),
              ('只有一支壓力計',
               '設備不准加裝，也不准對生產槽做激發'),
              ('兩項數學上可以互換',
               'r_{b} 差 2.5 倍的擬合，殘差只差 1%')]),
            ('為什麼這樣做', BLUE,
             [('先看形狀再擬合',
               '彎得夠明顯的段才留 → 280 收到 239'),
              ('拿已知答案校這把尺',
               '造假資料，只換掉真實速率，其餘照抄'),
              ('換三個角度去推翻它',
               '純物理、切分位置、ORP 各驗一次')]),
            ('解決了什麼', INK,
             [('速率被定出來了',
               '0.0126 [0.0112, 0.0142]，約 ±12%'),
              ('「速率不變」被排除',
               '恆定真值只給 ρ=0.304，實測 0.814，差 9σ'),
              ('而且跑得動',
               '純 NumPy，塞得進 60 MB 的監控電腦')])]
    cw, gap, x0, y0 = Cm(10.1), Cm(0.75), Cm(1.3), Cm(3.3)
    for j, (head, col, items) in enumerate(cols):
        x = x0 + j * (cw + gap)
        hb = rect(s, x, y0, cw, Cm(1.05), col)
        tf = textbox(s, x, y0 + Cm(0.22), cw, Cm(0.7))
        put(tf, [(head, 17, True, WHITE)], first=True,
            align=PP_ALIGN.CENTER)
        for i, (t1, t2) in enumerate(items):
            by = y0 + Cm(1.35) + i * Cm(3.55)
            b = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, by,
                                   cw, Cm(3.2))
            b.fill.solid(); b.fill.fore_color.rgb = BOXBG
            b.line.color.rgb = col; b.line.width = Pt(1.0)
            b.shadow.inherit = False
            tb = textbox(s, x + Cm(0.35), by + Cm(0.4), cw - Cm(0.7),
                         Cm(2.4))
            put(tb, [(t1, 15, True, col)], first=True, space_after=7,
                align=PP_ALIGN.CENTER)
            put(tb, [(t2, 12.5, False, GREY)], align=PP_ALIGN.CENTER)
        if j < 2:
            arrow(s, x + cw + Cm(0.06), y0 + Cm(5.6), gap - Cm(0.12),
                  Cm(0.55))


def p3(prs):
    s = page(prs, '研究設備 —— 階梯式分壓',
             '由高至低三層降壓，菌液維持微正壓', 3)
    # 圖高 = 28.07 × 0.457 ≈ 12.83，底邊落在 16.03，文字須排在其下
    pic(s, 'figE_pressure_cascade.png', Cm(4.2), Cm(3.3), Cm(25.5))
    caption(s, Cm(1.6), Cm(15.1), W - Cm(3.2), '1',
            '反應器的階梯式分壓架構。三個虛線區塊由左至右為反應物端、'
            '培養端、產物端；閥 V1~V4 為氣體閘門，PT 為壓力計。')
    tf = textbox(s, Cm(1.6), Cm(15.9), W - Cm(3.2), Cm(1.7))
    bullets(tf, ['氫氣與二氧化碳以 4:1 預混（CO_{2} + 4H_{2} → CH_{4} + 2H_{2}O 的'
                 '化學計量比）；循環泵將頭空氣體自槽底以氣泡送回'],
            fs=14, gap=6)
    put(tf, [('• ', 14), ('PT（壓力計）是本文唯一使用的通道', 14, True,
                          RED),
             ('；開啟閥門 V3 的控制器是封閉單元，其狀態不被記錄', 14)])


def p4(prs):
    s = page(prs, '實驗資料 —— 280 個補氣段的量化統計',
             '樣本很多、尺規很粗、訊號對雜訊夠大但對物理項很小', 4)
    tf = textbox(s, Cm(1.4), Cm(3.4), Cm(15.2), Cm(4.0))
    put(tf, [('四個可信通道', 16, True, BLUE)], first=True, space_after=9)
    put(tf, [('壓力 ×2、ORP、pH', 15)], space_after=9)
    put(tf, [('氣體分析儀的成分通道有 99.98% 是過期值，', 14, False, GREY),
             ('全篇不作為證據', 14, True, RED)], space_after=18)
    put(tf, [('本文只用頭空壓力一個通道', 17, True, RED)])
    table(s, Cm(17.4), Cm(3.2), Cm(15.0),
          [['項目', '值'],
           ['取樣', '每分鐘一筆'],
           ['量化階', '0.01 kg/cm^{2}'],
           ['補氣段數', '280 → 篩選後 239'],
           ['時長', '中位 10.3 hr ≈ 620 點'],
           ['振幅', '0.31 kg/cm^{2} = 31 個量化階'],
           ['殘差', '0.0065 kg/cm^{2} < 1 個量化階']],
          widths=[Cm(5.4), Cm(9.6)], fs=13)
    pic(s, 'figQ6_ladder.png', Cm(3.3), Cm(7.5), Cm(11.5))
    caption(s, Cm(1.4), Cm(14.1), Cm(15.2), '2',
            '一個補氣段的下降幅度、其中的生物份額，與單筆讀數的雜訊，'
            '都以感測器的刻度為單位。')
    note(s, '★ 待測的生物項約 15 個量化階，而每筆雜訊不到 1 階 —— '
            '難的不是雜訊，是它跟物理項長得太像。',
         color=INK)


def p5(prs):
    s = page(prs, '問題 —— 兩條途徑，一個通道',
             '封閉頭空的壓力下降同時來自生物消耗與物理溶解', 5)
    tf = textbox(s, Cm(1.4), Cm(3.3), Cm(15.4), Cm(7.0))
    bullets(tf, [[('• ', 17), ('生物', 17, True, RED),
                  ('：甲烷化每產生 1 莫耳氣體消耗 5 莫耳 → 壓力降', 17)],
                 [('• ', 17), ('物理', 17, True, BLUE),
                  ('：新注入的 CO_{2} 溶解 → 壓力也降', 17)]], gap=15)
    put(tf, [('領域慣常的解法是加第二個物理通道（例如量瓶重），'
              '但本設備不允許加裝，也不允許對生產中的槽體施加激發。',
              15, False, GREY)], space_after=18)
    put(tf, [('能不能只用一個量化壓力通道，把生物速率讀出來？', 18, True,
              RED)])
    pic(s, 'figD_device_pipeline.png', Cm(17.8), Cm(4.4), Cm(14.6))
    caption(s, Cm(17.8), Cm(11.7), Cm(14.6), '2',
            '一週的實際壓力紀錄。每一次「升到頂再一路下滑」就是一個補氣段。')
    note(s, '鋸齒即觸發迴路的特徵 —— 每一段下降側就是一次弛豫實驗，'
            '日常運轉每天自發產生約兩次，不影響生產。', color=INK)


def p5b(prs):
    """r_b 的化學意義。

    先前簡報只把 r_b 說成「壓力下降速率」，那是儀器的語言，不是化學的
    語言。聽眾會問：那到底代表多少甲烷？這頁把化學計量講清楚，並誠實
    標出「換算成 mol/hr 還缺什麼」。
    """
    s = page(prs, 'r_{b} 在化學上是什麼 —— 五個分子進去，一個出來',
             '4:1 預混就是照化學計量比配的；水是液態，不回到氣相')
    pic(s, 'figQ10_chemistry.png', Cm(4.9), Cm(3.1), Cm(24.0))
    caption(s, Cm(1.4), Cm(10.3), W - Cm(2.8), '3',
            '甲烷化的分子收支：反應物 5 個氣體分子，產物只有 1 個留在'
            '氣相，淨少 4 個。')
    chain = [('①', '我們量到的',
              'r_{b} = 0.0126 kg/cm^{2}/hr\n壓力每小時掉多少'),
             ('②', '換成分子數',
              '× 頭空體積 ÷ RT\n→ 淨氣體移除 mol/hr'),
             ('③', '換成甲烷',
              '÷ 4\n→ 甲烷生成 mol/hr')]
    bw, gap = Cm(9.4), Cm(1.2)
    for i, (no, t1, t2) in enumerate(chain):
        x = Cm(1.6) + i * (bw + gap)
        stepbox(s, x, Cm(11.4), bw, Cm(2.9), no, t1, t2,
                fill=(TROW2 if i == 1 else BOXBG))
        if i < 2:
            arrow(s, x + bw + Cm(0.12), Cm(12.6), gap - Cm(0.24))
    note(s, '⚠ 第 ② 步的頭空體積與操作溫度尚未確認，所以本文只報壓力'
            '單位的速率，不報 mol/hr —— 這兩個數字要向設備方問，不能自己'
            '假設。　★ 界線：r_{b} 是「淨氣體移除」中被歸給生物的那一份，'
            '不是直接量到的甲烷；氣體分析儀的甲烷通道 99.98% 是過期值，'
            '無法拿來核對。')


def p6(prs):
    s = page(prs, '困難 —— 兩項在數學上可以互換',
             '這不是實作缺陷，是指數擬合本身的性質', 6)
    tf = textbox(s, Cm(1.4), Cm(3.6), W - Cm(2.8), Cm(1.6))
    put(tf, [('P(t) = P_{eq} + A e^{−kt} − r_{b} t', 26, True)],
        first=True, align=PP_ALIGN.CENTER)
    tf2 = textbox(s, Cm(1.4), Cm(6.4), W - Cm(2.8), Cm(6.0))
    bullets(tf2, ['指數項 = 趨近平衡的物理過程；線性項 = 定速率的生物移除',
                  '當觀測窗內 kT 很小，e^{−kt} ≈ 1 − kt —— 兩項就可以互換'],
            fs=17, gap=15)
    put(tf2, [('• 實測後果：', 17),
              ('兩組 r_{b} 相差 2.5 倍的擬合，殘差平方和落在彼此的 1% 之內',
               17, True, RED)])
    note(s, '以 Gutenkunst 的語彙，模型沿著「以 A 與 k 交換 r_{b}」的方向是'
            '鬆散的（sloppy）；這個病態條件自 Lanczos 以來即被理解，'
            'Varah 已量化。', color=GREY)


def p6b(prs):
    """把「互換」畫出來——這是全篇最該用圖講的一件事。"""
    s = page(prs, '把「分不開」畫出來',
             '就像「10 元」可以是 7+3，也可以是 3+7 —— 只看總數，猜不出組成')
    pic(s, 'figQ1_why_hard.png', Cm(1.2), Cm(3.5), W - Cm(2.4))
    caption(s, Cm(1.2), Cm(13.05), W - Cm(2.4), '3',
            '左、中：同一段下降的兩種拆法，生物佔 39% 與佔 15%。'
            '右：兩者的總壓力，以及壓力計實際寫下的階梯數字。')
    tf = textbox(s, Cm(1.6), Cm(14.0), W - Cm(3.2), Cm(2.4))
    put(tf, [('• 左邊兩格是同一段下降的兩種拆法：', 15),
             ('生物佔 39%', 15, True, RED), ('，或只佔 ', 15),
             ('15%', 15, True, RED), ('　—— 差了 2.5 倍', 15)],
        first=True, space_after=8)
    put(tf, [('• 但把兩層加起來（右格），', 15),
             ('兩條總壓力曲線最大只差 0.0003，不到一個刻度的 3%', 15,
              True, RED)], space_after=8)
    put(tf, [('• 壓力計寫進檔案的階梯數字，兩種情況一字不差 —— '
              '這就是為什麼不能直接擬合了事', 15, False, GREY)])


def p6c(prs):
    """模型從哪來——論文只寫「Writing the descent as」，沒有交代由來。"""
    s = page(prs, '這條式子從哪裡來',
             '關鍵：菌吃的是「溶在液體裡」的氣體，不是頭空的氣體')

    # ── 上排：兩格模型 ──
    def cell(x, w, title, sub, fill, line):
        b = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, Cm(3.2),
                               w, Cm(2.7))
        b.fill.solid(); b.fill.fore_color.rgb = fill
        b.line.color.rgb = line; b.line.width = Pt(1.4)
        b.shadow.inherit = False
        tb = textbox(s, x + Cm(0.3), Cm(3.55), w - Cm(0.6), Cm(2.0))
        put(tb, [(title, 17, True, line)], first=True, space_after=6,
            align=PP_ALIGN.CENTER)
        put(tb, [(sub, 12.5, False, GREY)], align=PP_ALIGN.CENTER)

    cell(Cm(4.0), Cm(9.4), '頭空（氣體）', '壓力計量的是這一格', BOXBG,
         THEAD)
    arrow(s, Cm(13.6), Cm(4.2), Cm(2.4), Cm(0.7))
    tb = textbox(s, Cm(13.6), Cm(3.22), Cm(2.4), Cm(0.6))
    put(tb, [('溶解', 13, True, THEAD)], first=True,
        align=PP_ALIGN.CENTER)
    cell(Cm(16.2), Cm(9.4), '菌液（液體）', '菌在這裡吃溶解的氣體',
         TROW2, THEAD)
    arrow(s, Cm(25.8), Cm(4.2), Cm(2.4), Cm(0.7))
    tb = textbox(s, Cm(25.8), Cm(3.22), Cm(2.4), Cm(0.6))
    put(tb, [('甲烷化', 13, True, RED)], first=True,
        align=PP_ALIGN.CENTER)
    tb = textbox(s, Cm(28.6), Cm(4.15), Cm(4.4), Cm(0.9))
    put(tb, [('變成 CH_{4}', 14, True, RED)], first=True)

    tf = textbox(s, Cm(1.6), Cm(6.4), W - Cm(3.2), Cm(1.0))
    put(tf, [('所以頭空只有一個出口：氣體溶進液體。'
              '生物是「液體那一格」的出口，不是頭空的。', 15, True, INK)],
        first=True, align=PP_ALIGN.CENTER)

    # ── 下排：兩個階段 ──
    phases = [('補氣剛結束', '液體還不飽和，氣體大量往液體衝，'
               '壓力快速下降並逐漸趨緩', 'A e^{−kt}', '指數項＝物理'),
              ('液體飽和之後', '溶進去多少就被菌吃掉多少，'
               '頭空以固定速率持續流失', '− r_{b} t', '線性項＝生物')]
    for i2, (t1, t2, f, tag) in enumerate(phases):
        x = Cm(1.5) + i2 * Cm(16.0)
        b = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, Cm(7.8),
                               Cm(15.3), Cm(3.9))
        b.fill.solid(); b.fill.fore_color.rgb = BOXBG
        b.line.color.rgb = RED if i2 else THEAD
        b.line.width = Pt(1.2); b.shadow.inherit = False
        tb = textbox(s, x + Cm(0.4), Cm(8.1), Cm(14.5), Cm(3.3))
        put(tb, [('階段' + '一二'[i2] + '　' + t1, 15, True, INK)],
            first=True, space_after=5, align=PP_ALIGN.CENTER)
        put(tb, [(t2, 13, False, GREY)], space_after=7,
            align=PP_ALIGN.CENTER)
        put(tb, [(f, 20, True, RED if i2 else THEAD)], space_after=3,
            align=PP_ALIGN.CENTER)
        put(tb, [(tag, 12, False, GREY)], align=PP_ALIGN.CENTER)

    tf = textbox(s, Cm(1.6), Cm(12.2), W - Cm(3.2), Cm(1.6))
    put(tf, [('兩件事同時進行，疊加起來就是　', 15),
             ('P(t) = P_{eq} + A e^{−kt} − r_{b} t', 22, True, RED)],
        first=True, align=PP_ALIGN.CENTER)
    caption(s, Cm(1.6), Cm(13.9), W - Cm(3.2), '-',
            '兩格模型與兩個階段。頭空只透過「溶解」失去氣體，'
            '菌在液體那一格消耗；補氣初期液體不飽和造成指數項，'
            '飽和之後的定速消耗造成線性項，兩者疊加即為上式。')

    note(s, '★ 為什麼不用「生物直接從頭空扣掉」那個寫法：'
            '那樣解出來壓力會停在 P_{eq} − r_{b}/k 的平台上不再下降，'
            '而且 r_{b} 會被 P_{eq} 整個吸收、根本量不出來'
            '（那正是 8 月版卡住的地方）。'
            '實測的壓力是一路掉到下限才補氣，沒有停在平台上。')


def app0(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    rect(s, Cm(0.6), Cm(6.4), W - Cm(1.2), Cm(0.05), RULE)
    tf = textbox(s, Cm(2.0), Cm(7.4), W - Cm(4.0), Cm(4.5))
    put(tf, [('附　錄', 40, True, INK)], first=True, space_after=12,
        align=PP_ALIGN.CENTER)
    put(tf, [('洪政源　計畫簡報摘要', 22, False, INK)], space_after=10,
        align=PP_ALIGN.CENTER)
    put(tf, [('「以生物反應方式進行二氧化碳轉換成甲烷之'
              '微正壓循環控制系統開發」', 14, False, GREY)],
        align=PP_ALIGN.CENTER)
    rect(s, Cm(0.6), Cm(12.4), W - Cm(1.2), Cm(0.05), RULE)
    chrome(s, nextno())


def app1(prs):
    s = page(prs, '附錄一　系統架構與控制程序',
             '資料來源：洪政源計畫簡報')
    table(s, Cm(1.4), Cm(3.2), W - Cm(2.8),
          [['子系統', '壓力範圍', '內容'],
           ['反應物系統', '6 kg/cm^{2} 以下',
            '兩組 3L H_{2}/CO_{2} 鋼瓶 → 閥1、閥2 控比例 → 1L 混合槽約 4 kg/cm^{2}'],
           ['反應菌系統', '1.5 kg/cm^{2} 以下',
            '閥3 分壓到 5L 反應槽，壓差約 0.4 kg/cm^{2}，壓力回饋加限流閥'],
           ['生成物系統', '1 kg/cm^{2} 以下', '閥4 排氣到光學式氣體感測模組']],
          widths=[Cm(6.0), Cm(7.4), Cm(17.7)], fs=13)
    tf = textbox(s, Cm(1.6), Cm(8.4), W - Cm(3.2), Cm(6.0))
    bullets(tf, ['鋼瓶與混合槽耐壓 10 kg/cm^{2}；反應槽為透明壓克力，'
                 '耐氣體壓力 2 kg/cm^{2}、耐溫 40 度',
                 '循環氣體迴路：反應槽頂端抽氣、底部進氣，在液體中產生氣泡',
                 '循環以固定時間間隔運行（例如每小時 5 分鐘）；'
                 '作動時壓力下降，停止時壓力回升'], fs=15, gap=13)
    note(s, '★ 與本文的關係：本文完全不動這套硬體，只讀 PT 的壓力紀錄。'
            '「閥4 之後才有氣體感測器」也就是甲烷讀數多半過期的原因。',
         color=INK)


def app2(prs):
    s = page(prs, '附錄二　基礎實驗模型（7 組）',
             '固定初始壓力 1.5 kg/cm^{2}，觀察不同反應時間的甲烷濃度')
    table(s, Cm(2.4), Cm(3.2), Cm(29.0),
          [['實驗', '時間 (hrs)', '下降壓力速率\n@1.2 kg/cm^{2}',
            'CH_{4} (%)', 'CH_{4}%/hr'],
           ['1', '16（0.7 天）', '0.016', '0.6', '0.033'],
           ['2', '48（2 天）', '0.011', '5.5', '0.11'],
           ['3', '72（3 天）', '0.011', '9.8', '0.14'],
           ['4', '124（5.2 天）', '0.011', '24', '0.19'],
           ['5', '148（6.2 天）', '0.03', '72.5', '0.49'],
           ['6', '174（7.2 天）', '0.05', '75.3', '0.43'],
           ['7', '166（6.9 天）', '0.05', '72.4', '0.44']],
          widths=[Cm(3.0), Cm(7.0), Cm(8.0), Cm(5.5), Cm(5.5)], fs=13,
          hi_rows=(5, 6, 7), hi_col=2)
    note(s, '★ 前四組生物尚未穩定，壓力下降速率低、甲烷轉換不明顯；'
            '穩定後速率增快且穩定，約 7 天甲烷濃度可達 70%'
            '（實驗室級約 55–60%）。'
            '　⚠ 這欄是「總」下降速率（物理＋生物），與本文的 r_{b}'
            '（只有生物那一份）不是同一個量，不可直接並列比較。')


def app3(prs):
    s = page(prs, '附錄三　氣體循環提升轉換速率',
             '每小時循環 10 分鐘，頂端抽氣、底部進氣')
    table(s, Cm(3.4), Cm(3.2), Cm(27.0),
          [['實驗', '反應時間 (hrs)', '初始壓力', '累積總壓力', '初始 CH_{4}'],
           ['3', '20', '0.98', '0.91', '20%'],
           ['4', '49', '0.94', '3.53', '23%']],
          widths=[Cm(4.0), Cm(7.0), Cm(5.5), Cm(6.0), Cm(4.5)], fs=14)
    tf = textbox(s, Cm(1.6), Cm(6.6), W - Cm(3.2), Cm(7.0))
    bullets(tf, ['兩組實驗的總累積壓力差距約 3 倍多',
                 'CH_{4} 20%→60% 依模型約需 60 時，實驗3 只用 20 時 '
                 '→ 轉換速率提升約 3 倍',
                 'CH_{4} 20%→70% 依模型約需 70 時，實驗4 用 49 時 '
                 '→ 提升約 1.4 倍'], fs=16, gap=13)
    put(tf, [('• ORP 在新氣體輸入時急遽下降，之後週期性起伏回升；'
              'pH 也在新氣體進入時往酸變化，經菌種反應後往鹼變化。',
              15, False, GREY)])
    note(s, '★ 與本文的關係：這證實了「循環會改變質傳」，'
            '也就是本文把循環時間當成實驗條件（而非生物參數）的理由。',
         color=INK)


def p7(prs):
    """五步驟總覽——先給地圖，後面五頁逐步走。"""
    s = page(prs, '★ 結果是怎麼做出來的 —— 五個步驟',
             '每一步只做一件事，而且都可以用一句白話講完', 7)
    xs, y, bw, bh, gap = Cm(0.9), Cm(3.6), Cm(6.0), Cm(3.7), Cm(0.55)
    steps = [('①', '切', '把一週的壓力紀錄\n切成一段一段的下降'),
             ('②', '篩', '只留下「彎得夠明顯」\n的那些段'),
             ('③', '估', '每段算一個速率\n取中位數'),
             ('④', '校', '拿已知答案的假資料\n校正這把尺'),
             ('⑤', '驗', '換三個角度\n看結論會不會垮')]
    for i, (no, t, b) in enumerate(steps):
        x = xs + i * (bw + gap)
        stepbox(s, x, y, bw, bh, no, t, b,
                fill=(BOXBG if i < 3 else TROW2))
        if i < 4:
            arrow(s, x + bw + Cm(0.06), y + Cm(1.6), gap - Cm(0.12))
    tf = textbox(s, Cm(1.4), Cm(8.2), W - Cm(2.8), Cm(4.6))
    bullets(tf, [[('• 整條流程只用到「', 17),
                  ('把一條曲線配到資料上', 17, True, BLUE),
                  ('」這件事，沒有機器學習、沒有貝氏取樣。', 17)],
                 [('• 難的不是算，是', 17),
                  ('知道算出來的數字該不該信', 17, True, RED),
                  (' —— 所以步驟 ④ 和 ⑤ 佔掉大半篇幅。', 17)]], gap=14)
    note(s, '對照論文：步驟 ②③ 是 Algorithm 1（預篩與估計）、'
            '步驟 ④ 是 Algorithm 2（設計配對校準）、'
            '步驟 ⑤ 的第一項是 Algorithm 3（純物理參照）。', color=INK)


def p8(prs):
    s = page(prs, '步驟 ① 切 —— 把紀錄切成一段一段的下降',
             '設備每天自己做兩次實驗，我們只是把它們撿起來', 8)
    tf = textbox(s, Cm(1.4), Cm(3.3), Cm(15.6), Cm(8.0))
    bullets(tf, ['壓力升到上限就停止補氣，接著一路往下掉，掉到下限又補氣',
                 '每一段「往下掉」就是一次完整的弛豫過程 —— 這就是一次實驗',
                 '切法：偵測壓力自谷底明顯回升的時刻，前一點即為該段終點'],
            fs=16, gap=14)
    put(tf, [('• 條件一致的時期共切出 ', 16), ('280 段', 16, True, RED),
             ('。不同氣體比例、含無循環時段的批次事先排除，'
              '排除理由與結果無關。', 16)])
    pic(s, 'figD_device_pipeline.png', Cm(17.8), Cm(4.3), Cm(14.6))
    caption(s, Cm(17.8), Cm(11.6), Cm(14.6), '4',
            '切分結果：橘點為補氣頂點，綠點為該段終點（谷底）。')
    note(s, '⚠ 排除只依「檔名載明的實驗條件」，例如 1:1 氣體比、'
            '含無循環時段 —— 一律不得以「表現差」為由排除任何批次。')


def p9(prs):
    s = page(prs, '步驟 ② 篩 —— 一個「彎不彎」的數字',
             '先看形狀，再決定要不要擬合；不必先算就能判斷', 9)
    tf = textbox(s, Cm(1.4), Cm(3.4), W - Cm(2.8), Cm(1.4))
    put(tf, [('c ＝ 前半段掉了多少 ÷ 整段掉了多少', 24, True, BLUE)],
        first=True, align=PP_ALIGN.CENTER)
    table(s, Cm(3.4), Cm(5.4), Cm(27.0),
          [['軌跡形狀', 'c 值', '意義'],
           ['筆直下降', '恰好 0.5', '前後半段掉一樣多 → 兩項分不開'],
           ['明顯彎曲', '大於 0.5', '前半段掉得多 → 指數項現形，分得開'],
           ['低於門檻 0.45', '丟掉', '雜訊主導，勉強擬合會偏超過 25%']],
          widths=[Cm(7.0), Cm(5.4), Cm(14.6)], fs=14, hi_rows=(3,))
    sieve(s, Cm(6.4), Cm(9.6))
    note(s, '★ 門檻 0.45 是拿「已知答案的假資料」定出來的，不是在實測'
            '資料上挑的 —— 門檻若看著結果調，整個結論就白做了。', color=INK)


def p9b(prs):
    s = page(prs, '把「彎不彎」畫出來',
             '同樣從 1.17 掉到 0.93，形狀不同，能不能分開就完全不同')
    pic(s, 'figQ2_screen.png', Cm(3.9), Cm(3.2), Cm(26.0))
    caption(s, Cm(1.6), Cm(14.2), W - Cm(3.2), '5',
            '三條起點與終點完全相同、但形狀不同的下降軌跡，'
            '以及各自的曲率 c 與篩選判定。')
    note(s, '三條線的起點與終點完全一樣，差別只在「掉的過程」。'
            '筆直那條沒有任何形狀資訊可用，指數項與線性項互相頂替；'
            '彎的那條在前半段就把指數項暴露出來，兩項才分得開。',
         color=INK)


def p10(prs):
    s = page(prs, '步驟 ③ 估 —— 每段一個速率，取中位數',
             '為什麼用中位數而不是平均：少數幾段會給出離譜的值', 10)
    tf = textbox(s, Cm(1.4), Cm(3.4), Cm(14.4), Cm(9.0))
    bullets(tf, ['對每一段，把 P(t) = P_{eq} + A·e^{−kt} − r_{b}·t 這條曲線'
                 '配上去，讀出線性項 r_{b}',
                 '239 段就有 239 個值，排成一列取正中間那一個'],
            fs=15, gap=12)
    put(tf, [('• 中位數 ＝ ', 15), ('0.0128', 20, True, RED),
             (' kg/cm^{2}/hr（未修正）', 15)], space_after=14)
    put(tf, [('• 右圖就是為什麼不能用平均：', 15),
             ('平均被尾巴拖高 39%', 15, True, RED)], space_after=14)
    put(tf, [('• 為什麼不能就這樣拿去報？因為這把尺自己可能有偏差 —— '
              '下一步就是去量它偏多少。', 15, False, GREY)])
    pic(s, 'figQ4_percycle.png', Cm(16.3), Cm(3.4), Cm(16.3))
    caption(s, Cm(16.3), Cm(10.6), Cm(16.3), '5',
            '資料集 C 全部 280 段的逐段估計值分布，'
            '以及中位數與平均的位置。')
    note(s, '⚠ 逐段的值不可單獨使用：個別值散布極廣且與 k 耦合。'
            '本文任何內容都不足以支持把單一段讀成一次速率量測。')


def p11(prs):
    """全篇樞紐，用最白話的方式講校準。"""
    s = page(prs, '★ 步驟 ④ 校 —— 就是拿砝碼去校磅秤',
             '這一步是全篇的樞紐，道理其實非常單純', 11)
    tf = textbox(s, Cm(1.4), Cm(3.2), W - Cm(2.8), Cm(9.2))
    put(tf, [('問題：', 17, True, INK),
             ('我們有一把尺（整條分析流程），它量出 0.0128。'
              '但這把尺準不準？', 17)], first=True, space_after=15)
    put(tf, [('做法：拿一個「已經知道答案」的東西去量它。', 18, True,
              RED)], space_after=15)
    bullets(tf, ['用電腦造出一批假的壓力紀錄，這些紀錄的真實速率是我們'
                 '自己設定的、確定的',
                 '讓這批假紀錄走完全相同的流程 —— 同樣的切、同樣的篩、'
                 '同樣的估',
                 '如果流程把已知的 0.0100 量成了 0.0104，就知道這把尺'
                 '會多讀 4%，回推即可'],
            fs=16, first=False, gap=12)
    put(tf, [('• 校準曲線讀出的修正量：', 16), ('−3.7%', 21, True, RED)],
        space_after=8)
    put(tf, [('• 再與抽樣不確定度合成 → 定版 ', 16),
             ('0.0126 kg/cm^{2}/hr', 19, True, RED)])
    note(s, '這在統計上叫「間接推論」或「經驗校準」（Schuemie 等人）'
            '—— 不是本文發明的方法，但用在本領域是新的。', color=GREY)


def p11b(prs):
    s = page(prs, '把「校磅秤」畫出來',
             '橫軸是我們設定的已知答案，縱軸是流程量出來的值')
    pic(s, 'figQ3_calibration.png', Cm(9.6), Cm(3.1), Cm(14.6))
    caption(s, Cm(9.0), Cm(14.3), Cm(15.8), '6',
            '回收表現：橫軸為已知真值，縱軸為流程量出的值；'
            '紅星示範由實測讀數沿曲線回推。')
    tf = textbox(s, Cm(1.2), Cm(4.2), Cm(8.0), Cm(9.0))
    bullets(tf, ['灰色虛線是「量得完全準」的理想情況',
                 '藍線是流程實際的表現 —— 它偏在虛線上方，'
                 '表示這把尺會往多的方向讀',
                 '把實測讀數對到藍線上，橫著看回橫軸，'
                 '就得到修正後的答案'], fs=14, gap=12)
    put(tf, [('本示範的回收偏 ', 14), ('−5.3%', 16, True, RED),
             ('，與論文相容集合的 −4.1% ~ +5.8% 同一量級。', 14)])
    note(s, '⚠ 這張圖是現場跑的示範，用來說明校準這個動作；'
            '論文 §5 的定版修正量 −2.1% 跑在完整的配對條件上，'
            '兩者不是同一次計算。')


def p11c(prs):
    """校準的運算流程——把「怎麼算」一格一格攤開。"""
    s = page(prs, '步驟 ④ 的運算流程 —— 一格一格攤開',
             '對 239 段各跑一次，六個動作，沒有一個需要新的量測')
    boxes = [('①', '取一段真實紀錄', '從保留下來的 239 段裡拿一段'),
             ('②', '讀出它的條件', '鬆弛常數 k、振幅 A、平衡壓、時長、'
                                   '殘差大小與自相關'),
             ('③', '指定一個已知真值', '只有這一項是我們設定的'),
             ('④', '重新生成一段', '照 ② 的條件造軌跡，加 AR(1) 雜訊，'
                                   '量化到 0.01 階'),
             ('⑤', '走同一道流程', '同樣的曲率預篩、同樣的輪廓化擬合'),
             ('⑥', '比對兩個數字', '「量到的」對「已知的」差多少'
                                   '＝ 這把尺的偏差')]
    bw, bh, gap = Cm(10.2), Cm(3.5), Cm(0.65)
    for i, (no, t1, t2) in enumerate(boxes):
        r, c = divmod(i, 3)
        x = Cm(1.3) + c * (bw + gap)
        y = Cm(3.4) + r * (bh + Cm(1.15))
        b = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y, bw, bh)
        b.fill.solid(); b.fill.fore_color.rgb = BOXBG
        b.line.color.rgb = THEAD; b.line.width = Pt(1.0)
        b.shadow.inherit = False
        tb = textbox(s, x + Cm(0.35), y + Cm(0.42), bw - Cm(0.7),
                     bh - Cm(0.8))
        put(tb, [(no + '　' + t1, 15, True, INK)], first=True,
            space_after=7, align=PP_ALIGN.CENTER)
        put(tb, [(t2, 12, False, GREY)], align=PP_ALIGN.CENTER)
        if c < 2:
            arrow(s, x + bw + Cm(0.04), y + Cm(1.5), gap - Cm(0.08))
    # 第一列末 → 第二列首：畫一條折返提示
    tf = textbox(s, Cm(1.3), Cm(7.05), Cm(31.3), Cm(0.8))
    put(tf, [('↓　接下一列', 12, True, THEAD)], first=True,
        align=PP_ALIGN.CENTER)
    note(s, '★ 把 ①～⑥ 對 239 段各做一次，得到 239 個偏差；'
            '它們的中位就是修正量。整個過程沒有用到任何新的量測 —— '
            '所需的一切都在既有紀錄裡。', color=INK)


def p12(prs):
    s = page(prs, '步驟 ④ 的關鍵 —— 假資料必須長得跟真的一樣',
             '否則校出來的是別人的偏差，不是我們這把尺的偏差', 12)
    tf = textbox(s, Cm(1.4), Cm(3.3), Cm(15.4), Cm(9.0))
    put(tf, [('每一段假資料，都照抄它對應的那一段真資料：', 16, True,
              INK)], first=True, space_after=13)
    bullets(tf, ['一樣的長度、一樣的起伏高度、一樣的平衡點',
                 '一樣粗的 0.01 階梯',
                 '一樣的雜訊，而且雜訊會「記得上一分鐘」（不是白雜訊）'],
            fs=15, first=False, gap=10)
    put(tf, [('只有一件事被換掉：那段的真實生物速率。', 17, True, RED)],
        space_after=15)
    put(tf, [('這樣一來，尺的扭曲會同時出現在比較的兩邊，互相抵消。',
              16, False, GREY)])
    table(s, Cm(17.6), Cm(3.6), Cm(14.8),
          [['照抄的項目', '來源'],
           ['鬆弛常數 k、振幅 A', '該段自己的擬合值'],
           ['平衡壓 P_{eq}、時長', '該段自己的擬合值'],
           ['雜訊大小與自相關', '該段自己的殘差'],
           ['真實速率 r_{b}', '★ 只有這項由我們指定']],
          widths=[Cm(7.6), Cm(7.2)], fs=13, hi_rows=(4,))


def p12b(prs):
    """ρ 是什麼——不先講這個，下一頁的 0.814 沒有人聽得懂。"""
    s = page(prs, 'ρ 是什麼 —— 兩個算出來的數字會不會連動',
             '每個補氣段都會算出一對數字：鬆弛常數 k 與生物速率 r_{b}')
    pic(s, 'figQ12_rho.png', Cm(6.4), Cm(3.1), Cm(21.0))
    caption(s, Cm(1.4), Cm(11.2), W - Cm(2.8), '7',
            '同一條流程、同樣的配對條件，只換掉「真值是否隨 k 變」；'
            '深色線是每五分之一 k 的中位，趨勢看它就夠。')
    tf = textbox(s, Cm(1.6), Cm(12.4), W - Cm(3.2), Cm(2.4))
    put(tf, [('• ρ 就是這兩個數字的連動程度：', 16),
             ('一起大一起小就接近 1，各走各的就接近 0', 16, True, BLUE)],
        first=True, space_after=8)
    put(tf, [('• 為什麼要在意：如果估計器只是在「拿 k 換 r_{b}」，'
              '兩者也會連動 —— ', 16),
             ('所以光看連動，分不出是真的還是假影', 16, True, RED)])
    note(s, '⚠ 這兩格是示範用的小規模重跑（每格約 90 段），'
            '目的是讓「連動」看得見；ρ 的定版數字跑在完整的配對條件上，'
            '見下一頁。')


def p13(prs):
    s = page(prs, '★ 校準的第一個發現 —— 恆定真值被排除',
             '不假設速率怎麼變，改把「變多少」當成待反解的量', 13)
    pic(s, 'figB_matched_baseline.png', Cm(1.4), Cm(3.3), Cm(17.2))
    caption(s, Cm(1.4), Cm(10.6), Cm(17.2), '8',
            '(a) 橫軸是假設的變化強度 β，曲線是該假設下模擬出的 ρ，'
            '水平線是實測的 0.814，陰影是與實測相容的範圍。'
            '(b) 同一次校準讀出的兩種偏誤：估計器自身的扭曲（要修）'
            '與篩選的選擇效應（不修）。')
    table(s, Cm(19.4), Cm(3.3), Cm(13.1),
          [['假設的真值', '算出的相關 ρ'],
           ['完全不變（β=0）', '0.304 ± 0.056'],
           ['隨 k 微幅上升', '0.707'],
           ['隨 k 明顯上升', '0.747'],
           ['實際測到的', '0.814']],
          widths=[Cm(7.3), Cm(5.8)], fs=13, hi_rows=(1, 4))
    steps = [('①', '實測到 ρ = 0.814', '但這個數字不能照字面讀'),
             ('②', '反過來問', '什麼樣的真值，才會產生這個 ρ？'),
             ('③', '恆定真值只給 0.304', '差約 9 個標準差 → 排除')]
    for i, (no, t1, t2) in enumerate(steps):
        y = Cm(8.9) + i * Cm(2.0)
        b = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Cm(19.4), y,
                               Cm(13.1), Cm(1.75))
        b.fill.solid()
        b.fill.fore_color.rgb = TROW2 if i == 2 else BOXBG
        b.line.color.rgb = RED if i == 2 else THEAD
        b.line.width = Pt(1.0); b.shadow.inherit = False
        tb = textbox(s, Cm(19.75), y + Cm(0.22), Cm(12.4), Cm(1.4))
        put(tb, [(no + '　' + t1, 14, True, RED if i == 2 else INK)],
            first=True, space_after=3, align=PP_ALIGN.CENTER)
        put(tb, [(t2, 11.5, False, GREY)], align=PP_ALIGN.CENTER)
    note(s, '★ 9 個標準差的意思：如果真值真的不變，'
            '要靠運氣湊出 0.814 幾乎不可能發生。　'
            '★ 只讓速率有變異卻不跟 k 掛勾，相關反而掉到 0.143 → 也不是它。　'
            '★ 但這只排除了「不變」，沒有定出變化的確切形式 —— '
            '相容的強度是一整段 β ∈ [0.20, 0.80]，'
            '那正是最終區間裡「系統 ±5.1%」的來源。', color=INK)


def p14(prs):
    s = page(prs, '偏誤分解 —— 兩件事不可以混為一談', None, 14)
    table(s, Cm(1.4), Cm(3.2), W - Cm(2.8),
          [['', '大小', '性質', '處置'],
           ['篩選造成的選擇效應', '隨 β 升到 37%', '不是誤差，是定義',
            '不修'],
           ['估計器自身的扭曲', '−4.1% ~ +5.8%', '這才是量錯', '修']],
          widths=[Cm(10.2), Cm(8.0), Cm(8.5), Cm(4.4)], fs=15,
          hi_rows=(1, 2), hi_col=3)
    tf = textbox(s, Cm(1.4), Cm(7.4), W - Cm(2.8), Cm(4.8))
    put(tf, [('為什麼選擇效應不修：', 17, True, INK)], first=True,
        space_after=11)
    put(tf, [('篩選是以「彎得夠明顯」收段，它留下的那群段，'
              '真值本來就不等於全母體的真值。但我們報的是'
              '「在可辨識的段上」的速率，', 16),
             ('而篩選正是使它們可辨識的那件事。', 16, True, RED)])
    note(s, '這一點 8 月版沒有分開處理 —— 當時量測位置的統計量被離散平台'
            '鎖住，使分解的方向是反的。')


def p15(prs):
    s = page(prs, '★ 定版結果',
             '單一量化壓力通道，能把生物速率定到約 ±12%', 15)
    tf = textbox(s, Cm(1.4), Cm(3.3), W - Cm(2.8), Cm(2.0))
    put(tf, [('r_{b} ＝ 0.0126　[0.0112, 0.0142]　kg/cm^{2}/hr',
              32, True, RED)], first=True, align=PP_ALIGN.CENTER)
    tf1 = textbox(s, Cm(1.4), Cm(5.8), W - Cm(2.8), Cm(1.0))
    put(tf1, [('校準修正 −3.7%（只修估計器的扭曲），再與抽樣合成',
               14, False, GREY)], first=True, align=PP_ALIGN.CENTER)
    # 原本這裡還有一張誤差來源表，但它與圖的右半講同一件事——留圖去表。
    pic(s, 'figQ9_interval.png', Cm(5.9), Cm(6.9), Cm(22.0))
    caption(s, Cm(1.4), Cm(14.2), W - Cm(2.8), '8',
            '左：結果與 95% 區間，以及它離零有多遠。'
            '右：誤差的兩個來源，抽樣 ±5.5%、系統 ±5.1%，合成 ±11.9%。')
    note(s, '分開報的理由：延長量測只能壓縮前者。要收窄後者，'
            '需要知道速率隨 k 變化的確切形式，而那需要第二個化學通道。',
         color=GREY)


def p16(prs):
    s = page(prs, '步驟 ⑤ 驗一 —— 單指數的純物理做不出這個數字',
             '把生物項強制設為零，看流程還能不能生出 0.0128', 16)
    tf = textbox(s, Cm(1.4), Cm(3.3), Cm(16.4), Cm(4.4))
    put(tf, [('做法：同樣是造假資料，但這次真值設為 0', 17, True, BLUE)],
        first=True, space_after=11)
    bullets(tf, ['對每段先擬合一條「只有物理、沒有生物」的曲線',
                 '用它重新生成資料、加雜訊、量化到 0.01 階',
                 '再通過完全相同的篩選與估計器'],
            fs=15, first=False, gap=9)
    pic(s, 'figQ13_null.png', Cm(7.9), Cm(8.0), Cm(18.0))
    caption(s, Cm(1.6), Cm(14.5), W - Cm(3.2), '-',
            '左：真值設為零所生成的一段紀錄，也就是「完全沒有生物」'
            '該有的樣子。右：讓完全相同的流程去讀這種紀錄，'
            '算出的速率分布，以及實測中位數的位置。')
    table(s, Cm(18.6), Cm(3.3), Cm(13.8),
          [['', '算出的速率'],
           ['純物理（真值 = 0）', '+0.00008 ± 0.00010'],
           ['實測', '0.0128'],
           ['置換檢定', 'p = 0.024']],
          widths=[Cm(7.0), Cm(6.8)], fs=13, hi_rows=(3,))
    note(s, '⚠ 兩個界線：一、推論的方向 —— 它排除純物理的解釋，'
            '並未確立殘餘成分即為生物性。'
            '二、這裡的純物理是「單一時間常數」的；'
            '若溶解實際上有兩個時間常數，這個檢定沒有涵蓋 —— '
            '8 月版用雙指數虛無曾得到 p = 0.40，該情境尚未在本資料集上重測。')


def p17(prs):
    s = page(prs, '步驟 ⑤ 驗二 —— 切分位置沒有造出這個結果',
             '補氣段結束於補氣前最後一點，而該點正因壓力夠低才被選中', 17)
    tf = textbox(s, Cm(1.4), Cm(3.3), W - Cm(2.8), Cm(2.6))
    put(tf, [('疊加後看，末點平均比周圍低了整段振幅的 ', 16),
             ('6.8%', 16, True, RED),
             ('（其餘位置只差 0.6%）。斜率在端點最敏感 —— '
              '這是一條合理的高估途徑，必須查。', 16)], first=True)
    # 查核的運算流程，用四格說明「怎麼算」
    flow = [('①', '設定裁切量', 'N = 5, 10, 20, 30, 45, 60, 90 分鐘'),
            ('②', '砍掉每段末尾', '把最後 N 分鐘整段丟掉'),
            ('③', '重跑同一流程', '同樣的篩選與估計器，全部重算'),
            ('④', '看中位怎麼動', '若端點在作祟，中位會隨 N 單調移動')]
    bw, gap = Cm(7.55), Cm(0.6)
    for i, (no, t1, t2) in enumerate(flow):
        x = Cm(1.4) + i * (bw + gap)
        b = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, Cm(6.5),
                               bw, Cm(2.9))
        b.fill.solid(); b.fill.fore_color.rgb = BOXBG
        b.line.color.rgb = THEAD; b.line.width = Pt(1.0)
        b.shadow.inherit = False
        tb = textbox(s, x + Cm(0.3), Cm(6.9), bw - Cm(0.6), Cm(2.2))
        put(tb, [(no + '　' + t1, 14, True, INK)], first=True,
            space_after=6, align=PP_ALIGN.CENTER)
        put(tb, [(t2, 11.5, False, GREY)], align=PP_ALIGN.CENTER)
        if i < 3:
            arrow(s, x + bw + Cm(0.04), Cm(7.65), gap - Cm(0.08),
                  Cm(0.45))
    tf2 = textbox(s, Cm(1.4), Cm(10.2), W - Cm(2.8), Cm(4.6))
    put(tf2, [('結果：中位沒有單調移動', 17, True, BLUE)], first=True,
        space_after=12)
    bullets(tf2, [[('• 中位速率只在 ', 16),
                   ('0.0124 ~ 0.0133', 16, True, RED),
                   (' 之間來回（±5%），沒有隨 N 往同一個方向跑', 16)],
                  '沒有觸發選擇的配對模擬，漂移幅度也差不多',
                  '約 620 個取樣點裡的一個點，槓桿不足以扳動整條斜率'],
            first=False, gap=11)
    note(s, '→ 這個速率不是切分位置造成的假影', color=INK)


def p18a(prs):
    """ORP 是什麼、為什麼它能當獨立佐證、以及它不是什麼。

    先前只講「ORP 完全不進估計」，但沒講 ORP 到底量什麼，
    外行人聽不懂為什麼這算獨立證據。
    """
    s = page(prs, 'ORP 是什麼 —— 一支插在菌液裡的電極',
             '它和壓力量的是完全不同的東西，這正是它能當佐證的原因')
    facts = [('量什麼', '液體的還原力強弱', '單位毫伏特（mV）；'
              '菌越活躍，環境越還原'),
             ('在哪裡量', '菌液裡，不是氣相', '壓力量氣相 —— '
              '兩者是不同的物理通道'),
             ('有沒有進計算', '完全沒有', '整套估計只用壓力；'
              'ORP 是事後才拿來對答案的')]
    bw, gap = Cm(9.9), Cm(0.8)
    for i, (t1, t2, t3) in enumerate(facts):
        x = Cm(1.4) + i * (bw + gap)
        b = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, Cm(3.2),
                               bw, Cm(3.3))
        b.fill.solid(); b.fill.fore_color.rgb = BOXBG
        b.line.color.rgb = THEAD; b.line.width = Pt(1.0)
        b.shadow.inherit = False
        tb = textbox(s, x + Cm(0.35), Cm(3.55), bw - Cm(0.7), Cm(2.7))
        put(tb, [(t1, 13, False, GREY)], first=True, space_after=5,
            align=PP_ALIGN.CENTER)
        put(tb, [(t2, 17, True, BLUE)], space_after=7,
            align=PP_ALIGN.CENTER)
        put(tb, [(t3, 11.5, False, GREY)], align=PP_ALIGN.CENTER)
    pic(s, 'figQ11_orp_groups.png', Cm(7.2), Cm(6.8), Cm(19.5))
    caption(s, Cm(1.4), Cm(14.6), W - Cm(2.8), '12',
            '資料集 C 的 280 段依各自的氧化還原變化量排序，'
            '以三分位切成三等分；紅線為切點 −88 與 −27 mV。'
            '切點事先由三分位決定，不是看結果挑的。')
    note(s, '⚠ 兩個必須先說清楚的地方：'
            '一、記錄器只存絕對值，真實的 ORP 是負的，'
            '加回負號後約 −357 mV（相對標準氫電極），與文獻相符。'
            '二、ORP 不是氫氣計 —— 它同時受 pH 與溶解 CO_{2} 影響，'
            '所以只能當「活躍度」的順序指標，不能換算成速率。')


def p18(prs):
    s = page(prs, '★ 步驟 ⑤ 驗三 —— ORP 給出同樣的排序',
             'ORP 完全不進估計，而且它不是速率 —— '
             '正因為不在模型裡，才能拿來檢查', 18)
    table(s, Cm(1.4), Cm(3.4), Cm(15.2),
          [['依 ORP 分成三組', '該組的聚合速率'],
           ['還原力最弱（−126 mV）', '0.0099'],
           ['中間（−57 mV）', '0.0134'],
           ['還原力最強（+2 mV）', '0.0152']],
          widths=[Cm(8.4), Cm(6.8)], fs=15, hi_rows=(3,))
    pic(s, 'figQ7_orp.png', Cm(3.5), Cm(7.6), Cm(11.0))
    caption(s, Cm(1.4), Cm(14.1), Cm(15.2), '11',
            '三組各自聚合出的生物速率，由還原力最弱到最強。'
            '跨度 54%，拔靴區間 [0.0004, 0.0137] 不含零。')
    tf = textbox(s, Cm(17.6), Cm(3.8), Cm(14.9), Cm(7.5))
    put(tf, [('跨度 ', 17), ('54%', 21, True, RED),
             ('，拔靴區間 [0.0004, 0.0137] ', 17),
             ('不含零', 17, True, RED)], first=True, space_after=15)
    put(tf, [('一個在不同物理通道（液相，不是氣相）量到的東西，'
              '把壓力軌跡給出的速率排出了同樣的順序 —— '
              '這是單靠壓力給不出來的。', 16)])
    note(s, '必須同時講的界線：排序是聚合的、不是逐段；ORP 同時受 pH 與'
            '溶解 CO_{2} 影響，不是氫氣計；沒有成分錨點就無法換算成速率。')


def p19(prs):
    s = page(prs, '模擬器像不像真的？用分類器去分辨',
             '配對基準若建立在不像真的模擬器上，整套校準就沒有意義', 19)
    table(s, Cm(1.4), Cm(3.4), Cm(15.2),
          [['雜訊模型', '被分類器認出的程度 AUC'],
           ['白高斯（最天真）', '0.968'],
           ['AR(1)（會記得上一分鐘）', '0.832'],
           ['AR(1) 再放大 1.3 倍（定版）', '0.695']],
          widths=[Cm(9.4), Cm(5.8)], fs=13, hi_rows=(3,))
    pic(s, 'figQ8_auc.png', Cm(1.8), Cm(7.8), Cm(14.4))
    caption(s, Cm(1.4), Cm(13.6), Cm(15.2), '12',
            '三種雜訊模型在同一把量尺上的位置；越靠左表示模擬越像真的。')
    tf = textbox(s, Cm(17.6), Cm(3.8), Cm(14.9), Cm(7.5))
    bullets(tf, ['AUC = 0.5 表示完全分不出真假，愈接近 1 表示愈容易被看穿',
                 '實測殘差的自相關中位 0.266 —— 本來就不是白雜訊',
                 '校準後十項邊際特徵全部吻合到 0.29 個標準差之內'],
            fs=15, gap=13)
    note(s, '⚠ 不宣稱模擬器已經充分：殘餘 AUC 0.695 表示仍然分得出來，'
            '不吻合處位於我們尚未辨識出的聯合結構。')


def p20(prs):
    s = page(prs, '三項限制', None, 20)
    pic(s, 'figQ5_budget.png', Cm(20.6), Cm(3.6), Cm(12.4))
    caption(s, Cm(20.0), Cm(11.4), Cm(13.6), '9',
            '三種部署組態的安裝體積與監控電腦的可用預算。')
    tf = textbox(s, Cm(1.4), Cm(3.4), Cm(18.4), Cm(12.5))
    for tag, body in [
        ('① 逐段的值不可用',
         '聚合中位數可以回復，但個別值散布極廣且與 k 耦合。本文任何內容'
         '都不足以支持把單一段讀成一次速率量測。ORP 檢查同樣是聚合層次。'),
        ('② 模擬器仍然分得出來（AUC 0.695）',
         '配對基準因此只是近似。我們不在這個模擬器上做模擬式推論 —— '
         '由設定錯誤的模擬器學到的後驗會是又窄又錯，而不只是不確定。'),
        ('③ 部署預算只有 60 MB',
         '瓶頸是函式庫體積而不是演算法成本：NumPy 單獨 27 MB，完整科學'
         '堆疊 129 MB。整條流程僅以 NumPy 撰寫。這也是未採用學習式模型的'
         '原因 —— 困難在可辨識性，不在函數逼近。')]:
        put(tf, [(tag, 18, True, BLUE)], space_after=8)
        put(tf, [(body, 15)], space_after=22)


def p21(prs):
    s = page(prs, '與 8 月版的數字對照', None, 21)
    table(s, Cm(1.4), Cm(3.2), W - Cm(2.8),
          [['', '8 月版', '本版'],
           ['補氣段數', '26（三批次）', '280 → 篩選後 239'],
           ['估計量', '單步聯合擬合', '曲率預篩＋輪廓化最小平方'],
           ['速率', '0.01104', '0.0126'],
           ['不確定度', 'CV 11.6%', '±11.9%（抽樣 5.5＋系統 5.1）'],
           ['對虛無', 'p = 0.40（失敗）', 'p = 0.024'],
           ['主結論', 'r_{b} 未被辨識', '恆定真值被排除（9σ），速率可回復']],
          widths=[Cm(5.2), Cm(11.4), Cm(14.5)], fs=13, hi_rows=(6,),
          hi_col=2)
    note(s, '為什麼翻轉：8 月版的虛無與估計量共用同一個單指數模型，'
            '虛無偵測不到自己的設定誤差。本版改用逐段擬合的純物理參照，'
            '並另外掃描速率隨 k 的變化強度。')


def p22(prs):
    s = page(prs, '仍待確認', None, 22)
    table(s, Cm(1.4), Cm(3.3), W - Cm(2.8),
          [['#', '事項', '對象'],
           ['1', '四位作者 ORCID', '全體'],
           ['2', '金屬中心正式英文地址、郵遞區號、聯絡信箱', '洪博'],
           ['3', '經費來源與計畫編號（Acknowledgements 現為空）', '洪博'],
           ['4', '利益揭露措辭（專利 TW I923176 屬金屬中心）', '洪博'],
           ['5', 'Springer 版權讓與書親筆簽名（不接受電子簽章）', '全體'],
           ['6', '閘閥型式確認 —— 圖上標 Gate valve 係依口述', '洪博'],
           ['7', '16 筆文獻的引用貼切性抽查', '陳老師'],
           ['8', '頭空體積與操作溫度（把 r_{b} 換算成 mol/hr 用）', '洪博']],
          widths=[Cm(1.8), Cm(22.3), Cm(7.0)], fs=13)


def p23(prs):
    s = page(prs, '關鍵實驗請求', '沿用 8 月版，四項仍然成立', 23)
    table(s, Cm(1.4), Cm(3.3), W - Cm(2.8),
          [['#', '實驗', '為什麼要做', '優先'],
           ['1', '純 CO_{2} 對照',
            '移除電子供體後速率應為 0，是校準協定最強的驗證', '最高'],
           ['2', '補 2~3 min 批次',
            'kLa 在 1→5 min 大幅增加、5→10 min 已飽和，槓桿在 2~3 min',
            '高'],
           ['3', '換液對照',
            '全程未換液，循環時間／菌齡／CO_{2} 飽和完全共線', '高'],
           ['4', '觸發改固定時間間隔', '消除內生觸發的混淆，硬體零成本',
            '中']],
          widths=[Cm(1.8), Cm(7.6), Cm(17.7), Cm(4.0)], fs=13,
          hi_rows=(1,), hi_col=3)


def p24(prs):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    rect(s, Cm(0.6), Cm(3.8), W - Cm(1.2), Cm(0.05), RULE)
    tf = textbox(s, Cm(2.0), Cm(6.4), W - Cm(4.0), Cm(6.0))
    put(tf, [('謝謝聆聽！', 44, True, INK)], first=True, space_after=12,
        align=PP_ALIGN.CENTER)
    put(tf, [('煩請指正與評價！', 40, True, INK)], space_after=18,
        align=PP_ALIGN.CENTER)
    put(tf, [('Thank you for your time and attention.', 22, False, BLUE)],
        align=PP_ALIGN.CENTER)
    rect(s, Cm(0.6), Cm(14.4), W - Cm(1.2), Cm(0.05), RULE)
    chrome(s, nextno())


def main():
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H
    cover(prs)
    for fn in (p1b, p2, p_map, p3, p3b, p3c, p4, p5, p5b, p6, p6b, p6c, p7, p8, p9, p9b, p10, p11,
               p11b, p11c, p12, p12b, p13, p14, p15, p16, p17, p18a, p18, p19, p20,
               p21,
               p22, p23, p24, app0, app1, app2, app3):
        fn(prs)
    prs.save(OUT)
    print('OK', OUT, '共', len(prs.slides._sldIdLst), '頁')


if __name__ == '__main__':
    main()
