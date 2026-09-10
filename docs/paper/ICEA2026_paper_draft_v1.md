> # ⚠️ 本稿已作廢（2026-08-06）— 主結果被自己的檢驗推翻
>
> **不要以本稿投稿。** 題目承諾的「聯合估計出生物速率 r_b」不成立：
> Algorithm 4（設定誤差虛無檢定）以**雙指數模型 r_b ≡ 0** 當真相產生虛無資料，
> **回收出 100% 的實測值**（無噪聲 0.01099 vs 實測 0.01104，**p = 0.40**）；
> 完整管線對真值為零的資料判定顯著 **5/5**。十種方法失敗形態一致，
> 根因是**只有頂空壓力、缺溶解氣體電極**——觀測不足，換方法救不回來。
>
> **現行論文**：`docs/paper/ICEA2026_論文骨架_v2_資料探勘_2026-08-06.md`
> 題目 *Edge-Side Pressure-Only Change-Point Mining Recovers Undocumented
> Setpoint Changes and Manual Interventions in a Micro-Pressurized
> Recirculating Hydrogenotrophic Biomethanation Reactor*
>
> **本稿仍可回收的三塊**（不要整份丟）：
> | 本稿章節 | 搬去新論文 |
> |---|---|
> | §5.3 + Table 6 + Algorithm 4 | 新 §6 可辨識性邊界 |
> | §6 部署成本（330 MB vs 60 MB、203×） | 新 §7 Edge Deployment |
> | §7 Scope 聲明 | 新 §8 Limitations |
>
> 成果現況總表：`docs/analysis/目前貢獻與成果總表_2026-08-06.md`

---

# ~~Bootstrap-Calibrated Joint Parameter Estimation from Threshold-Triggered Pressure Relaxations in Hydrogenotrophic Biomethanation~~（作廢）

> **Draft v1.2 — 2026-08-05.** Springer proceedings format. American English.
> Running head suggestion: *Bootstrap-Calibrated Joint Estimation*
> Short author form for running head: *C.-Y. Li et al.*

Cheng-Yu Li¹✉, Chun-Hao Chen¹, Cheng-Yuan Hung², and Yen-Jie Huang²

¹ Department of Computer Science and Information Engineering,
National Kaohsiung University of Science and Technology, Kaohsiung, Taiwan
² Optoelectronics Technology Division,
Metal Industries Research & Development Centre, Kaohsiung, Taiwan

*[Affiliation of Y.-J. Huang to be confirmed — listed under ² provisionally.]*

✉ Corresponding author: `lkkyb555@gmail.com`

---

**Abstract.** In a threshold-triggered biomethanation reactor, every automatic gas refill initiates a closed-headspace pressure relaxation, so routine production yields a continuous sequence of identification experiments—2.2 per day at zero production interruption. We use 26 such relaxations, spanning three circulation-time settings on a patented micro-pressure recirculating reactor, to estimate gas–liquid mass transfer and biological gas consumption jointly. We first show that the conventional two-stage apparent-parameter regression used for this decomposition is severely biased: on synthetic data generated with the biological rate fixed at zero, it recovers a spurious rate of 0.0187 kg cm⁻² h⁻¹, *larger* than the 0.0143 measured on real data, despite an apparent correlation of r = −0.935 (p = 2.6 × 10⁻¹²). A single-step joint estimator reduces this bias by 96% and yields 0.0110 ± 0.0013 kg cm⁻² h⁻¹, significant against that null. We then show the qualifier matters: the null is generated from the same single-exponential model the estimator assumes, and replacing it with a better-fitting biexponential that contains no biological sink reproduces the reported rate in full (0.01099, p = 0.40), while the complete pipeline returns "significant" on data whose true rate is zero in five trials of five. The biological rate is therefore not identified from headspace pressure alone—biological activity itself being established independently by vent methane of 31.6–43.0%. The transferable result is that a resampling calibration built on the fitted model certifies the estimator, not the model class. On-device, that calibration costs roughly 200× a single estimate, is embarrassingly parallel (5.7–6.2× on multicore), and never touches the GPU.

**Keywords:** Edge computing · Parameter identification · Bootstrap calibration · Estimation bias · Biomethanation · Identification from routine operating data

---

## 1 Introduction

