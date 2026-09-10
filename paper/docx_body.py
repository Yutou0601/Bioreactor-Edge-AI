
# -*- coding: utf-8 -*-
"""
論文本體 — §1–§3（ICEA 2026 10 頁版）
════════════════════════════════════════════════════════════════════════
ICEA 2026 規定 6–10 頁，**含圖、表、附錄與參考文獻**。
初版量得 15 頁 / 5,496 字，故本版依「承重程度」壓縮：

  保留  主張本身、支撐主張的數字、以及使主張可信的方法選擇
  壓縮  Related Work（四段→兩段）、Limitations（五個小節→一段）、
        §4.3 混淆說明（一長段→三句）
  移除  Table 1 門檻敏感度（→ 一句話）、Table 3 事件分類（→ 散文）、
        Table 5 雙峰（數字已在 Fig. 3 內）
  併入  §5.1 覆蓋率 → §3 資料

排版工具與文獻表在 build_docx.py。
"""
import sys

from docx.enum.text import WD_ALIGN_PARAGRAPH

from build_docx import (h1, h3, body, para, text, rich, figure, cite, xref,
                        _rpr_font)

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ABSTRACT = (
    'Industrial bioreactors are instrumented for control, not for observation. '
    'When a logged variable changes, the operationally useful question is '
    'whether someone moved a setpoint, someone intervened by hand, or the '
    'reactor itself drifted. Answering it normally requires controller-level '
    'signals, which a small edge-deployed reactor does not record. We show '
    'that the attribution can be recovered from a single quantized pressure '
    'trace. The pipeline first reconstructs which derived channels carry '
    'usable control information, using only the time structure of each '
    'channel, and then applies per-channel calibrated change-point detection '
    'with a minimum effect size set by sensor resolution. Applied to 255 '
    'cycles and 1,228 refill events spanning 365 days, of which 235 carry '
    'logged data, across five recirculation settings and two feed '
    'compositions, it recovers eight trigger-setpoint changes, including an '
    'undocumented reconfiguration located to within three days by two '
    'independent estimators, and 18 manual venting events subsequently '
    'confirmed by the equipment operator, while detecting all four '
    'independently documented process events to within one day. The '
    'plane-reconstruction stage is what removes the controller-access '
    'assumption, and its contribution is measurable: admitting a nominally '
    'correct but noise-degraded control channel lowers event classification '
    'from 3/4 to 2/4. The governing quantity is the ratio of actuation noise '
    'to sensor resolution, which suggests the criterion transfers to other '
    'threshold-controlled equipment.')


def front_matter(doc):
    p = para(doc, WD_ALIGN_PARAGRAPH.CENTER, after=10)
    text(p, 'Edge-Side Pressure-Only Change-Point Mining Recovers Undocumented '
            'Setpoint Changes and Manual Interventions in a Micro-Pressurized '
            'Recirculating Hydrogenotrophic Biomethanation Reactor', 14,
         bold=True)

    p = para(doc, WD_ALIGN_PARAGRAPH.CENTER, after=6)
    rich(p, [('Cheng-Yu Li', ''), ('1', 'sup'), ('*', 'sup'), (', ', ''),
             ('Chun-Hao Chen', ''), ('1', 'sup'), (', ', ''),
             ('Cheng-Yuan Hung', ''), ('2', 'sup'), (', and ', ''),
             ('Yen-Jie Huang', ''), ('2', 'sup')], size=12)

    p = para(doc, WD_ALIGN_PARAGRAPH.CENTER, after=0)
    rich(p, [('1', 'sup'),
             ('Department of Computer Science and Information Engineering, '
              'National Kaohsiung University of Science and Technology, '
              'Kaohsiung, Taiwan', '')], size=9)
    p = para(doc, WD_ALIGN_PARAGRAPH.CENTER, after=0)
    rich(p, [('2', 'sup'),
             ('Opto-Electronics Technology Section, Energy and Agile '
              'System Department, Metal Industries Research & Development '
              'Centre, Kaohsiung, Taiwan', '')], size=9)
    p = para(doc, WD_ALIGN_PARAGRAPH.CENTER, after=10)
    _rpr_font(p.add_run('lkkyb555@gmail.com'), 9, name='Courier New')

    p = para(doc, after=5)
    text(p, 'Abstract. ', 9, bold=True)
    text(p, ABSTRACT, 9)

    p = para(doc, after=12)
    text(p, 'Keywords: ', 9, bold=True)
    text(p, 'Process-state mining · Change-point detection · '
            'Bioreactor monitoring · Edge computing · Biomethanation', 9)


