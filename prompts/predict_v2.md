<!--
=============================================================================
predict_v2.md — live prediction prompt
Explaining Markets · Q3 2026 · version 3.0.0 · owner: ahi · 2026-08-13

v3.0.0 restructures the order of reasoning. Through v2.1.0 the model read
~30,000 characters of rules, anti-patterns and precedence logic BEFORE it
reached a single fact about the company, and the output schema let it name a
rule before it had written down what the quarter actually said. The result was
a classifier: find the nearest matching rule, emit its range.

Two changes fix that. The announcement now comes first, and the output schema
forces the model to extract and interpret the facts before it is permitted to
reference any rule. Because generation is sequential, the schema order is what
actually constrains the reasoning.

Also new: conviction is now binding. It sets how far from 0.50 the model is
allowed to go. Conditional shrinkage of this kind reorders predictions and
therefore moves R², unlike a uniform shift, which provably does not.
=============================================================================
-->

## Task

Forecast this stock's next-trading-day abnormal return — its return net of the
overall market — and express it as a percentile against every other earnings
event this quarter.

Work in this order and do not skip ahead. Read the announcement and establish
what it says. Only then consult the frameworks below. A framework tells you how
to weigh a fact; it cannot tell you what the facts are.

---

# STEP 1 — The announcement

Read this before anything else in this document.

{summary_text}

---

## STEP 2 — Extract, before you judge

Write down what the announcement actually reports. Quote figures verbatim where
they are given. You will be asked to output this before you output an estimate.

- **Headline results** — revenue, earnings, margin, and their direction and size.
- **Forward guidance** — raised, lowered, reaffirmed, withdrawn, or not mentioned.
  This is the single most important item on the page. If guidance is absent from
  the summary, say so rather than inferring it.
- **Quality of the result** — is the headline flattered or depressed by anything
  non-recurring, one-off, or accounting-driven?
- **Discrete events** — contracts, approvals, financings, departures, buybacks,
  restructurings. Note whether the economics are quantified or merely announced.
- **What is conspicuously absent** — a metric management used to give and no
  longer does is itself information.

## STEP 3 — What did the market already expect?

You are predicting **belief revision**, not company performance. Strong results
can be neutral when already priced; weak results can be positive when the market
feared worse.

Be honest about the limits here. Where a rule asks you to compare against a
baseline you have not been given, **say that the baseline is unavailable and
weight that rule down.** Do not invent it from the tone of the writing —
inferring "the market expected more" from cautious phrasing is fabrication, and
it has been our most expensive habit.

### This company's dossier

{dossier}

**`prior_reactions` and `reaction_statistics`** — how this stock has actually
behaved on its own earnings days, measured net of the market exactly as this
competition scores. Use it for **magnitude and asymmetry, not direction**. A
name whose `median_absolute_reaction_pct` is 2 rarely moves 15%. Where several
quarters show a consistent pattern — punishing misses far harder than it rewards
beats, say — treat that as a mild prior. Fewer than four observations is not a
pattern.

**`forward_estimates`, when present** — consensus analyst estimates: `eps_avg`
with its `low`/`high` range, the number of analysts, `eps_year_ago`, and recent
estimate revisions. **This is the expectations baseline.** When it is here, use
it: compare what was reported against `eps_avg`, and read the `low`–`high`
spread as how much disagreement there was. A beat against a tight range with
many analysts is a different event from a beat against a wide range with three.
A dense cluster of downward `eps_revisions_last_30d` means expectations had
already been walked down, so an in-line result is less bad than it looks.

Two cautions. Check that the estimate period actually corresponds to the quarter
being reported — if it plainly refers to a different period, say so and fall
back to treating the baseline as unavailable. And `as_of` records when the
estimates were captured; if it is far from this announcement, treat them as
indicative rather than precise.

**If the `forward_estimates` block is absent, you have no consensus baseline.**
Say so, and weight expectation-dependent rules down accordingly.

### Industry context

This tells you which metrics matter for this business and which way they cut. It
does not set magnitude, and a trigger matching is not by itself a reason to
leave the middle of the distribution.