Edge devices increasingly perform local parameter estimation rather than merely forwarding raw measurements. Where the plant's own controller perturbs the process on a regular schedule, those perturbations are free excitation: no dedicated experiment is required, and the identifying information arrives as a by-product of production. Exploiting it, however, demands an estimator whose output can be trusted. Once an estimate leaves the device, downstream consumers treat it as fact—yet the computational cost of establishing that an estimate is not an artifact, as opposed to merely producing it, is rarely measured, and the consequences of skipping that step are rarely quantified.

We study this question on a concrete edge deployment: a micro-pressure recirculating bioreactor in which hydrogenotrophic methanogens convert CO₂ and H₂ into CH₄. The headspace pressure falls for two reasons at once—CO₂ physically dissolving into the liquid, and the microbial community consuming gas—and the practical question is how much of the decline each channel contributes. A widely suggested route is to exploit the circulation time as a lever: the mass-transfer coefficient *k*_La depends on circulation, whereas the biological rate *r*_b should not, so fitting an apparent saturation pressure per condition and regressing it against 1/*k*_La should recover both. We show that this two-stage procedure, applied to data of this kind, manufactures an artifact of the same sign and the same magnitude as the effect it purports to measure.

The edge setting is not incidental. Gas-phase concentration sensors on this reactor only register a reading during venting and cannot capture the true peak, leaving pressure, oxidation–reduction potential (ORP), and pH as the only trustworthy signals. More importantly, the identifying information itself is generated by the controller: every automatic refill initiates a closed-headspace relaxation transient. Capturing those transients requires continuous on-site observation, which is precisely what an edge device provides.

This paper makes three contributions.

1. We quantify the bias of two-stage apparent-parameter regression on the physical–biological separation problem, and show that the resulting artifact exceeds the measured effect—invalidating the circulation-time lever as commonly implemented.
2. We give a single-step joint estimator together with a parametric-bootstrap calibration protocol, reduce the bias by 96%, and report the first bias-calibrated biological rate for this reactor class.
3. We measure the on-device cost of that calibration across hardware platforms, showing it to be CPU-bound, GPU-irrelevant, embarrassingly parallel, and schedulable within the idle interval between refills.

> **Fig. 1.** System architecture: sensors → edge ingestion → streaming cycle segmentation → joint estimation → bootstrap calibration gate → upstream reporting. *(to be drawn; see §D of the companion checklist)*

## 2 Related Work

**Two-Stage Versus Joint Estimation.** That a two-stage procedure—fit each unit separately, then model the fitted parameters—inflates variance and biases downstream inference relative to single-step population estimation has been established in population pharmacokinetics since the 1980s; the standard two-stage approach can overestimate variability several-fold [1]. Our contribution is not to rediscover this, but to quantify its magnitude on the physical–biological separation problem and to show that it invalidates a separation scheme that would otherwise appear decisively supported.

**Gas–Liquid Mass Transfer in Biomethanation.** Hydrogen gas–liquid mass transfer is the accepted rate-limiting step for hydrogenotrophic methanogenesis [2], and pressurized operation near 2.2 bar with H₂:CO₂ = 80:20 is established practice [3]. The reactor studied here operates at a comparable absolute pressure; what differs is the threshold-triggered cyclic refill rather than continuous flow.

**Identification from Routine Operating Data.** Closed-loop system identification from routine operating data, without dedicated excitation, is mature in the process industries [4]. We are not aware of its application to separating mass-transfer from biological consumption in a bioreactor.

**Machine Learning for Anaerobic Digestion.** Recurrent models for biogas prediction are well developed, and recent work compares them directly against the ADM1 mechanistic model [9], finding random forests and LSTMs competitive with simplified ADM1 while requiring far less substrate characterization—at the cost of a training time two orders of magnitude larger [5]. Accordingly, the neural results reported here serve only to verify deployability; they are not claimed as a contribution.

## 3 Apparatus and Data

The reactor is a granted invention patent of the Metal Industries Research & Development Centre [10]. Its controller fills the headspace to 1.2 kg cm⁻² (gauge) and refills automatically once the pressure decays to 0.9 kg cm⁻², repeating indefinitely.

**Table 1.** Reactor configuration and the subset of patented functions used in this study.

| Item | Setting |
|---|---|
| Micro-pressure recirculation | Enabled (fill 1.2 → refill at 0.9 kg cm⁻², gauge) |
| Feed gas ratio H₂:CO₂ | 4:1, fixed |
| Temperature | 30 °C, fixed |
| Circulation time τ | 1 / 5 / 10 min per hour (only varied factor) |
| Electro-fermentation (applied potential) | Not enabled |
| Conductive carbon | Not installed |
| Edge signals used | Reactor pressure, ORP, pH (1-min sampling) |

The patent also covers electro-fermentation, which was **not** enabled in this study: no potential or current was applied and no conductive carbon was installed. This distinction matters for signal interpretation, because an applied potential in the liquid would dominate the ORP electrode reading rather than the hydrogen redox couple. The data are consistent with a free-floating electrode: ORP drops by more than 100 mV at each refill and then recovers freely, ranging continuously between 230 and 686 mV over the campaign, whereas a potentiostatically controlled electrode would be pinned near its setpoint.

**Table 2.** Three fixed-protocol batches, 2026-07-22 to 2026-08-03.

| Batch | τ (min h⁻¹) | Duration (h) | Cycles analyzed | Mean decline rate (kg cm⁻² h⁻¹) |
|---|---|---|---|---|
| 1.1 | 1 | 114.5 | 6 | 0.0178 |
| 2.1 | 5 | 71.7 | 8 | 0.0361 |
| 3.1 | 10 | 96.0 | 12 | 0.0388 |

The campaign comprises 33,573 one-minute records. Twenty-six complete cycles enter the analysis; the terminal cycle of each batch (truncated by venting) and cycles whose pressure drop falls outside 0.15–0.35 kg cm⁻² are excluded.

## 4 Method

### 4.1 Two-Channel Model

For a closed headspace, the pressure declines through physical dissolution and biological consumption:

  d*P*/d*t* = −*k*_La (*P* − *P*_eq) − *r*_b   (1)

