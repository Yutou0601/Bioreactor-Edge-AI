# ICEA 2026 — §4 Mining Pipeline ＋ §5 Results（英文正稿 draft 1）

**Paper**: *Edge-Side Pressure-Only Change-Point Mining Recovers Undocumented Setpoint
Changes and Manual Interventions in a Micro-Pressurized Recirculating Hydrogenotrophic
Biomethanation Reactor*

Cheng-Yu Li¹✉, Chun-Hao Chen¹, Cheng-Yuan Hung², and Yen-Jie Huang²

¹ Department of Computer Science and Information Engineering, National Kaohsiung
University of Science and Technology, Kaohsiung, Taiwan
² Optoelectronics Technology Division, Metal Industries Research & Development Centre,
Kaohsiung, Taiwan

> Draft 1 — 2026-08-06. Springer LNCS format, American English.
> 對應中文骨架：`ICEA2026_論文骨架_v2_資料探勘_2026-08-06.md`

---

## 4 Mining Pipeline

The reactor is instrumented for control, not for observation. Its edge controller logs a
single trustworthy state variable at one-minute resolution — headspace pressure,
quantized to 0.01 kg cm⁻² — and exposes no controller-level signals: setpoints, valve
states, and pump commands are not recorded. Prior work on separating operator-originated
from process-originated anomalies assumes access to controller variables [Iturbe et al.].
That assumption does not hold here. The pipeline below therefore reconstructs the control
plane from the process variable itself before attempting any attribution.

All five stages run on the logged pressure trace alone. No additional instrumentation,
no process model, and no labeled events are required.

### 4.1 Streaming Cycle Segmentation (Alg. 1)

Threshold-triggered refill partitions the record into *cycles*: a rapid pressure rise
when gas is admitted, followed by a slow decline as CO₂ dissolves and is consumed.
Segmentation exploits an asymmetry that is a physical property of the device rather than
a tuned heuristic. Measured over 1,219 refill events, the mean rise rate is
1.8–13.6 kg cm⁻² h⁻¹, whereas the decline proceeds at approximately
0.03 kg cm⁻² h⁻¹ — a separation of **60–450×, i.e. two orders of magnitude**.
Any threshold within that gap yields the same segmentation, so the stage is effectively
parameter-free.

The detector is single-pass and keeps O(1) state: a running valley estimate, the index of
the current cycle start, and the previous sample. Cycles are emitted when the pressure
exceeds the running valley by more than 0.03 kg cm⁻², or when a recording discontinuity
exceeds one hour.

Because several archive folders overlap in time, cycles are **deduplicated on
(start timestamp, duration)** before any analysis; in one folder pair this reduced 31
apparent cycles to 20 distinct ones. Omitting this step inflates event counts and
manufactures spurious change points at folder boundaries.

### 4.2 Weak-Form Rate Estimation (Alg. 2)

Pressure is quantized to 0.01 kg cm⁻² and a typical cycle traverses only 1–5 quantization
steps per hour. Finite differences on such a record are dominated by quantization noise.
We therefore never differentiate the data. Instead, each rate is obtained in weak form:
the trace is multiplied by a compactly supported test function φ and integrated by parts,

$$\left\langle \frac{dP}{dt} \right\rangle_\varphi
= \frac{\int \dot\varphi(t)\,P(t)\,dt}{\int \varphi(t)\,dt},$$

so that the derivative acts on the analytically known φ rather than on the measurement.
Weak forms have been developed systematically for exactly this purpose — identifying
dynamics from noisy measurements without differentiating them [Messenger & Bortz 2021] —
although here the construction is used only for rate estimation, not model selection. We
use φ(u) = (1 − u²)⁶ on a half-width of 1.5 h.

The same construction yields a composition-corrected mass-transfer proxy. Early in a
cycle the headspace is far from equilibrium and the physical term is approximately
k_La·p_CO₂ = k_La·f_CO₂·P, giving

$$\hat\kappa \;=\; \frac{\langle dP/dt\rangle_\varphi}{f_{\mathrm{CO_2}}\,\langle P\rangle_\varphi}.$$

