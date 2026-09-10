
# -*- coding: utf-8 -*-
"""論文本體 — §5–§8 與參考文獻（ICEA 2026 10 頁版，第二輪壓縮）。

1,114 → 約 800 字；圖說由每則約 70 字收到 40 字以內（Springer 允許簡短圖說，
且不成完整句時不加句點）。§7 由兩段收成一段。
"""
import sys

from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Mm

from build_docx import (h1, h2, body, para, text, figure, table, cite, xref,
                        REFS)

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def sec_results(doc):
    h1(doc, 5, 'Results')

    # ── 5.1 ────────────────────────────────────────────────
    h2(doc, '5.1', 'A Year of Trigger-Setpoint History')
    body(doc, 'The refill starting pressure is a direct readout of the trigger '
              'threshold at the instant the controller fires. Taken as the '
              'modal value over non-overlapping windows of 15 refills, it '
              'resolves the setpoint to a fraction of the quantization step '
              'and is immune to the minority of refills following a deep vent '
              '(' + xref('Fig. 2') + '). The record is not one continuous '
              'experiment, so the figure labels the campaigns beneath the '
              'axis: feed is 4:1 except for 2026-01-09 to 01-23, and the '
              'recirculation series occupies 2026-07-22 onward. What makes the '
              'trace meaningful across those boundaries is that the trigger '
              'threshold is a control parameter, not a process response, so it '
              'should persist when the feed or duty cycle changes; Sect. 5.3 '
              'confirms that it does.')

    figure(doc, 'fig2_setpoint_history.png', 2,
           'Recovered trigger-setpoint history. Points are individual refills; '
           'the step line is the modal setpoint over 15-refill windows. Shaded '
           'bands mark intervals longer than three days with no refill. The '
           'lower band identifies the campaigns')

    body(doc, 'Eight setpoint changes exceeding the three-step threshold are '
              'recovered. Seven fall between 2025-08 and 2025-10, where the '
              'modal value moves 1.22, 0.97, 0.72 with modal-cluster shares of '
              'only 9 to 49 %, the signature of a commissioning period. The '
              'eighth is different: after 2025-10-28 the setpoint holds at '
              '0.710 for thirteen consecutive windows, roughly nine months, '
              'with 76 to 100 % of refills in the modal bin.')
    body(doc, 'That regime ends in mid-July 2026, when the trigger floor moves '
              'from 0.72 to 0.92 and holds. The change appears in no operating '
              'record. Two independent estimators place it within three days '
              'of each other: cycle-level end pressures at 2026-07-11, and '
              'modal tracking of refill starting pressures at 2026-07-14, the '
              'latter limited by its window. From end pressures the monthly '
              'robust level is 0.71 to 0.73 for eight months and 0.92 '
              'thereafter (Mann-Whitney, n = 8 and 29, z = -3.73, '
              'p = 1.9 x 10-4). From minute-level starting pressures, which '
              'bypass cycle segmentation entirely, the distribution shifts '
              'cleanly rather than becoming bimodal: the share starting '
              'between 0.60 and 0.80 falls from 89.3 % to 4.5 % (n = 159 and '
              '44) while the share between 0.85 and 1.00 rises from 0.6 % to '
              '77.3 %.', first=False)
    body(doc, 'The distinction matters. Had automatic control continued '
              'unchanged with manual gas additions superimposed, the '
              'explanation the operator first offered, both clusters would '
              'persist. Instead the old threshold stopped firing. Nor is this '
              'a gap artifact: the preceding gap closes on 07-01 and refills '
              'through 07-08 still start at 0.71.', first=False)

    # ⚠ 雙峰圖已移除：其兩組百分比已完整寫入上一段，論證不依賴圖像，
    #   而該圖佔 69 mm 加圖說約 0.4 頁。四張圖中只有它與內文重複。
    #   圖檔仍保留在 docs/paper_figures/，投稿的補充資料可用。

    # ── 5.2 ────────────────────────────────────────────────
    h2(doc, '5.2', 'A Year of Manual Interventions')
    body(doc, 'Isolated deep excursions of the trigger floor, followed by '
              'immediate return, occur 18 times, that is 7.1 % of cycles: 17 '
              'downward and one upward, with a median depth of 0.40 kg/cm2 '
              'against a local median holding at 0.71 to 0.72. The equipment '
              'operator confirmed that these are manual venting, and the '
              'detector had no access to any venting record. This is the '
              'largest external validation available and is independent of the '
              'known-event set below. All detected events and the monthly data '
              'coverage appear in ' + xref('Fig. 3') + '.')

    figure(doc, 'fig5_event_timeline.png', 3,
           'Recovered operating history. Upper: detected events per month by '
           'class. Lower: days on which pressure was logged, from raw sample '
           'timestamps. Classes use fill and hatch so the figure stays legible '
           'in grayscale')

    # ── 5.3 ────────────────────────────────────────────────
    h2(doc, '5.3', 'Validation Against Known Events')
    body(doc, 'Four events are independently documented: a manual venting on '
              '2026-04-07, a new campaign on 2026-07-22, and recirculation '
              'changes on 2026-07-27 and 07-30. A fifth, the feed change of '
              '2026-01-09, is known from the acquisition configuration. Two '
              'evaluations are reported separately, since the ablation and the '
              'final method were measured on different event sets.')
    body(doc, 'Assigning every detection to either reconfiguration or drift '
              'and evaluating against all four, detection is 4/4 within one '
              'day; classification is 3/4 with the plane partition and 2/4 '
              'without it, which is the ablation quoted earlier. Under the '
              'final four-class method we exclude 2026-04-07, whose ground '
              'truth is genuinely ambiguous because it coincides with a '
              '2.4-fold step in the mass-transfer proxy; on the remaining '
              'three, detection is 3/3 and classification 2/3. The single '
              'disagreement is 2026-07-30, labeled a transient intervention. '
              'Two facts bear on it: a genuine vent did occur that day, the '
              'floor dropping to 0.22 and returning, and the recirculation '
              'change it was expected to capture produced no measurable '
              'response, the proxy moving only from 0.1714 to 0.1686. The '
              'event set assigns one label per day, and two events coincided.',
         first=False)

    # ── 5.4 ────────────────────────────────────────────────
    h2(doc, '5.4', 'Mass-Transfer State')
    body(doc, 'Median values of the composition-corrected proxy order '
              'monotonically with duty cycle across five conditions spanning '
              'both feed compositions (' + xref('Table 2') + '). The '
              'resolvable structure is a two-group separation, not a '
              'five-level ordering: low-duty operation separates from '
              'high-duty operation, but within the high-duty group the ranges '
              'overlap and the three settings are indistinguishable at this '
              'sample size, while the pump-off and 1 min/hr ranges touch. We '
              'therefore claim the grouping and the ordering of medians, not '
              'pairwise separation.')

    table(doc, 2,
          'Composition-corrected mass-transfer proxy by recirculation setting',
          ['Condition', 'Median (/hr)', 'Interquartile range', 'n'],
          [['Pump off', '0.0954', '0.0909 to 0.1023', '40'],
           ['1 min/hr', '0.1065', '0.1019 to 0.1101', '6'],
           ['5 min/hr', '0.1659', '0.1484 to 0.1737', '8'],
           ['Continuous 5 min', '0.1677', '0.1345 to 0.2192', '16'],
           ['10 min/hr', '0.1708', '0.1653 to 0.1782', '12']],
          widths=[38, 27, 40, 17])

    body(doc, 'An independent contrast over pump-off and pump-on periods of a '
              'single campaign gives 0.0187 against 0.0449, a factor of 2.4, '
              'with non-overlapping cluster-bootstrap intervals; this is the '
              'sharpest available statement of the effect. Marginal returns '
              'fall sharply, since raising the duty cycle from 5 to 10 min/hr '
              'doubles pump runtime for 8.8 % of the gain per minute obtained '
              'over the first minute. We report that as a measured contrast, '
              'not a functional law: with four conditions and duty cycle '
              'confounded with culture age, a fitted saturation curve is not '
              'identifiable. Absolute coefficients are not claimed, the proxy '
              'being calibrated against no reference method ' +
              cite('tobajas') + '.')


