# -*- coding: utf-8 -*-
"""2026-09-21 分析報告的簡報版（19 頁）。

★ 2026-10-02 架構重寫：原先把溶解與生物當成兩條並聯途徑，
  並據此主張「壓降主因不是溶解」。實際上兩者是**串聯**：
  溶解是通道、生物是匯。封面與前三頁已重寫，
  「佐證一：碳源切斷」與「佐證二：曲線是直線」兩頁已刪除
  （它們的觀察已由新的第二節解釋）。

版式函式取自 build_deck.py，與 8 月版模板一致。內容來源為
docs/reports/分析報告_2026-09-21_氫氣流失與壓降歸因.md，此檔只負責挑重點與排版。

  python docs/build/build_deck_0921.py

⚠ 圖檔在 docs/analysis_charts_3batch/，不是 build_deck 預設的 paper_figures/，
  故本檔自備 pic2()。圖一律先量原始長寬比再決定要以寬度還是高度貼齊，
  否則寬高比不同的圖會超出版面。
"""
import os
import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pptx import Presentation
from pptx.enum.text import PP_ALIGN
from pptx.util import Cm, Pt

from build_deck import (BLUE, GREY, H, INK, RED, W, bullets, caption, note,
                        page, put, table, textbox)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIGDIR = os.path.join(REPO, 'docs', 'analysis_charts_3batch')
OUT = os.path.join(REPO, 'docs', 'decks', '簡報_2026-09-21_氫氣流失與壓降歸因.pptx')

TOP = Cm(3.0)
BOT = Cm(18.0)          # 底部色帶之上


def pic2(slide, name, x=None, y=None, w=None, h=None):
    """貼圖。只給 w 或 h 其一，另一邊依原圖比例算，避免變形或超版。"""
    from PIL import Image
    p = os.path.join(FIGDIR, name)
    if not os.path.isfile(p):
        raise SystemExit('找不到圖檔：%s' % p)
    iw, ih = Image.open(p).size
    ar = ih / iw
    if w is not None:
        h = Cm(w.cm * ar)
    elif h is not None:
        w = Cm(h.cm / ar)
    if x is None:
        x = Cm((W.cm - w.cm) / 2)
    if y is None:
        y = Cm(TOP.cm + (BOT.cm - TOP.cm - h.cm) / 2)
    slide.shapes.add_picture(p, x, y, width=w, height=h)
    return y.cm + h.cm          # 圖的底緣（cm）；圖說與內文接在這之後


def body(slide, x=Cm(1.6), y=None, w=None, h=Cm(13.5)):
    return textbox(slide, x, y or Cm(3.5), w or (W - Cm(3.2)), h)


