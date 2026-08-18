# Explaining Markets — Development Log

This document tracks the evolution of our approach to the Explaining Markets earnings-prediction competition. Each version represents a meaningful change to the prediction methodology based on either new information about the competition or observed performance from previous versions.

The objective throughout is to predict the **next-trading-day abnormal return following an earnings announcement**, submitted as a percentile relative to the cross-section of earnings events.

---

# v0 — Initial Architecture

**Basis:** Initial research and system design  
**Reference:** `EM-Knowledge-Repo-and-Prompt-v0.md`

## Approach

Our initial thesis was that our primary advantage would come from the **context we could provide the model before it made a prediction**.

Explaining Markets provides relatively short fact-bullet summaries rather than full earnings-call transcripts. Because every agent receives essentially the same event information, we concluded that much of the potential edge would have to come from information we supplied ourselves: expectations, company-specific history, and industry knowledge.

We therefore designed the prediction around three additional sources of information:

- **Global rules:** general principles governing expectations, guidance, earnings quality, transitory items, and other recurring earnings patterns.
- **Industry playbooks:** conditional rules describing how industry-specific developments should affect predictions.
- **Ticker dossiers:** company-specific context unavailable from the event bullets.

The initial feature roadmap prioritized expectations framing, prior announcement reactions, guidance trajectory, industry rules, analyst consensus, analyst focus, and eventually an outcomes feedback loop.

## Ticker dossiers

The dossier was intended to tell the model something about the company **before** it interpreted the announcement.

The initial design considered fields including:

- prior earnings surprises;
- prior next-day abnormal returns;
- consensus estimates;
- guidance trajectory;
- analyst focus;
- seasonality;
- geographic exposure; and
- eventually options-implied moves.

Prior reactions were viewed as particularly valuable because they could show how a specific stock historically trades around its own earnings announcements.

## Rule system

Global and industry rules were originally structured as conditional triggers associated with numerical percentile ranges.

For example:

```yaml
trigger: >
  Capex guidance raised materially without corresponding
  revenue or FCF visibility

action:
  percentile_range: [0.15, 0.30]
```

The idea was to give the model explicit historical/financial heuristics rather than asking it to reason entirely from scratch.

## Prediction process

The initial prediction process was approximately:

```text
Event bullets
      +
Global rules
      +
Industry playbook
      +
Ticker dossier
      ↓
Reason about expectations and belief revision
      ↓
Predicted percentile
```

The prompt explicitly emphasized that markets react to **belief revision relative to expectations**, rather than absolute financial performance.

## Outcomes ledger

We also designed an outcomes ledger from the beginning so predictions could eventually be evaluated against realized results.

The original fields included:

```text
event_id
ticker
prompt_version
predicted_percentile
confidence
rules_applied
realized_abnormal
realized_percentile
```



This established the foundation for using competition results to modify the system rather than relying entirely on intuition.

---

# v1 — Return-Space Reasoning and Rebalancing the Rulebook

**Basis:** August 4–6 results  
**Reference:** `EM-Diagnostics-Aug6.md`

## What we observed

The first useful scored sample revealed a major directional asymmetry.

Our system was unusually good at identifying **severe negative reactions**. Cases such as UWMC, CDLX, TEAD, PZZA, INSG, and ANGI demonstrated that the rules could recognize situations where headline results looked acceptable but guidance, earnings quality, or the underlying business were substantially worse.

At the same time, we performed extremely poorly on many positive reactions.

The explanation was visible in the rulebook itself: there were substantially more negative rules than positive ones.

The system had effectively become a:

> **disaster detector rather than a general return predictor.**

## Rule-snapping

A second problem was visible in the distribution of predictions.

Outputs repeatedly appeared around values such as:

```text
0.05
0.08
0.10
0.12
0.15
0.18

0.88
0.90
0.92
0.95
```

These values closely corresponded to the ranges contained in individual rules.

For example, a rule prescribing `0.10–0.20` frequently resulted in a prediction around `0.15`. The model appeared to be identifying the closest rule and then selecting a value from its prescribed interval rather than independently estimating the magnitude of the event.

This effectively transformed a continuous prediction problem into a small number of discrete buckets.

## Calibration problem

Analysis of realized abnormal returns also showed that our intuition about percentiles was poorly calibrated.

Approximately:

