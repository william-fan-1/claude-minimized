<!--
=============================================================================
predict_v0.md — live prediction prompt
Explaining Markets · Q3 2026 · version 0.1.0 · owner: ahi · added 2026-08-03
=============================================================================

PLACEHOLDERS TO SUBSTITUTE AT CALL TIME
  {event_bullets}   the fact bullets delivered by the platform webhook
  {dossier}         cached ticker dossier (knowledge/tickers/<TICKER>.yaml)
                    omit the section entirely if no dossier exists
  {core_directive}  the `principles` block from knowledge/playbooks/_global.yaml
  {industry_rules}  rules pre-filtered by industry + company profile.
                    Global rules + the matching industry playbook ONLY.
                    Do not dump the full rulebook — it dilutes attention
                    and wastes tokens.

OUTPUT CONTRACT
  Model returns JSON only. Parse `percentile` -> predicted_percentile.
  Log `confidence`, `top_drivers`, `rules_applied` to the outcomes ledger.

INTEGRATION NOTES FOR predict()
  1. NORMALIZE THE SCALE. Published model cards for the baselines note that
     models occasionally emit the percentile on a 0-100 scale instead of 0-1.
     Guard for it: if value > 1, divide by 100. Then clamp to [0, 1].
  2. FALL BACK, DON'T CRASH. If the model call fails or JSON parsing fails,
     return 0.5 and log the error. A neutral prediction scores nothing but
     costs nothing; a missed submission reduces our coverage, and the
     leaderboard reports prediction counts.
  3. VERSION EVERY CALL. Write prompt_version into the ledger with each
     prediction so we can attribute ΔR² changes to specific prompt edits.
  4. ONE CALL PER EVENT. No chained calls, no live retrieval inside the
     5-minute window. Everything expensive happens in the overnight cache job.
=============================================================================
-->

## Task

Estimate where this stock's next-day ABNORMAL (market-adjusted) return will fall in the cross-section of ALL earnings announcements this quarter (~1,800 events).

Output a percentile from 0.00 to 1.00.

- 0.00 = most negative reaction of the quarter
- 0.50 = completely typical reaction
- 1.00 = most positive reaction of the quarter

Your job is RELATIVE RANKING, not predicting a percentage move. Use the full range where the evidence supports it. Roughly 10% of events deserve above 0.85 and 10% below 0.15 — but a genuinely ambiguous event belongs near 0.50. Forcing conviction you do not have is worse than admitting uncertainty: it adds noise without adding signal. Reserve the tails for events where the read is clear.

## Core directive

{core_directive}

## Calibration anchors

| Percentile | What it looks like |
|---|---|
| 0.05 | Severe guidance cut, or a broken core-business thesis |
| 0.20 | Beat on headline but forward guide clearly below expectations |
| 0.35 | In-line quarter, cautious tone, no catalyst |
| 0.50 | Solid quarter that meets already-high expectations |
| 0.65 | Clean beat plus a modest raise, credible and well received |
| 0.80 | Meaningful raise with genuine positive surprise on a key driver |
| 0.95 | Shock: large guidance raise, transformative announcement, or reversal of a widely-held negative thesis |

## Event bullets

{event_bullets}

## Company dossier

{dossier}

## Applicable playbook rules

{industry_rules}

## Reasoning steps

Work through these in order before answering.

1. **What was already expected going into this call?** Use the dossier's consensus, guidance trajectory, and analyst focus items. If no dossier is available, reason from the bullets about what a company like this would be expected to deliver.
2. **What in these bullets is genuinely NEW information?** Separate the new from the merely confirmatory. Most of a call confirms what was already assumed.
3. **What is the direction and magnitude of the belief revision** that the new information causes? This — not the quality of the results — is what gets priced.
4. **How does THIS stock historically react to news like this?** Check `prior_reactions` and `reaction_profile` in the dossier. Some stocks are poorly rewarded for beats and heavily punished for misses.
5. **Which playbook rules fire?** If rules conflict, apply the precedence order: more specific beats more general, negative operational specifics beat positive narratives, guidance beats headline results.

## Output

Return JSON only. No preamble, no commentary outside the object.

```json
{
  "predicted_percentile": 0.00,
  "direction": "up | neutral | down",
  "confidence": "high | medium | low",
  "top_drivers": ["driver one", "driver two", "driver three"],
  "rules_applied": ["GLB-EXPECT-01", "GLB-GUID-01"]
}
```

`rules_applied` must list the IDs of every rule that materially influenced the answer. The overnight job uses this to score which rules actually work against realized outcomes and retire the ones that don't.
