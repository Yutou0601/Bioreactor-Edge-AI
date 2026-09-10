# ICEA 2026 — §1–§3 ＋ §6–§8（英文正稿 draft 1）

**Paper**: *Edge-Side Pressure-Only Change-Point Mining Recovers Undocumented Setpoint
Changes and Manual Interventions in a Micro-Pressurized Recirculating Hydrogenotrophic
Biomethanation Reactor*

> Draft 1 — 2026-08-06. 與 `ICEA2026_paper_v2_sections4-5.md` 合併即為全文。
>
> **結構調整**：原骨架的 §6「可辨識性邊界」已移除。該節屬於舊主軸（生物速率估計）
> 的範圍，在本文的主軸下屬離題，且刪除後篇幅才排得進 LNCS 10 頁。
> 相關的範圍聲明壓縮為 §7 的兩段。

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
which layer moved first [Iturbe et al. 2016]. On a small edge-deployed reactor those
signals are not recorded. What is recorded is one pressure trace.

We show that the attribution can be recovered from that trace alone, and that doing so
yields an operating history the plant did not otherwise possess.

The vehicle is a micro-pressurized recirculating bioreactor for hydrogenotrophic
biomethanation (CO₂ + 4H₂ → CH₄ + 2H₂O), operated under a granted patent
(TW I923176). Its control loop admits gas when headspace pressure falls to a threshold,
then lets pressure decay as CO₂ dissolves and is consumed. Every refill is thus an
unforced step excitation, delivered about 2.2 times per day at no cost in downtime — and
the threshold that triggers it is a control parameter written into the pressure record
itself.

Our contributions are:

1. **A pressure-only mining pipeline** that reconstructs the control plane from the
   process variable, then attributes detected changes to control reconfiguration,
   transient intervention, or process drift. The plane-partitioning stage is what
   removes the controller-access assumption of prior attribution work, and its
   contribution is measurable: including a nominally-correct but noise-degraded control
   channel lowers classification accuracy from 3/4 to 2/4.
2. **A recovered year of operating history** from 255 cycles and 1,219 refill events:
   eight trigger-setpoint changes — including an undocumented reconfiguration on
   2026-07-11 confirmed by two independent estimators — and 18 manual venting events
   subsequently **confirmed by the equipment operator**.
3. **An edge-side cost characterization** showing that the binding constraint on this
   class of deployment is interpreter and library memory rather than computation, and
   quantifying the sampling change that would unlock further measurements at zero
   hardware cost.

---

## 2 Related Work

**Mass-transfer measurement.** Volumetric mass-transfer coefficients are conventionally
obtained by dedicated experiments — gassing-out, the dynamic method, or the dynamic
pressure method [Linek et al. 1989, 1994; Scargiali et al. 2010]. All require either a
deliberate perturbation or a production interruption, and a direct comparison of standard
methods on the same fermentation system reports that they do not agree
[Tobajas & García-Calvo 2000]. Our composition-corrected quantity is accordingly reported
as a proxy for *ordering* rather than as a calibrated coefficient.

**Attribution in process monitoring.** Assessing a control loop against a benchmark, and
separating setpoint tracking from disturbance rejection, is long-established
[Harris 1989; Jelali 2006]. Multivariate statistical process control has been extended to
monitor process-level and controller-level variables jointly so that the origin of an
anomaly can be identified [Iturbe et al. 2016, evaluated on the Tennessee-Eastman
simulator]. We adopt that framing and relax its instrumentation premise: no
controller-level variable is available to us, so the control plane is reconstructed from
the process variable and then verified to be usable (Sect. 4.3).

**Change-point detection and intervention analysis.** Exact optimal partitioning
[Jackson et al. 2005] and its pruned variants [Killick et al. 2012] are standard. The
distinction we draw between transient and persistent events is the pulse-versus-step
dichotomy of classical intervention analysis [Box & Tiao 1975]; our contribution is not
that dichotomy but its application to a control channel that is itself inferred, together
with the calibration and effect-size discipline that a quantized, gap-interrupted
production record requires.

