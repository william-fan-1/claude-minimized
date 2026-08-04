# Knowledge Repo + v0 Prompt — Ahi's workstream
**For:** Monday 12 noon meeting · **Owner:** Ahi (prompt + knowledge base) · **Pairs with:** Will's infra/cache

---

## 0. The finding that reframes everything

Will confirmed the platform gives us **short, bullet-list summaries of each call** — not full transcripts. The FAQ corroborates this ("the event materials delivered by the platform — the fact bullets"). Two consequences, both big:

1. **Our edge is almost entirely what we bring, not what we read.** With thin input, every team gets the same thin bullets. Deep-reading skill matters less; the *context we inject* (expectations, prior reactions, sector rules) becomes the dominant source of ΔR². The knowledge repo isn't a nice-to-have — it *is* the strategy.
2. **The cost objection largely evaporates.** Bullets + dossier ≈ a couple thousand input tokens per event, not tens of thousands. A stronger model across ~1,800 events is far cheaper than we feared. **Action: Will's "test run on a single sample to measure cost" is exactly right — do that before we settle the model.** Test on Gemini credits, but don't rule out Sonnet for live on cost grounds until we've measured.

---

## 1. Feature priority — ranked by incremental gain per unit effort

This is the list Will asked for. Build top-down; stop wherever we run out of time before Aug 10.

| # | Feature | Effort | Expected gain | Notes |
|---|---|---|---|---|
| 1 | **Expectations framing + calibration anchors in the prompt** | Free | **Highest** | The paper's core finding. Costs nothing but prompt text. |
| 2 | **Stock's own prior announcement-day reactions** (last 4–8 qtrs) | Low | **High** | Cheapest real alpha we have. Some names systematically pop/fade; some barely react. Personalizes every prediction. |
| 3 | **Guidance trajectory** (last 2–4 qtrs: raised / held / cut) | Low | High | Belief revision is the mechanism; trajectory is the setup. |
| 4 | **Industry playbook conditional rules** | Medium | High | ACE added ~3pp R² in the paper doing exactly this. |
| 5 | **Consensus + dispersion + coverage** (point-in-time) | Medium | Medium | Check first whether the bullets already contain the surprise — don't rebuild what's given. |
| 6 | **Pre-call analyst focus items** ("what they're watching") | Medium | Medium | Koijen explicitly endorsed this. Day-before is inside the cutoff. |
| 7 | **Options-implied move** | Medium-high | Medium | Calibrates *magnitude*, not direction. Strong v2. |
| 8 | **Seasonality / fiscal-quarter effects** | Low | Low-Medium | Your idea — cheap, real, but second-order. Ships as a dossier field, not a workstream. |
| 9 | **Outcomes feedback loop** | Medium | Compounding | Pays off from ~week 3 onward. Build the ledger now, harvest later. |
| 10 | MOE / multi-agent by sector | High | Unknown | v3. We have 5 agent slots; use them for A/B, not architecture. |

---

## 2. Two course corrections

**Geography-first taxonomy — I'd flip this.** The instinct (1,800 names is too big to treat as one blob, need hierarchy) is right. But the evidence points at **industry**, not geography: the paper's heterogeneity results are by Fama-French 12 industry, Koijen's own "certain models perform better in different industries" comment is industry-framed, and the universe is US-listed equities scored against a US market proxy (VTI) — so geography is mostly a *within-company revenue exposure* attribute, not a top-level partition. **Proposal: partition by industry, carry geographic revenue exposure as a cross-cutting tag** (e.g. "42% China revenue" matters enormously for a semi name — but it's a modifier on a semis rule, not its own branch).

**The feedback loop won't prevent overfitting by itself.** Will's hypothesis — continuous new stimuli prevents overfitting on old announcements — is half right. Fresh data does stop us fitting a stale sample, but a naive loop introduces the opposite failure: **chasing noise**, updating rules off single events that were coin flips. Three guardrails:
- Run reflection as a **nightly batch job**, never inside the 5-minute prediction call (latency + cost + coupling).
- **Require evidence before promoting a rule** — no rule goes live off n=1. Track hit rate; retire rules that decay.
- Keep a **held-out slice** to validate rule changes, mirroring the paper's early/late split.

Also on "AI slop fuels AI slop": fair worry, and the fix is grounding. Pre-reports must be **extractive** — retrieve consensus numbers, prior guidance language, actual prior-day price reactions — not the model free-associating about a company. Generated *opinion* is slop; generated *summary of retrieved facts* is fine.

