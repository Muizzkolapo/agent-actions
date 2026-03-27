# Probabilistic Prompt Injection Detection via Distributional Distance Metrics, Topic Modeling, and Bayesian Inference

**Authors:** Muizz Lateef et al.
**Date:** February 2026
**Version:** 1.0

---

## Abstract

Prompt injection remains the foremost security vulnerability in large language model (LLM) applications, ranked LLM01 in the OWASP Top 10 for LLMs (2025). Existing defenses rely predominantly on rule-based pattern matching, supervised classifiers, or perplexity thresholds---all of which suffer from brittleness against novel attack vectors. We propose a multi-layered statistical detection framework that treats prompt injection as a *distributional anomaly problem*. Our approach combines three complementary techniques: (1) **topic modeling** via ProdLDA and BERTopic to detect semantic drift in prompt topic distributions, (2) **data loss prevention** (DLP) techniques adapted for LLM input/output monitoring, and (3) **Bayesian probabilistic inference** using Pyro to model expected prompt distributions and flag statistical outliers with calibrated uncertainty. We introduce the **Prompt Frechet Distance (PFD)**, a novel metric inspired by the Frechet Inception Distance (FID) used in GAN evaluation, which measures the distributional distance between incoming prompts and a reference distribution of legitimate prompts in sentence embedding space. Unlike pointwise classifiers, PFD captures both mean shift and covariance structure changes, providing a mathematically principled foundation for detecting injection attacks that evade conventional defenses. We present the theoretical framework, connect it to existing literature on distributional distance metrics and out-of-distribution detection, and describe an implementation architecture using agent-actions workflow orchestration.

---

## 1. Introduction

### 1.1 The Prompt Injection Problem

Large language models process system instructions, context, and user input as a single natural-language token stream with no syntactic boundary between "code" and "data" [1]. This architectural property---the absence of privilege separation---constitutes the fundamental vulnerability exploited by prompt injection attacks. An attacker crafts input that overrides or supplements the system prompt, redirecting the model's behavior to serve adversarial objectives.

The attack surface is broad. Direct injection occurs when user input explicitly overrides instructions ("Ignore all previous instructions..."). Indirect injection plants malicious payloads in external data sources---RAG corpora, emails, API responses---that the LLM processes during retrieval-augmented generation [2, 17]. Jailbreaks bypass safety constraints through role-playing, encoding tricks, or context window manipulation [18]. Multi-turn escalation gradually pushes boundaries across conversation turns, with each individual message appearing benign [1].

Research demonstrates that these attacks remain effective against state-of-the-art models. Role-playing-based direct injections achieve an 89.6% Attack Success Rate [1]. Best-of-N jailbreaking achieves 89% success on GPT-4o and 78% on Claude 3.5 Sonnet given sufficient attempts, following power-law scaling [19]. Google DeepMind's evaluation of Gemini found that three out of four in-context defenses were only "marginally successful" [17].

### 1.2 Limitations of Current Approaches

Existing defenses fall into several categories, each with fundamental limitations:

**Rule-based/regex:** Pattern matching for known attack signatures (e.g., `/ignore\s+previous\s+instructions/i`) is fast and deterministic but trivially bypassed by paraphrasing, encoding attacks (base64, ROT13, unicode tricks), or typoglycemia [1].

**Perplexity-based:** Adversarial prompts often exhibit unusual statistical properties---unnaturally high perplexity from gibberish suffixes or anomalous token distributions. However, sophisticated attackers generate semantically coherent jailbreak prompts with normal perplexity, rendering this defense "marginally successful" [17].

**Supervised classifiers:** Fine-tuned models (e.g., DeBERTa-based ProtectAI Prompt-Guard) achieve strong performance on known attack distributions but require labeled training data and fail to generalize to novel attack vectors not present in training [15].

**LLM-based detection:** Using a second LLM to analyze prompts for injection patterns is expensive (additional inference call per request) and susceptible to the same injection vulnerabilities it aims to detect.

### 1.3 Our Contribution

We propose treating prompt injection detection as a **distributional anomaly detection** problem and introduce a multi-layered framework grounded in probability theory and information geometry. Our key contributions are:

1. **Prompt Frechet Distance (PFD):** A novel distributional distance metric, inspired by FID in GAN evaluation [7], that measures the statistical distance between incoming prompts and a reference distribution of legitimate prompts in sentence embedding space.

2. **Bayesian Prompt Model:** A generative model implemented in Pyro [8] that learns the expected distribution of legitimate prompts and provides calibrated posterior probabilities for anomaly detection, with principled uncertainty quantification.

3. **Topic-Distributional Divergence:** Jensen-Shannon divergence [10] computed on topic distributions inferred by ProdLDA [2a] or BERTopic [3], detecting semantic drift that indicates injection attempts.

4. **Integrated Detection Pipeline:** A four-layer defense-in-depth architecture combining fast heuristic filtering, embedding-based drift detection, topic analysis, and full Bayesian inference.

---

## 2. Background and Related Work

### 2.1 Prompt Injection Taxonomy

Following the comprehensive taxonomy of Vassilev et al. [1] and the OWASP classification [7a], we categorize prompt injection attacks along two axes:

**By delivery mechanism:**
- *Direct injection:* Attacker's input directly contains malicious instructions
- *Indirect injection:* Malicious payload is planted in external data sources (RAG documents, API responses, emails) processed by the LLM [16, 17]

**By objective:**
- *Goal hijacking:* Redirecting model behavior to serve attacker's purpose
- *Prompt leaking:* Extracting system prompts, hidden instructions, or API keys
- *Safety bypass (jailbreak):* Circumventing content safety constraints
- *Data exfiltration:* Extracting sensitive information via output channels

**By technique:**
- Instruction override, role-playing/virtualization [18]
- Encoding attacks (base64, ROT13, unicode smuggling) [1]
- Multi-turn escalation, payload splitting [1]
- Context window manipulation, many-shot jailbreaking [19]
- Few-shot injection, adversarial suffixes [1]

### 2.2 Distributional Distance Metrics

#### 2.2.1 Frechet Distance

The Frechet distance between two probability distributions P and Q on a metric space (M, d) is defined as the 2-Wasserstein distance:

$$d_F(P, Q) = \inf_{\gamma \in \Gamma(P,Q)} \left( \mathbb{E}_{(X,Y) \sim \gamma} [d(X,Y)^2] \right)^{1/2}$$

where $\Gamma(P, Q)$ is the set of all joint distributions (couplings) with marginals P and Q [13].

When $P = \mathcal{N}(\mu_1, \Sigma_1)$ and $Q = \mathcal{N}(\mu_2, \Sigma_2)$ are multivariate Gaussian, Dowson and Landau [6] proved the closed-form solution:

$$d_F^2(P, Q) = \|\mu_1 - \mu_2\|_2^2 + \text{tr}\left(\Sigma_1 + \Sigma_2 - 2(\Sigma_1^{1/2} \Sigma_2 \Sigma_1^{1/2})^{1/2}\right)$$

The first term captures **mean shift** (centroid displacement). The second term captures **covariance mismatch** (shape divergence). This decomposition is critical: prompt injection attacks may produce embeddings with similar means to legitimate prompts but anomalous covariance structure, or vice versa.

#### 2.2.2 Frechet Inception Distance (FID)

Heusel et al. [7] introduced FID for evaluating GAN-generated images by:

1. Extracting pool3 layer activations (2048-d vectors) from Inception-v3 for both real and generated images
2. Fitting multivariate Gaussians to both sets of activations
3. Computing the Frechet distance between the fitted Gaussians

FID captures two failure modes simultaneously: **mode collapse** (low diversity, shrinking $\Sigma_g$) and **quality degradation** (shifting $\mu_g$). Lower FID indicates generated images are closer to real images in perceptual feature space.

#### 2.2.3 Frechet BERT Distance (FBD)

Xiang et al. [14] extended FID to NLP by replacing Inception-v3 with BERT, creating the Frechet BERT Distance for evaluating dialogue systems:

$$\text{FBD} = \|\mu_{\text{real}} - \mu_{\text{synth}}\|_2^2 + \text{tr}\left(\Sigma_{\text{real}} + \Sigma_{\text{synth}} - 2(\Sigma_{\text{real}} \Sigma_{\text{synth}})^{1/2}\right)$$

This demonstrated that the Gaussian approximation in embedding space is empirically reasonable for aggregated BERT representations.

#### 2.2.4 Mahalanobis Distance

For single-sample detection, the Mahalanobis distance from a point x to a distribution $\mathcal{N}(\mu, \Sigma)$ is:

$$D_M(x) = \sqrt{(x - \mu)^T \Sigma^{-1} (x - \mu)}$$

Lee et al. [11a] established Mahalanobis distance as a unified framework for detecting out-of-distribution samples and adversarial attacks. Podolskiy et al. [11b] demonstrated its effectiveness for Transformer-based out-of-domain detection, finding that the choice of layer matters significantly. Under the Gaussian model, $D_M^2(x) \sim \chi^2_d$, providing a principled p-value:

$$\text{p-value} = P(\chi^2_d \geq D_M^2(\psi(p)))$$

Critically, **Mahalanobis distance is the single-sample analog of FID**: for a degenerate distribution consisting of a single point mass $\delta_x$, FID reduces to the squared Mahalanobis distance.

#### 2.2.5 Maximum Mean Discrepancy (MMD)

MMD [12] is a kernel-based, nonparametric metric that does not require the Gaussian assumption:

$$\text{MMD}^2(P, Q) = \mathbb{E}_{x,x' \sim P}[k(x,x')] - 2\mathbb{E}_{x \sim P, y \sim Q}[k(x,y)] + \mathbb{E}_{y,y' \sim Q}[k(y,y')]$$

Gao et al. [12a] proved that MMD with deep kernels (SAMMD) is aware of adversarial attacks. The MMD-MP method [12b] demonstrated that kernel-based distributional tests can distinguish human-written from machine-generated text, directly relevant to detecting injection payloads with machine-generated characteristics.

#### 2.2.6 Jensen-Shannon Divergence

The Jensen-Shannon divergence [10a] between distributions P and Q is:

$$\text{JSD}(P \| Q) = \frac{1}{2} D_{KL}(P \| M) + \frac{1}{2} D_{KL}(Q \| M), \quad M = \frac{1}{2}(P + Q)$$

Endres and Schindelin [10b] proved that $\sqrt{\text{JSD}}$ is a proper metric. JSD is bounded in $[0, 1]$ (using $\log_2$), symmetric, and always defined---properties that make it suitable for comparing topic distributions where KL divergence may be undefined due to zero-probability events.

### 2.3 Topic Modeling

#### 2.3.1 Latent Dirichlet Allocation (LDA)

Blei, Ng, and Jordan [9] introduced LDA as a generative model where each document is a mixture of K topics:

$$\theta_d \sim \text{Dirichlet}(\alpha) \quad \text{(per-document topic proportions)}$$
$$z_n \sim \text{Categorical}(\theta_d) \quad \text{(topic assignment for word n)}$$
$$w_n \sim \text{Categorical}(\beta_{z_n}) \quad \text{(word from topic vocabulary)}$$

#### 2.3.2 ProdLDA

Srivastava and Sutton [2a] replaced the Dirichlet prior with a logistic-normal approximation, enabling efficient amortized variational inference:

```python
logtheta = pyro.sample("logtheta",
    dist.Normal(logtheta_loc, logtheta_scale).to_event(1))
theta = F.softmax(logtheta, -1)
```

ProdLDA trains significantly faster than vanilla LDA and produces consistently better topics, making it practical for real-time detection pipelines.

#### 2.3.3 BERTopic

Grootendorst [3] replaced LDA's bag-of-words assumption with contextual Transformer embeddings, using Sentence-BERT embeddings, UMAP dimensionality reduction, HDBSCAN clustering, and c-TF-IDF for topic representation. BERTopic demonstrates "categorical superiority over LDA" for topic coherence and can capture injection attempts that share surface-level vocabulary with legitimate prompts but diverge semantically.

### 2.4 Embedding-Based Detection

Recent work confirms the viability of embedding-based prompt injection detection. Ayub and Majumdar [15] demonstrated that Random Forest and XGBoost classifiers on prompt embeddings outperform encoder-only neural network classifiers on a dataset of 467,057 unique prompts (109,934 malicious). The ZEDD framework [4] achieves 95.55% accuracy using zero-shot embedding drift detection with cosine distance and GMM-based threshold calibration. The Attention Tracker [5] achieves AUROC of 1.00 on multiple datasets by monitoring LLM attention patterns.

### 2.5 Bayesian Inference for Anomaly Detection

Malinin and Gales [20a] established reverse KL-divergence training of Prior Networks for uncertainty estimation and adversarial robustness. The Bayesian nonparametric perspective on Mahalanobis distance [11c] relaxes the single Gaussian assumption to Gaussian process or Dirichlet process mixture models. Posterior Mean Matching [6a] demonstrated that Bayesian inference with conjugate Gaussian pairs achieves FID scores comparable to diffusion models, connecting the Bayesian and distributional distance frameworks.

---

## 3. Proposed Framework

### 3.1 Core Hypothesis

**If a prompt's embedding distribution diverges significantly from the expected distribution for a given application context, it is likely an injection attempt.**

This hypothesis is grounded in the observation that prompt injection attacks are fundamentally *distributional anomalies*:

1. **Semantic shift:** Injected instructions ("ignore previous instructions...") occupy a different region of embedding space than legitimate task-oriented prompts.
2. **Stylistic anomaly:** Adversarial prompts combine multiple registers (user query + system-level commands), producing embeddings with unusual covariance structure.
3. **Structural deviation:** Injection payloads create multi-modal distributions that violate the unimodal assumptions of legitimate traffic.

### 3.2 The Prompt Frechet Distance (PFD)

We introduce the **Prompt Frechet Distance**, directly analogous to FID in GAN evaluation:

| GAN Evaluation | Prompt Injection Detection |
|---|---|
| Real image distribution $P_{\text{real}}$ | Legitimate prompt distribution $P_{\text{legit}}$ |
| Generated image distribution $P_{\text{gen}}$ | Incoming prompt distribution $P_{\text{incoming}}$ |
| Inception-v3 features $\phi(x)$ | Sentence-BERT embeddings $\psi(p)$ |
| FID measures generation quality | PFD measures prompt legitimacy |
| High FID = poor generation | High PFD = potential injection |

**Definition (Prompt Frechet Distance):** Given a reference corpus of legitimate prompts $\mathcal{C}_{\text{legit}} = \{p_1, \ldots, p_N\}$ and an incoming batch of prompts $\mathcal{B} = \{q_1, \ldots, q_M\}$, with sentence embedding function $\psi$:

$$\mu_{\text{legit}} = \frac{1}{N} \sum_{i=1}^{N} \psi(p_i), \quad \Sigma_{\text{legit}} = \text{Cov}(\{\psi(p_i)\})$$

$$\mu_{\text{batch}} = \frac{1}{M} \sum_{j=1}^{M} \psi(q_j), \quad \Sigma_{\text{batch}} = \text{Cov}(\{\psi(q_j)\})$$