```text
Abnormal return       Percentile

  0.0%                   0.50
 +1.9%                   0.60
 +3.4%                   0.70
 +6.0%                   0.80
+12.0%                   0.90

 -1.6%                   0.40
 -3.7%                   0.30
 -6.6%                   0.20
-12.0%                   0.10
```



Several perfectly ordinary +2–4% reactions were being assigned predictions around 0.10–0.18 because some negative rule had fired.

## What changed in v1

### 1. Predict abnormal return first

The largest architectural change was moving the model's reasoning out of percentile space.

Instead of directly asking:

> What percentile should this announcement receive?

we changed the task to:

> What abnormal percentage return should this stock experience on the next trading day?

The resulting abnormal return could then be mechanically converted to a percentile.

The pipeline became:

```text
Event + context
      ↓
Estimate abnormal return
      ↓
Return-to-percentile conversion
      ↓
Submitted percentile
```

This was intended to force the model to reason continuously rather than simply copying a rule's percentile range.

### 2. Rebalance positive and negative rules

We also added positive rules to correct the original rulebook's strong negative asymmetry.

The goal was **not** to remove the negative rules that had worked well. In fact, preserving the system's ability to identify genuine disasters was explicitly one of the constraints on subsequent changes.

Instead, we wanted comparable logic for genuinely positive belief revisions.

### 3. Introduce stronger materiality thinking

Ordinary cautionary language, small one-time items, or minor segment weakness should not automatically justify a large negative prediction.

The system increasingly distinguished between:

```text
signal exists
```

and:

```text
signal is material enough to change investor beliefs
```

---

# v2 — Reducing Rule-Snapping and Restoring the Middle

**Basis:** August 10 observations  
**Reference:** `EM-Observations-Aug10.md`

## What we observed

The v1 changes successfully reduced the overwhelming negative skew and restored positive predictions.

However, the distribution exposed a new problem.

Predictions were still concentrated in the tails.

Instead of behaving primarily as a negative classifier, the model increasingly behaved as a **two-sided tail classifier**.

Across 123 industry rules:

- 81 had ranges entirely outside the central 0.30–0.70 region;
- only 15 rule midpoints were between 0.30 and 0.70;
- none were between 0.40 and 0.50; and
- only one was between 0.50 and 0.60.

The rulebook itself was teaching the model that recognizable earnings patterns should usually correspond to large moves.

## Why it was happening

Several design choices contributed to this.

First, industry rules still contained explicit abnormal-return and percentile ranges.

Second, industry rules could override global rules based on specificity. Because virtually every earnings announcement contains some recognizable industry KPI, an industry rule could fire even when the development was modest or already expected.

Third, neutral was effectively treated as the outcome when **nothing else applied**.

Finally, conflicting rules were sometimes resolved mechanically, which encouraged additional reuse of predefined numerical anchors.

## What changed in v2

### 1. Remove numerical ranges from industry rules

Industry rules stopped prescribing abnormal-return or percentile ranges.

Instead, they became directional considerations:

```yaml
trigger: >
  Volume growth with maintained or expanded margins
  despite material input-cost pressure.

implication: positive

severity_basis: >
  Stronger when the volume surprise and margin resilience
  exceed expectations and support higher forward earnings.
```



The division of responsibility became:

```text
INDUSTRY RULES
What matters?
Is it positive or negative?
What makes it important?

            ↓

GLOBAL FRAMEWORK
Was it expected?
Is it material?
Is it persistent?
What offsets it?

            ↓

MODEL
How large should the abnormal return be?
```

### 2. Global rules remain binding

Industry specificity no longer automatically overrides the global framework.

Industry rules identify economically relevant information, while the global rules determine whether that information is surprising and material enough to justify moving away from an ordinary return.

### 3. Neutral becomes a legitimate forecast

Neutral was changed from a residual category into a competing outcome.

A quarter can contain recognizable positive and negative developments while still producing little net belief revision.

Thus:

```text
rule fires ≠ large return
```

A signal that is expected, small, temporary, or offset by another signal can still result in an abnormal return near zero.

### 4. Conflicting evidence shrinks toward zero

Rather than averaging the numerical ranges of conflicting rules, positive and negative evidence should be evaluated according to its effect on the forward earnings path.

When neither side clearly dominates, the predicted abnormal return should move toward zero.

---

# v3 — Improving Expectations, Calibration, and Diagnostics

**Basis:** Post-August 10 results and subsequent iteration

