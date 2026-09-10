# Edge-Side Pressure-Only Change-Point Mining Recovers Undocumented Setpoint Changes and Manual Interventions in a Micro-Pressurized Recirculating Hydrogenotrophic Biomethanation Reactor

> **Full draft v2.0 — 2026-08-06.** Springer LNCS format, American English.
> Merged from `ICEA2026_paper_v2_sections1-3_6-8.md` and `ICEA2026_paper_v2_sections4-5.md`.
> Figures: `docs/paper_figures/` (captions in `CAPTIONS.md`).
> References: 12 entries, all DOI-verified — `ICEA2026_references_verified.md`.
> No funding statement and no ORCIDs — neither is mandatory for LNCS.

Cheng-Yu Li¹✉, Chun-Hao Chen¹, Cheng-Yuan Hung², and Yen-Jie Huang²

¹ Department of Computer Science and Information Engineering,
National Kaohsiung University of Science and Technology, Kaohsiung, Taiwan
² Optoelectronics Technology Division,
Metal Industries Research & Development Centre, Kaohsiung, Taiwan

✉ Corresponding author

**Running head:** *Pressure-Only Change-Point Mining at the Edge*

---

## Abstract

Industrial bioreactors are instrumented for control, not for observation. When a logged
variable changes, the operationally useful question is whether someone moved a setpoint,
someone intervened by hand, or the reactor itself drifted. Answering it normally requires
reading controller-level signals, which a small edge-deployed reactor does not record. We
show that the attribution can be recovered from a single quantized pressure trace. The
pipeline reconstructs which derived channels carry usable control information before
attributing change, using only each channel's own time structure, and then applies
per-channel calibrated change-point detection with a minimum effect size set by sensor
resolution. Applied to 255 cycles and 1,228 refill events spanning 351 days of a
micro-pressurized recirculating hydrogenotrophic biomethanation reactor, it recovers eight
trigger-setpoint changes — including an undocumented reconfiguration located to within
three days by two independent estimators — and 18 manual venting events subsequently
confirmed by the equipment operator, while detecting all four independently documented
process events to within one day. The plane-reconstruction stage is what removes the
controller-access assumption, and its contribution is measurable: admitting a nominally
correct but noise-degraded control channel lowers event classification from 3/4 to 2/4.
The governing quantity is the ratio of actuation noise to sensor resolution, which
suggests the criterion transfers to other threshold-controlled equipment. Computation is
negligible at 0.1 µs per sample; the binding edge constraint is library memory.

**Keywords:** process-state mining · change-point detection · bioreactor monitoring ·
edge computing · biomethanation

---

## 1 Introduction

Industrial bioreactors are instrumented for control, not for observation. A pressure
transducer exists so that a valve can be opened at the right moment; a pump duty cycle
exists so that gas is redissolved. Neither is placed to make the process observable. The
consequence is familiar to anyone who has tried to reconstruct what a reactor did last
quarter: the plant has logged millions of samples, and almost none of them have been
analyzed.

This is not a data-scarcity problem. It is an attribution problem. When a logged variable
changes, the question that matters operationally is *what changed* — did someone move a
setpoint, did someone intervene by hand, or did the reactor itself drift? Answering it
normally requires reading the controller: setpoints, valve states, and mode flags are
compared against process measurements, and the origin of an anomaly is inferred from
which layer moved first [2]. On a small edge-deployed reactor those signals are not
recorded. What is recorded is one pressure trace.

We show that the attribution can be recovered from that trace alone, and that doing so
yields an operating history the plant did not otherwise possess.

The vehicle is a micro-pressurized recirculating bioreactor for hydrogenotrophic
biomethanation (CO₂ + 4H₂ → CH₄ + 2H₂O), operated under a granted patent (TW I923176).
Its control loop admits gas when headspace pressure falls to a threshold, then lets
pressure decay as CO₂ dissolves and is consumed. Every refill is thus an unforced step
excitation, delivered 1.4 times per day averaged over covered time and 3.0 times per day
in the most recent campaign, at no cost in downtime — and the threshold that triggers it
is a control parameter written into the pressure record itself.