The correction is not cosmetic. Without it, the 1:1 H₂:CO₂ campaign is indistinguishable
from the 5- and 10-minute recirculation settings, and a change in feed composition is
misread as a change in recirculation.

### 4.3 Control–Response Plane Partitioning (Alg. 3)

Attribution requires knowing which derived channels reflect *control configuration* and
which reflect *process response*. Prior work obtains this from controller-level
measurements [Iturbe et al. 2016]; with no controller log, it must be inferred.

A natural approach — testing each channel for independence from a process-state proxy —
fails here for a structural reason worth stating, because it constrains any method
operating on a single trace. Every candidate proxy derived from the same pressure record
shares endpoints with the candidate setpoint channels: the mass-transfer proxy carries
⟨P⟩ in its denominator, which is mechanically coupled to the refill ceiling, and the
normalized cycle shape carries (y₀ − y_end) in its denominator, which *is* the trigger
threshold. Correlation-based partitioning is therefore confounded by construction.

We instead partition on **time structure within each channel alone**, which admits no
cross-channel confounding. Two statistics are computed per channel:

* **Discreteness** — normalized entropy of the sensor-quantized values. A setpoint takes
  few discrete values; a process outcome is continuously distributed.
* **Persistence** — mean run length of identical quantized values, standardized against a
  permutation null that destroys temporal order.

Only channels expressed in the units the controller compares against are eligible: the
controller thresholds on pressure, so derived quantities (cycle duration in hours, κ in
h⁻¹) cannot be setpoints regardless of their statistics.

Applied to the three pressure-valued channels, the partition is unambiguous:

| Channel | Norm. entropy | Top-3 mass | Mean run | Null run | z | Plane |
|---|---|---|---|---|---|---|
| Trigger floor P_end | 0.449 | **64.7 %** | 1.60 | 1.23 | +11.1 | **Control** |
| Refill ceiling P₀ | 0.571 | 34.9 % | 1.39 | 1.07 | +19.5 | Response |
| Band width | 0.615 | 28.2 % | 1.24 | 1.05 | +13.7 | Response |

The partition recovers the trigger floor as the sole usable control channel. Its
practical value is measurable: treating the refill ceiling as a control channel as well
degrades downstream event classification from **3/4 to 2/4** on the known-event set of
Sect. 5.4.

We emphasize what this criterion does and does not identify. The equipment operator
confirmed that refill is terminated on pressure, which makes the ceiling a genuine
setpoint in the control architecture — Alg. 3 does not recover the architecture. What it
recovers is which channels are *usable* at the available sensor resolution. The ceiling's
realized value carries ±0.02 kg cm⁻² of overshoot jitter from actuation lag and
one-minute sampling; at a 0.01 kg cm⁻² quantum that is two LSBs, enough to defeat the
discreteness criterion. The operational conclusion generalizes: **when actuation noise
exceeds a few sensor LSBs, a genuine setpoint becomes unusable as a control channel, and
including it actively degrades attribution.**

### 4.4 Calibrated Change-Point Detection (Alg. 4)

Change points are located by exact optimal partitioning [Jackson et al. 2005] under a
penalty β; pruned variants [Killick et al. 2012] give the same segmentation at lower cost
and would be used in a streaming implementation. Three choices matter.

**Cost.** For control-plane channels the segment cost is the within-segment sum of
squares, which responds to mean shifts only. A variance-sensitive cost such as
n·log σ̂² reports "reconfigurations" across which the level is unchanged.

**Penalty.** β is calibrated **per channel** so that AR(1) surrogates matched to that
channel's lag-1 autocorrelation yield a change point with probability ≤ 0.05. A fixed
BIC-style β = 3 log n is not conservative on this data: AR(1) surrogates with φ = +0.57
produce up to 11 spurious change points against 18 observed.

**Minimum effect size.** A shift is retained only if the level changes by at least three
quantization steps (0.03 kg cm⁻²). This threshold is set by sensor resolution, not
chosen: a one-LSB movement of the refill ceiling coinciding with a recirculation change
was, before this filter, sufficient to trigger a spurious reconfiguration.

