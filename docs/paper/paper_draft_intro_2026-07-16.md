**A Gas Utilization Prediction Model for Hydrogenotrophic Methanogens Under Pressure**

Cheng-Yu Lee¹\*, Chun-Hao Chen¹, Cheng-Yuan Hung²

¹ Department of Computer Science and Information Engineering, National Kaohsiung University of Science and Technology, Kaohsiung, Taiwan
² Optoelectronics Technology Division, Metal Industries Research & Development Centre, Kaohsiung, Taiwan

\* lkkyb555@gmail.com

> **Note on author names (please confirm before submission):** romanization of
> Chinese names follows Hanyu Pinyin convention here (Lee Cheng-Yu, Chen
> Chun-Hao, Hung Cheng-Yuan). Taiwanese authors sometimes use a different
> preferred spelling for the running head / author index (e.g. "Lee" vs "Li"
> for 李, "Hung" vs "Hong" for 洪) — please verify each co-author's preferred
> spelling before submission, since Springer names cannot be changed after
> publication (see template §3.3).

**Abstract.** Hydrogenotrophic methanogenesis (CO₂ + 4H₂ → CH₄ + 2H₂O) offers a biological route for upgrading biogas under pressure, but the CO₂ that disappears from the reactor headspace during operation is the combined result of two concurrent processes — physical dissolution into the liquid phase and biological consumption by the methanogen community — that cannot be separated from pressure alone. This paper builds on an edge-deployed pipeline (EMA/Savitzky-Golay signal conditioning, adaptive oxidation-reduction potential (ORP) phase detection, and a genetic algorithm-selected Ridge regression) that predicts per-cycle CH₄ peak concentration with a leave-one-out RMSE of 3.13%, using only ORP, pressure, and pH as continuous, trustworthy signals. This paper extends that pipeline to a mechanistically deeper target: separating the physically dissolved and biologically consumed fractions of injected CO₂ using only continuous ORP, pressure, and pH signals, without relying on the reactor's CO₂/CH₄ gas sensors, which we show are unsuitable for this purpose due to slow response and sampling-line lag. We formulate the separation as an underdetermined inverse problem and address it with a multi-objective heuristic search (NSGA-II) rather than a closed-form solution, and we report a factorial experimental design (circulation duration × intake dose, with reactor ORP phase treated as a noise factor) intended to supply the short-window ground truth this problem requires.

**Keywords:** Hydrogenotrophic Methanogenesis · Edge Computing · Oxidation-Reduction Potential · Multi-objective Optimization · Biogas Upgrading · Design of Experiments

## 1 Introduction

In-situ biological biogas upgrading via hydrogenotrophic methanogenesis has attracted growing interest as a route to convert CO₂ and externally supplied H₂ into CH₄ within an existing anaerobic digester, avoiding the capital cost of a separate upgrading unit. The reaction (CO₂ + 4H₂ → CH₄ + 2H₂O) proceeds in the liquid phase and is commonly operated under mild positive pressure to improve gas-liquid mass transfer, since the low aqueous solubility of H₂ is the principal rate-limiting step reported in the literature [CITATION NEEDED]. Existing characterizations of the methanogen strains involved, however, have largely examined the reaction at or near atmospheric pressure; the actively cycled, elevated-pressure regime central to the reactor system used in this work remains comparatively unexamined in the literature [CITATION NEEDED]. Monitoring such a system in real time is further complicated by the fact that the two gas-phase species of practical interest — CO₂ and CH₄ — are usually measured by a shared, discretely-sampled gas analyzer that only produces a reading at the moment of venting, rather than continuously.

The system used in this work sidesteps this limitation for a related, narrower prediction task, described fully in Section 2: given the oxidation-reduction potential (ORP) trajectory of a reactor cycle (gas injection to vent), an edge-deployed signal-conditioning and phase-detection pipeline segments the cycle into three biologically-motivated phases and predicts the cycle's CH₄ peak concentration with a leave-one-out cross-validated RMSE of 3.13% across six observed cycles. That pipeline remains the only part of the system that consumes the CO₂/CH₄ gas analyzer reading directly, and only as a single, sparse, end-of-cycle label.

This paper is motivated by a companion question raised during subsequent work on a pressure-based extension of that system: the reactor's pressure decline over a cycle reflects the sum of two physically distinct processes — CO₂ physically dissolving into the liquid phase, governed by Henry's law and driven by the imposed headspace pressure, and CO₂ actively consumed by the methanogen community as a growth substrate — and only the latter constitutes genuine "gas usage" in the sense relevant to predicting biological performance. Separating the two from pressure alone is not possible, since both processes reduce headspace pressure in the same direction. A companion analysis of approximately 600 historical CSV log files spanning eight months of prior reactor operation confirmed that the reactor's CO₂/CH₄ gas analyzer cannot supply the ground truth needed to calibrate such a separation directly: readings update only at manually timed venting events, are subject to several hours of sampling-line decay after each vent, and in several historical cycles yield internally inconsistent (negative) dissolved or consumed quantities when used in a straightforward mass-balance calculation. Oxidation-reduction potential, reactor pressure, and pH, by contrast, are logged every minute throughout operation and are the only signals available with sufficient continuity and reliability to support this separation.