**On manual pre-reports for 1,800 names:** correctly rejected, and we don't need 1,800 anyway. Events cluster hard (in the paper's quarter, one week held 46% of all events; three industries held >50%). Tier the coverage:
- **Tier 1** (~150 most liquid / most-watched names): full dossier
- **Tier 2**: light dossier (prior reactions + guidance trajectory only)
- **Tier 3**: industry playbook only
The calendar tells us where to spend each week.

---

## 3. Repo structure

```
knowledge/
  playbooks/
    _global.yaml          # cross-market rules (expectations, guidance, transitory items)
    busequ.yaml           # per FF12 industry
    health.yaml
    fin.yaml
    ...
  tickers/
    AAPL.yaml             # point-in-time dossier, regenerated T-36h
  calendar/
    2026-08-11.json       # upcoming events, tiering assignment
  outcomes/
    ledger.parquet        # prediction vs realized, appended post-event
  prompts/
    predict_v0.md         # versioned, git-tracked
```

Everything in **git, versioned, plain text**. Two reasons: prize eligibility requires a code audit, and we need to know *which prompt version* produced which result when we compare ΔR².

### Rule schema (playbooks)

Format follows the ACE rulebook from the paper — conditional trigger → percentile range → rationale. That structure is proven; don't invent a new one.

```yaml
- id: TECH-CAPEX-01
  scope: {industry: BusEq, size: mega_cap}
  trigger: >
    Capex guidance raised materially without corresponding
    revenue or FCF visibility in the same period
  action: {percentile_range: [0.15, 0.30]}
  rationale: >
    Market currently penalizes capex outrunning monetization;
    spending is read as margin risk, not growth investment
  confidence: medium
  evidence: {n: 0, hit_rate: null}
  added: 2026-08-03
  review_by: 2026-09-01
```

`evidence` is filled by the nightly job from the outcomes ledger. Rules that don't earn their keep get retired. This is how the feedback loop compounds without turning into noise-chasing.

### Ticker dossier schema

```yaml
ticker: AAPL
as_of: 2026-08-09T18:00:00Z      # MUST be before the event knowledge_cutoff
industry: BusEq
geo_revenue_exposure: {US: 0.42, China: 0.19, EU: 0.24, other: 0.15}
consensus: {eps: 1.42, revenue_bn: 94.2, dispersion: 0.04, coverage: 38}
guidance_trajectory:            # last 4 quarters
  - {q: 2025Q3, action: raised,  delivered: true}
  - {q: 2025Q4, action: held,    delivered: true}
  - {q: 2026Q1, action: cut,     delivered: false}
  - {q: 2026Q2, action: held,    delivered: true}
prior_reactions:                # ← the highest-value cheap field
  - {q: 2025Q3, surprise_pct: 3.1, next_day_abnormal: -0.021}
  - {q: 2025Q4, surprise_pct: 1.8, next_day_abnormal: 0.004}
  - {q: 2026Q1, surprise_pct: -0.9, next_day_abnormal: -0.058}
  - {q: 2026Q2, surprise_pct: 4.2, next_day_abnormal: 0.011}
reaction_profile: "beats poorly rewarded; misses heavily punished; asymmetric"
analyst_focus: ["services margin", "China unit trajectory", "capex guide"]
seasonality_note: "FQ3 typically guides conservatively ahead of product cycle"
implied_move_pct: 4.8           # optional, v2
```

`prior_reactions` + `reaction_profile` is the field I'd fight for first. It teaches the model *how this specific stock trades its own news*, which the bullets can never convey and most competitors won't bother to build.

---

## 4. The calibration insight that changes prompt design

Worth understanding before writing a single line of prompt, because it kills a whole category of wasted effort.

Scoring is **R² of a regression** of realized returns on our prediction. The regression coefficient absorbs scale and intercept — which means **any affine transform of our predictions leaves R² unchanged.** Multiply everything by 0.8, add 0.1: identical score.

Three implications:

1. **Being "unbiased" is worth nothing.** The paper found GEPA optimization mostly *de-biased* the model, and that's precisely why R² barely moved (their MSE decomposition, §3.4.2). Don't spend effort making the average prediction correct.
2. **Only RANKING moves the score.** What matters is whether we correctly order events from worst to best reaction. Every prompt instruction should serve discrimination.
3. **Uniform shrinkage toward 0.5 does literally nothing** — it's affine. Confidence-based shrinkage still works, but only because it's *conditional*: it moves low-confidence names toward the middle **relative to** high-confidence ones. That's a genuine reordering. Implement it conditionally or not at all.