Where a channel is near-deterministic — piecewise constant and heavily quantized — the
AR(1) surrogate is misspecified and over-conservative, and we track the modal value
directly instead (Sect. 5.2). Change-point machinery is applied to the response plane,
where the signal is continuous and noisy, and withheld from the control plane, where it
is not.

### 4.5 Event Typology and Gap Masking (Alg. 5)

Detections are assigned to one of four classes:

| Class | Criterion | Interpretation |
|---|---|---|
| **Transient intervention** | isolated control-plane excursion that returns within two cycles (Hampel, 0.15 kg cm⁻²) | manual venting |
| **Persistent reconfiguration** | control-plane mean shift ≥ 3 LSB, sustained | setpoint change |
| **Process drift** | response-plane change only; control plane stable | reactor state change |
| **Recording artifact** | coincides with a > 3-day recording gap | not claimable |

The transient/persistent distinction is the pulse-versus-step dichotomy of intervention
analysis [Box & Tiao 1975]; the contribution here is its application to a control channel
that is itself reconstructed from the process variable.

The fourth class is not a refinement but a correctness requirement. Coverage is
discontinuous (Sect. 5.1), and change points falling at the resumption of recording are
recording discontinuities, not process events. Of 81 candidate detections at a fixed
penalty, 8 fell in gaps; after per-channel calibration, 5 of 69 did.

---

## 5 Results

### 5.1 Dataset and Coverage

The record spans 2025-08-16 to 2026-08-03 and yields **255 distinct cycles** after
deduplication, together with **1,219 refill events** resolved at the minute level. Feed
composition covers two settings (H₂:CO₂ = 4:1 and 1:1) and recirculation covers five
duty cycles (pump off; 1, 5, and 10 min h⁻¹; continuous 5-min operation).

Coverage within that span is discontinuous. Twelve gaps exceed three days, the longest
54.7 days, so the **351-day span contains 174 days of actual coverage (49 %)**. All
results below are reported against covered time, and detections coinciding with gap
boundaries are excluded by Alg. 5.

### 5.2 A Year of Trigger-Setpoint History

The refill starting pressure is a direct readout of the trigger threshold at the instant
the controller fires. Estimated as the modal value over non-overlapping windows of 15
refills, it resolves the setpoint to a fraction of the quantization step and is immune to
the minority of refills that follow a deep manual vent.

| Period | Setpoint (kg cm⁻²) | Modal-cluster share |
|---|---|---|
| 2025-08 | 1.22 | 17 % |
| 2025-09 | 0.97 | 9 % |
| 2025-10 | 0.72 | 49 % |
| 2025-11 – 2026-05 | **0.71** | 76–100 % |
| **2026-07 – 2026-08** | **0.92** | 56–78 % |

Eight setpoint changes exceeding the 3-LSB threshold are recovered. Seven fall in
2025-08 through 2025-10 and are accompanied by modal-cluster shares of 9–49 %, the
signature of a commissioning period in which no threshold was held. The eighth is
different: after 2025-10-28 the setpoint holds at 0.710 for thirteen consecutive
windows — roughly nine months — with 76–100 % of refills in the modal bin.

**That regime ends on 2026-07-11, when the trigger floor moves from 0.72 to 0.92 and
holds.** The change appears in no operating record. Two independent estimators agree.
From cycle-level end pressures, the monthly robust level is 0.71–0.73 for eight
consecutive months and 0.92 thereafter (Mann–Whitney, n₁ = 8, n₂ = 29, z = −3.73,
p = 1.9 × 10⁻⁴). From minute-level refill starting pressures — which do not pass through
cycle segmentation at all — the distribution shifts cleanly rather than becoming bimodal:

| Period | Cluster 0.60–0.80 | Cluster 0.85–1.00 |
|---|---|---|
| 2025-11 – 2026-05 (n = 159) | **89.3 %** | 0.6 % |
| 2026-07-11 – 08-04 (n = 44) | 4.5 % | **77.3 %** |

The distinction matters. Had automatic control continued unchanged with manual gas
additions superimposed — the explanation initially offered by the equipment operator —
both clusters would persist. Instead the 0.72 cluster essentially vanishes: the old
threshold stopped firing. The change is not a gap artifact; the preceding gap closes on
07-01, and refills on 07-01 through 07-08 still start at 0.71. (Fig. 3.)