Our contributions are:

1. **A pressure-only mining pipeline** that reconstructs the control plane from the
   process variable, then attributes detected changes to control reconfiguration,
   transient intervention, or process drift. The plane-partitioning stage is what removes
   the controller-access assumption of prior attribution work, and its contribution is
   measurable: including a nominally-correct but noise-degraded control channel lowers
   classification accuracy from 3/4 to 2/4.
2. **A recovered year of operating history** from 255 cycles and 1,228 refill events:
   eight trigger-setpoint changes — including an undocumented reconfiguration in mid-July
   2026, located to within three days by two independent estimators — and 18 manual
   venting events subsequently **confirmed by the equipment operator**.
3. **An edge-side cost characterization** showing that the binding constraint on this
   class of deployment is interpreter and library memory rather than computation, and
   quantifying the sampling change that would unlock further measurements at zero
   hardware cost.

## 2 Related Work

**Mass-transfer measurement.** Volumetric mass-transfer coefficients are conventionally
obtained by dedicated experiments — gassing-out, the dynamic method, or the dynamic
pressure method [5, 6, 7]. All require either a deliberate perturbation or a production
interruption, and a direct comparison of standard methods on the same fermentation system
reports that they do not agree [8]. Our composition-corrected quantity is accordingly
reported as a proxy for *ordering* rather than as a calibrated coefficient.

**Attribution in process monitoring.** Assessing a control loop against a benchmark, and
separating setpoint tracking from disturbance rejection, is long-established [9, 10].
Multivariate statistical process control has been extended to monitor process-level and
controller-level variables jointly so that the origin of an anomaly can be identified
[2, evaluated on the Tennessee-Eastman simulator]. We adopt that framing and relax its
instrumentation premise: no controller-level variable is available to us, so the control
plane is reconstructed from the process variable and then verified to be usable
(Sect. 4.3).

**Change-point detection and intervention analysis.** Exact optimal partitioning [3] and
its pruned variants [4] are standard. The distinction we draw between transient and
persistent events is the pulse-versus-step dichotomy of classical intervention analysis
[1]; our contribution is not that dichotomy but its application to a control channel that
is itself inferred, together with the calibration and effect-size discipline that a
quantized, gap-interrupted production record requires.

**Data mining on bioprocess records.** Multivariate statistical analysis of batch and
bioprocess trajectories is established practice for detecting deviations [11]. Such work
generally assumes a richly instrumented pilot or manufacturing platform. The regime
addressed here — one trustworthy variable, minute resolution, sensor quantization
comparable to the signal of interest, and roughly half the calendar span missing — has
not to our knowledge been treated as a mining target in this application area.

## 3 Reactor, Signals and Data

**Device.** The reactor implements micro-pressurized recirculation under granted patent
TW I923176: headspace gas is periodically driven back into the liquid phase by a
circulation pump operating for τ minutes each hour (Fig. 1). The patent also covers
electrofermentation; **that capability was not enabled in any campaign reported here**,
no external potential was applied, and no conductive carbon electrode was installed.
Liquid temperature is controlled at 30 °C.

**Signals.** Four channels are trustworthy at production cadence: reactor pressure,
mixing-tank pressure, ORP, and pH. Headspace CO₂ and CH₄ are read by a gas analyzer that
updates only when the vessel is vented; 99.98 % of logged values are stale carry-forward,
and these channels are excluded from all analysis. Two column labels are transposed in
the acquisition schema — the field labelled *reactor pressure* is the mixing tank, and
the field labelled *mixing-tank pressure* is the reactor — and are corrected on ingest.

Pressure is sampled at one-minute intervals and quantized to 0.01 kg cm⁻². A cycle
traverses 1–5 quantization steps per hour, which is why every rate in this work is
obtained in weak form (Sect. 4.2).