def sec_edge(doc):
    h1(doc, 6, 'Edge Deployment')
    body(doc, 'The pipeline targets the monitoring workstation beside the '
              'reactor, which has 4 GB of memory shared with acquisition and '
              'dashboard services; roughly 60 MB is available to an analysis '
              'process. Computation is not the constraint: streaming '
              'segmentation costs 0.1 microseconds per sample against a '
              '60-second sampling interval, and a per-cycle estimate with its '
              'standard error costs 0.32 milliseconds, so the daily budget is '
              'under a millisecond.')
    body(doc, 'Memory is the constraint, and it is dominated by imports rather '
              'than data; a cycle buffer is 600 samples, under 5 kB. The '
              'reference implementation peaks at 330 MB, of which the '
              'scientific stack is 129 MB: the array library alone is 27 MB, '
              'and either common companion library exhausts the budget on its '
              'own. An array-library-only implementation fits the envelope; '
              'the reference implementation does not. Querying accelerator '
              'availability through a deep-learning framework costs a further '
              '307 MB, five times the budget, where a subprocess call to the '
              'vendor utility costs nothing persistent. For this class of '
              'deployment, library selection rather than algorithm selection '
              'determines feasibility.', first=False)


def sec_limits(doc):
    h1(doc, 7, 'Limitations and Future Work')
    body(doc, 'A third of the calendar span is unrecorded, and detections at '
              'the resumption of recording are excluded rather than '
              'interpreted. Classification of known events is 3/4 for the '
              'two-class variant and 2/3 for the final method, the '
              'disagreement arising where two events coincided. On mass '
              'transfer we report ordering, not a calibrated coefficient; an '
              'absolute value needs one gassing-out reference against this '
              'vessel, and separately the duty cycle is confounded with '
              'culture age because the reactor was not reinoculated, which '
              'randomized within-batch alternation would break at no cost.')
    body(doc, 'The pipeline attributes changes; it does not resolve physical '
              'and biological rates into separate components. Under headspace '
              'pressure alone the biological consumption rate is not '
              'identified, and standard practice for that separation needs a '
              'dissolved-gas probe, so this is an observability limit and we '
              'make no claim on that quantity. Refill transients are '
              'informative in principle, the rise rate being inversely '
              'proportional to headspace volume at fixed gas flow, but a '
              'refill completes within one sampling interval for 67 % of '
              'events, so its duration is censored; sampling at 5 to 10 '
              'seconds during refill only, a logging change with no hardware '
              'cost, would yield 6 to 12 samples per transient. Finally, only '
              'the batch pipeline has been characterized: a streaming '
              'implementation and the reduced-dependency rewrite remain to be '
              'built.', first=False)