whose solution is a single exponential with apparent saturation pressure

  *P*_eq′ = *P*_eq − *r*_b / *k*_La   (2)

Equation (2) is the basis of the circulation-time lever: if *k*_La varies with τ while *r*_b does not, then *P*_eq′ plotted against 1/*k*_La should be a straight line of slope −*r*_b and intercept *P*_eq. This is the procedure we examine.

### 4.2 Streaming Cycle Segmentation

Cycles are extracted online, one sample at a time, with constant memory (Algorithm 1).

```
Algorithm 1  Streaming cycle segmentation
Input : pressure stream p[t]; rise threshold δ = 0.03 kg/cm²;
        gap tolerance G = 30 min; refill merge window W = 20 min
Output: cycles, each spanning refill peak → decline valley

 1  valley ← p[0];  t_prev ← 0
 2  for each incoming sample p[t]:
 3      if t − t_prev > G:                  # recording interruption
 4          close current cycle; reset state
 5      if p[t] − valley > δ:               # refill edge detected
 6          if within W of the previous edge: extend current refill
 7          else: close current cycle; open a new one
 8          valley ← p[t]
 9      else if p[t] < valley:
10          valley ← p[t]                   # track running minimum
11      t_prev ← t
```

Three design choices are load-bearing. The 30-minute interruption threshold replaces a stricter 5-minute rule that misclassified benign logging pauses as interruptions and discarded otherwise valid cycles. The 20-minute merge window accommodates refills that ramp over ten or more minutes, which would otherwise be split into several spurious events. Finally, the decline segment terminates at the running minimum rather than at the next peak; terminating at the peak places the endpoint on the rising edge and severely underestimates the decline rate.

### 4.3 Single-Step Joint Estimation

Rather than fitting each batch independently and regressing the results, we determine all parameters under one objective (Algorithm 2). The mass-transfer coefficient is free per batch, while *P*_eq and *r*_b are shared across all three—the constraint that the two-stage procedure lacks.

```
Algorithm 2  Joint estimation across batches
Input : cycles grouped by batch i ∈ {1, 5, 10 min}; bounds B
Output: θ = (k_La,1 , k_La,2 , k_La,3 , P_eq , r_b)

 1  minimize  Σ_i Σ_{j ∈ cycles(i)} Σ_t [ P_ij(t) − P̂(t; k_La,i , P_eq , r_b , P_ij(0)) ]²
 2      subject to θ ∈ B
 3  stage 1: L-BFGS-B from initial point p₀
 4  stage 2: Nelder–Mead refinement, with the same bounds B
```

Two implementation choices matter. First, the bounds must be supplied to the refinement stage as well as the initial stage. Omitting them is a reproducible failure mode: the simplex escapes the feasible region and returns solutions such as *k*_La ≈ 2 × 10⁹ with a compensating saturation pressure, which fit the data no better but are physically meaningless. Second, the two-stage local scheme is preferred over a global search: differential evolution converges to the same optimum but costs 35–39× more (5.50 s versus 0.155 s per fit on the workstation of Sect. 6), which is prohibitive once the fit is nested inside 200 bootstrap replicates.

### 4.4 Parametric Bootstrap Calibration

To decide whether an estimated *r*_b is distinguishable from an artifact, we generate synthetic data under the null hypothesis *r*_b ≡ 0 and pass it through the identical estimator (Algorithm 3). The procedure is a parametric bootstrap [7] in which residuals are resampled in blocks [8] rather than pointwise.

```
Algorithm 3  Bootstrap calibration of the null
Input : data D; estimator Ê; replicates B = 200; block length L = 60 min
Output: null distribution of r_b under H₀ : r_b ≡ 0

 1  θ₀ ← fit D with r_b fixed at 0
 2  ρ_ij ← P_ij − model(θ₀)                 # residuals, per cycle
 3  for b = 1 … B:
 4      for each cycle ij:
 5          ρ* ← resample ρ_ij in blocks of L      # preserve autocorrelation
 6          D*_ij ← model(θ₀) + ρ*
 7          quantize D*_ij to 0.01 kg/cm²          # match sensor resolution
 8      r_b^(b) ← Ê(D*)
 9  p ← #{ r_b^(b) ≥ r̂_b } / B
```

Two details matter. Residuals are resampled in 60-minute blocks rather than pointwise, so that the synthetic series retain the autocorrelation of the originals; pointwise resampling would produce an unrealistically narrow null and an over-optimistic test. Synthetic pressures are re-quantized to the sensor resolution, so that the null and the observation face identical measurement granularity. Because the residuals may themselves contain real biological signal, this null is if anything inflated, making the resulting test conservative.

## 5 Results

### 5.1 The Conventional Estimator Fails Its Own Null

Applying the two-stage procedure to the 26 cycles yields what appears to be overwhelming support (Table 3, left). Running the identical procedure on synthetic data generated with *r*_b ≡ 0 recovers a median spurious rate of 0.0187 kg cm⁻² h⁻¹—larger than the 0.0143 obtained from the real data.

**Table 3.** Two-stage apparent-parameter regression against its own null (B = 200).

| Quantity | Observed | Null (*r*_b ≡ 0) |
|---|---|---|
| Correlation of *P*_eq′ with 1/*k*_La | r = −0.935 | — |
| p-value of that correlation | 2.6 × 10⁻¹² | — |
| Recovered *r*_b (kg cm⁻² h⁻¹) | 0.0143 | median 0.0187; 95th pct 0.0276 |
| p against the null | — | **0.735** |

The mechanism is a correlated estimation error. When the pressure trajectory is close to linear over the observation window—as it is here, since the cycle spans well under one time constant—*k*_La and *P*_eq trade off along a ridge in the likelihood surface—a practical non-identifiability in the sense of [6]—and their estimation errors are positively correlated. Projected onto the *P*_eq′ versus 1/*k*_La plane, that correlation reproduces the sign of the true physical relationship. The regression therefore cannot distinguish signal from fitting geometry, and its nominal p-value of 2.6 × 10⁻¹² carries no evidential weight.

### 5.2 Joint Estimation Is Nearly Unbiased—Against a Null Drawn From Its Own Model

**Table 4.** Bias of the two estimators on identical *r*_b ≡ 0 synthetic data, generated from the single-exponential model.

| Estimator | Recovered *r*_b, median | 95th pct | Max | Bias reduction |
|---|---|---|---|---|
| Two-stage regression | 0.01872 | 0.02757 | — | — |
| Single-step joint | **0.00075** | 0.00515 | 0.00826 | **96%** |

The observed estimate, *r̂*_b = 0.01104, exceeds the maximum of that null distribution over 200 replicates, giving p < 0.005. Section 5.3 shows why this statement must be read with its qualifier: the null of Table 4 is generated from the *same* single-exponential model that the estimator assumes, so it can certify the estimator but not the model.

**Table 5.** Parameters conditional on the single-exponential model, with two measures of uncertainty.

| Parameter | Value | Uncertainty to quote | LOO spread |
|---|---|---|---|
| *P*_eq (shared) | 0.9054 kg cm⁻² | — | ± 0.0046 |
| *r*_b (shared) | 0.01104 kg cm⁻² h⁻¹ | **± 0.00129 (bootstrap, CV 11.6%, n = 26)** | ± 0.00029 |
| *k*_La (τ = 1 min) | 0.0384 h⁻¹ | not quantified | — |
| *k*_La (τ = 5 min) | 0.1489 h⁻¹ | not quantified | — |
| *k*_La (τ = 10 min) | 0.1673 h⁻¹ | not quantified | — |

The leave-one-cycle-out spread measures the *influence* of a single cycle, not the precision of the estimate, and is especially insensitive for parameters constrained to be shared across batches; it is 4.4× tighter than the bootstrap standard deviation and should not be reported as an error bar. No uncertainty is available for *k*_La, which matters for one claim in particular: three estimators disagree on the change from τ = 5 to 10 min (+12.4%, −0.6%, −15.4%), and the only one carrying a standard error puts the difference at 0.79σ. Saturation of the lever beyond 5 min is therefore supported; the specific figure of +12% is not, and the increase from 1 to 5 min is best quoted as a range of 2.4–4.2×.

**Table 6.** Channel decomposition at *P* = 1.05 kg cm⁻².

| Batch | Physical *k*_La(*P* − *P*_eq) | Biological *r*_b | Biological share |
|---|---|---|---|
| τ = 1 min | 0.0056 | 0.0110 | 67% |
| τ = 5 min | 0.0215 | 0.0110 | 34% |
| τ = 10 min | 0.0242 | 0.0110 | 31% |

Three qualifications are essential. First, the shares are properties of a chosen pressure, not of a batch: evaluated at each batch's own cycle limits they sweep 53→94%, 22→82% and 20→85%, because the physical driving force vanishes as *P* → *P*_eq and the biological share necessarily tends to unity. Only the ordering at a fixed pressure, set by *k*_La, is robust. Second, the declining share across τ does not indicate declining biological activity: *r*_b is a single shared value, and the share falls only because circulation strengthens the physical channel. Third, models with and without *r*_b do not differ significantly in per-cycle predictive error (Wilcoxon signed-rank p = 0.468 over 26 held-out cycles). The correct statement is that *r*_b is *estimated stably* under the assumed model—Section 5.3 shows that it is not thereby identified—not that adding a biological channel improves prediction. The existence of biological activity is established independently: methane at the vent reaches 31.6–43.0%.

> **Fig. 2.** Two-stage bias and its calibrated remedy. (a) The two-stage regression appears decisive; (b) its null distribution under *r*_b ≡ 0 exceeds the observed value; (c) the joint estimator is nearly unbiased against a null drawn from its own model; (d) the resulting channel decomposition, conditional on that model. *(file: `fig26_calibrated_joint_fit.png`)*

### 5.3 The Calibration Certifies the Estimator, Not the Model

The null of Table 4 is generated by adding block-bootstrapped residuals to trajectories of the same single-exponential model the estimator fits. Any misspecification of that model is therefore present in both the observed and the synthetic data and cancels. The test asks whether the estimator manufactures *r*_b from noise; it cannot ask whether the model is right.

The model is not right. Reconstructing each cycle from the calibrated parameters leaves an end-point residual that is positive in **26 of 26 cycles** (sign test p = 3 × 10⁻⁸): the model does not fall far enough, by 0.019, 0.031 and 0.033 kg cm⁻² at τ = 1, 5 and 10 min, or 8–13% of the total pressure drop. The residual traces a U-shape along the cycle and changes sign in the early phase as τ increases—the signature of a single exponential fitted to a two-timescale process. A biexponential fits better (RMSE 0.0087 versus 0.0103–0.0158), and AICc already favors it decisively.

We therefore repeat the calibration with the truth drawn from a *different* model class (Algorithm 4): a biexponential that, by construction, contains no constant sink, so *r*_b ≡ 0 exactly. Feeding the noise-free biexponential trajectories to the joint estimator returns *r̂*_b = 0.01099—**100% of the value obtained from the real data**, as deterministic bias, before any noise is added. Over 200 bootstrap replicates the observed 0.01104 sits inside the null (p = 0.40 with a per-cycle asymptote, 0.36 with a per-batch asymptote). Running the complete pipeline—joint fit plus its own bootstrap calibration—on synthetic data whose true *r*_b is zero returns "significant" in 5 of 5 trials.

**Table 6.** Verification of Algorithm 4.

| # | Check | Result |
|---|---|---|
| V1 | Positive control: plant *r*_b = 0.011 | recovers 0.01071 (−2.7%) |
| V2 | Negative control: plant *r*_b = 0 | recovers 0.00000 |
| V3 | Biexponential truth, no noise | recovers 0.01099 = 100% of observed |
| V4 | Parameter bounds | 0 of 100 solutions at a bound |
| V5 | Slow component share of in-cycle drop | 21 / 90 / 91% |
| V6 | Slow timescale forced to be resolvable | recovers 0.00000 |
| V7 | Full pipeline on data with true *r*_b = 0 | 5 / 5 false positives |

V5 and V6 bound the claim. The bias requires a component slow enough to be unresolved within a cycle: when the second timescale is constrained to a half-life below 4.6 h, no spurious *r*_b appears. The component the data actually prefer has a half-life 1.9–3.3× the cycle length and carries 90% of the drop in the 5 and 10 min batches, so within one cycle it is very nearly linear. A reader may object that such a component is a constant sink under another name—but that objection concedes the point: from headspace pressure alone the two are observationally equivalent.

The correct statement is therefore not that *r*_b is spurious, but that **it is not identified**. Biological activity is established independently by vent methane of 31.6–43.0%; what the pressure trajectory cannot do is quantify it.

> **Fig. 3.** Misspecification null. Recovered *r*_b under a biexponential truth containing no biological sink, for a per-cycle (left) and per-batch (right) asymptote; the observed value falls inside both distributions. *(file: `fig30_misspecification_null.png`)*

### 5.4 Identification from Endogenous Excitation

Each refill completes one closed-headspace relaxation experiment at no cost: 26 experiments accumulated over 12 days, or **2.2 per day**, with no production interruption, no injected test signal, and no additional reagent. A continuous-flow reactor at steady state provides none.

**Table 7.** Learning curve of estimator precision (subsampling of the 26 observed cycles, 60 repeats each).

| Cycles *n* | ≈ days | *r*_b | SD | CV |
|---|---|---|---|---|
| 3 | 1.4 | 0.01204 | 0.00431 | 35.8% |
| 8 | 3.7 | 0.01187 | 0.00250 | 21.1% |
| 16 | 7.4 | 0.01173 | 0.00175 | 14.9% |
| 20 | 9.2 | 0.01119 | 0.00145 | 13.0% |
| 26 | 12.0 | 0.01113 | 0.00129 | 11.6% |

Precision improves with an exponent of **−0.507** in the accumulated cycle count, against the theoretical −0.50 for independent samples: each cycle contributes nearly independent information, whereas repeated observation of a single drifting system would saturate at an exponent approaching zero. Extrapolating, CV < 10% requires roughly 38 cycles, or 17 days of continuous operation.

Grid points beyond *n* = 26 are excluded. Reaching them requires resampling the 26 observed cycles with replacement, which shrinks the variance as 1/√n by construction; including them would build the very −0.5 law being tested into the data, and inflates the fitted exponent to −0.541. The quantity in Table 7 is the *precision* of the estimator, not its correctness—Section 5.3 shows that *r*_b itself is not identified—so the learning curve should be read as the rate at which the platform accumulates information, not as evidence that *r*_b has been reliably measured.

> **Fig. 4.** Identification from endogenous excitation. (a) Threshold-triggered cycles across the campaign; (b) learning curve against the 1/√n reference, with resampled points beyond *n* = 26 shown hollow and excluded from the fit; (c) convergence of the estimate with operating days. *(file: `fig27_self_identifying_platform.png`)*

## 6 Deployment Cost of the Calibration

Calibration does not by itself make an estimate trustworthy—Section 5.3 is the counterexample—but it is the minimum an on-device estimate should carry, so its cost decides whether that minimum is affordable. We measured the full pipeline on two x86 platforms with one script and automatic platform detection (Table 8).

**Table 8.** Pipeline cost on two x86 platforms.

| Stage | Laptop, 14-core | Workstation, 12-core |
|---|---|---|
| Cycle detection, streaming | 0.56 µs/sample | 0.100 µs/sample |
| Joint estimate (Alg. 2) | 0.878 s | 0.148 s |
| Bootstrap calibration, B = 200 (Alg. 3) | ≈ 3.0 min | 0.50 min |
| **Calibration / estimate cost ratio** | — | **203×** |
| Multicore speedup of calibration | 6.2× (13 proc.) | 5.67× (11 proc.) |
| Peak memory | 326 MB | 330 MB |

Certification costs about **200×** the estimate it certifies—0.15 s for one value of *r*_b against 200 replicates—yet it is schedulable: streaming detection consumes 0.1 µs per sample against a one-minute sampling interval, and refills are 6–15 h apart, so a 0.5–3 min calibration fits inside the idle interval. The workload is numerical optimization throughout and never uses the GPU, which sits idle even on the workstation's RTX 3060; because replicates are independent, throughput scales nearly linearly with cores instead.

Memory binds, and is predictable before deployment: peak usage is essentially platform-independent (326 versus 330 MB despite a sixfold speed difference) and is dominated by imports rather than data—129 MB for numpy, pandas, SciPy and Matplotlib, of which numpy alone is 27 MB. Against the ≈60 MB budget of the 4 GB monitoring machine hosting this deployment, the verdict is that the present implementation does not fit and a numpy-only path would. One caveat compounds this: importing a deep-learning framework merely to query GPU availability costs 307 MB—five times that budget—and 10–18% throughput, for a workload that never uses it, whereas an `nvidia-smi` subprocess probe costs neither.

## 7 Discussion and Limitations

**Scope of the Claim.** This work does *not* supply a validated quantitative value for the biological rate. Section 5.3 shows that *r*_b is not identified from headspace pressure: a purely physical two-timescale relaxation reproduces the reported value in full. Biological activity itself is established independently by vent methane of 31.6–43.0%; what remains unmeasured is its magnitude.

**What a Bootstrap Null Can and Cannot Certify.** The general lesson is that a resampling calibration built on the fitted model tests the estimator, not the model class. Certifying the model requires a null drawn from a *different* class (Algorithm 4) or an external condition of known truth. We recommend reporting both, and treating a calibration that supplies only the former as incomplete.

**Endogenous Trigger.** Refill is triggered by a pressure threshold, so an intrinsically slower cycle both takes longer to reach any given pressure and exhibits a smaller decline rate there. Cycle duration and mean rate correlate at r = 0.66–0.89 across batches, and any cross-cycle comparison must therefore include cycle fixed effects. Changing the trigger to a fixed time interval would remove this confound at no hardware cost.

**Autocorrelation.** One-minute sampling produces strongly autocorrelated series; an F-test treating several thousand correlated points as independent returns a spurious p of zero. All model comparisons here use leave-one-cycle-out or leave-one-batch-out cross-validation instead.

**Sensor Resolution.** pH spans only 7–9 quantization steps per cycle and contributes nothing to either parameter identification or supervised prediction—two independent lines of evidence. The slow ORP drift that carries biological information is only +2.26 mV h⁻¹ against ±20 mV noise, requiring roughly twelve cycles to become significant.

**Falsification Test.** Feeding pure CO₂ removes the electron donor and forces *r*_b to zero, supplying the external condition of known truth that no resampling scheme can substitute for. It is now the decisive experiment rather than a confirmatory one: it would separate the two-timescale relaxation of Section 5.3 from a genuine biological sink, because only the latter disappears when the donor is withdrawn. The abiotic variant—sparging into medium without inoculum—is the standard dynamic gassing-out determination of *k*_La and would fix the physical channel independently.

## 8 Conclusion

We estimated gas–liquid mass transfer and biological gas consumption jointly from threshold-triggered pressure relaxations, and then asked what the accompanying calibration actually certifies. The conventional two-stage separation manufactures an artifact of the same sign and magnitude as the effect sought, and a single-step joint estimator reduces that bias by 96% against a null drawn from its own model. That null, however, shares the model with the estimator: replacing it with a better-fitting model class that contains no biological sink reproduces the reported rate in full, and the complete pipeline returns "significant" on data whose true rate is zero in five trials of five. The biological rate is therefore not identified from headspace pressure, and the platform's learning curve measures precision rather than correctness.

The transferable result is a negative one with a constructive form: **a resampling calibration built on the fitted model certifies the estimator, not the model class.** Certifying the model needs a null drawn from a different class, or an external condition of known truth—here, withdrawal of the electron donor. On an edge device the first costs roughly two hundred times a single estimate, which we measured on real hardware; the second costs one experiment. Because the refill controller turns routine production into a continuous stream of relaxation experiments, the platform supplies the observations at 2.2 per day and no interruption to production; what it cannot supply, and what no amount of resampling will substitute for, is a condition in which the answer is known in advance.

**Acknowledgments.** The authors thank the Metal Industries Research & Development Centre for access to the experimental platform. *[Funding source and grant number to be inserted.]*

**Disclosure of Interests.** The reactor studied here is the subject of granted Taiwanese invention patent TW I923176, assigned to the Metal Industries Research & Development Centre, with which author C.-Y. Hung is affiliated. The authors declare no other competing interests.

## References

*All entries below were verified against CrossRef, PubMed, or the publisher of record on 2026-08-05. Author lists, volumes, page ranges, and DOIs are as printed by the source.*

1. Ette, E.I., Williams, P.J.: Population pharmacokinetics II: estimation methods. Ann. Pharmacother. **38**(11), 1907–1915 (2004). https://doi.org/10.1345/aph.1E259
2. Jensen, M.B., Ottosen, L.D.M., Kofoed, M.V.W.: H₂ gas-liquid mass transfer: a key element in biological Power-to-Gas methanation. Renew. Sustain. Energy Rev. **147**, 111209 (2021). https://doi.org/10.1016/j.rser.2021.111209
3. Braga Nan, L., Trably, E., Santa-Catalina, G., Bernet, N., Delgenès, J.-P., Escudié, R.: Biomethanation processes: new insights on the effect of a high H₂ partial pressure on microbial communities. Biotechnol. Biofuels **13**, 141 (2020). https://doi.org/10.1186/s13068-020-01776-y
4. Shardt, Y.A.W., Huang, B.: Closed-loop identification with routine operating data: effect of time delay and sampling time. J. Process Control **21**(7), 997–1010 (2011). https://doi.org/10.1016/j.jprocont.2011.06.015
5. Tisocco, S., Weinrich, S., Møller, H.B., Ward, A.J., Kilmartin, L., Zhan, X., Crosson, P.: Machine learning vs. ADM1: reliable biogas prediction with minimal data requirements in full-scale plants. Environ. Sci. Ecotechnol. **29**, 100662 (2026). https://doi.org/10.1016/j.ese.2026.100662
6. Raue, A., Kreutz, C., Maiwald, T., Bachmann, J., Schilling, M., Klingmüller, U., Timmer, J.: Structural and practical identifiability analysis of partially observed dynamical models by exploiting the profile likelihood. Bioinformatics **25**(15), 1923–1929 (2009). https://doi.org/10.1093/bioinformatics/btp358
7. Efron, B., Tibshirani, R.J.: An Introduction to the Bootstrap. Chapman & Hall, New York (1993). ISBN 978-0-412-04231-7
8. Künsch, H.R.: The jackknife and the bootstrap for general stationary observations. Ann. Statist. **17**(3), 1217–1241 (1989). https://doi.org/10.1214/aos/1176347265
9. Batstone, D.J., Keller, J., Angelidaki, I., Kalyuzhnyi, S.V., Pavlostathis, S.G., Rozzi, A., Sanders, W.T.M., Siegrist, H., Vavilin, V.A.: The IWA Anaerobic Digestion Model No 1 (ADM1). Water Sci. Technol. **45**(10), 65–73 (2002). https://doi.org/10.2166/wst.2002.0292
10. Metal Industries Research & Development Centre: Micro-pressure circulation control system and its method for anaerobic methane fermentation. TW Patent I923176 (2026)

> **Still to add (target 12–18).** Candidate topics: edge-constrained inference under latency/energy budgets; Jetson deployment case studies; gassing-out *k*_La measurement methodology. **Every added entry must be DOI-verified before insertion**—do not cite from memory.
>
> **Ordering.** Entries are currently in citation order. Springer LNCS (`splncs04.bst`) sorts alphabetically by first author surname; the BibTeX run will renumber automatically, so in-text numbers must not be hard-coded in the final LaTeX.