def build():
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H

    # ── 1 封面 ──────────────────────────────────────────────
    s = page(prs, '壓降歸因與氫氣收支',
             '微正壓循環生物甲烷化反應器｜2026-09-21（10-02 架構修正）｜李承育')
    tf = body(s, y=Cm(5.0), h=Cm(9.0))
    put(tf, [('兩個要分開的問題：', 22, True, INK)], first=True, space_after=12)
    put(tf, [('① 壓力為什麼會掉　', 20, True, BLUE),
             ('氣泵把氣體打進水裡（裝置本來就是這樣設計），再被菌吃掉。',
              18, False, INK)], space_after=8)
    put(tf, [('　 由甲烷換算，生物解釋 ', 17, False, GREY),
             ('39%', 19, True, INK),
             (' 的壓降；', 17, False, GREY),
             ('殘餘 61% 尚待解釋', 19, True, RED),
             ('。', 17, False, GREY)], space_after=16)
    put(tf, [('② 剩下的氣體比例不對　', 20, True, BLUE),
             ('二氧化碳對氫氣比補進去的比例高 1.33 – 2.79 倍。', 18, False, INK)],
        space_after=8)
    put(tf, [('　 溶進水裡解釋不了這件事：二氧化碳溶掉會讓比值變小，'
              '但實測是變大。這是另一個待解的問題。', 17, False, GREY)], space_after=16)
    put(tf, [('⚠ 本版修正了先前的模型錯誤：', 18, True, RED)], space_after=6)
    put(tf, [('原先把「溶進水裡」與「被菌吃掉」當成兩條各走各的路，'
              '並據此說「壓降主因不是溶解」。實際上是一個接著一個：'
              '氣體先溶進水裡，再被菌吃掉。那個說法已撤回。',
              16, False, INK)])
    note(s, '前提：進料確認為 CO₂:H₂ = 1:4。'
            '氣體讀數僅排氣當下 1~2 分鐘可信，全資料庫 35 筆。')

    # ── 2 壓力為什麼會掉：串聯模型 ──────────────────────────
    s = page(prs, '一、壓力為什麼會掉', '氣泵把氣體打進水裡，再被菌吃掉')
    yb = pic2(s, 'deck15_series.png', w=Cm(24.0), y=Cm(3.2))
    tf = body(s, y=Cm(yb + 0.3), h=Cm(17.8 - yb - 0.3))
    put(tf, [('⚠ 先前把這兩件事當成各走各的，並據此說'
              '「壓降主因不是溶解」。', 16, False, INK),
             ('該主張已撤回。', 18, True, RED)],
        first=True, align=PP_ALIGN.CENTER)

    # ── 3 這個模型解釋了什麼 ────────────────────────────────
    s = page(prs, '二、這樣看一次解釋了三件事', '這三件先前都當成各自獨立的謎')
    table(s, Cm(1.6), Cm(4.0), W - Cm(3.2), [
        ['先前的觀察', '先前的解讀', '正確的解釋'],
        ['91% 的壓降曲線接近直線',
         '⚠ 曾解讀為「不是溶解」', '水裡的碳一直被菌吃掉、吸不飽，所以溶解是固定速度——那本來就是直線'],
        ['菌吃多快與平衡壓力分不開',
         '⚠ 曾視為巧合', '本來就是直線，卻拿彎曲的公式去套，當然套不出來'],
        ['切斷碳源後壓降速率不變',
         '⚠ 曾解讀為「氫氣流失」', '水裡存的碳還夠用幾十天，所以碳源根本沒斷'],
    ], widths=[Cm(9.0), Cm(9.0), Cm(12.7)], fs=14, hi_rows=())
    tf = body(s, y=Cm(11.6), h=Cm(5.5))
    put(tf, [('三項先前各自成謎的觀察，在正確的模型下都是',
              18, False, INK),
             ('必然的結果', 20, True, RED),
             ('。', 18, False, INK)], first=True, align=PP_ALIGN.CENTER)
    put(tf, [('⟹ 真正待解的是兩件：菌吃掉的量解釋不了的那 61% 壓降，'
              '以及剩下的氣體比例為何不對。', 17, False, GREY)],
        align=PP_ALIGN.CENTER)

    # ── 4 資料可信度 ────────────────────────────────────────
    s = page(prs, '三、先確認：氣體讀數什麼時候可信',
             '補進去的是二氧化碳與氫氣、不含甲烷，槽內真實氣體必定被稀釋')
    yb = pic2(s, 'deck1_sensor.png', w=Cm(25.0), y=Cm(3.4))
    tf = body(s, y=Cm(yb + 0.25), h=Cm(17.9 - yb))
    put(tf, [('實測斜率 ', 17, False, INK), ('+0.008 ± 0.225', 19, True, RED),
             ('，距「真的量到槽內氣體」應有的 −1 差了 4.5 個標準差。'
              '分析儀只有在排氣當下的一至二分鐘可信——全資料庫僅 35 筆，'
              '後續所有氣體計算只用這 35 筆。', 17, False, INK)],
        first=True, align=PP_ALIGN.CENTER)

    # ── 6 核心結果 ──────────────────────────────────────────
    s = page(prs, '四、剩下的氣體比例與補進去的不同',
             '紅色虛線 = 只有產甲烷反應時應有的位置')
    yb = pic2(s, 'deck2_hydrogen.png', w=Cm(25.0), y=Cm(3.3))
    tf = body(s, y=Cm(yb + 0.25), h=Cm(17.9 - yb))
    put(tf, [('34/35 次高於進料比　｜　中位 2.79 倍　｜　p < 0.0001'
              '（甲烷當零的最壞情況仍 1.33 倍）', 17, True, RED)],
        first=True, align=PP_ALIGN.CENTER)
    put(tf, [('⚠ 這整頁的前提是「補進去的真的是 1:4」。'
              '10-02 查出只要補氣少 3.6% 的氫氣就能造出全部超量，見第 17 頁。',
              15, False, GREY)], align=PP_ALIGN.CENTER)

    # ── 7 穩健性 ────────────────────────────────────────────
    s = page(prs, '五、這不是量測誤差造成的', '以 2026-07-30 那次排氣為例')
    tf = body(s, y=Cm(4.0), h=Cm(11.0))
    put(tf, [('量測到：二氧化碳 21.3%、甲烷 34.79%', 20, True, INK)],
        first=True, space_after=14)
    bullets(tf, [
        [('若殘餘氣體真的維持 1:4，扣除甲烷與水蒸氣後，'
          '二氧化碳應該只有 ', 18, False, INK), ('12.6%', 20, True, BLUE)],
        [('即使把甲烷讀數', 18, False, INK), ('全部當成零', 20, True, RED),
         ('（最極端的假設），氫氣上限也只有 78.7%，比值仍為 0.27', 18, False, INK)],
    ], fs=18, first=False, gap=14)
    put(tf, [('', 10, False, INK)], space_after=10)
    put(tf, [('也就是說——二氧化碳的實測值本身，就高到與 1:4 不相容。',
              22, True, RED)], space_after=16)
    put(tf, [('量級換算（保守估計）：要讓比值漂移到實測中位數，'
              '需要額外移除約 2.57 莫耳氫氣，相當於進料氫氣的 64%。',
              16, False, GREY)])
    note(s, '此換算為單次通過的保守估計，實際為連續補氣，數值僅示意量級。')

    # ── 11 ORP ──────────────────────────────────────────────
    s = page(prs, '六、ORP（水的氧化還原狀態）該怎麼讀',
             '數值本身正常，但循環裡的起伏不是菌造成的')
    yb = pic2(s, 'deck5_orp.png', w=Cm(18.0), y=Cm(3.2))
    tf = body(s, y=Cm(yb + 0.3), h=Cm(15.2 - yb))     # 收在 note（15.45）之上
    put(tf, [('數值本身：', 17, True, INK),
             ('−357 mV，落在文獻最適範圍 −335.6 ± 29.0 mV ', 16, False, INK),
             ('之內', 17, True, BLUE)], first=True, space_after=5)
    put(tf, [('循環裡的起伏：', 17, True, INK),
             ('一補氣就跳 +37 mV，氣泵一開每分鐘再走 +3.5 ~ +10.8 mV'
              '——都是操作造成的。', 16, False, INK)],
        space_after=5)
    put(tf, [('連碳源已用完、菌不可能在產甲烷的時段，ORP 照樣在動。',
              16, True, RED)])
    note(s, '文獻把 ORP 當成「菌有多活躍」的指標，但那些系統沒有從外面加氫氣；'
            '本反應器的氫氣是打進去的，會直接把數值壓住，那套讀法不能照搬。')

    # ── 11b 先解釋 PINN 是什麼 ──────────────────────────────
    s = page(prs, '七、先說明什麼是 PINN',
             '後面兩頁會用到，這裡先把它講清楚')
    yb = pic2(s, 'deck11_pinn_what.png', w=Cm(25.0), y=Cm(3.2))
    tf = body(s, y=Cm(yb + 0.35), h=Cm(17.8 - yb - 0.35))
    put(tf, [('一句話：', 18, True, INK),
             ('用神經網路取代「固定公式」，但要求它同時滿足物理定律。',
              18, False, INK)], first=True, align=PP_ALIGN.CENTER)
    put(tf, [('這樣生物速率就不必被假設成固定值——它本來就會隨氫氣耗盡而改變。',
              16, False, GREY)], align=PP_ALIGN.CENTER)

    # ── 12 試過但不成立的方法 ───────────────────────────────
    s = page(prs, '八、試過但不成立的兩個方法', '誠實記錄，避免後續重複投入')
    tf = body(s, y=Cm(3.2), h=Cm(5.8))
    put(tf, [('① 以「曲率」分離生物與物理', 20, True, INK)], first=True, space_after=8)
    put(tf, [('前提是生物速率為定值，但它會隨氫氣耗盡而變動。'
              '以已知答案驗證：真實物理份額 0% 時，該方法報出 ', 17, False, INK),
             ('101%', 19, True, RED), ('。', 17, False, INK)], space_after=12)
    put(tf, [('② 以物理資訊神經網路（PINN）反推生物速率', 20, True, INK)],
        space_after=8)
    put(tf, [('方向正確，但方程式本身存在一個恰好抵銷的自由度（見次頁）。',
              17, False, INK)])
    pic2(s, 'deck6_pinn.png', w=Cm(16.5), y=Cm(9.2))

    # ── 12b PINN 為什麼撈不回來：兩個未知數互換 ─────────────
    # ⚠ deck7/deck8 長寬比 0.502，w=25cm 的高度就有 12.6cm；
    #   這兩頁圖上下都要擺字，故寬度壓到 22cm 並且不使用 note()。
    s = page(prs, '九、PINN 為什麼撈不回來',
             '不是網路不夠大，是壓力這一個通道裡沒有這個資訊')
    tf = body(s, y=Cm(3.1), h=Cm(3.2))
    put(tf, [('氣體變少只有兩個原因：溶進水裡（物理）、被菌吃掉（生物）。'
              '壓力計只看得到兩者的', 17, False, INK),
             ('總和', 19, True, RED),
             ('。把生物項算多一點、同時把「平衡壓力」調高一點，'
              '兩者剛好互相抵銷——壓力曲線一模一樣。', 17, False, INK)],
        first=True)
    pic2(s, 'deck8_pinn_corr.png', w=Cm(22.0), y=Cm(6.5))

    # ── 12c 同一條壓降，兩種歸因 ────────────────────────────
    s = page(prs, '十、同一條壓降，兩種完全不同的說法',
             '兩者的擬合誤差幾乎相同，資料無從選擇')
    yb = pic2(s, 'deck7_pinn_features.png', w=Cm(23.0), y=Cm(3.2))
    tf = body(s, y=Cm(yb + 0.4), h=Cm(17.8 - yb - 0.4))
    put(tf, [('但要講清楚：分不開的是生物速率的', 17, False, INK),
             ('平均值', 19, True, RED),
             ('。它的', 17, False, INK),
             ('時間變化', 19, True, BLUE),
             ('其實還留在資料裡（訊噪比 6.0），'
              '只是被「速率不可為負」這個設定連帶壓死了——'
              '把平均值另外定住，變化的形狀就回來了（相關 0.97）。',
              17, False, INK)], first=True)

    # ── 13 限制 ─────────────────────────────────────────────
    # ── 12d 碳酸鹽脫氣：另一個不需要洩漏的解釋 ───────────────
    s = page(prs, '十一、比例不對的解釋之一：水裡的碳冒回來',
             '2026-09-23 補充——這個解釋不需要任何洩漏')
    # ⚠ 本頁不用 note()：note 固定佔 15.45~17.85cm，會與圖重疊。
    #   圖寬壓到 23cm（高 11.8）使底緣 15.1，內文接在其下。
    yb = pic2(s, 'deck9_carbonate.png', w=Cm(23.0), y=Cm(3.3))
    tf = body(s, y=Cm(yb + 0.35), h=Cm(17.8 - yb - 0.35))
    put(tf, [('量級檢查：只需 ', 17, False, INK),
             ('2.6%', 20, True, RED),
             (' 的「水裡溶著的碳」在排氣瞬間冒出來，就足以解釋全部的偏離。',
              17, False, INK)], first=True, align=PP_ALIGN.CENTER)
    put(tf, [('方向性檢驗（壓降越大應脫越多）實測 ρ=+0.21，方向符合，'
              '但 35 筆資料最少要 0.46 才看得出來，樣本不足以分辨；'
              '排氣後立刻補氣會降 pH，故 pH 檢驗遭混淆、不可單獨解讀。',
              14, False, GREY)], align=PP_ALIGN.CENTER)

    # ── 12e 關聯集合 ────────────────────────────────────────
    s = page(prs, '十二、ORP 與酸鹼值到底有沒有關係',
             '現場觀察到兩者有關聯——資料顯示有，但不是想像的那種')
    yb = pic2(s, 'deck10_coupling.png', w=Cm(24.0), y=Cm(3.3))
    tf = body(s, y=Cm(yb + 0.3), h=Cm(17.8 - yb - 0.3))
    put(tf, [('關聯確實存在，但是「ORP 的高低」對「pH 的變化」；'
              'ORP 與 pH 的', 17, False, INK),
             ('變化量之間幾乎無關', 19, True, RED),
             ('（+0.02）。扣掉時間漂移後這些關聯幾乎不變，故不是時間造成的。',
              17, False, INK)], first=True)

    # ── 12f 排氣本身就會選擇性移除 H2 ───────────────────────
    s = page(prs, '十三、比例不對的解釋之二：排氣挑掉氫氣',
             '2026-09-27 補充——這也不需要洩漏')
    yb = pic2(s, 'deck13_ventloss.png', w=Cm(25.0), y=Cm(3.2))
    tf = body(s, y=Cm(yb + 0.3), h=Cm(17.8 - yb - 0.3))
    put(tf, [('先前只數到 ', 17, False, INK),
             ('35 次', 19, True, INK),
             ('排氣（限有氣體讀數的），改以壓力驟降去找，實際有 ', 17, False, INK),
             ('108 次', 19, True, RED),
             ('。', 17, False, INK)], first=True, align=PP_ALIGN.CENTER)

    # ── 12g 洪博要的 CO2 消耗量 ─────────────────────────────
    s = page(prs, '十四、二氧化碳的消耗量',
             '洪博要求的數字——不需要氫氣感測器就能給')
    yb = pic2(s, 'deck12_co2.png', w=Cm(25.0), y=Cm(3.2))
    tf = body(s, y=Cm(yb + 0.3), h=Cm(17.8 - yb - 0.3))
    put(tf, [('以總容積 1.8 L、水佔一半估算：長期 ', 17, False, INK),
             ('0.120', 19, True, BLUE),
             ('、初始 ', 17, False, INK),
             ('0.391 mmol/hr', 19, True, RED),
             ('（⚠ 待水位確認）', 17, False, INK)],
        first=True, align=PP_ALIGN.CENTER)

    # ── 12h 四個方法的匯聚 ──────────────────────────────────
    s = page(prs, '十五、四個方法都指向同一個方向',
             '論文定版的生物速率可能被低估')
    yb = pic2(s, 'deck14_curvature.png', w=Cm(24.0), y=Cm(3.2))
    tf = body(s, y=Cm(yb + 0.3), h=Cm(17.8 - yb - 0.3))
    put(tf, [('曲率配對是本次新做的：用既有資料裡「氣體溶進水的快慢不同」的兩條曲線'
              '互相對消，即可解出生物速率，不需要新實驗。', 16, False, INK)],
        first=True, align=PP_ALIGN.CENTER)

    s = page(prs, '十六、這份分析做不到的事', '引用時應一併說明')
    tf = body(s, y=Cm(4.0), h=Cm(12.0))
    bullets(tf, [
        '氫氣濃度為差額推算，非直接量測（分析儀僅量二氧化碳與甲烷）',
        '無法區分氫氣流失的機制：洩漏、穿透、或其他耗氫生化反應',
        '僅 35 筆可用的氣體組成資料，平均每 11 天一筆',
        '碳源中斷時進料組成同時改變，兩時段的差異不僅限於碳源有無',
        '酸鹼值的結果效應量極小（約為儀器刻度的七分之一），屬方向性證據',
    ], fs=18, first=True, gap=16)

    # ── 13b 補氣本身的比例 ─────────────────────────────────
    s = page(prs, '十七、比例不對的解釋之三：補氣的比例本身',
             '2026-10-02 補充——這個解釋既不需要洩漏，也不需要脫氣')
    tf = body(s, y=Cm(3.6), h=Cm(11.6))
    put(tf, [('做法：', 18, True, INK),
             ('把「兩次排氣之間多出來的二氧化碳」對「同期間補氣的壓力增量」'
              '做回歸。斜率就是補氣偏離 1:4 的程度，', 17, False, INK),
             ('與水位無關', 18, True, BLUE),
             ('（兩邊都正比於氣體空間，約掉了）。', 17, False, INK)],
        first=True, space_after=12)
    put(tf, [('實測：有效補氣比 = 1 : ', 18, False, INK),
             ('3.85', 24, True, RED),
             ('　（95% 區間 1 : 4.03 ~ 1 : 3.63）', 18, False, INK)],
        space_after=10)
    put(tf, [('也就是說——補氣只要比 1:4 少 ', 19, True, INK),
             ('3.6%', 24, True, RED),
             (' 的氫氣，就足以造出全部觀測到的超量。', 19, True, INK)],
        space_after=12)
    bullets(tf, [
        [('一般配氣與流量計的誤差就是這個量級，而且誤差是', 17, False, INK),
         ('單向累積', 18, True, RED),
         ('的：消耗嚴格 1:4、補氣稍微偏二氧化碳，殘餘比就會一路往上爬，'
          '最後把氫氣逼到近零——正是 35 筆裡最極端那幾筆的樣子。',
          17, False, INK)],
        [('無補氣的 09-12 短程實驗殘餘比只有 ', 17, False, INK),
         ('1.08 倍', 19, True, BLUE),
         ('（長紀錄中位 2.79 倍）-> 超量是一次一次補氣累積出來的。',
          17, False, INK)],
        [('⚠ 同樣大小的氫氣洩漏會給出一模一樣的斜率，這批資料分不開兩者。'
          '差別在於：配氣誤差不需要洩漏，而且查一份氣體分析報告就知道。',
          17, False, INK)],
    ], fs=17, first=False, gap=11)
    note(s, '純二氧化碳補氣已被排除：那要求的碳輸入是生物消耗的 14 倍，'
            '且每 4 天要讓液體多吸收 0.19 M 的碳，酸鹼值不可能像實測這樣平。')

    # ── 14 建議 ─────────────────────────────────────────────
    s = page(prs, '十八、建議', '第一項完成前，其餘方向都無法定案')
    tf = body(s, y=Cm(3.6), h=Cm(4.0))
    put(tf, [('最優先：確認補氣用的氣體組成', 24, True, RED)], first=True, space_after=8)
    put(tf, [('一份氣體分析報告或流量計讀數就能回答，卻直接決定第 4 頁的結論'
              '能不能成立——誤差要確認到 1% 以內。'
              '第二順位才是氫氣氣密性檢查：於無菌條件下以氮氣與氫氣分別充壓至'
              '相同絕對壓力，記錄壓力變化；同時檢查橡膠墊片是否適用於氫氣。',
              17, False, INK)])
    table(s, Cm(1.6), Cm(8.4), W - Cm(3.2), [
        ['項目', '現況', '建議', '可解鎖什麼'],
        ['排氣頻率', '平均每 11 天一次', '每 3.5 小時一次', '一週的資料量超過過去一整年'],
        ['排氣期取樣', '每分鐘一筆', '每 10 秒一筆', '排氣僅橫跨 3~4 筆，容易錯過峰值'],
        ['酸鹼值解析度', '0.01', '0.001', 'pH 是唯一符號相反的判別通道'],
        ['氣體分析', 'CO₂、CH₄', '加測 H₂', '核心結論可由推算改為直接量測'],
        ['排氣氣體量', '未量測', '加裝氣量計', '直接關閉氣體收支的缺口'],
    ], widths=[Cm(5.2), Cm(6.0), Cm(5.6), Cm(13.9)], fs=14, hi_rows=(1,))

    # ── 20 給洪博的請求（收尾頁，講清楚要對方做什麼）──────────
    s = page(prs, '十九、需要協助與確認的事項', '2026-10-02')
    tf = body(s, y=Cm(3.3), h=Cm(6.0))
    put(tf, [('最優先（10-02 改）：補氣用的氣體實際組成', 22, True, RED)],
        first=True, space_after=6)
    put(tf, [('補氣比只要是 1 : 3.85 而非 1 : 4，第 4 頁的超量就全部被解釋掉。',
              17, False, INK)], space_after=10)
    put(tf, [('第二順位：無菌（或不含活性菌）靜態保壓', 22, True, RED)],
        space_after=6)
    put(tf, [('以 N₂ 與 H₂ 分別充壓至相同絕對壓力，各記錄約 ', 17, False, INK),
             ('3.5 天', 19, True, INK),
             ('。', 17, False, INK)], space_after=6)
    put(tf, [('⚠ 前 33 小時不可採計', 18, True, RED),
             ('：剛充壓時氣體仍在溶進水裡，那段壓降不是洩漏。', 16, False, INK)])
    table(s, Cm(1.6), Cm(9.5), W - Cm(3.2), [
        ['量到什麼', '代表什麼', '後續處置'],
        ['H₂ 掉得比 N₂ 快約 3.74 倍', '機械洩漏（Graham 定律）', '查接頭、閥件、焊道'],
        ['比例不是 3.74，但 H₂ 明顯較快', '材料穿透', '更換墊片材質'],
        ['兩者都幾乎不掉', '洩漏被排除，剩水裡的碳冒回來', '改由加密排氣取樣驗證'],
    ], widths=[Cm(9.5), Cm(9.5), Cm(11.7)], fs=15, hi_rows=(1,))
    tf2 = body(s, y=Cm(13.6), h=Cm(4.3))
    put(tf2, [('需要確認的現場資訊（未敢自行假設）：', 18, True, INK)],
        first=True, space_after=6)
    put(tf2, [('① 滅菌／去活性方式　② ', 17, False, INK),
              ('液位', 18, True, RED),
              ('（最優先，水佔三成 vs 七成，整機速率差 2.3 倍）　'
               '③ 墊片材質　④ 水溫　⑤ 總容積究竟是 1.8 還是 1.99 L',
               17, False, INK)], space_after=8)
    put(tf2, [('⑥ ', 17, False, INK),
              ('水裡的碳總量（鹼度 TA）', 18, True, RED),
              ('——需酸鹼滴定；目前是由 pH 回推，它直接決定上述兩個機制的強度。',
               17, False, INK)])

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    prs.save(OUT)
    print('已輸出 %s' % os.path.relpath(OUT, REPO))
    print('共 %d 頁' % len(prs.slides.__iter__.__self__._sldIdLst))


if __name__ == '__main__':
    build()
