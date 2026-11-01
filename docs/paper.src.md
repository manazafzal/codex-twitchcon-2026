# NOUS: testing thought injection and a defending mind

Chat tries to bring an idea into a small local AI's answer.  
A Mind-Reader tries to identify that idea without seeing the chat's target.  
A separate defence tries to remove the injected signal while preserving the task.  
We committed our predictions before collecting this study's measurements.  
Every comparison below says whether it actually ran; missing evidence proves nothing.  
This is a test of a small game mechanism, with fallible measurements and limited scope.

## Abstract

We present a preregistered, offline evaluation of NOUS. Matched everyday tasks compare thought injection doses, injection locations, vector constructions, blind readouts and a projection-based Neural Immune System. We distinguish label classification from tamper detection, test held-out prompt families and seeds, and report concept-cluster uncertainty. We publish executable comparisons that can contradict our predictions. The tables distinguish executed measurements from unavailable experiments; an unrun row has no estimate, and cannot support a hypothesis.

{{table:registration}}

## Method

### Registered design and provenance

The linked registration fixes sampling, primary conditions, decision rules and all grids. The sweeps vary one factor around the primary condition, with matched controls, rather than searching an unspecified Cartesian product. Every cell states its actual answer count, concept-cluster count and planned answer count. Unrun cells carry reasons. A failed or empty answer prevents a cell from being reported complete. The raw-mean and seeded random-direction conditions are negative or weak baselines that may defeat the proposed construction. Confidence intervals are descriptive across this preregistered collection; there is no multiplicity correction.

We generate self-described concept sets and neutral sets from the same local model. Absolute position zero is excluded from injection, state capture, contrast means and calibration. Directions are unit length. For the leave-one-out construction, with concept means $\mu_c$, the direction is

$$
d_c=\frac{\mu_c-\frac{1}{C-1}\sum_{j\ne c}\mu_j}
{\left\|\mu_c-\frac{1}{C-1}\sum_{j\ne c}\mu_j\right\|}.
$$

Other constructions subtract a common neutral mean, retain the raw mean, subtract matched neutral generations, whiten a neutral difference with regularized covariance, or use seeded Gaussian directions. The same construction is applied independently at injection and readout layers. All share contrast texts, neutral texts, seeds and unit normalization. The paired baseline matches template and generation seed. This isolates vector construction while retaining its possible dependence on shared data.

### Injection and readout

The intervention applies to every newly processed position, including prefill except the excluded sink position:

$$
h_{L,p}\leftarrow h_{L,p}+s d_c,\qquad
s=\alpha m\left(1-e^{-D/\kappa}\right).
$$

Here $m$ is the registered reference norm and $D$ is accumulated dose. The evaluation holds the target for an answer with saturating pushes and bounded dose response. Its deliberately wider dose grid exists only in a research adapter. The public game's faction-share cap and production dose limits are unchanged.

The original blind readout evaluates every concept on a rolling mean $\bar h_R$:

$$
u_c=\cos(\bar h_R,d_c),\qquad z_c=(u_c-\mu_c^{\mathrm{neutral}})/\sigma_c^{\mathrm{neutral}}.
$$

Neutral calibration uses the same rolling-window statistic. The alternative classifier concatenates answer-mean states at registered layers. Training-only centering, standardization or regularized whitening precedes shrinkage LDA or multinomial logistic regression. LDA uses a spherical shrinkage target; logistic regression uses fixed full-batch updates. Regularization and the winning architecture use validation accuracy only, with deterministic ties. The predefined full classifier is reported separately from that winner. Training sizes are balanced nested prefixes; smaller prefixes may lack injected examples, so size and training mixture are partly confounded. Families, seeds and normalized generated-text hashes must be disjoint across training, validation and test. An overlap fails fitting rather than being quietly removed. Held-out classifier comparisons use the same texts and paired concept-cluster resampling. The held-out cosine comparison uses the stored answer mean at its layer; generation and alarm measurements use rolling token windows.

### Clamp, alarm and measurement

The clamp is applied successively over all concept directions at the layer following injection:

$$
h\leftarrow h-\max(0,h\cdot d_c-t_c)d_c.
$$