**Data.** The record spans 2025-08-16 to 2026-08-03 across eight acquisition folders.
Folders overlap in time and are deduplicated on (start timestamp, duration), yielding
**255 distinct cycles** and **1,228 refill events** (2,353 raw pressure rises merged into
1,228 refills; 1,219 of these have a resolvable amplitude and are used wherever a rate is
computed). Feed composition covers H₂:CO₂ = 4:1
and 1:1; recirculation covers pump-off, τ = 1, 5, and 10 min h⁻¹, and a continuous
5-minute setting. Coverage is discontinuous: twelve gaps exceed three days and the
longest is 54.7 days, so the 351-day span contains 174 days of coverage.

Biological activity is established independently of any model: vented gas assayed
31.6–43.0 % CH₄.

## 4 Mining Pipeline

The reactor is instrumented for control, not for observation. Its edge controller logs a
single trustworthy state variable at one-minute resolution — headspace pressure,
quantized to 0.01 kg cm⁻² — and exposes no controller-level signals: setpoints, valve
states, and pump commands are not recorded. Prior work on separating operator-originated
from process-originated anomalies assumes access to controller variables [2]. That
assumption does not hold here. The pipeline below therefore reconstructs the control
plane from the process variable itself before attempting any attribution.

All five stages run on the logged pressure trace alone. No additional instrumentation,
no process model, and no labeled events are required.

### 4.1 Streaming Cycle Segmentation (Alg. 1)

Threshold-triggered refill partitions the record into *cycles*: a rapid pressure rise
when gas is admitted, followed by a slow decline as CO₂ dissolves and is consumed.
Segmentation exploits the resulting asymmetry. Over 1,228 refill events, the median rise
rate is 1.80 kg cm⁻² h⁻¹ and the monthly median ranges from 1.8 to 34.2, whereas the
decline proceeds at roughly 0.03 kg cm⁻² h⁻¹ — a separation of two to three orders of
magnitude at the median. The asymmetry is not uniform: the slowest 5 % of refills rise at
0.06 kg cm⁻² h⁻¹, only twice the decline rate, so the two populations are not perfectly
separated.

The detector is single-pass and keeps O(1) state: a running valley estimate, the index of
the current cycle start, and the previous sample. Cycles are emitted when the pressure
exceeds the running valley by more than 0.03 kg cm⁻², or when a recording discontinuity
exceeds one hour.

The rise threshold is the one tuned parameter, and we report its sensitivity rather than
asserting robustness (Table 1). Cycle count is stable to within 1.5 % across thresholds
of 0.05–0.20 kg cm⁻², but collapses at 0.02 where quantization noise is admitted as
refills. Our operating value of 0.03 sits on the shoulder of that plateau and yields 5 %
fewer cycles than the plateau itself; we retain it because it is the smallest value above
the noise floor, and all downstream results were checked to be unchanged in sign and
ordering at 0.05.

**Table 1.** Sensitivity of cycle count to the rise threshold.

| Rise threshold (kg cm⁻²) | 0.02 | **0.03** | 0.05 | 0.08 | 0.12 | 0.20 |
|---|---|---|---|---|---|---|
| Distinct cycles | 96 | **255** | 269 | 272 | 271 | 268 |

Because several archive folders overlap in time, cycles are **deduplicated on
(start timestamp, duration)** before any analysis. Deduplication is not incidental: in
the subset of equilibrium-reaching cycles it reduced 31 apparent cycles to 20 distinct
ones. Omitting this step inflates event counts and manufactures spurious change points at
folder boundaries.

### 4.2 Weak-Form Rate Estimation (Alg. 2)

Pressure is quantized to 0.01 kg cm⁻² and a typical cycle traverses only 1–5 quantization
steps per hour. Finite differences on such a record are dominated by quantization noise.
We therefore never differentiate the data. Instead, each rate is obtained in weak form:
the trace is multiplied by a compactly supported test function φ and integrated by parts,