def sec_intro(doc):
    h1(doc, 1, 'Introduction')
    body(doc, 'Industrial bioreactors are instrumented for control, not for '
              'observation. A pressure transducer exists so that a valve can '
              'be opened at the right moment; a pump duty cycle exists so that '
              'gas is redissolved. Neither is placed to make the process '
              'observable. The consequence is that a plant may hold millions '
              'of logged samples of which almost none have been analyzed.')
    body(doc, 'This is an attribution problem rather than a data-scarcity one. '
              'When a logged variable changes, what matters operationally is '
              'whether someone moved a setpoint, someone intervened by hand, '
              'or the reactor itself drifted. Answering it normally requires '
              'reading the controller and inferring the origin of an anomaly '
              'from which layer moved first ' + cite('iturbe') + '. On a small '
              'edge-deployed reactor those signals are not recorded. What is '
              'recorded is one pressure trace, and we show that the '
              'attribution can be recovered from it alone.', first=False)
    body(doc, 'The vehicle is a micro-pressurized recirculating bioreactor for '
              'hydrogenotrophic biomethanation, operated under a granted '
              'patent (TW I923176). Its control loop admits gas when headspace '
              'pressure falls to a threshold, then lets pressure decay as '
              'carbon dioxide dissolves and is consumed. Every refill is thus '
              'an unforced step excitation delivered at no cost in downtime, '
              'and the threshold that triggers it is a control parameter '
              'written into the pressure record itself (' + xref('Fig. 1') +
              ').', first=False)
    body(doc, 'We contribute, first, a pressure-only mining pipeline that '
              'reconstructs the control plane from the process variable before '
              'attributing change; this is what removes the controller-access '
              'assumption of prior work, and its value is measured rather than '
              'asserted. Second, a recovered year of operating history: eight '
              'trigger-setpoint changes, one of them undocumented, and 18 '
              'manual venting events subsequently confirmed by the equipment '
              'operator. Third, an edge-side cost characterization showing '
              'that the binding constraint is library memory rather than '
              'computation.', first=False)

    figure(doc, 'fig1_pipeline.png', 1,
           'System and mining pipeline. The reactor admits gas when headspace '
           'pressure falls to a trigger threshold and recirculates headspace '
           'gas into the liquid for tau minutes each hour. Controller-level '
           'signals are not logged, so the pipeline receives only the pressure '
           'trace, sampled once per minute and quantized to 0.01 kg/cm2. Stage '
           '3 (highlighted) reconstructs which derived channels carry usable '
           'control information')


def sec_related(doc):
    h1(doc, 2, 'Related Work')
    body(doc, 'Volumetric mass-transfer coefficients are conventionally '
              'obtained by dedicated experiments such as gassing-out or the '
              'dynamic pressure method ' +
              cite('linek89', 'linek94', 'scargiali') + ', all of which '
              'require a deliberate perturbation or a production interruption, '
              'and the choice among them is itself a subject of comparative '
              'study ' + cite('tobajas') + '. Having no reference measurement '
              'against this vessel, we report our composition-corrected '
              'quantity as a proxy for ordering rather than as a calibrated '
              'coefficient.')
    body(doc, 'Assessing a control loop against a benchmark, and separating '
              'setpoint tracking from disturbance rejection, is long '
              'established ' + cite('harris', 'jelali') + ', and multivariate '
              'statistical process control has been extended to monitor '
              'process-level and controller-level variables jointly so that '
              'the origin of an anomaly can be identified ' + cite('iturbe') +
              '. We adopt that framing and relax its instrumentation premise: '
              'no controller-level variable is available to us, so the control '
              'plane is reconstructed from the process variable and then '
              'verified to be usable (Sect. 4.3). Exact optimal partitioning ' +
              cite('jackson') + ' and its pruned variants ' + cite('killick') +
              ' supply the detection machinery, and the distinction we draw '
              'between transient and persistent events follows classical '
              'intervention analysis ' + cite('box') + '; the contribution is '
              'not that distinction but its application to a control channel '
              'that is itself inferred.', first=False)
    body(doc, 'Multivariate analysis of batch and bioprocess trajectories is '
              'established practice for detecting deviations ' +
              cite('nomikos') + ', but generally assumes a richly instrumented '
              'platform. The regime addressed here, one trustworthy variable '
              'at minute resolution with quantization comparable to the signal '
              'of interest and roughly a third of the calendar span missing, '
              'has not to our knowledge been treated as a mining target in '
              'this application area.', first=False)


def sec_data(doc):
    h1(doc, 3, 'Reactor, Signals and Data')

    p = h3(doc, 'Device and Signals.')
    text(p, 'The reactor implements micro-pressurized recirculation under '
            'Taiwan patent TW I923176, granted 2026-04-21 to the Metal '
            'Industries Research and Development Centre: headspace gas is '
            'periodically driven back into the liquid by a circulation pump '
            'operating for tau minutes each hour, with liquid temperature held '
            'at 30 degrees Celsius. The patent also claims electrofermentation '
            'with a conductive carbon electrode; that capability was not '
            'enabled in any campaign reported here and no external potential '
            'was applied. Four '
            'channels are trustworthy at production cadence: reactor pressure, '
            'mixing-tank pressure, oxidation-reduction potential, and pH. '
            'Headspace carbon dioxide and methane are read by an analyzer that '
            'updates only on venting, so 99.98 % of those values are stale '
            'carry-forward and they are excluded throughout. Pressure is '
            'sampled once per minute and quantized to 0.01 kg/cm2; a cycle '
            'traverses only one to five quantization steps per hour, which is '
            'why every rate in this work is obtained in weak form '
            '(Sect. 4.2).', 10)

    p = h3(doc, 'Dataset and Coverage.')
    text(p, 'The record spans 2025-08-04 to 2026-08-03 across eight '
            'acquisition folders. Folders overlap in time and are deduplicated '
            'on the pair of start timestamp and duration, yielding 255 '
            'distinct cycles and 1,228 refill events, of which 1,219 have a '
            'resolvable amplitude and are used wherever a rate is computed. '
            'Feed composition covers hydrogen-to-carbon-dioxide ratios of 4:1 '
            'and 1:1; recirculation covers pump-off, tau of 1, 5, and '
            '10 min/hr, and a continuous five-minute setting. Coverage is '
            'discontinuous and is counted from raw sample timestamps rather '
            'than inferred from the spacing of derived events: pressure was '
            'logged on 235 of the 365 days (64 %), monthly coverage ranges '
            'from 3 to 31 days, and June 2026 is absent entirely. Inferring '
            'coverage from gaps between cycles would give 174 days and from '
            'gaps between refills 232 days; cycles occur only 1.4 times per '
            'day, so a multi-day gap between them indicates an absence of '
            'cycling rather than an absence of data. Biological activity is '
            'established independently of any model: vented gas assayed 31.6 '
            'to 43.0 % methane over three readings, which we use as an '
            'existence statement only and never as a rate.', 10)
