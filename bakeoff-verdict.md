# Bake-off verdict — polymarket-faa-attribution-01 (2026-11-14)

Task given to all three models (identical prompt, saved at faa-bakeoff/ alongside raw outputs):
design a deterministic offline Python-3.13-stdlib program that reads ~24 prediction markets'
Yes prices (0..1) at every minute of the last 72h and outputs, per market and per minute of the
next 240, the 5/25/50/75/95% quantiles of the price. Score = mean pinball loss (percentage
points, lower better). House baseline to beat: persistence median + Gaussian spread
0.0025*sqrt(h), which scored ~0.364 on the same event family. Constraints: <=8 s/case, 1 CPU,
deterministic, no network.

## Scores

- **Nemotron Ultra (OpenRouter, nvidia/nemotron-3-ultra-550b-a55b:free) — 24/30 — WINNER.**
  Logit-space random walk, persistence median (correct under pinball for a near-martingale),
  pooled empirical standardised quantiles k_q (fat tails: k_0.05 ~ -2.1 vs Gaussian -1.645),
  EWMA recent vol (half-life 180m) blended 0.7/0.3 with long-run MAD, James-Stein-style
  shrinkage 0.65 own / 0.35 pooled, sigma floor, sqrt(h) scaling, zero-increment filtering
  insight for forward-filled data, fully concrete parameters, trivial runtime.
  Flaws: (1) claims the house baseline widens linearly — false, the starter code widens with
  sqrt(h) too, so its headline "30% saving" argument is bogus; (2) filtering zero increments
  before MAD biases sigma up unless corrected for the zero fraction — it does not correct;
  (3) per-h scaling from the 1-minute distribution only (sigma_1*sqrt(h)) instead of measuring
  empirical h-step changes directly.

- **DeepSeek V4.1 Flash (Token Harbor, deepseek-v4.1-flash:free) — 19/30.**
  Logit-space Gaussian random walk, persistence median kept in price space, MAD scale over two
  windows (240m / 2880m), Student-t awareness with a fixed kurtosis inflation kappa=1.10.
  Sound core, consistent with the proven recipe's log-odds leg. Flaws: Gaussian quantiles
  ignore the empirically fat tails on this event family; no direct h-step measurement;
  the helper truncated its answer mid-section-2, so pooling/drift/boundary sections were
  never delivered — scored on what arrived.

- **MiMo v2.5 (Token Harbor, mimo-v2.5:free) — 0/30.**
  Three attempts (full prompt twice, condensed once) all returned an empty body.
  No design delivered. (Same model answered fine in the 2026-11-14 aggregator bake-off;
  the endpoint simply returned nothing today.)

## Decision — winner leads, proven recipe overrules on the central point

Nemotron leads the design, mixed with our proven recipe (the verified
polymarket-nvidia-ceo-forecast-01 entry: practice pinball 0.276 vs house baseline 0.3636 on
this same event family). As in the aggregator bake-off, all outside models are overruled on
one point: instead of deriving every horizon from a 1-minute sigma (Nemotron) or a Gaussian
(DeepSeek), the build measures EMPIRICAL h-step change quantiles directly on a geometric
horizon grid, because that is what graded 0.276 in production on this event family.

Final design (what the Gemini build session implements from a prose brief):
1. Two legs ensembled 50/50 in price space: (A) absolute price changes, (B) log-odds changes
   (clip [0.0005, 0.9995]).
2. Per leg: sigma_1 from one-step changes with a robust floor; EWMA (45m half-life) of
   absolute recent changes vs full-series mean absolute change gives a vol-trend ratio that
   adjusts horizon widths.
3. Empirical h-step changes on a 19-point geometric grid (1..240); blend full-history changes
   with a recent 360-minute window when genuinely distinct and >=60 changes.
4. Cross-market pooled empirical distribution of h-step changes, each market's pooled curve
   scaled by its own sigma_h; blend own-market and pooled curves by series length.
5. Quantiles around the persistence median (last price; log-odds centre in leg B), width
   factors 0.55 (absolute) / 0.65 (log-odds); interpolate over the horizon grid; clip to
   [0,1]; enforce non-decreasing rows; round 6dp.
6. Adopted from Nemotron: pooled tail-shape emphasis and shrinkage discipline (already
   embodied in steps 3-4), zero-increment awareness handled via floors + pooled scaling.
   Adopted from DeepSeek: two-window scale cross-check (embodied in step 3's recent-window
   blend).

## Addendum (2026-11-14 ~10:50 WIB) — entry goes to faa-attribution-02, not -01

The bake-off above was run for the shared FAA-attribution problem. The original pick was
polymarket-faa-attribution-01 (0 submissions, deadline 2026-11-15T09:00Z), but its kit
`init` refuses with evidence: "polymarket-faa-attribution-01 has not opened yet: drand's
latest round is 33941528 ... the anchor must be round 33962212 or later, which drand emits
at 2026-11-14T21:00:00.000Z" — the competition only opens 2026-11-14T21:00Z (04:00 WIB),
so no anchored entry can be built or submitted before then, and its CLI status reads
can_submit=false. polymarket-faa-attribution-02 is the identical competition (same event
family, same practice event, same rules/prizes) that is open NOW: init succeeds (anchor
round 33941538 in a scratch test), CLI status can_submit=true, our entries_made=0, day cap
3 left. Its deadline is 2026-11-14T14:00Z (21:00 WIB today) with 721 submissions. The
entry is therefore built for -02; the design and bake-off carry over unchanged.
bring-the-humans-01 ($1000) was rejected as infeasible: scoring is verified human signups
through a referral link — a solo agent cannot produce real human signups.
btc-cent-forecast-01 ($250) was feasible but lower value: its prize gate is beating a
persistence baseline on 4h BTC MAE, and persistence is near-optimal for a random walk, so
the proven pinball design's demonstrated 24% margin over its house baseline is the
stronger expected value.
