# Diagnostics — Aug 4–6 Results
**Date:** August 6, 2026 · **Sample:** ~330 scored events, of which Aug 6 (~250) is the first batch with rules genuinely running

> Aug 4 and most of Aug 5 are contaminated by the JSON parsing bug — those are hardcoded 0.5 and contribute nothing to ΔR². **The real evidence is the Aug 6 batch.** Everything below is drawn from it.

---

## 1. Headline: the rulebook is half-built, not broken

The single most useful pattern in the data is an asymmetry, and it's very clean.

**Where we are excellent — genuine disasters.** Compare our absolute error to the field's median error on the same event:

| Ticker | Predicted | Actual | CAR | Our error | Field median |
|---|---|---|---|---|---|
| UWMC | 0.00 | 0.00 | −34.6% | **0.00** | 0.45 |
| CDLX | 0.00 | 0.08 | −13.8% | **0.08** | 0.42 |
| TEAD | 0.00 | 0.06 | −15.7% | **0.06** | 0.11 |
| PZZA | 0.00 | 0.06 | −17.0% | **0.06** | 0.11 |
| INSG | 0.05 | 0.01 | −28.4% | **0.04** | 0.11 |
| ANGI | 0.00 | 0.02 | −22.6% | **0.02** | 0.46 |

We are beating the field decisively on catastrophes. CDLX is the standout — a **+13.2% earnings surprise** and the stock fell 13.8%. Most competitors were fooled; our rules weren't. That's exactly the "beat but the guidance/quality is rotten" logic working as designed.

**Where we are terrible — positive surprises.**

| Ticker | Predicted | Actual | CAR | Our error | Field median |
|---|---|---|---|---|---|
| HTZ | 0.05 | 0.98 | +29.6% | **0.93** | 0.39 |
| GTM | 0.03 | 0.91 | +13.3% | **0.88** | 0.58 |
| FWRD | 0.05 | 0.93 | +15.7% | **0.88** | 0.34 |
| TRUP | 0.08 | 0.93 | +15.6% | **0.85** | 0.43 |
| PAYS | 0.15 | 0.98 | +29.5% | **0.83** | 0.28 |
| ZVRA | 0.08 | 0.91 | +13.0% | **0.83** | 0.46 |
| BKSY | 0.05 | 0.88 | +10.5% | **0.83** | 0.23 |
| OPRT | 0.18 | 0.99 | +33.0% | **0.81** | 0.27 |

**The diagnosis writes itself.** Count the rules in `_global.yaml`: eight setters that push predictions *down* (GUID-01/02/03, QUAL-01/02/03/04, TONE-01) versus **two** that push up (EXPECT-03, GUID-04). Most modifiers are negative too, and `Q3-CAL-02` adds another −0.05 to anything resembling a miss.

We built a disaster detector, not a return predictor. It works beautifully at what it does. It's simply blind in one direction.

---

## 2. Rule-snapping — the model is classifying, not reasoning

Look at the distinct values we actually emit. Sorted by frequency, our predictions pile up at **0.15, 0.12, 0.18, 0.08, 0.10, 0.05, 0.00** on the low side and **0.88, 0.90, 0.92, 0.95** on the high side.

Those aren't reasoned estimates. They're our rule ranges:

- `GLB-QUAL-03` says apply 0.10–0.20 → model emits **0.15** (the midpoint)
- `GLB-GUID-01` says 0.12–0.28 → model emits **0.12** or **0.18**
- `GLB-EXPECT-03` says 0.85–0.97 → model emits **0.88/0.90/0.92**

The model is pattern-matching a transcript to a rule, then emitting the range. It never reasons about *magnitude within* the range.

**Why this caps our score.** We are effectively running an 8-bucket classifier against a continuous, uniform target. All within-bucket discrimination — which is where most of the available R² lives across ~1,800 events — is thrown away before we start.

---

## 3. The calibration error that explains most of the damage

This is the big one, and it's fixable in one edit.

I built an empirical map from the scored data — realized abnormal return (CAR1) against realized percentile:

| Percentile | CAR needed |
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
| **0.50** | **≈ 0.0%** |
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