$$\left\langle \frac{dP}{dt} \right\rangle_\varphi
= \frac{\int \dot\varphi(t)\,P(t)\,dt}{\int \varphi(t)\,dt},$$

so that the derivative acts on the analytically known φ rather than on the measurement.
Weak forms have been developed systematically for exactly this purpose — identifying
dynamics from noisy measurements without differentiating them [12] — although here the
construction is used only for rate estimation, not model selection. We use
φ(u) = (1 − u²)⁶ on a half-width of 1.5 h.

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
measurements [2]; with no controller log, it must be inferred.

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

Applied to the three pressure-valued channels, the partition is unambiguous (Table 2).

**Table 2.** Control–response partition of the pressure-valued channels.

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

Change points are located by exact optimal partitioning [3] under a penalty β; pruned
variants [4] give the same segmentation at lower cost and would be used in a streaming
implementation. Three choices matter.

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

Detections are assigned to one of four classes (Table 3).

**Table 3.** Event classes and their criteria.

| Class | Criterion | Interpretation |
|---|---|---|
| **Transient intervention** | isolated control-plane excursion that returns within two cycles (Hampel, 0.15 kg cm⁻²) | manual venting |
| **Persistent reconfiguration** | control-plane mean shift ≥ 3 LSB, sustained | setpoint change |
| **Process drift** | response-plane change only; control plane stable | reactor state change |
| **Recording artifact** | coincides with a > 3-day recording gap | not claimable |

The transient/persistent distinction is the pulse-versus-step dichotomy of intervention
analysis [1]; the contribution here is its application to a control channel that is
itself reconstructed from the process variable.

The fourth class is not a refinement but a correctness requirement. Coverage is
discontinuous (Sect. 5.1), and change points falling at the resumption of recording are
recording discontinuities, not process events. Of 81 candidate detections at a fixed
penalty, 8 fell in gaps; after per-channel calibration, 5 of 69 did.

## 5 Results

### 5.1 Dataset and Coverage

The record spans 2025-08-16 to 2026-08-03 and yields **255 distinct cycles** after
deduplication, together with **1,228 refill events** resolved at the minute level. Feed
composition covers two settings (H₂:CO₂ = 4:1 and 1:1) and recirculation covers five duty
cycles (pump off; 1, 5, and 10 min h⁻¹; continuous 5-min operation).

Coverage within that span is discontinuous. Twelve gaps exceed three days, the longest
54.7 days, so the **351-day span contains 174 days of actual coverage (49 %)**. All
results below are reported against covered time, and detections coinciding with gap
boundaries are excluded by Alg. 5.

### 5.2 A Year of Trigger-Setpoint History

The refill starting pressure is a direct readout of the trigger threshold at the instant
the controller fires. Estimated as the modal value over non-overlapping windows of 15
refills, it resolves the setpoint to a fraction of the quantization step and is immune to
the minority of refills that follow a deep manual vent (Fig. 2).

**Table 4.** Recovered trigger setpoint by period.

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

**That regime ends in mid-July 2026, when the trigger floor moves from 0.72 to 0.92 and
holds.** The change appears in no operating record. Two independent estimators support
it and place it within three days of each other: cycle-level end pressures locate it at
2026-07-11, and modal tracking of refill starting pressures at 2026-07-14, the latter
limited by its 15-refill window. We quote 2026-07-11 as the earlier and more finely
resolved of the two.

From cycle-level end pressures, the monthly robust level is 0.71–0.73 for eight
consecutive months and 0.92 thereafter (Mann–Whitney, n₁ = 8, n₂ = 29, z = −3.73,
p = 1.9 × 10⁻⁴). From minute-level refill starting pressures — which do not pass through
cycle segmentation at all — the distribution shifts cleanly rather than becoming bimodal
(Table 5, Fig. 3).

