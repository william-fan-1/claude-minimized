# Diagnosing and Reducing Rule-Snapping in Earnings Predictions

## Background

Recent changes to the global and industry rulebooks successfully reduced the model's overwhelming negative bias and restored positive predictions. However, based on initial results from the morning of August 10 (Day 1), the prediction distribution remains overly concentrated in the tails: the model appears to avoid much of the middle approximately 60% of the percentile range and may still be snapping estimates to prescribed rule intervals.

The objective of the next revision is therefore not simply to make predictions less negative. It is to make estimates more continuous, preserve the middle of the distribution for ordinary or mixed quarters, and reserve tail forecasts for genuinely material belief revisions.

## Diagnosis

The industry playbook itself strongly encourages a bimodal distribution. Across 123 industry rules:

- 81 rules (66%) have ranges lying wholly outside the central 0.30–0.70 percentile region.
- Only 15 rule midpoints fall between 0.30 and 0.70.
- No rule midpoint falls between 0.40 and 0.50.
- Only one rule midpoint falls between 0.50 and 0.60.
- Most midpoints cluster around 0.10–0.30 or 0.70–0.90.

Thus, although the prompt describes the ranges as calibration references rather than prediction setters, the numerical examples presented to the model are overwhelmingly tail-oriented. The model can follow a simple classification process: identify the closest industry narrative, select its prescribed range, and choose a value within that range.

Several other design choices reinforce this behavior:

1. **Industry-over-global precedence.** The current rule that a more specific industry rule overrides a global rule can displace the global neutral and expectations rules whenever an announcement contains a recognizable industry KPI. Because nearly every earnings announcement discusses items such as volume, pricing, margins, costs, backlog, retention, or guidance, industry rules are likely to appear applicable even when the development is modest or expected.

2. **Setter terminology.** Most directional global rules are defined as setters that establish the base estimate. Once a trigger is recognized, the model is encouraged to begin inside the associated range instead of treating the rule as one piece of evidence.

3. **Explicit ranges beside triggers.** Each industry rule contains both an abnormal-return range and a percentile range. These anchors are then reinforced by the conversion map in the industry file and the conversion table in the main prompt. Instructions to estimate continuously are less salient than repeated concrete numerical associations.

4. **Residual definition of neutral.** The neutral rule applies when no other rule fires cleanly. This makes neutrality a fallback for unclassifiable events rather than the correct result whenever recognized positive and negative developments are expected, modest, or offsetting.

5. **Mechanical conflict resolution.** The instruction to take the midpoint when equally specific setters conflict directly encourages canned values. Mixed evidence should instead be netted in return space and generally shrink the estimate toward zero unless one side clearly dominates.

6. **Aggressive positive setters.** The rules added to correct negative bias frequently prescribe high positive ranges. This appears to have changed the model from a negative-heavy classifier into a more symmetric two-tail classifier. In particular, an adequate quarter from an out-of-favor company may not justify an automatic +8% to +25% abnormal-return estimate unless it decisively removes a major thesis or liquidity overhang.

## Preferred Redesign

### 1. Retain mild ranges only in the global rules

Broad global ranges can provide useful calibration for general classes of outcomes, especially:

- ordinary or adequately in-line quarters;
- modest positive or negative belief revisions;
- material guidance changes;
- rare thesis-changing events.

These ranges should be broad and mild enough to communicate the relative scale of the event without turning the rules into narrow output bins. More extreme global ranges should require explicit, quantified, thesis-changing evidence.

This preserves a common magnitude framework across companies and industries while limiting the number of numerical anchors shown to the model.

### 2. Convert industry rules into directional considerations

Industry rules should primarily identify:

- which KPIs matter in that industry;
- whether a development is generally positive or negative;
- what makes the signal persistent or transitory;
- what evidence would strengthen, weaken, or offset the signal.

They should generally not prescribe abnormal-return or percentile ranges. For example:

```yaml
- id: COMMERCIAL_PRODUCTS_1
  trigger: >
    Volume growth with maintained or expanded margins despite material
    tariff or input-cost pressure.
  implication: positive
  severity_basis: >
    Stronger when both the volume surprise and margin resilience exceed
    prior expectations and support a higher forward earnings path.
```

The model would then use the global framework to determine magnitude after considering expectations, materiality, offsets, and the company dossier.

### 3. Soften industry-over-global precedence

Industry knowledge should determine which operating evidence is relevant, but it should not override the global expectation, materiality, offset, or neutral gates.

A revised precedence rule could state:

```yaml
- order: 1
  rule: >
    Global rules and principles determine the base estimate and remain binding.
    Industry rules provide directional evidence based on the KPIs most relevant
    to the company, but do not override global expectation, materiality,
    persistence, offset, or neutral judgments. Use an industry's severity_basis
    to adjust the magnitude of the estimate in the indicated direction only to
    the extent that the evidence is surprising, material, persistent, and
    supported by the announcement. A trigger match alone does not justify
    leaving the middle of the distribution.
```

This retains the value of industry expertise without allowing specificity alone to determine forecast magnitude.

### 4. Make neutral a competing outcome, not a residual outcome

The model should be allowed to recognize an industry trend while still forecasting near neutral. A quarter can contain modest volume strength, normal margin pressure, or a small guidance change without materially revising investor beliefs.

The neutral rule should therefore apply whenever the net belief revision is small, including when directional rules match but are expected, immaterial, transitory, or substantially offset.

### 5. Replace midpoint conflict resolution with shrinkage

When material positive and negative signals conflict, the model should assess their relative impact on the forward earnings path. If neither clearly dominates, it should shrink the estimate toward zero rather than average prescribed rule ranges.

## Alternative: Add Neutral Industry Rules

Adding neutral or moderate scenarios to every industry would make the numerical examples less bimodal. However, this is likely inferior to removing industry-level ranges:

- It increases an already long prompt.
- It adds more triggers for the model to classify against.
- It preserves the underlying tendency to select a rule and copy its range.
- Neutrality is fundamentally a judgment about surprise and materiality, not a separate industry-specific narrative.
- Similar neutral language would need to be repeated across many industries.

A small number of industry-specific neutral examples could be tested if particular sectors have genuinely distinctive in-line outcomes. However, the default solution should be to make industry rules directional and let the global framework own magnitude and neutrality.

## Recommended Initial Changes

For afternoon of August 10:

- Retain mild global ranges but removes all `abnormal_return_pct` and `percentile_range` fields from industry rules.
- Industry triggers, directional implications, rationales, and severity conditions remain unchanged.
- Global expectation, materiality, offset, and neutral principles explicitly remain binding.
- Only one return-to-percentile conversion table is provided, after the return estimate is complete.

Compare results from the morning with later results on:

- share of predictions in the central 0.20–0.80 and 0.30–0.70 regions;
- frequency of repeated values or values near former rule midpoints and boundaries;
- mean and dispersion of predicted abnormal returns;

If the treatment produces excessive compression near 0.50, introduce a short global magnitude rubric rather than restoring numerical ranges to every industry rule.