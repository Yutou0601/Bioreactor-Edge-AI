
# -*- coding: utf-8 -*-
"""論文本體 — §4 管線（ICEA 2026 10 頁版，第二輪壓縮）。

第一輪只是合併段落，字數僅降 12%；本輪針對句法：拆掉從屬子句、
刪去可由數字自明的說明、把「為什麼不用某方法」由一段收成一句。
1,268 → 約 850 字。保留的是主張、數字、以及使主張可信的方法選擇。
"""
import sys

from build_docx import (h1, h2, body, table, add_equation, cite, xref,
                        _run, _frac, _m)

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def sec_pipeline(doc):
    h1(doc, 4, 'Mining Pipeline')
    body(doc, 'The edge controller logs one trustworthy state variable and '
              'exposes no controller-level signals. Prior work on separating '
              'operator-originated from process-originated anomalies assumes '
              'access to controller variables ' + cite('iturbe') + '. That '
              'assumption fails here, so the pipeline reconstructs the control '
              'plane from the process variable before attributing anything. '
              'All five stages run on the pressure trace alone: no extra '
              'instrumentation, no process model, no labeled events.')

    # ── 4.1 ────────────────────────────────────────────────
    h2(doc, '4.1', 'Streaming Cycle Segmentation')
    body(doc, 'Threshold-triggered refill partitions the record into cycles: a '
              'rapid rise when gas is admitted, then a slow decline. '
              'Segmentation exploits that asymmetry. Over 1,228 refills the '
              'median rise rate is 1.80 kg/cm2/hr, with monthly medians from '
              '1.8 to 34.2, against a decline of roughly 0.03 kg/cm2/hr. The '
              'asymmetry is not uniform: the slowest 5 % of refills rise at '
              '0.06 kg/cm2/hr, twice the decline rate, so the populations are '
              'not perfectly separated.')
    body(doc, 'The detector is single-pass with O(1) state. A cycle is emitted '
              'when pressure exceeds a running valley by more than '
              '0.03 kg/cm2, or when a recording gap exceeds one hour. That '
              'threshold is the one tuned parameter, and we report its '
              'sensitivity rather than asserting robustness: cycle count is '
              '269, 272, 271, and 268 at thresholds of 0.05, 0.08, 0.12, and '
              '0.20 kg/cm2, but collapses to 96 at 0.02 where quantization '
              'noise is admitted as refills. Our value of 0.03 yields 255 '
              'cycles, 5 % below that plateau; we keep it as the smallest '
              'value above the noise floor, downstream results being unchanged '
              'in sign and ordering at 0.05. Cycles are deduplicated on start '
              'timestamp and duration, since archive folders overlap and '
              'omitting this manufactures spurious change points at folder '
              'boundaries.', first=False)

    # ── 4.2 ────────────────────────────────────────────────
    h2(doc, '4.2', 'Weak-Form Rate Estimation')
    body(doc, 'A cycle traverses only one to five quantization steps per hour, '
              'so finite differences are dominated by quantization noise and '
              'we never differentiate the data. Each rate is obtained in weak '
              'form: the trace is multiplied by a compactly supported test '
              'function and integrated by parts (Eq. 1), moving the derivative '
              'onto the analytically known test function.')

    add_equation(doc, [
        _m('sSub', _m('e', _run('⟨dP/dt⟩')), _m('sub', _run('φ'))),
        _run(' = ', italic=False),
        _frac([_run('∫'), _run('φ̇'), _run('(t)'), _run('P'), _run('(t)'),
               _run(' dt')],
              [_run('∫'), _run('φ'), _run('(t)'), _run(' dt')]),
    ], 1)

    body(doc, 'Weak forms have been developed for exactly this purpose ' +
              cite('messenger') + ', though here they serve rate estimation '
              'and not model selection. The test function is the sixth power '
              'of one minus u squared, on a half-width of 1.5 hours. The same '
              'construction yields a composition-corrected mass-transfer '
              'proxy: early in a cycle the physical term is approximately the '
              'product of the mass-transfer coefficient, the carbon dioxide '
              'mole fraction, and the total pressure (Eq. 2).')

    add_equation(doc, [
        _run('κ̂'),
        _run(' = ', italic=False),
        _frac([_m('sSub', _m('e', _run('⟨dP/dt⟩')), _m('sub', _run('φ')))],
              [_m('sSub', _m('e', _run('f')), _m('sub', _run('CO2'))),
               _m('sSub', _m('e', _run('⟨P⟩')), _m('sub', _run('φ')))]),
    ], 2)

    body(doc, 'The correction is not cosmetic: without it the 1:1 campaign is '
              'indistinguishable from the five- and ten-minute recirculation '
              'settings, and a feed change is misread as a recirculation '
              'change. The proxy is a first-order rate constant, since the '
              'pressure units cancel, and is therefore comparable across feed '
              'compositions and operating pressures.')

    # ── 4.3 ────────────────────────────────────────────────
    h2(doc, '4.3', 'Control-Response Plane Partitioning')
    body(doc, 'Attribution requires knowing which derived channels reflect '
              'control configuration and which reflect process response. Prior '
              'work reads this from controller-level measurements ' +
              cite('iturbe') + '; with no controller log it must be inferred. '
              'Testing each channel for independence from a process-state '
              'proxy is confounded by construction, because every proxy '
              'derived from the same trace shares endpoints with the candidate '
              'setpoint channels. This constrains any method operating on a '
              'single trace.')
    body(doc, 'We partition instead on time structure within each channel '
              'alone. Discreteness is the normalized entropy of the quantized '
              'values, since a setpoint takes few discrete values whereas a '
              'process outcome is continuous; persistence is the mean run '
              'length of identical values, standardized against a permutation '
              'null. Only channels in the units the controller compares '
              'against are eligible, so cycle duration cannot be a setpoint '
              'whatever its statistics. The partition is unambiguous (' +
              xref('Table 1') + ').', first=False)

    table(doc, 1, 'Control-response partition of the pressure-valued channels',
          ['Channel', 'Norm. entropy', 'Top-3 mass', 'Mean run', 'Null run',
           'Plane'],
          [['Trigger floor', '0.449', '**64.7 %**', '1.60', '1.23',
            '**Control**'],
           ['Refill ceiling', '0.571', '34.9 %', '1.39', '1.07', 'Response'],
           ['Band width', '0.615', '28.2 %', '1.24', '1.05', 'Response']],
          widths=[27, 21, 18, 17, 17, 22])

    body(doc, 'The trigger floor is the sole usable control channel, and the '
              'value of establishing that is measurable: treating the refill '
              'ceiling as a control channel too degrades classification from '
              '3/4 to 2/4 (Sect. 5.3). We are precise about what the criterion '
              'identifies. The operator confirmed that refill terminates on '
              'pressure, so the ceiling is a genuine setpoint; the partition '
              'recovers not the architecture but which channels are usable at '
              'the available resolution. The realized ceiling carries about '
              '0.02 kg/cm2 of overshoot jitter, two least-significant bits at '
              'a 0.01 kg/cm2 quantum, enough to defeat the discreteness test. '
              'The conclusion generalizes: when actuation noise exceeds a few '
              'sensor bits, a genuine setpoint becomes unusable as a control '
              'channel, and including it actively degrades attribution.')

    # ── 4.4 ────────────────────────────────────────────────
    h2(doc, '4.4', 'Calibrated Detection and Event Typology')
    body(doc, 'Change points are located by exact optimal partitioning ' +
              cite('jackson') + '; pruned variants ' + cite('killick') +
              ' give the same segmentation at lower cost. Three choices '
              'matter. For control-plane channels the cost is the '
              'within-segment sum of squares, responding to mean shifts only, '
              'since a variance-sensitive cost reports reconfigurations across '
              'which the level is unchanged. The penalty is calibrated per '
              'channel so that autoregressive surrogates matched to that '
              'channel yield a change point with probability at most 0.05; a '
              'fixed information-criterion penalty is not conservative here, '
              'as surrogates with a lag-one coefficient of 0.57 produce up to '
              '11 spurious change points against 18 observed. A shift is kept '
              'only if the level moves by at least three quantization steps, a '
              'threshold set by sensor resolution: before this filter, a '
              'one-bit movement of the refill ceiling was enough to trigger a '
              'spurious reconfiguration. Where a channel is piecewise constant '
              'and heavily quantized the surrogate is misspecified and '
              'over-conservative, and we track the modal value directly '
              'instead.')
    body(doc, 'Detections fall into four classes. A transient intervention is '
              'an isolated control-plane excursion returning within two '
              'cycles, which we read as manual venting; a persistent '
              'reconfiguration is a sustained control-plane mean shift of at '
              'least three quantization steps; process drift is a '
              'response-plane change with the control plane stable; and a '
              'recording artifact coincides with a gap longer than three days. '
              'The transient-versus-persistent distinction follows classical '
              'intervention analysis ' + cite('box') + ', the contribution '
              'being its application to a control channel that is itself '
              'reconstructed. The fourth class is a correctness requirement, '
              'not a refinement: change points at the resumption of recording '
              'are recording discontinuities. Of 81 candidates at a fixed '
              'penalty, 8 fell in gaps; after calibration, 5 of 69 did.',
         first=False)
