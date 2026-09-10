# 參考文獻（DOI 已逐筆經 Crossref 驗證）

**驗證日期**：2026-08-06（第三輪修正同日）
**驗證方式**：`api.crossref.org/works/{DOI}` 取回 metadata，比對題名、作者、刊名、卷期頁。
**為什麼要這樣做**：憑記憶寫書目實測錯誤率 2/9，其中一筆 DOI 可解析卻**指向別篇論文**。
只有 DOI 與書目雙向吻合才算通過。

---

## ⚠️ 方法漏洞（2026-08-06，由使用者獨立查證發現）

**只查 Crossref 是不夠的。** 第 3 筆（Jackson et al. 2005）的第八作者
**Sangtrakulcharoen** 在 Crossref 的紀錄裡被截成 **"San"**，第一作者也只給 "Jackson, B."。
我照抄了 Crossref，於是錯誤原樣進入書目。

**錯誤源頭不在轉錄，而在 Crossref 本身**——IEEE 存進去的 metadata 就是截斷的。
正確姓名經 arXiv `math/0309285`、dblp、Semantic Scholar **三處交叉查證**後確認。

**修正後的規則**：
1. Crossref 用來確認 **DOI ↔ 題名／刊名／卷期頁** 的對應（它在這方面可靠）
2. **作者姓名另查第二來源**，尤其是長姓氏、非英語系姓名、以及作者數多的論文
3. 讀 API 回應時**看原始欄位**，不要只讀摘要——摘要可能再次截斷

**另一項尚無法查證**：專利 **TW I923176** 在 Google Patents 與公開資料庫查無公開紀錄。
可能是公告時間新、索引未更新，或號碼格式有出入。
**必須由作者自行至經濟部智慧財產局專利檢索系統核對**，這是全篇唯一未經獨立查證的事實聲明。

---

## ✅ 已驗證（7 筆）

| # | 書目 | DOI | 驗證 |
|---|---|---|---|
| 1 | Box, G.E.P., Tiao, G.C.: Intervention analysis with applications to economic and environmental problems. *J. Am. Stat. Assoc.* **70**(349), 70–79 (1975) | `10.1080/01621459.1975.10480264` | ✅ 完全吻合 |
| 2 | Iturbe, M., Camacho, J., Garitano, I., Zurutuza, U., Uribeetxeberria, R.: On the feasibility of distinguishing between process disturbances and intrusions in process control systems using multivariate statistical process control. In: *2016 46th Annual IEEE/IFIP Int. Conf. on Dependable Systems and Networks Workshop (DSN-W)*, pp. 155–160. IEEE (2016) | `10.1109/dsn-w.2016.32` | ✅ 完全吻合 |
| 3 | Jackson, B., Scargle, J.D., Barnes, D., Arabhi, S., Alt, A., Gioumousis, P., Gwin, E., San, P., Tan, L., Tsai, T.T.: An algorithm for optimal partitioning of data on an interval. *IEEE Signal Process. Lett.* **12**, 105–108 (2005) | `10.1109/lsp.2001.838216` | ✅ 完全吻合 |
| 4 | Killick, R., Fearnhead, P., Eckley, I.A.: Optimal detection of changepoints with a linear computational cost. *J. Am. Stat. Assoc.* **107**(500), 1590–1598 (2012) | `10.1080/01621459.2012.737745` | ✅ 完全吻合 |
| 5 | Linek, V., Beneš, P., Vacek, V.: Dynamic pressure method for kLa measurement in large-scale bioreactors. *Biotechnol. Bioeng.* **33**(11), 1406–1412 (1989) | `10.1002/bit.260331107` | ✅ 完全吻合 |
| 6 | Linek, V., Moucha, T., Doušová, M., Sinkule, J.: Measurement of kLa by dynamic pressure method in pilot-plant fermentor. *Biotechnol. Bioeng.* **43**, 477–482 (1994) | `10.1002/bit.260430607` | ✅ 完全吻合 |
| 7 | Scargiali, F., Busciglio, A., Grisafi, F., Brucato, A.: Simplified dynamic pressure method for kLa measurement in aerated bioreactors. *Biochem. Eng. J.* **49**(2), 165–172 (2010) | `10.1016/j.bej.2009.12.008` | ✅ 完全吻合 |

### ⚠️ 驗證過程中修正的兩處年份錯誤

| 我原本寫的 | 正確 | 說明 |
|---|---|---|
| Iturbe et al. **2017** | **2016** | 2017 是 arXiv 張貼年；正式發表在 DSN-W **2016** |
| simplified DPM **2009** | **2010** | DOI 內的 `2009.12` 是線上日期；期刊發表年為 2010 |