### 5.3 A Year of Manual Interventions

Isolated deep excursions of the trigger floor, followed by immediate return, occur **18
times** across the record (7.1 % of cycles): 17 downward and 1 upward, with a median
depth of 0.40 kg cm⁻² against a local median that holds at 0.71–0.72. **The equipment
operator confirmed that these correspond to manual venting.** The detector had no access
to any venting record.

This is the pipeline's largest external validation, and it is independent of the
known-event set below.

### 5.4 Validation Against Known Events

Four process events are independently documented: a manual venting on 2026-04-07, the
start of a new campaign on 2026-07-22, and recirculation changes on 2026-07-27 and
2026-07-30. A fifth, the feed-composition change of 2026-01-09, is known from the
acquisition configuration.

**Detection is exact: 4/4, with 0–1 day error.** Classification is **3/4**. The single
disagreement is 2026-07-30, which the pipeline labels a transient intervention rather
than a process change. Two facts bear on it. A genuine vent did occur that day — the
trigger floor drops to 0.22 and returns — so the label is not unfounded; and the
recirculation change it was expected to capture produced no measurable response, with
κ moving from 0.1714 to 0.1686 between the 5- and 10-minute settings. The event set
assigns one label per day, and two events coincided.

### 5.5 Mass-Transfer State

Median values of the composition-corrected proxy order monotonically with recirculation
duty cycle across five conditions spanning both feed compositions:

| Condition | κ median | IQR | n |
|---|---|---|---|
| Pump off | 0.0954 | [0.0909, 0.1023] | 40 |
| 1 min h⁻¹ | 0.1065 | [0.1019, 0.1101] | 6 |
| 5 min h⁻¹ | 0.1659 | [0.1484, 0.1737] | 8 |
| Continuous 5 min | 0.1677 | [0.1345, 0.2192] | 16 |
| 10 min h⁻¹ | 0.1708 | [0.1653, 0.1782] | 12 |

The resolvable structure is a two-group separation rather than a five-level ordering
(Fig. 4). Low-duty operation (pump off, 1 min h⁻¹; medians 0.095 and 0.107) is clearly
separated from high-duty operation (5 min, continuous 5 min, 10 min h⁻¹; medians
0.166–0.171). Within the high-duty group the interquartile ranges overlap substantially
and the three settings are not distinguishable at this sample size, and the pump-off and
1 min h⁻¹ ranges themselves touch. We therefore claim the grouping and the ordering of
medians, not pairwise separation of all five conditions.

An independent contrast over the pump-off and pump-on periods of a single campaign gives
0.0187 versus 0.0449, a factor of 2.4, with non-overlapping cluster-bootstrap intervals.
This is the sharpest available statement of the recirculation effect.

Marginal returns fall sharply. Raising the duty cycle from 5 to 10 min h⁻¹ doubles pump
runtime and returns 8.8 % of the gain per minute obtained over the first minute. We
report this as a measured contrast rather than a functional law: with four conditions and
recirculation confounded with culture age — the reactor was not reinoculated — a fitted
saturation curve is not identifiable, and randomized within-batch alternation of the duty
cycle would be required to separate the two.

Absolute k_La is not claimed. The proxy is calibrated to no reference method, and the
literature records that different standard methods return different values on the same
vessel; the claim here is the ordering and its stability, which is what a state-tracking
application requires.

---

## Notes for the next pass

- **§5.4**: keep the 3/4 number in the text. It is the denominator for the Alg. 3 ablation
  in §4.3 and removing it would leave that comparison unsupported.
- **§5.1**: the 49 % coverage figure is load-bearing for §4.5's gap masking.
- Still needed: ORCIDs, grant number, English vector figures, and a gassing-out reference
  measurement if absolute k_La is ever to be claimed.
- **Citations: 7 entries DOI-verified via Crossref on 2026-08-06** — see
  `docs/paper/ICEA2026_references_verified.md`. Two year errors were corrected in the process
  (Iturbe 2017→2016, simplified DPM 2009→2010). Five statements in §2 still carry no
  citation and must be either sourced or rewritten before submission; they are listed in
  the same file.