**Read what this means.** A stock that closes dead flat is at **0.50**. A stock that drifts up an unremarkable **+2%** is at **0.61**. A stock that drifts up **+3.4%** is at **0.70**.

Now look at what we did to exactly those events:

| Ticker | CAR | Actual | We said |
|---|---|---|---|
| TRGP | +3.3% | 0.69 | **0.15** |
| WTI | +2.9% | 0.67 | **0.12** |
| REPX | +3.4% | 0.69 | **0.10** |
| CHRD | +2.1% | 0.61 | **0.18** |
| MGY | +4.5% | 0.74 | **0.03** |
| HMN | +4.0% | 0.73 | **0.12** |
| FNF | +3.0% | 0.67 | **0.15** |
| PRI | +2.0% | 0.60 | **0.15** |

These aren't dramatic events. They're **ordinary companies having perfectly fine quarters and drifting up two or three percent.** The correct answer is 0.60–0.72. We said 0.10–0.18 every time.

**The mechanism:** almost every earnings call contains *some* cautionary language, *some* one-time item, *some* soft segment. Our triggers are written without materiality thresholds, so they fire on ordinary quarters — and then the model snaps to the range midpoint. An unremarkable quarter with mild hedging gets 0.15 instead of 0.60.

That's a ~0.50 error on a large fraction of the sample, and it's the dominant source of our damage.

---

## 4. What is NOT the problem

**Bias itself is not the problem.** The scoring regression absorbs scale and intercept, so a uniform downward shift costs nothing in R². Don't spend effort "centering" the predictions.

What the bias costs us is **resolution**: roughly 60% of our predictions sit below 0.30, compressed into a narrow band where they become mutually indistinguishable. That's the real damage — not the level, the crowding.

**The middle-zone question from yesterday is now settled empirically.** The band 0.45–0.55 corresponds to CAR between −0.7% and +1.0%. That's a genuinely dense part of the distribution — plenty of real events belong there. Our problem was never that we used the middle too much. We barely used it at all.

---

## 5. Options

### Option A — Recalibrate the prompt (recommended, do immediately)
Have the model estimate the **abnormal return in percent** first, then convert to a percentile via the table above.

This structurally kills rule-snapping, because return estimates are continuous and intuitive while the conversion is mechanical. It also fixes the "fine quarter = 0.15" error directly, since the model must ask "will this stock move −8% or +2%?" rather than "which rule fires?"

Cost: one prompt edit. Risk: low. Expected impact: largest of the three.

### Option B — Rebalance the rulebook (do this week)
Add positive setters to match the negative ones, and add materiality thresholds to the existing triggers so they stop firing on ordinary quarters. Convert setters from *ranges* to *adjustments off a 0.50 baseline*.

Cost: a few hours on the YAML. Risk: medium — we could break what's currently working on disasters.

### Option C — A/B test with the spare agent slots
We're allowed **five agents per account**. Run the current build unchanged as a control alongside the recalibrated version. Same events, same scoring, direct comparison.

This is the only option that produces evidence rather than opinion, and we have the infrastructure sitting unused.

---

## 6. Recommendation

1. **Compute actual ΔR² on the Aug 6 batch before changing anything.** Yuvraj has the scoring code. We're reasoning from error patterns; we should know the real number. It's plausible we're currently *negative* versus the surprise baseline.
2. **Ship Option A now** as a new agent, keep the current build running as control.
3. **Do Option B over the weekend**, informed by whether A moved the number.
4. **Leave the disaster rules alone.** They're the best thing we have — UWMC, CDLX, TEAD, PZZA, ANGI are wins the field missed. Whatever we change, don't break those.

## 7. Answering the "can we run analytics on submitted data" question

Yes, and it's worth doing properly once. Three cuts that would pay for themselves:

- **Error by rule fired.** We log `rules_applied` — group absolute error by rule ID and we'll know exactly which rules earn their keep. That's the outcomes-ledger loop finally paying off.
- **Error by predicted bucket.** Confirms the snapping thesis and shows which anchors are worst.
- **Our error vs. field median error.** The data already gives us the field's median error per event. Grouping by industry tells us where we're beating the field and where we're the problem — and that's what should drive which sector playbook gets attention next.
