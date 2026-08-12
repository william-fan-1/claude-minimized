<!--
=============================================================================
predict_v1.md — live prediction prompt
Explaining Markets · Q3 2026 · version 2.0.0 · owner: ahi · 2026-08-06

A version of v1 that was edited for brevity and removed rules surrounding
"target allocations" to percentiles and more mild "surprise returns"
============================================================================= 
-->

## Task

Forecast the stock's next-trading-day abnormal return: its return net of the
overall market. Estimate the abnormal return first, then convert it to a
percentile using the table below. Do not reason directly in percentile space.

## Core directive

{core_directive}

## Estimation procedure

1. Compare the announcement with what the market likely expected.
2. Identify material new information that changes the persistent forward path.
   Discount immaterial, transitory, previously known, or offsetting information.
3. Use global rules to calibrate the base estimate and industry rules to
   identify relevant directional evidence. Industry evidence affects magnitude
   only to the extent that it is surprising, material, persistent, and
   unoffset. A trigger match alone does not require moving away from neutral.
4. Use `prior_reactions`, when available, as a magnitude and
   asymmetry prior. 
5. Commit to one abnormal-return estimate. An ordinary quarter with no material
   belief revision should remain near zero; typical is ±3%, beyond ±8% is unusual and needs a nameable cause
6. Ask plainly: by what percent will this stock move, relative to the market, on the day
   after this announcement?

   Anchor yourself in reality. Typical is ±3%, beyond ±8% is unusual and needs a nameable cause — a shattered thesis, a transformative announcement, a guidance change large enough to reset the forward model.

## Return-to-percentile conversion

| Percentile | Abnormal return |
| ---------- | --------------- |
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
| 0.50 | 0.0% |
| 0.45 | -0.7% |
| 0.40 | -1.6% |
| 0.35 | -2.6% |
| 0.30 | -3.7% |
| 0.25 | -4.7% |
| 0.20 | -6.6% |
| 0.15 | -8.8% |
| 0.10 | -12% |
| 0.05 | -17.5% |
| 0.01 | -31% |

Interpolate between rows and report the percentile to two decimal places.

## Precedence

{precedence}

## Anti-patterns

{anti_patterns}

# Global rules

{global_rules}

## Playbook rRles

{industry_rules}

## Company dossier

{dossier}

## Earnings summary

{summary_text}

## Output

Return JSON only:

{
  "expected_abnormal_return_pct": "<number>",
  "predicted_percentile": "<number from 0 to 1>",
  "direction": "up | neutral | down",
  "confidence": "high | medium | low",
  "top_drivers": ["<driver one>", "<driver two>", "<driver three>"],
  "rules_applied": ["<materially influential rule ID>"]
}

The return and percentile must agree. List only rules that materially influenced
the estimate.