Because directions need not be orthogonal, this is a sequential operation; later updates can change earlier projections. Clamp thresholds come from neutral projections. Alarm thresholds come from fresh neutral generations. For each token, the alarm attributes the largest positive excess among concepts exceeding either a projection threshold or the calibrated readout cutoff:

$$
a_{c,t}=\max(h_t\cdot d_c-q_c,\ z_{c,t}-z_*).
$$

A same-concept consecutive-token run is required. The topical exemption suppresses concepts named by aliases or stems in the task. We compare it on ordinary tasks and explicitly topical matched tasks. A classifier-confidence alarm uses a separate neutral validation set and the same run rule; it does not replace the operational projection/z alarm. Public tamper reports remain restricted to an enabled defence. Private detector measurements can be evaluated with the defence disabled.

Keyword hit is whole-word alias occurrence; stem hit and independently neutral-calibrated embedding hit are separate secondary proxies. Task kept is the existing lexical-anchor and repetition proxy, not a human quality rating. The registered keyword comparison uses target-keyword detection. As a secondary blind label baseline, first-mentioned keyword selects the first concept alias and counts no match as wrong. The target-detection baseline is not a blind classifier. Blind cosine and classifier predictions rank all concepts. Chance is contextual, not evidence of semantic understanding.

Intervals resample concepts with replacement and retain all answers in each selected cluster. Paired differences are computed within matched concept, task and seed before resampling. Relative hit reduction is undefined when the control has no hits; bootstrap samples with undefined ratios cannot yield a complete interval. Wilson intervals are supplementary answer-level summaries, not replacements for cluster uncertainty. Tables omit runtime timing so identical artifacts and seeds can reproduce byte-identical tables. CPU generation uses deterministic algorithms and a single numerical thread where supported.

## Results

The decision table applies the registered rules. Crossing a required confidence bound is inconclusive; absent observations remain unrun. Neither outcome is silently converted to support. Tables and figures below are generated exclusively from the evidence artifacts. Full machine-readable grids accompany the condensed classifier and alarm views. No exploratory hints are treated as results.

{{table:hypotheses}}

### Dose, task retention and injection location

{{table:dose}}

{{fig:dose}}

{{table:injection_layer}}

{{fig:injection_layer}}

### Vector construction and blind readout

{{table:vector}}

{{fig:vector}}

{{table:readout_layer}}

{{fig:readout_layer}}

### Held-out classifier comparison

The table includes the predefined full classifier and, when fitted, the validation-selected variant. Its held-out outcomes do not influence selection. Residual errors may involve neighbouring concepts; finite-sample accuracy is never a guarantee.

{{table:v4}}

{{fig:v4}}

### Defence and attribution

{{table:immune}}

{{fig:immune}}

{{table:alarm}}

{{fig:alarm}}

{{fig:roc}}

{{fig:false_alarms}}

{{fig:attribution}}

### Matched differences

{{table:paired}}

{{table:paired_control}}

## Limitations

This study is limited to one half-billion-parameter local model, thirty concepts, six ordinary task prompts and one primary generation seed. The classifier's additional split seeds test a different question and do not turn the generation experiment into a multi-seed study. Keyword and embedding proxies can miss valid meanings or reward irrelevant mentions; the task proxy can accept a poor answer or reject a good paraphrase. Human task-quality ratings are absent.

The readout comes from the same model family and representations as the injection. The library is fitted on data it also reads, so successful classification is partly a test of that construction rather than independent evidence about a model's inner experience. Held-out prompt families and seeds reduce some overlap but do not remove this dependence. Contrast sets and readout calibration are reused across ablations, with shared estimation uncertainty not fully represented by an answer-cluster bootstrap. Training-size prefixes change both sample count and injected-answer mixture.

CPU determinism concerns the specified local environment. Other numerical libraries, CPU instructions or package versions may change generated tokens; fixed seeds do not promise identical output across hardware. Local trained weights and the optional plotting dependency are required to regenerate empirical results. Unrun rows disclose unavailable evidence, rather than establish safety or effectiveness. The wider research doses are experimental and do not alter the game's production limits. Public chat secrecy and viewer fairness require their separate existing tests; these ablations alone cannot establish them.