$$\text{PFD}(\mathcal{C}_{\text{legit}}, \mathcal{B}) = \|\mu_{\text{legit}} - \mu_{\text{batch}}\|_2^2 + \text{tr}\left(\Sigma_{\text{legit}} + \Sigma_{\text{batch}} - 2(\Sigma_{\text{legit}}^{1/2} \Sigma_{\text{batch}} \Sigma_{\text{legit}}^{1/2})^{1/2}\right)$$

**Single-sample variant (Mahalanobis-PFD):** For real-time per-prompt detection:

$$\text{PFD}_1(q) = (\psi(q) - \mu_{\text{legit}})^T \Sigma_{\text{legit}}^{-1} (\psi(q) - \mu_{\text{legit}})$$

Under $H_0$ (prompt is legitimate), $\text{PFD}_1(q) \sim \chi^2_d$, providing a principled detection threshold.

**Multi-layer variant:** Following Podolskiy et al. [11b], compute PFD at multiple Transformer layers:

$$\text{PFD}_{\text{multi}} = \sum_{l=1}^{L} \alpha_l \cdot \text{PFD}_l$$

where $\text{PFD}_l$ uses hidden state at layer $l$ and $\alpha_l$ are learned weights. This captures both lexical anomalies (early layers) and semantic anomalies (later layers).

### 3.3 Topic-Distributional Divergence Detection

For each application context $c$, define the expected topic distribution:

$$\theta_{\text{expected}}(c) = \mathbb{E}[\theta_d \mid d \in \mathcal{D}_c]$$

where $\mathcal{D}_c$ is the corpus of legitimate prompts for context $c$. For an incoming prompt $p$, infer its topic distribution $\theta_p$ via the ProdLDA encoder, then compute:

$$\text{TDD}(p, c) = \text{JSD}(\theta_p \| \theta_{\text{expected}}(c))$$

Flag when $\text{TDD}(p, c) > \tau_{\text{topic}}$, calibrated on validation data.

**Why BERTopic over LDA:** BERTopic uses contextual Sentence-BERT embeddings rather than bag-of-words features. This means it captures semantic similarity rather than lexical overlap, detecting injection attempts that share surface vocabulary with legitimate prompts but diverge in meaning (e.g., "What are the instructions?" as a legitimate question vs. a prompt-leaking attempt).

### 3.4 Bayesian Anomaly Model in Pyro

We define a full generative model of legitimate prompt behavior using Pyro probabilistic programming:

**Generative Model:**

```python
def prompt_model(data=None, num_topics=20, vocab_size=10000):
    # Prior on topic-word distributions
    with pyro.plate("topics", num_topics):
        beta = pyro.sample("beta",
            dist.Dirichlet(torch.ones(vocab_size) * 0.1))

    # Per-document topic proportions
    with pyro.plate("documents", data.shape[0]):
        theta = pyro.sample("theta",
            dist.Dirichlet(torch.ones(num_topics) * 0.5))
        word_probs = torch.matmul(theta, beta)
        pyro.sample("words",
            dist.Multinomial(total_count=int(data.sum(-1).max()),
                             probs=word_probs), obs=data)
```

**Training via Stochastic Variational Inference:**

```python
svi = SVI(prompt_model, prompt_guide,
          Adam({"lr": 1e-3}), TraceMeanField_ELBO())
for epoch in range(num_epochs):
    loss = svi.step(training_data)
```

**Anomaly Scoring:** For an incoming prompt $p$:

1. **ELBO as anomaly score:**
$$\text{ELBO}(p) = \mathbb{E}_{q}[\log p(p|\theta)] - D_{KL}(q(\theta) \| p(\theta))$$
Anomalous prompts have low ELBO because they are poorly explained by the learned generative model.

2. **Posterior KL divergence:**
$$D_{KL}(q(\theta_p) \| p(\theta))$$
Large values indicate the prompt requires topic proportions far from what the model expects.

3. **Bayesian model comparison:**
$$\text{Bayes Factor} = \frac{p(\text{prompt} \mid \text{injection model})}{p(\text{prompt} \mid \text{benign model})}$$

**Advantages of the Bayesian approach:**
- Calibrated uncertainty estimates, not just point predictions
- Incorporates prior knowledge about attack patterns via informative priors
- Handles small training sets gracefully through regularization
- Posterior naturally adapts as more data is observed (online learning / self-hardening)
- Supports hierarchical models for multi-tenant/multi-context applications

### 3.5 Data Loss Prevention (DLP) Layer

DLP techniques adapted for LLM security operate at three levels:

**Input DLP (pre-LLM):**
- Named Entity Recognition (NER) to detect PII/PHI in prompts
- Regex patterns for structured sensitive data (SSN, credit cards, API keys)
- Unicode normalization and invisible character stripping (Tags Unicode Block U+E0000-U+E007F, variation selectors U+FE00-U+FE01)
- Canary token injection for exfiltration detection

**Output DLP (post-LLM):**
- System prompt leakage pattern detection
- Credential/API key exposure monitoring
- Information flow tracking from trusted (system prompt, RAG) to untrusted (output) channels