The contribution of this paper is threefold. First, we show, using the historical operating data referenced above, that the separation of dissolved and consumed CO₂ cannot be recovered from a single continuous proxy signal (pH, or its chemically more appropriate hydrogen-ion-activity form) under any tested smoothing scale, and that the problem is more accurately framed as underdetermined rather than merely noisy: only the two end-of-cycle gas-analyzer readings constrain the total dissolved and consumed quantities over a full cycle, while the instantaneous decomposition within a cycle admits no unique solution from the available signals. Second, we formulate the separation as a multi-objective search over a small mechanistic model — CO₂ dissolution driven by the pH signal, and a residual gas-phase balance attributed to biological consumption, cross-validated against ORP as an independent proxy for methanogenic activity — and solve it with NSGA-II rather than a closed-form or regression-based estimator, since the underlying problem has no unique solution to regress toward. Third, we present a factorial experimental design (circulation duration and intake pressure range as controlled factors, reactor ORP phase treated as a noise factor per Taguchi's control/noise factor distinction) intended to collect short, deliberately timed observation windows that avoid the sampling and timing limitations identified in the historical data, providing the ground truth required to validate the proposed separation model.

## 2 System Architecture

This section describes the edge-computing pipeline developed as part of
this research program around a patented micro-pressure circulation reactor
for anaerobic methane fermentation [1]. The signal-conditioning and
phase-detection components below are reused directly as inputs to the
pressure-decomposition method introduced in Section 3. The pipeline
consists of three stages, deployed on a Jetson Orin Nano edge device and
connected to the reactor's monitoring PC via MQTT.

### 2.1 Signal Conditioning

The reactor's ORP electrode is subject to transient spikes caused by liquid agitation and passing gas bubbles. Raw one-per- minute readings are cleaned with a first-difference threshold to bridge spike artifacts, then smoothed with an exponential moving average (EMA, α = 2/(N+1), N = 10) for causal, real-time use, and separately with a Savitzky-Golay filter (window W = 11, polynomial order d = 2) for offline analysis where the non-causal lag of the EMA is undesirable.

### 2.2 Adaptive Phase Detection

Because injection pressure varies across runs
(observed range 0.896–1.5 kg/cm²), a fixed threshold on the ORP slope is not
portable across operating conditions. Instead, the slope statistics (μ, σ)
of the current cycle are used to set a dynamic threshold, segmenting each
cycle into three phases: Phase 1 (slope < μ − kσ, rapid ORP decline
following gas injection, interpreted as the onset of H₂/CO₂ consumption),
Phase 2 (μ − kσ ≤ slope ≤ μ + kσ, stable active methanogenesis), and
Phase 3 (slope > μ + kσ, ORP recovery as substrate is depleted). A 30-minute
debounce window prevents spurious phase switching from residual noise.

### 2.3 Feature Selection and Prediction

Eleven candidate features are derived
from the phase-segmented signal (e.g. cycle length, per-phase duration and
fraction, phase-3 onset fraction, mean pressure and pH per phase). A genetic
algorithm searches the 2¹¹ candidate feature subsets, using leave-one-out
cross-validated RMSE of a Ridge regression as its fitness function; on six
observed reactor cycles it converges within five generations to a five-
feature subset (cycle length, Phase 2 duration and fraction, Phase 3 onset
fraction, mean pressure), achieving RMSE = 3.13% for predicting the cycle's
CH₄ peak concentration, against RMSE = 10.17% for an untuned Random Forest
baseline on the same features.

This architecture is the only part of the overall system that consumes a
CO₂/CH₄ gas-analyzer reading, and only as a single value at the end of each
cycle; it does not require, and was not designed to exploit, any continuous
or intra-cycle CO₂/CH₄ signal. The remainder of this paper concerns a
separate question — the composition of the pressure decline observed
*within* a cycle — for which this existing pipeline supplies validated
signal-conditioning and phase-detection building blocks (Section 3) but not
a ready-made answer.

## References (in Basic style — incomplete, see notes)

1. Metal Industries Research and Development Centre: Micro-pressure circulation control system and method for anaerobic methane fermentation (in Chinese). Taiwan Invention Patent I923176 (2026)
2. [CITATION NEEDED — H₂ aqueous solubility as the rate-limiting step in hydrogenotrophic methanogenesis; three candidate papers were identified in earlier literature search but their full bibliographic details were not carried into this draft and need to be re-confirmed]
3. [CITATION NEEDED — ask Dr. Hung whether the foreign literature on the methanogen strain itself (confirmed to exist, but not under pressure) has a specific paper he can point to]

> **Note:** patent metadata above (grant status, patent no. I923176, term 2026-04-21 to
> 2044-12-02) is taken from the MIRDC 技轉園地 public listing shared 2026-07-16. Please
> verify the English title translation and citation format with Dr. Hung/MIRDC before
> submission, since this is the first formal citation of the patent in an academic paper.