v3 builds on the v2 architecture rather than changing its basic philosophy.

The major changes were:

1. **adding analyst EPS expectations to ticker dossiers;**
2. **softening positive abnormal-return calibration;** and
3. **expanding the prediction ledger with additional metadata.**

## Problem 1 — Expectations were still underspecified

From v0 onward, one of our central instructions had been:

> Judge the announcement relative to what investors already expected.

But there was a practical problem: the model did not always have enough information to know what those expectations actually were.

This was especially important because the entire prediction framework had increasingly become centered on **belief revision**.

## Change — Current and forward EPS estimates

Ticker dossiers were expanded to include analyst EPS estimates.

In particular, we added both:

- **current-period analyst EPS expectations**, and
- **forward analyst EPS expectations**.

This gives the model a more explicit quantitative baseline for interpreting the event.

The distinction between current and forward estimates is important.

An announcement can:

```text
Beat current EPS
      +
Lower the future earnings path
      ↓
Negative belief revision
```

or:

```text
Report an ordinary current quarter
      +
Raise the future earnings path
      ↓
Positive belief revision
```

The new dossier information therefore makes the "relative to expectations" instruction substantially more concrete.

---

## Problem 2 — Positive predictions remained too aggressive

The positive rules added during v1 solved a genuine problem, but some subsequently produced the opposite calibration issue.

The August 10 analysis had already identified this possibility: an adequate quarter from an out-of-favor company should not automatically justify something like a +8% to +25% abnormal-return estimate unless the announcement actually removes a major thesis or liquidity overhang.

## Change — Softer positive global rules

Positive abnormal-return ranges in the global framework were therefore moderated.

Large positive estimates now require stronger evidence of a genuinely material belief revision.

For example, a strong positive tail should generally require some combination of:

```text
large unexpected improvement
        +
persistent effect
        +
higher forward earnings path
        +
major guidance change / thesis change
```

Simply reporting a good quarter, beating estimates modestly, or showing stabilization is not sufficient by itself.

The purpose of the change is not to eliminate positive tails. It is to make the **magnitude of the prediction proportional to the magnitude of the new information**.

---

## Problem 3 — We needed better visibility into why predictions succeed or fail

The outcomes ledger was originally designed to support a feedback loop, and early diagnostics demonstrated its usefulness.

For example, logging `rules_applied` makes it possible to calculate prediction error conditional on individual rules and determine whether those rules actually add value.

As the system became more complex, however, the original ledger was no longer sufficient to explain every prediction.

## Change — Expanded prediction metadata

v3 therefore added additional metadata to the prediction ledger.

The expanded ledger is intended to make it easier to reconstruct:

```text
What information did the model have?
        ↓
What did it predict?
        ↓
Which logic contributed?
        ↓
What actually happened?
        ↓
Where did the prediction fail?
```

This allows future analysis to move beyond aggregate prediction error toward diagnostics by prompt version, rule usage, prediction characteristics, industry, confidence, and other stored metadata.

---

# Current State

The progression from v0 through v3 can be summarized as:

```text
v0
Build context around thin event bullets
│
├── global rules
├── industry playbooks
├── ticker dossiers
└── prediction ledger
        ↓
v1
Early results reveal negative bias + rule-snapping
│
├── preserve strong disaster detection
├── add positive logic
└── predict abnormal return before percentile
        ↓
v2
Positive predictions return, but distribution becomes bimodal
│
├── remove numerical ranges from industry rules
├── make industry rules directional
├── restore global materiality/expectation gates
├── make neutral a legitimate outcome
└── shrink conflicting evidence toward zero
        ↓
v3
Improve expectation baseline and calibration
│
├── add current analyst EPS estimates
├── add forward analyst EPS estimates
├── soften positive abnormal-return rules
└── expand prediction-ledger metadata
```

The architecture has therefore evolved from a **rule-driven percentile predictor** toward a system in which the model is asked to estimate a continuous belief revision using increasingly structured information about what investors knew before the announcement.

The central idea remains the same as in v0, but the implementation has become increasingly explicit:

> **The relevant question is not whether an earnings announcement is good or bad. It is how much the announcement should change investor beliefs relative to what was already expected.**

Future versions should continue to be driven by the same loop:

```text
Predict
   ↓
Record
   ↓
Observe realized outcomes
   ↓
Diagnose systematic errors
   ↓
Change one identifiable part of the system
   ↓
Compare
```