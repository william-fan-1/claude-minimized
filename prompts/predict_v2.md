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

# Task

Your task is to predict what percentile the stock's next day trading performance will fall in relative to the market.

---

# Summary of the Earnings Call

{summary_text}

# Prediction Objective

You are predicting **belief revision**, not company performance. Strong results
can be neutral when already priced; weak results can be positive when the market
feared worse.

# This company's dossier

**`prior_reactions` and `reaction_statistics`** — how this stock has actually
behaved on its own earnings days, measured net of the market exactly as this
competition scores. Use it for **magnitude and asymmetry, not direction**.

**`forward_estimates`, when present** — consensus analyst estimates: `eps_avg`
with its `low`/`high` range, the number of analysts, `eps_year_ago`, and recent
estimate revisions. **This is the expectations baseline.** When it is here, use
it.

**If the `forward_estimates` block is absent, you have no consensus baseline.**

{dossier}

# Industry Trends

These are observed trends in the industry to consider before making a prediction.

{industry_rules}

---

# Global Observations

These are selected empirical patterns that may be useful context. They are neither exhaustive nor deterministic; assess their relevance alongside all available evidence.
{global_rules}

---

# Output

Return JSON only, with the keys in exactly this order. The order matters: you
are establishing the facts before you interpret them.

```json
{
  "relevant_context": ["<trend or observation ID, only if materially relevant>"],
  "predicted_percentile": <number between 0 and 1>
}
```