**Table 5.** Refill starting pressure by cluster, before and after 2026-07-11.

| Period | Cluster 0.60–0.80 | Cluster 0.85–1.00 |
|---|---|---|
| 2025-11 – 2026-05 (n = 159) | **89.3 %** | 0.6 % |
| 2026-07-11 – 08-04 (n = 44) | 4.5 % | **77.3 %** |

The distinction matters. Had automatic control continued unchanged with manual gas
additions superimposed — the explanation initially offered by the equipment operator —
both clusters would persist. Instead the 0.72 cluster essentially vanishes: the old
threshold stopped firing. The change is not a gap artifact; the preceding gap closes on
07-01, and refills on 07-01 through 07-08 still start at 0.71.

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

We report two evaluations, because the ablation of Sect. 4.3 and the final method were
measured on different event sets, and conflating them would overstate either.

**Two-class variant, four-event set.** Assigning every detection to either
reconfiguration or drift, and evaluating against all four documented events, detection is
**4/4 with 0–1 day error**. Classification is **3/4** with the plane partition of
Sect. 4.3 and **2/4** without it — this is the ablation quoted earlier.

**Final three-class method, three-event set.** The manual venting of 2026-04-07 is
excluded here: it coincides with a 2.4× step in the mass-transfer proxy, so its ground
truth is genuinely ambiguous between intervention and drift, and scoring it either way
would be arbitrary. On the remaining three events, detection is **3/3** and
classification **2/3**.

The single disagreement in the three-class evaluation is 2026-07-30, labeled a transient
intervention rather than a process change. Two facts bear on it. A genuine vent did occur
that day — the trigger floor drops to 0.22 and returns — so the label is not unfounded;
and the recirculation change it was expected to capture produced no measurable response,
with κ moving from 0.1714 to 0.1686 between the 5- and 10-minute settings. The event set
assigns one label per day, and two events coincided.

### 5.5 Mass-Transfer State

Median values of the composition-corrected proxy order monotonically with recirculation
duty cycle across five conditions spanning both feed compositions (Table 6, Fig. 4).

**Table 6.** Composition-corrected mass-transfer proxy by recirculation setting.

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

Absolute k_La is not claimed. The proxy is calibrated to no reference method, and a
direct comparison of standard methods reports that they disagree on the same system [8];
the claim here is the ordering and its stability, which is what a state-tracking
application requires.

## 6 Edge Deployment

The pipeline is intended to run on the monitoring workstation beside the reactor, which
has 4 GB of RAM shared with the acquisition and dashboard services; roughly **60 MB** is
available to an analysis process, as reported by the operator.

Computation is not the constraint. Streaming segmentation costs 0.1 µs per sample against
a 60-second sampling interval, and a per-cycle mass-transfer estimate with its standard
error costs 0.32 ms; at fewer than three cycles per day the daily analysis budget is under
a millisecond.

Memory is the constraint, and it is dominated by imports rather than by data. A cycle
buffer is 600 samples — under 5 kB. The reference implementation peaks at **330 MB**, of
which the scientific stack accounts for 129 MB (NumPy 27 MB; adding either pandas or
SciPy exhausts the budget on its own). A NumPy-only implementation of the pipeline stages
described here fits the 60 MB envelope; the reference implementation does not. We note
also that querying GPU availability through a deep-learning framework costs +307 MB —
five times the entire budget — where an `nvidia-smi` subprocess costs nothing persistent.

The practical conclusion for this class of deployment is that library selection, not
algorithm selection, determines feasibility.

## 7 Limitations and Future Work

**Coverage and attribution.** Half the calendar span is unrecorded, and detections at the
resumption of recording are recording discontinuities rather than process events; these
are excluded rather than interpreted (Sect. 4.5). Classification of known events is 3/4,
with the single disagreement arising where two events coincided on one day.