**Exfiltration detection:**
- URL/image markdown injection monitoring (data exfiltration via encoded URLs)
- Base64-encoded PII detection in output

### 3.6 Composite Risk Score

The four-layer pipeline produces a unified risk score:

$$\text{risk}(p) = w_1 \cdot \mathbb{1}[\text{regex\_match}] + w_2 \cdot \sigma(\text{PFD}_1 - \tau_e) + w_3 \cdot \sigma(\text{TDD} - \tau_t) + w_4 \cdot \sigma(-\text{ELBO} - \tau_b)$$

where $\sigma$ is the sigmoid function and $w_1, \ldots, w_4$ are calibrated weights. Flag when $\text{risk}(p) > \tau_{\text{composite}}$. The weights can themselves be learned via Bayesian optimization on labeled data.

---

## 4. The PFD-FID Analogy: A Deeper Analysis

### 4.1 Why FID's Properties Transfer to Prompt Detection

FID captures two GAN failure modes: **mode collapse** (low diversity, shrinking covariance) and **quality degradation** (shifting mean). In prompt injection detection, these map to:

- **Mean shift ($\|\mu_1 - \mu_2\|^2$):** Detects prompts whose semantic centroid has moved---e.g., a customer support chatbot receiving prompts about hacking instead of product questions.
- **Covariance mismatch ($\text{tr}(\ldots)$):** Detects prompts with unusual correlation structure---e.g., injection payloads that combine system-instruction vocabulary with user-query vocabulary, creating cross-domain correlations absent from legitimate prompts.

### 4.2 The Gaussian Assumption in Embedding Space

A known limitation of FID is the assumption that features are multivariate Gaussian. Jayasumana et al. [7b] demonstrated this assumption can be violated for Inception embeddings and proposed normalizing-flow alternatives (FLD+). In the prompt setting:

**Argument for:** Aggregated Sentence-BERT embeddings over large prompt corpora empirically approximate Gaussians, as demonstrated by the success of FBD for dialogue evaluation [14].

**Argument against:** Multi-modal legitimate prompt distributions (e.g., an application serving both technical and non-technical users) violate unimodality.

**Mitigation strategies:**
1. **Gaussian Mixture Models:** Fit K-component GMMs instead of single Gaussians, computing PFD against each component and taking the minimum.
2. **Bayesian nonparametric extensions:** Use Dirichlet process mixtures for automatic component selection [11c].
3. **Kernel methods (MMD-PFD):** Replace the Gaussian assumption entirely with kernel-based distributional tests using deep kernels [12a].

### 4.3 Computational Considerations

**Offline phase (one-time):**
- Embed N legitimate prompts: $O(N \cdot T_{\text{SBERT}})$
- Compute covariance: $O(Nd^2)$
- Invert covariance: $O(d^3)$

For $d = 768$ (SBERT dimension), $\Sigma^{-1}$ requires ~450M multiply-adds---precomputed once.

**Online phase (per-prompt):**
- Embed incoming prompt: $O(T_{\text{SBERT}})$ (~5ms)
- Compute Mahalanobis distance: $O(d^2)$ (~0.6M multiply-adds, <1ms)

Total per-prompt overhead: ~5-6ms, dominated by embedding computation.

**Batch monitoring (sliding window):**
- Compute window statistics: $O(Md^2)$
- Compute matrix square root for full PFD: $O(d^3)$ (~450M ops, ~10ms)

### 4.4 Regularization for High Dimensions

When corpus size $N < d = 768$, the sample covariance is singular. Strategies:

1. **Ledoit-Wolf shrinkage:** $\Sigma_{\text{reg}} = (1-\alpha)\Sigma + \alpha \cdot \frac{\text{tr}(\Sigma)}{d} I$, with optimal $\alpha$
2. **PCA reduction:** Project to top-$k$ principal components ($k = 128$ retains >95% variance), reducing $d$ dramatically
3. **Tikhonov regularization:** $\Sigma_{\text{reg}} = \Sigma + \lambda I$

---

## 5. Detection Pipeline Architecture

### Layer 1: Fast Heuristic Filtering (~microseconds)

- OWASP-derived regex patterns with fuzzy matching
- Unicode normalization (NFKC) and invisible character stripping
- Input length validation and token count limits
- DLP input scanning (NER, structured data patterns)

### Layer 2: Embedding Drift Detection (~5ms)

- Compute Sentence-BERT embedding $\psi(p)$
- Compute Mahalanobis-PFD: $\text{PFD}_1(p)$
- Flag if $\text{PFD}_1(p) > \tau_{\chi^2}$

### Layer 3: Topic Distribution Analysis (~10ms)

- Infer topic distribution $\theta_p$ using trained ProdLDA encoder
- Compute $\text{TDD}(p, c) = \text{JSD}(\theta_p \| \theta_{\text{expected}})$
- Flag if $\text{TDD} > \tau_{\text{topic}}$

### Layer 4: Bayesian Anomaly Scoring (~100ms)