{industry_rules}

---

## STEP 4 — Now apply the framework

You should already know what the quarter said. Use the rules to weigh it.

### Core principles

{core_directive}

### Rules

{global_rules}

### Anti-patterns — these override a matching rule

{anti_patterns}

### Resolving conflicts

{precedence}

---

## STEP 5 — Commit to an abnormal return

Ask plainly: **by what percent will this stock move, relative to the market, on
the day after this announcement?**

Anchor yourself in reality:

- **Roughly half of all events land between −3% and +3%.** Most companies report
  a quarter that broadly confirms what was already believed. That is the modal
  outcome, not a failure to find the signal.
- Beyond ±8% is unusual and needs a nameable cause — a shattered thesis, a
  transformative announcement, a guidance change large enough to reset the
  forward model.
- An ordinary quarter in which you simply found nothing wrong is an estimate
  near **0%**, not near +10%.

### The quote test

Before committing to an estimate beyond ±6%, name the specific figure from the
announcement that justifies it. Management tone, a generally upbeat call, and
the absence of bad news are not figures. If you cannot quote one, pull the
estimate back inside ±6%.

The bar is higher on the upside. Our positive calls have been materially less
reliable than our negative ones, so require more evidence before committing to a
strong positive than you would to a strong negative.

## STEP 6 — Direction and conviction

**Direction** is the sign of your estimate: `up`, `neutral` (inside roughly
±1%), or `down`.

**Conviction** is how much the facts support that direction, and it is binding —
it caps how far from 0.50 you may go:

| Conviction | Means | Permitted percentile range |
|---|---|---|
| `high` | You can quote specific figures that make both direction and rough magnitude clear. Guidance moved materially, or a quantified event resets the forward model. | **0.02 – 0.98** (full range) |
| `medium` | Direction is clear from the facts, magnitude is uncertain. | **0.20 – 0.80** |
| `low` | Evidence is thin, mixed, substantially offsetting, or rests on tone rather than figures. | **0.35 – 0.65** |

If you find yourself wanting a percentile outside the band your conviction
allows, you do not have the evidence for it. Lower the percentile, not the
standard. Forcing conviction you do not have adds noise without adding signal.

## STEP 7 — Convert to a percentile

Convert the abnormal return using this table, interpolating between rows, then
clamp the result into the band your conviction permits.

| Percentile | Abnormal return | | Percentile | Abnormal return |
| --- | --- | --- | --- | --- |
| 0.99 | +33% | | 0.45 | −0.7% |
| 0.95 | +19% | | 0.40 | −1.6% |
| 0.90 | +12% | | 0.35 | −2.6% |
| 0.85 | +8% | | 0.30 | −3.7% |
| 0.80 | +6% | | 0.25 | −4.7% |
| 0.75 | +4.7% | | 0.20 | −6.6% |
| 0.70 | +3.4% | | 0.15 | −8.8% |
| 0.65 | +2.7% | | 0.10 | −12% |
| 0.60 | +1.9% | | 0.05 | −17.5% |
| 0.55 | +1.0% | | 0.01 | −31% |
| 0.50 | 0.0% | | | |

---

## Output

Return JSON only, with the keys in exactly this order. The order matters: you
are establishing the facts before you interpret them.

```json
{
  "key_metrics": ["<figure quoted from the announcement>", "<figure>", "<figure>"],
  "guidance": "raised | lowered | reaffirmed | withdrawn | not_mentioned",
  "result_quality": "<one line: is the headline flattered, depressed, or clean?>",
  "expectation_gap": "<one line: what changed versus what was already believed, and whether you could actually observe the baseline>",
  "rules_applied": ["<materially influential rule ID>"],
  "expected_abnormal_return_pct": <number>,
  "direction": "up | neutral | down",
  "confidence": "high | medium | low",
  "predicted_percentile": <number between 0 and 1>
}
```

`expected_abnormal_return_pct` and `predicted_percentile` must agree under the
conversion table, and `predicted_percentile` must lie inside the band your
`confidence` permits. List only rules that materially influenced the estimate —
an empty list is a valid and honest answer.
