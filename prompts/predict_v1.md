<!--
=============================================================================
predict_v1.md — live prediction prompt
Explaining Markets · Q3 2026 · version 1.0.0 · owner: ahi · 2026-08-06
=============================================================================

WHAT CHANGED FROM v0.1 AND WHY
Driven by the Aug 6 scored results (see docs/EM-Diagnostics-Aug6.md).

1. THE MODEL NOW ESTIMATES AN ABNORMAL RETURN FIRST, THEN CONVERTS.
   In v0 the model picked a percentile directly, which caused it to
   pattern-match a rule and emit that rule's range. Our predictions
   collapsed onto ~8 distinct values (0.15, 0.12, 0.88, 0.90...), which
   turned a continuous forecast into a coarse classifier and destroyed
   within-bucket ranking. Reasoning in return space is continuous and
   intuitive; the percentile conversion is then mechanical.

2. ADDED THE EMPIRICAL CONVERSION TABLE, built from our own scored
   results. It encodes the fact that killed us: a flat stock is 0.50, and
   an ordinary company drifting up 2-3% is 0.61-0.70 — NOT 0.15.

3. EXPLICIT WARNING ABOUT RULEBOOK ASYMMETRY. Our playbook has 8 negative
   setters vs 2 positive, so the model must not infer that the market is
   mostly negative. Roughly half of all events land above 0.50.

4. ANTI-SNAPPING INSTRUCTION plus two-decimal output.

PLACEHOLDERS (unchanged from v0)
  {event_bullets} {core_directive} {industry_rules} {dossier}

OUTPUT CONTRACT — NOTE THE FIELD NAME CHANGE FOR THE HARNESS
  The model returns `percentile`. The competition API expects
  `predicted_percentile`. Map it explicitly — this mismatch silently cost
  us two days of predictions. Also: if the value is > 1, divide by 100,
  then clamp to [0, 1]. On any failure return 0.5 and log.

  Log `expected_abnormal_return_pct` to the ledger as well — it lets us
  diagnose whether errors come from the return estimate or the conversion.
=============================================================================
-->

## Task

You are forecasting how a stock will react to its earnings announcement.

Work in two steps. **First** estimate the stock's abnormal return — its move on the next trading day, net of the overall market. **Then** convert that estimate to a percentile using the table below.

Do not skip to the percentile. The return estimate is the reasoning; the percentile is arithmetic.

## Step 1 — Estimate the abnormal return

Ask plainly: **by what percent will this stock move, relative to the market, on the day after this announcement?**

Anchor yourself in reality. The great majority of earnings reactions fall between −8% and +8%. Moves beyond ±15% require something genuinely dramatic — a shattered thesis, a transformative announcement, a guidance change large enough to reset the forward model.

A company that reports a perfectly adequate quarter with no real surprise typically drifts somewhere between −1% and +3%. That is the single most common outcome. It is not a dramatic event and must not be forecast as one.

## Step 2 — Convert to a percentile

| Percentile | Abnormal return |
|---|---|
| 0.99 | +33% |
| 0.95 | +19% |
| 0.90 | +12% |
| 0.85 | +8% |
| 0.80 | +6% |
| 0.75 | +4.7% |
| 0.70 | +3.4% |
| 0.65 | +2.7% |
| 0.60 | +1.9% |
| 0.55 | +1.0% |
| **0.50** | **0.0%** |
| 0.45 | −0.7% |
| 0.40 | −1.6% |
| 0.35 | −2.6% |
| 0.30 | −3.7% |
| 0.25 | −4.7% |
| 0.20 | −6.6% |
| 0.15 | −8.8% |
| 0.10 | −12% |
| 0.05 | −17.5% |
| 0.01 | −31% |

Interpolate between rows. Report two decimal places.

Note how compressed the middle is: the entire band from 0.45 to 0.55 spans less than two percentage points of return. Small differences in your return estimate matter a great deal there, so estimate carefully rather than defaulting.

## Core directive

{core_directive}

## Reasoning steps

1. **What was already expected going into this call?** Use the dossier's consensus, guidance trajectory and analyst focus. Without a dossier, reason about what a company like this would be expected to deliver.
2. **What here is genuinely NEW?** Most of a call confirms existing assumptions. Isolate what actually changes the picture.
3. **How much does that revision move the forward path?** Small revision, small move. Only a reset of the earnings or growth outlook produces a double-digit move.
4. **How does THIS stock react to news like this?** Check `prior_reactions` and `reaction_profile`. A name that habitually moves 1% on earnings will not move 15% now.
5. **Now commit to a number.** State the expected abnormal return in percent, then convert.

## Calibration discipline

Use the full range **where the evidence supports it**. Roughly 10% of events deserve above 0.85 and 10% below 0.15 — but a genuinely ambiguous event belongs near 0.50. Forcing conviction you do not have is worse than admitting uncertainty: it adds noise without adding signal. Reserve the tails for events where the read is clear.

Equally: do not let a mildly cautious tone drag an ordinary quarter into the bottom decile. The bottom decile means the stock fell **more than 12%**. Ask yourself whether you actually believe that before going there.

## Output

Return JSON only. No preamble, no commentary outside the object.

```json
{
  "expected_abnormal_return_pct": 0.0,
  "predicted_percentile": 0.00,
  "direction": "up | neutral | down",
  "confidence": "high | medium | low",
  "top_drivers": ["driver one", "driver two", "driver three"],
  "rules_applied": ["GLB-EXPECT-01"]
}
```

`predicted_percentile` must be consistent with `expected_abnormal_return_pct` per the conversion table. `rules_applied` must list every rule that materially influenced the estimate — this is what lets us score which rules work and retire the ones that don't.

## How to use the playbook rules

Three instructions on applying these, and they matter:

**Rules inform your return estimate. They do not replace it.** When a rule fires, ask what it implies about the *size* of the move, then estimate that move. Never output a rule's range as your answer.

**The rulebook is deliberately asymmetric and you must correct for it.** It contains far more rules describing negative outcomes than positive ones, because negative patterns are easier to specify. This does not mean the market is mostly negative. **Roughly half of all earnings events produce a positive abnormal return.** If your reasoning keeps landing on negative outcomes for ordinary companies, you are over-applying the rulebook.

**Rules need materiality to fire.** Nearly every earnings call contains some cautious phrasing, some one-time item, some soft segment. That is normal and is already priced. A rule should only fire when the condition is *material and represents a change* from what the market already expected — not merely because the words appear somewhere in the transcript.

{industry_rules}

## Company dossier

{dossier}

## Event bullets

{event_bullets}