**Scope of the mass-transfer claim.** We report ordering and stability, not calibrated
k_La. Establishing an absolute coefficient requires one gassing-out reference measurement
against this vessel. Separately, recirculation duty cycle is confounded with culture age
and liquid-phase saturation, because the reactor was not reinoculated during the
campaigns; randomized within-batch alternation of τ would break that collinearity at no
material cost.

**What a single pressure trace cannot support.** The pipeline attributes *changes*; it
does not resolve the reactor's physical and biological rates into separate components.
Under headspace pressure alone the biological consumption rate is not identified, and
standard practice for that separation relies on a dissolved-gas probe. This is an
observability limit rather than a modeling one, and we make no claim on that quantity.

**Sampling.** Refill transients are informative in principle — at fixed gas flow the rise
rate is inversely proportional to headspace volume, which would give a level measurement
with no level sensor — but a refill completes within one sampling interval for 67 % of
events, so its duration is censored rather than resolved. Sampling at 5–10 s during
refill only, a logging-configuration change with no hardware cost, would yield 6–12
samples per transient and make this measurement available.

**Deployment.** Only the batch pipeline has been characterized. A streaming
implementation and the NumPy-only rewrite required by the 60 MB envelope remain to be
built.

## 8 Conclusion

A production reactor's own pressure log contains a recoverable operating history. From a
single quantized trace, with no controller-level signals and no additional
instrumentation, we recovered a year of trigger-setpoint history — eight changes,
including a nine-month stable regime that ends in an undocumented reconfiguration in
mid-July 2026, located to within three days by two independent estimators — together
with 18 manual venting
events confirmed by the equipment operator, and a mass-transfer ordering that separates
low- from high-duty recirculation across five settings.

The step that makes this possible is reconstructing which observable channels carry
usable control information before attempting attribution, rather than assuming access to
the controller. Its value is measurable rather than asserted: admitting a nominally
correct but noise-degraded control channel halves the classification accuracy. The
governing quantity is the ratio of actuation noise to sensor resolution, which suggests
the criterion transfers to other threshold-controlled equipment.

---

## References

1. Box, G.E.P., Tiao, G.C.: Intervention analysis with applications to economic and
   environmental problems. J. Am. Stat. Assoc. **70**(349), 70–79 (1975).
   `10.1080/01621459.1975.10480264`
2. Iturbe, M., Camacho, J., Garitano, I., Zurutuza, U., Uribeetxeberria, R.: On the
   feasibility of distinguishing between process disturbances and intrusions in process
   control systems using multivariate statistical process control. In: 2016 46th Annual
   IEEE/IFIP International Conference on Dependable Systems and Networks Workshop
   (DSN-W), pp. 155–160. IEEE (2016). `10.1109/dsn-w.2016.32`
3. Jackson, B., Scargle, J.D., Barnes, D., Arabhi, S., Alt, A., Gioumousis, P., Gwin, E.,
   San, P., Tan, L., Tsai, T.T.: An algorithm for optimal partitioning of data on an
   interval. IEEE Signal Process. Lett. **12**, 105–108 (2005). `10.1109/lsp.2001.838216`
4. Killick, R., Fearnhead, P., Eckley, I.A.: Optimal detection of changepoints with a
   linear computational cost. J. Am. Stat. Assoc. **107**(500), 1590–1598 (2012).
   `10.1080/01621459.2012.737745`
5. Linek, V., Beneš, P., Vacek, V.: Dynamic pressure method for kLa measurement in
   large-scale bioreactors. Biotechnol. Bioeng. **33**(11), 1406–1412 (1989).
   `10.1002/bit.260331107`
6. Linek, V., Moucha, T., Doušová, M., Sinkule, J.: Measurement of kLa by dynamic
   pressure method in pilot-plant fermentor. Biotechnol. Bioeng. **43**, 477–482 (1994).
   `10.1002/bit.260430607`
7. Scargiali, F., Busciglio, A., Grisafi, F., Brucato, A.: Simplified dynamic pressure
   method for kLa measurement in aerated bioreactors. Biochem. Eng. J. **49**(2),
   165–172 (2010). `10.1016/j.bej.2009.12.008`