The practical failure mode to avoid: predictions bunched around 0.45–0.55. No spread, no covariance, no ΔR². The prompt must actively push the model to **use the full range and commit.**

---

## 5. v0 prompt template

```markdown
## Task
Estimate where this stock's next-day ABNORMAL (market-adjusted) return will fall
in the cross-section of ALL earnings announcements this quarter (~1,800 events).

Output a percentile from 0.00 to 1.00.
  0.00 = most negative reaction of the quarter
  0.50 = completely typical reaction
  1.00 = most positive reaction of the quarter

Your job is RELATIVE RANKING, not predicting a percentage move.
Use the full range and commit. Roughly 10% of events deserve >0.85,
and roughly 10% deserve <0.15. Clustering near 0.50 is a failure mode.

## Core directive: good is already priced in
Announcement returns are driven by BELIEF REVISION versus prior expectations,
not by absolute performance.
- Public companies are EXPECTED to grow, beat, and improve margins. A company
  reporting record profits and strong growth that merely meets elevated
  expectations is a NEUTRAL outcome (0.40-0.60), not a positive one.
- Forward guidance usually dominates the headline beat. A beat with soft
  guidance frequently trades DOWN.
- Headline numbers inflated by one-time or transitory items earn little credit.
- A concrete negative operational specific (execution failure, key segment
  declining, churn rising) can override an otherwise positive narrative.
- To justify >0.85 the news must be genuinely surprising, not merely good.

## Calibration anchors
  0.05  severe guidance cut, or a broken core-business thesis
  0.20  beat on headline but forward guide clearly below expectations
  0.35  in-line quarter, cautious tone, no catalyst
  0.50  solid quarter that meets already-high expectations
  0.65  clean beat plus modest raise, credible and well-received
  0.80  meaningful raise with a genuine positive surprise on a key driver
  0.95  shock: large guidance raise, transformative announcement, or
        a reversal of a widely-held negative thesis

## Context
EVENT BULLETS:
{event_bullets}

COMPANY DOSSIER:
{dossier}          # consensus, guidance trajectory, prior reactions,
                   # reaction_profile, analyst_focus, seasonality

APPLICABLE PLAYBOOK RULES:
{industry_rules}   # pre-filtered by industry + size; do NOT dump all rules

## Reasoning steps (work through these before answering)
1. What was ALREADY EXPECTED going into this call?
2. What in these bullets is genuinely NEW information?
3. Direction and magnitude of the belief revision that new info causes?
4. How does THIS stock historically react to news like this? (see prior_reactions)
5. Which playbook rules fire, and do any conflict? If they conflict, the more
   specific rule wins.

## Output (JSON only)
{
  "percentile": 0.00-1.00,
  "direction": "up" | "neutral" | "down",
  "confidence": "high" | "medium" | "low",
  "top_drivers": ["...", "...", "..."],
  "rules_applied": ["TECH-CAPEX-01", "..."]
}
```

**Why `rules_applied` matters:** it's what lets the nightly job score *which rules actually work* against realized outcomes — the same mechanism ACE uses when its Generator flags which rules proved useful or misleading. Without it, the feedback loop has nothing to grade.

**Why rules are pre-filtered:** dumping the whole playbook wastes tokens and dilutes attention. Will's cache should attach only the rules matching that event's industry and size tier.

---

## 6. Ahi's build order this week

1. Write `_global.yaml` — the expectations/guidance/transitory rules above, formalized. *(Half a day. Highest ROI thing in this doc.)*
2. Write `predict_v0.md` exactly as templated, commit it to the repo so Will can wire it in.
3. Draft playbooks for the **three biggest industries first** — Business Equipment, Health, Finance. They were >50% of the paper's sample and will be most of ours. 5–8 rules each; quality over volume.
4. Define the dossier schema with Will so the cache job and prompt agree on field names.
5. Spec the outcomes ledger (columns: event_id, ticker, prompt_version, predicted_percentile, confidence, rules_applied, realized_abnormal, realized_percentile).

## Open items for Monday
- Confirm whether the bullets already include the earnings surprise (changes priority #5).
- Confirm first-vs-last submission scoring (docs contradict each other — treat as *first counts* until answered).
- Confirm what pre-Aug-10 submissions are for — practice/retrospective seems right, and the baselines already showing ~1,900 predictions supports that, but worth asking.
- Measure real per-event cost on one sample before locking the live model.