**Data mining on bioprocess records.** Multivariate statistical analysis of batch and
bioprocess trajectories is established practice for detecting deviations
[Nomikos & MacGregor 1994]. Such work generally assumes a richly instrumented pilot or
manufacturing platform. The regime addressed here — one trustworthy variable, minute
resolution, sensor quantization comparable to the signal of interest, and roughly half
the calendar span missing — has not to our knowledge been treated as a mining target in
this application area.

---

## 3 Reactor, Signals and Data

**Device.** The reactor implements micro-pressurized recirculation under granted patent
TW I923176: headspace gas is periodically driven back into the liquid phase by a
circulation pump operating for τ minutes each hour. The patent also covers
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
**255 distinct cycles** and **1,219 refill events**. Feed composition covers H₂:CO₂ = 4:1
and 1:1; recirculation covers pump-off, τ = 1, 5, and 10 min h⁻¹, and a continuous
5-minute setting. Coverage is discontinuous: twelve gaps exceed three days and the
longest is 54.7 days, so the 351-day span contains 174 days of coverage.

Biological activity is established independently of any model: vented gas assayed
31.6–43.0 % CH₄.

---

## 6 Edge Deployment

The pipeline is intended to run on the monitoring workstation beside the reactor, which
has 4 GB of RAM shared with the acquisition and dashboard services; roughly **60 MB** is
available to an analysis process.

Computation is not the constraint. Streaming segmentation costs 0.1 µs per sample against
a 60-second sampling interval, and a per-cycle mass-transfer estimate with its standard
error costs 0.32 ms; at 2.2 cycles per day the daily analysis budget is under a
millisecond.

Memory is the constraint, and it is dominated by imports rather than by data. A cycle
buffer is 600 samples — under 5 kB. The reference implementation peaks at **330 MB**, of
which the scientific stack accounts for 129 MB (NumPy 27 MB; adding either pandas or
SciPy exhausts the budget on its own). A NumPy-only implementation of the pipeline stages
described here fits the 60 MB envelope; the reference implementation does not. We note
also that querying GPU availability through a deep-learning framework costs +307 MB —
five times the entire budget — where a `nvidia-smi` subprocess costs nothing persistent.

The practical conclusion for this class of deployment is that library selection, not
algorithm selection, determines feasibility.

---

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

---

## 8 Conclusion

A production reactor's own pressure log contains a recoverable operating history. From a
single quantized trace, with no controller-level signals and no additional
instrumentation, we recovered a year of trigger-setpoint history — eight changes,
including a nine-month stable regime that ends in an undocumented reconfiguration on
2026-07-11 supported by two independent estimators — together with 18 manual venting
events confirmed by the equipment operator, and a mass-transfer ordering that separates
low- from high-duty recirculation across five settings.

The step that makes this possible is reconstructing which observable channels carry
usable control information before attempting attribution, rather than assuming access to
the controller. Its value is measurable rather than asserted: admitting a nominally
correct but noise-degraded control channel halves the classification accuracy. The
governing quantity is the ratio of actuation noise to sensor resolution, which suggests
the criterion transfers to other threshold-controlled equipment.

---

## Notes for the next pass

- §2 citations require DOI verification before submission: Iturbe et al. (2017),
  Box & Tiao (1975), Linek et al. (1989, 1994), simplified DPM (2009).
- §6 workstation figures come from `edge_backend/edge_benchmark.py`; the 60 MB envelope
  is an operator-reported budget and should be attributed as such.
- §3 CH₄ assay range 31.6–43.0 % is from three vent readings; keep it as an existence
  statement only, never as a rate.
- Estimated length with §4–§5: ~4,300 words, within the LNCS 10-page envelope once
  figures and tables are placed.