- Compute $\text{ELBO}(p)$ under trained Pyro generative model
- Compute posterior $q(\theta_p)$ and $D_{KL}(q(\theta_p) \| p(\theta))$
- Compute predictive log-likelihood
- Flag if anomaly score exceeds Bayesian threshold with credible interval

### Layer 5: DLP Output Monitoring (post-inference)

- System prompt leakage detection
- Canary token verification
- Exfiltration pattern matching

---

## 6. Self-Hardening and Adaptive Defense

### 6.1 Bayesian Online Updating

The Gaussian conjugate structure enables online updating of the reference distribution:

$$\mu_n = \frac{\Sigma_0^{-1}\mu_0 + n\Sigma_{\text{obs}}^{-1}\bar{x}}{\Sigma_0^{-1} + n\Sigma_{\text{obs}}^{-1}}, \quad \Sigma_n = (\Sigma_0^{-1} + n\Sigma_{\text{obs}}^{-1})^{-1}$$

As new legitimate prompts are observed, the posterior tightens, improving detection sensitivity. Conversely, detected injections are excluded from updates, preventing adversarial poisoning.

### 6.2 Attack Corpus Augmentation

Following Rebuff's self-hardening mechanism [21], detected injection attempts are stored in a vector database. Future prompts are compared against both the legitimate reference distribution (PFD) and the injection corpus (similarity search), creating two complementary detection signals.

### 6.3 Concept Drift Handling

Legitimate prompt distributions evolve as applications change. We handle concept drift through:

1. **Exponential forgetting:** Weight recent prompts more heavily in covariance estimation
2. **Change-point detection:** Monitor PFD of the legitimate corpus against itself over time; spikes indicate genuine distribution shifts vs. injection campaigns
3. **Periodic recalibration:** Rebuild reference statistics with human-verified recent prompts

---

## 7. Relationship to Existing Frameworks

### 7.1 Comparison with ZEDD

ZEDD [4] uses cosine distance between system prompt embedding and processed prompt embedding, with GMM-based threshold calibration. Our framework extends this by:

- Using **full covariance structure** (PFD) rather than scalar cosine distance
- Providing **batch-level monitoring** for coordinated attacks
- Adding **Bayesian uncertainty** for calibrated confidence
- Incorporating **topic-level analysis** for interpretable explanations

### 7.2 Comparison with NeMo Guardrails

NVIDIA NeMo Guardrails [22] provides rule-based conversational safety via the Colang language. Our framework complements NeMo by adding:

- **Statistical foundation:** Principled anomaly detection vs. rule authoring
- **Generalization:** Detects novel attacks without explicit rules
- **Calibration:** Quantified confidence in detection decisions

### 7.3 Comparison with Attention Tracker

Attention Tracker [5] monitors LLM internal attention patterns, achieving AUROC of 1.00 on some benchmarks. However, it requires access to model internals (attention weights), limiting it to open-weight models. Our framework operates purely on input text, making it applicable to any LLM including API-only services (GPT-4, Claude).

---

## 8. Theoretical Analysis

### 8.1 Detection Power

Under the alternative hypothesis $H_1$ (prompt is an injection), the expected Mahalanobis distance is:

$$\mathbb{E}[D_M^2 \mid H_1] = (\mu_{\text{inject}} - \mu_{\text{legit}})^T \Sigma_{\text{legit}}^{-1} (\mu_{\text{inject}} - \mu_{\text{legit}}) + d$$

The first term (non-centrality parameter) determines detection power. Attacks with larger semantic distance from legitimate prompts are easier to detect.

### 8.2 Adversarial Robustness Considerations

An adversary aware of PFD could craft injections that are semantically malicious but close to $\mu_{\text{legit}}$ in embedding space---the prompt-domain analog of adversarial examples. Defense strategies:

1. **Multi-layer PFD:** Evasion in one layer's feature space does not guarantee evasion in all layers
2. **Topic-level analysis:** Even if embedding distance is small, topic distribution may diverge
3. **ELBO scoring:** Bayesian anomaly detection captures higher-order structure beyond first two moments
4. **Ensemble defense:** The composite score from multiple layers provides defense-in-depth

### 8.3 False Positive Analysis

The chi-squared threshold provides direct false positive rate control:

$$\text{FPR} = P(\chi^2_d > \tau) = 1 - F_{\chi^2_d}(\tau)$$

For $d = 768$ and $\text{FPR} = 0.01$: $\tau \approx 849.5$. In practice, PCA reduction to $d = 128$ gives $\tau \approx 165.5$, a more practical threshold.

---

## 9. Implementation Architecture

We implement the detection pipeline as an agent-actions workflow, enabling modular composition and parallel execution of detection layers:

```
┌────────────────────────────────────────────────────────────────┐
│                  Prompt Injection Detection Workflow            │
│                                                                │
│  ┌──────────┐   ┌──────────────┐   ┌───────────────┐         │
│  │ DLP/Regex │   │ Embedding    │   │ Topic Model   │         │
│  │ Filter    │──>│ PFD Score    │──>│ JSD Score     │         │
│  │ (Layer 1) │   │ (Layer 2)    │   │ (Layer 3)     │         │
│  └──────────┘   └──────────────┘   └───────────────┘         │
│       │               │                   │                    │
│       v               v                   v                    │
│  ┌────────────────────────────────────────────────┐           │
│  │              Bayesian Scorer (Layer 4)          │           │
│  │         ELBO + Posterior KL + Bayes Factor      │           │
│  └────────────────────────────────────────────────┘           │
│                          │                                     │
│                          v                                     │
│  ┌────────────────────────────────────────────────┐           │
│  │           Composite Risk Aggregator             │           │
│  │   risk(p) = w1*L1 + w2*sigmoid(L2) + ...       │           │
│  └────────────────────────────────────────────────┘           │
│                          │                                     │
│                    ┌─────┴─────┐                              │
│                    │ PASS/FLAG │                              │
│                    └───────────┘                              │
└────────────────────────────────────────────────────────────────┘
```

---

## 10. Open Research Questions

1. **Gaussianity of sentence embeddings:** Systematic empirical validation of the Gaussian approximation for diverse prompt populations across embedding models.

2. **Adaptive adversaries:** Characterization of the adversarial robustness of PFD against embedding-space attacks specifically designed to minimize Mahalanobis distance while maintaining injection efficacy.

3. **Multi-modal legitimate distributions:** Evaluation of GMM-based and Bayesian nonparametric PFD variants for applications with diverse prompt types.

4. **Cross-lingual transfer:** Extension of PFD to multilingual settings where injections may use language-switching as an evasion technique.

5. **Computational scaling:** Development of streaming estimators for covariance matrices and incremental PFD computation for high-throughput production systems.

6. **Optimal layer selection:** Systematic study of which Transformer layers provide maximum detection power for different attack categories.

---

## 11. Conclusion

We have presented a mathematically principled framework for prompt injection detection that treats the problem as distributional anomaly detection. The Prompt Frechet Distance (PFD), inspired by FID's success in GAN evaluation, provides a rigorous metric for measuring how far incoming prompts deviate from expected legitimate distributions. Combined with topic-distributional divergence analysis via ProdLDA/BERTopic and full Bayesian anomaly scoring in Pyro, our four-layer defense-in-depth pipeline addresses the fundamental limitations of existing approaches: brittleness (regex), narrow coverage (perplexity), and poor generalization (supervised classifiers).

The key insight---borrowed from the GAN evaluation literature---is that **distributional distance captures both mean shift and covariance structure changes**, detecting attacks that pointwise classifiers miss. The Bayesian formulation provides calibrated uncertainty and self-hardening through posterior updating.

---

## References

[1] OWASP Foundation. "OWASP Top 10 for Large Language Model Applications, Version 2025." OWASP Gen AI Security Project. https://genai.owasp.org/resource/owasp-top-10-for-llm-applications-2025/

[2] Pereira, J. A. et al. "Prompt Injection Attacks in Large Language Models and AI Agent Systems: A Comprehensive Review." *Information*, 17(1), 54, 2025. https://www.mdpi.com/2078-2489/17/1/54

[2a] Srivastava, A. and Sutton, C. "Autoencoding Variational Inference for Topic Models." In *ICLR 2017*. https://arxiv.org/abs/1703.01488

[3] Grootendorst, M. "BERTopic: Neural Topic Modeling with a Class-Based TF-IDF Procedure." *arXiv preprint arXiv:2203.05794*, 2022. https://arxiv.org/abs/2203.05794

[4] Sekar, A. et al. "Zero-Shot Embedding Drift Detection: A Lightweight Defense Against Prompt Injections in LLMs." *arXiv preprint arXiv:2601.12359*, 2025. https://arxiv.org/abs/2601.12359

[5] Hung, K.-H. et al. "Attention Tracker: Detecting Prompt Injection Attacks in LLMs." In *Findings of NAACL 2025*, pp. 2309-2322. https://aclanthology.org/2025.findings-naacl.123/

[6] Dowson, D. C. and Landau, B. V. "The Frechet Distance between Multivariate Normal Distributions." *Journal of Multivariate Analysis*, 12(3):450-455, 1982. https://doi.org/10.1016/0047-259X(82)90077-X

[6a] Posterior Mean Matching. "Generative Modeling with Bayesian Sample Inference." *arXiv preprint arXiv:2502.07580*, 2025. https://arxiv.org/abs/2502.07580

[7] Heusel, M., Ramsauer, H., Unterthiner, T., Nessler, B., and Hochreiter, S. "GANs Trained by a Two Time-Scale Update Rule Converge to a Local Nash Equilibrium." In *NeurIPS 2017*, pp. 6626-6637. https://arxiv.org/abs/1706.08500

[7a] OWASP Foundation. "OWASP Top 10 for LLMs - LLM01: Prompt Injection." https://genai.owasp.org/llmrisk/llm01-prompt-injection/

[7b] Jayasumana, S. et al. "Rethinking FID: Towards a Better Evaluation Metric for Image Generation." *arXiv preprint arXiv:2401.09603*, 2024. https://arxiv.org/abs/2401.09603

[8] Bingham, E. et al. "Pyro: Deep Universal Probabilistic Programming." *Journal of Machine Learning Research*, 20(28):1-6, 2019. http://www.jmlr.org/papers/v20/18-403.html