8. Tobajas, M., García-Calvo, E.: Comparison of experimental methods for determination of
   the volumetric mass transfer coefficient in fermentation processes. Heat Mass Transf.
   **36**, 201–207 (2000). `10.1007/s002310050385`
9. Harris, T.J.: Assessment of closed loop performance. Can. J. Chem. Eng. **67**,
   856–861 (1989). `10.1002/cjce.5450670519`
10. Jelali, M.: An overview of control performance assessment technology and industrial
    applications. Control Eng. Pract. **14**(5), 441–466 (2006).
    `10.1016/j.conengprac.2005.11.005`
11. Nomikos, P., MacGregor, J.F.: Monitoring batch processes using multiway principal
    component analysis. AIChE J. **40**(8), 1361–1375 (1994). `10.1002/aic.690400809`
12. Messenger, D.A., Bortz, D.M.: Weak SINDy for partial differential equations.
    J. Comput. Phys. **443**, 110525 (2021). `10.1016/j.jcp.2021.110525`

---

## Figures

| Ref | File | Caption |
|---|---|---|
| Fig. 1 | `paper_figures/fig1_pipeline.pdf` | System and mining pipeline |
| Fig. 2 | `paper_figures/fig2_setpoint_history.pdf` | Recovered trigger-setpoint history |
| Fig. 3 | `paper_figures/fig3_bimodality.pdf` | Refill starting pressure, before/after |
| Fig. 4 | `paper_figures/fig4_masstransfer.pdf` | Mass-transfer proxy by duty cycle |

Full captions in `paper_figures/CAPTIONS.md`.

## Submission checklist

- [x] All 12 references DOI-verified via Crossref
- [x] Figures: vector PDF, 122 mm, Type 42 fonts, grayscale-legible
- [x] Author affiliations confirmed
- [x] No funding statement (none to declare — not mandatory for LNCS)
- [x] No ORCIDs (not mandatory for LNCS)
- [x] Numeric audit against source scripts (2026-08-06) — corrections listed below
- [ ] Convert to LNCS LaTeX (`llncs.cls`, `splncs04.bst`)
- [ ] Word count against the 10-page limit after typesetting (~4,900 words + 6 tables + 4 figures)
- [ ] Confirm whether patent TW I923176 requires a rights note

## Numeric audit — corrections applied 2026-08-06

Every quantity was re-derived from the source scripts. Six statements were wrong or
imprecise and have been corrected:

| Claim as first written | Corrected to | Why |
|---|---|---|
| "any threshold yields the same segmentation, so the stage is effectively parameter-free" | Sensitivity table (Table 1) + explicit statement that 0.03 sits 5 % below the plateau | **Untested assertion, and false**: cycle count collapses from ~270 to 96 at a 0.02 threshold |
| rise rate "1.8–13.6", separation "60–450×" | median 1.80, monthly medians 1.8–34.2, plus the caveat that the slowest 5 % rise at only 0.06 | Range understated, and the overlap with the decline population was hidden |
| "2.2 cycles per day" | 1.4 per day over covered time; 3.0 per day in the most recent campaign | 2.2 was the rate of one earlier campaign, not the record |
| "1,219 refill events" | 1,228 merged refills; 1,219 with resolvable amplitude | Two scripts used different filters |
| "reconfiguration on 2026-07-11 confirmed by two estimators" | mid-July 2026, located to within three days (07-11 and 07-14) | The two estimators agree on existence and direction, not on the exact day |
| "4/4 detection, 3/4 classification" quoted for the three-class method | Both evaluations reported separately with their event sets | The ablation was measured on the two-class variant over four events; the final three-class method scores 3/3 and 2/3 over three events |
| "in one folder pair this reduced 31 cycles to 20" | in the equilibrium-reaching subset | Misattributed which subset the figure came from |