def sec_conclusion(doc):
    h1(doc, 8, 'Conclusion')
    body(doc, 'A production reactor’s own pressure log contains a recoverable '
              'operating history. From a single quantized trace, with no '
              'controller-level signals and no additional instrumentation, we '
              'recovered eight trigger-setpoint changes, including a '
              'nine-month stable regime ending in an undocumented '
              'reconfiguration located to within three days by two independent '
              'estimators, together with 18 manual venting events confirmed by '
              'the equipment operator and a mass-transfer ordering separating '
              'low- from high-duty recirculation.')
    body(doc, 'What makes this possible is reconstructing which observable '
              'channels carry usable control information before attempting '
              'attribution, rather than assuming access to the controller. Its '
              'value is measurable rather than asserted: admitting a nominally '
              'correct but noise-degraded control channel halves the '
              'classification accuracy. The governing quantity is the ratio of '
              'actuation noise to sensor resolution, which suggests the '
              'criterion transfers to other threshold-controlled equipment.',
         first=False)


def sec_refs(doc):
    p = para(doc, WD_ALIGN_PARAGRAPH.LEFT, before=12, after=5)
    text(p, 'References', 12, bold=True)
    for i, (_, s) in enumerate(REFS, 1):
        q = para(doc, WD_ALIGN_PARAGRAPH.JUSTIFY, after=1)
        q.paragraph_format.left_indent = Mm(7)
        q.paragraph_format.first_line_indent = Mm(-7)
        text(q, f'{i}. ', 9)
        text(q, s, 9)