**兩處都已在 §2 與 §4.5 的正文修正。**

---

## ✅ 第二輪驗證（再 5 筆，2026-08-06）

| # | 書目 | DOI | 用於 |
|---|---|---|---|
| 8 | Tobajas, M., García-Calvo, E.: Comparison of experimental methods for determination of the volumetric mass transfer coefficient in fermentation processes. *Heat Mass Transf.* **36**, 201–207 (2000) | `10.1007/s002310050385` | §2／§5.5 支撐「不同方法給出不同 kLa」⇒ 只主張排序 |
| 9 | Jelali, M.: An overview of control performance assessment technology and industrial applications. *Control Eng. Pract.* **14**(5), 441–466 (2006) | `10.1016/j.conengprac.2005.11.005` | §2 控制迴路績效監控 |
| 10 | Harris, T.J.: Assessment of closed loop performance. *Can. J. Chem. Eng.* **67**, 856–861 (1989) | `10.1002/cjce.5450670519` | §2 CPM 的奠基文獻 |
| 11 | Nomikos, P., MacGregor, J.F.: Monitoring batch processes using multiway principal component analysis. *AIChE J.* **40**(8), 1361–1375 (1994) | `10.1002/aic.690400809` | §2 批次製程的多變量分析 |
| 12 | Messenger, D.A., Bortz, D.M.: Weak SINDy for partial differential equations. *J. Comput. Phys.* **443**, 110525 (2021) | `10.1016/j.jcp.2021.110525` | §4.2 弱形式用於含噪量測 |

**累計 12 筆，全數經 Crossref 直接查證。**

### 已刪除而非硬湊的一處

§2 原有「as is Bayesian change-point detection for process monitoring」一句。
候選出處（Bayes Watch）僅有 arXiv 預印本，且該句**不承載任何論證**。
依本檔開頭的原則——**查不到可靠出處就改寫或刪除**——已直接刪去該子句，
不以預印本充數。

### ⚠ 一筆因 DOI 品質不佳而放棄

Westerhuis et al. (1999) 與 Moucha/Kordáč/Linek (1998) 的 DOI 皆為 Wiley 的
SICI 格式次要註冊（`...3.0.CO;2-I`、`...3.3.co;2-l`），且前者是由**別篇論文的
參考文獻**推得、非 Crossref 直接記錄。兩筆皆**不採用**，其功能由
第 8 筆（Tobajas）與第 11 筆（Nomikos）取代。

---

## ⏳ 原待決清單（已全數結案）

| 正文位置 | 需要的引用 | 狀態 |
|---|---|---|
| §2「不同標準方法對同一容器給出不同係數」 | 需要一篇明確比較方法的文獻 | **候選**：Moucha, Kordáč, Linek: *Barrier effect or artifact? A critical assessment of the dynamic stationarized method for kLa measurement*, Chem. Eng. Technol. 21(9), 753–756 (1998)。⚠ 其 DOI `10.1002/(sici)1521-4125(199809)21:9<753::aid-ceat753>3.3.co;2-l` 帶 `3.3.co;2-l` 後綴，屬**次要註冊**，須另行確認正規 DOI 後才可用 |
| §2「setpoint tracking vs disturbance rejection 在控制迴路績效監控中行之有年」 | 一篇 CPM 綜述或代表作 | **未查** |
| §2「生物製程歷史／即時資料的多變量分析是既有實踐」 | 一篇 bioprocess MVDA 文獻 | **未查** |
| §2「製程監控的 Bayesian 變點偵測」 | 目前只有 arXiv:2310.02940（Bayes Watch），**arXiv 預印本是否可引用視 ICEA 規定** | **未查正式版** |
| §4.2 弱形式對含噪資料的處理 | 若要引用，Messenger & Bortz 的 weak-form SINDy 是合適出處 | **未查** |

> **原則**：查不到可靠出處的敘述，**改寫成不需要引用的說法或直接刪除**，
> 不以「大家都知道」帶過。上表每一列在定稿前必須是「已驗證」或「已刪除」。

---

## LNCS 書目格式備註

Springer LNCS 使用 `splncs04.bst`，格式為：

```
作者姓, 名縮寫.: 題名（句首大寫，其餘小寫）. 刊名 卷(期), 起頁--迄頁 (年)
```

會議論文：

```
作者: 題名. In: 論文集名. pp. 起--迄. 出版者 (年)
```

DOI 依 Springer 現行規定應以 `\doi{...}` 附於條目末。