[9] Blei, D. M., Ng, A. Y., and Jordan, M. I. "Latent Dirichlet Allocation." *Journal of Machine Learning Research*, 3:993-1022, 2003. https://jmlr.csail.mit.edu/papers/v3/blei03a.html

[10a] Lin, J. "Divergence Measures Based on the Shannon Entropy." *IEEE Transactions on Information Theory*, 37(1):145-151, 1991. https://doi.org/10.1109/18.61115

[10b] Endres, D. M. and Schindelin, J. E. "A New Metric for Probability Distributions." *IEEE Transactions on Information Theory*, 49(7):1858-1860, 2003. https://doi.org/10.1109/TIT.2003.813506

[11a] Lee, K. et al. "A Simple Unified Framework for Detecting Out-of-Distribution Samples and Adversarial Attacks." In *NeurIPS 2018*. https://papers.nips.cc/paper/7947

[11b] Podolskiy, A. et al. "Revisiting Mahalanobis Distance for Transformer-Based Out-of-Domain Detection." In *AAAI 2021*. https://cdn.aaai.org/ojs/17612/17612-13-21106-1-2-20210518.pdf

[11c] Bayesian Nonparametric Perspective on Mahalanobis Distance for OOD Detection. *arXiv preprint arXiv:2502.08695*, 2025.

[12] Gretton, A. et al. "A Kernel Two-Sample Test." *JMLR*, 13:723-773, 2012. https://www.jmlr.org/papers/v13/gretton12a.html

[12a] Gao, F. et al. "Maximum Mean Discrepancy Test is Aware of Adversarial Attacks." In *ICML 2021*. https://proceedings.mlr.press/v139/gao21b.html

[12b] MMD-MP. "Detecting Machine-Generated Texts by Multi-Population Aware Optimization for Maximum Mean Discrepancy." *arXiv preprint arXiv:2402.16041*, 2024. https://arxiv.org/abs/2402.16041

[13] Peyre, G. and Cuturi, M. "Computational Optimal Transport." *Foundations and Trends in Machine Learning*, 11(5-6):355-607, 2019. https://arxiv.org/abs/1803.00567

[14] Xiang, J. et al. "Assessing Dialogue Systems with Distribution Distances." In *Findings of ACL-IJCNLP 2021*, pp. 2192-2198. https://doi.org/10.18653/v1/2021.findings-acl.193

[15] Ayub, M. A. and Majumdar, S. "Embedding-based Classifiers Can Detect Prompt Injection Attacks." *arXiv preprint arXiv:2410.22284*, 2024. https://arxiv.org/abs/2410.22284

[16] Hines, K. et al. "Defending Against Indirect Prompt Injection Attacks With Spotlighting." *arXiv preprint arXiv:2403.14720*, 2024. https://arxiv.org/abs/2403.14720

[17] Shi, C. et al. "Lessons from Defending Gemini Against Indirect Prompt Injections." *arXiv preprint arXiv:2505.14534*, 2025. https://arxiv.org/abs/2505.14534

[18] Wei, A., Haghtalab, N., and Steinhardt, J. "Jailbroken: How Does LLM Safety Training Fail?" In *NeurIPS 2023*. https://arxiv.org/abs/2307.02483

[19] Anil, C. et al. "Many-Shot Jailbreaking." In *NeurIPS 2024*. https://www.anthropic.com/research/many-shot-jailbreaking

[20a] Malinin, A. and Gales, M. "Reverse KL-Divergence Training of Prior Networks: Improved Uncertainty and Adversarial Robustness." In *NeurIPS 2019*. https://arxiv.org/abs/1905.13472

[20b] Lee, S. and Lee, D. "Semi-supervised Anomaly Detection Algorithm Based on KL Divergence." *arXiv preprint arXiv:2203.14539*, 2022. https://arxiv.org/abs/2203.14539

[21] ProtectAI. "Rebuff: Self-Hardening Prompt Injection Detector." https://github.com/protectai/rebuff

[22] NVIDIA. "NeMo Guardrails." https://github.com/NVIDIA-NeMo/Guardrails

[23] Reimers, N. and Gurevych, I. "Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks." In *EMNLP-IJCNLP 2019*, pp. 3982-3992. https://doi.org/10.18653/v1/D19-1410

[24] Mahalanobis, P. C. "On the Generalised Distance in Statistics." *Proceedings of the National Institute of Sciences of India*, 2:49-55, 1936.

[25] Embedding-Based Detection of Indirect Prompt Injection Using Semantic Context Analysis. *Algorithms*, 19(1), 92, 2026. https://www.mdpi.com/1999-4893/19/1/92

[26] CrowdStrike. "BERT Embeddings: A New Approach for Command-Line Anomaly Detection." https://www.crowdstrike.com/en-us/blog/bert-embeddings-new-approach-for-command-line-anomaly-detection/

[27] Gupta, S. et al. "Frechet Distance for Offline Evaluation of Information Retrieval Systems with Sparse Labels." In *EACL 2024*. https://aclanthology.org/2024.eacl-long.26/
