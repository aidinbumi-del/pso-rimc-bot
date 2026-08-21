# Strategy Spec: "PSO + RIMC + 1-Minute Entry"

Reconstructed from two source types:
1. YouTube transcripts of a trading channel (session commentary, live examples).
2. NJAT's own official material ("Not Just A Trade"), added later: their
   RIMC Model guide, 1-Minute Trade Entry guide, private Telegram
   "Structure & Timeframes" doc, private Telegram "Lingo" glossary, and a
   third-party Twitter/X thread explaining RIMC. These appear to be the
   original source the YouTube trader's terminology comes from, and they
   give several genuinely numeric rules the YouTube transcripts never did.

Each rule below is tagged with where it comes from:
- **[SOURCE]** — an exact number or rule stated directly in the material.
- **[GUESS]** — my own reasonable default where the material only
  describes something qualitatively/visually. Tune these against real
  data, don't treat them as gospel.

## 1. Bias (Pre-Session Observation, "PSO")
- On a higher timeframe (config: `htf_timeframe`, default 4H), detect a
  sideways range followed by a breakout ("initiation"). **[SOURCE — NJAT
  Telegram]**: a confirmed range needs a minimum of 3 candles ("Think
  Fractal Highs/Lows").
- Bias = direction of that breakout (long if broke up, short if broke
  down). **[SOURCE — NJAT Telegram]**: a swing-high break-of-structure
  = "huge pile of buy orders" (bullish intention); swing-low break =
  "huge pile of sell orders" (bearish intention).
- If no clear breakout is currently active, there is **no bias** and the
  bot takes no trades that session.
- **[SOURCE — NJAT Telegram, not yet implemented]**: a trend isn't
  confirmed just by a new high/low — it needs a subsequent Higher Low
  (uptrend) or Lower High (downtrend) to hold. The current code uses a
  simpler "most recent breakout direction" proxy and doesn't check for
  this HL/LH confirmation. Documented gap, not built — would need a
  swing-point sequence detector, a nontrivial addition.

## 2. Location filter (premium/discount) — regime-dependent
**[SOURCE — NJAT RIMC Model guide]**: the rule differs by market regime,
which earlier versions of this spec didn't distinguish:
- **Trending market**: simple 50% split of the current leg. Only buy
  below 50% (discount), only sell above 50% (premium). Buying above 50%
  in a trend, or selling below 50%, is explicitly called out as a
  mistake ("Sideways price action above the 50% = Buying high = do not
  trade that range").
- **Consolidation market**: NOT a 50% split — only the outer 25% edges
  of the range count as tradeable ("Edge Top 25% = High Probability",
  "Edge Bottom 25% = High Probability"). The middle 50% (25%-75%) is
  explicitly labeled the **"slaughterhouse"** — a no-entry zone.
- Regime is classified per bar as `trending` or `consolidation` based on
  whether the HTF is currently inside a detected range (config:
  `classify_market_regime`).
- Note: because this strategy's entries happen at the exact edge of a
  broken range by construction (see #4 below), the consolidation-edge
  rule is satisfied automatically by the entry mechanic itself — the
  location filter's real job is applying the *trending* 50%-split rule
  to the broader swing context.

## 3. Setup (RIMC — Range, Initiation, Mitigation, Continuation)
- Range: price consolidates. **[SOURCE]** minimum 3 candles
  (`range_min_bars`); **[GUESS]** the ATR-relative tightness threshold
  (`range_max_atr_mult`) — NJAT shows this visually, not numerically.
- Initiation: breakout from that range **[GUESS: `breakout_atr_mult`]**.
  **[SOURCE — NJAT Telegram]**: initiation should show clear
  aggression/speed — "Look for aggression at highs/lows... not candle
  formation."
- Mitigation: pullback into the broken range.
- Continuation: price resumes in the breakout direction — confirmed by
  taking out the prior internal swing high/low.

## 4. Entry trigger (1-minute execution model)
- Entry happens at the edge of the broken range once price returns to it
  (mitigation). **[SOURCE — NJAT 1-Minute Trade Entry guide]** the entry
  checklist: mitigation confirmed, clean structure, clear HTF narrative,
  risk defined before entry.

## 5. Entry filter — stop-size cap
- Reject any setup whose required stop distance exceeds `max_stop_pips`
  **[SOURCE — YouTube]** (a 7-pip stop explicitly rejected on camera) —
  and below `min_stop_pips` **[SOURCE — YouTube]** ("I don't go below
  2.2"). **[SOURCE — NJAT]** independently shows 3-pip stops as typical.

## 6. Stop placement — now regime/strength-aware
- Short: just above the range high; Long: just below the range low
  (+ `stop_buffer_pips`).
- **[SOURCE — NJAT Telegram, "Strong Highs/Lows" / "Weak Highs/Lows"]**:
  not every range boundary is equally trustworthy for a tight stop.
  - A **strong** high/low forms from one fast, sharp rejection and gets
    "protected" by BFIs — safe to trust for a tight stop.
  - A **weak** high/low forms slowly with multiple "stacked" touches at
    the same level, doesn't cause a structural break, and price is
    "likely to shoot through it" — a bad place to anchor a tight stop.
  - **[GUESS — my proxy for this qualitative rule]**: count how many
    bars within the range touched within `stacked_touch_atr_mult` × ATR
    of the extreme. More than `max_stacked_touches_for_strong` touches =
    weak. `require_strong_swing_filter` (default True) skips any setup
    whose stop would sit behind a weak boundary.

## 7. Target / R:R
- Minimum reward multiple 5, up to 10 for stronger setups
  **[SOURCE — both YouTube and NJAT]**: NJAT's material independently
  confirms "4-10% gains" per winning trade, 1% loss when a range doesn't
  play out — consistent with the YouTube-derived 1:5–1:10 range.

## 8. Break-even management
- Once price takes out the prior internal swing low/high in the trade's
  favor, move stop to entry (break-even).

## 9. Session & frequency
- Default session window: 08:00–10:00 London time. **[SOURCE — NJAT
  1-Minute guide]** independently confirms "fixed 2-Hour Window."
- Max trades per session: 2. Trading days: Mon-Thu **[SOURCE — YouTube]**.
- Timezone handled properly via `Europe/London` conversion (auto-adjusts
  for BST/GMT) when timestamps are timezone-aware; falls back to a
  manual offset for naive timestamps (e.g. MT5).

## Terminology cross-reference (NJAT Telegram "Lingo" doc)
For anyone reading NJAT's own material alongside this code:
- **BFI** = "Banks and Financial Institutions" — the trader's term for
  the large players whose order flow this strategy tries to follow.
- **BOS** = Break of Structure = this code's `breakout_dir` detection.
- **Inefficiency / Liquidity ($)** = imbalanced price zones the market
  is expected to return to and fill — a supporting concept for *why*
  mitigation happens, not a separately-coded rule here.
- **POI** = Point of Interest — roughly this code's `range_high` /
  `range_low` reference levels.

## Known gaps / discretionary judgment still not fully resolved
- Exact ATR-relative "tightness" and "aggression" thresholds for range
  and breakout detection are still my own defaults — NJAT shows these
  visually across many chart examples, never as a formula.
- HL/LH trend confirmation (see #1) is documented but not implemented.
- The strong/weak swing classifier (#6) is my own concrete proxy for a
  qualitative NJAT rule, verified to behave correctly on hand-crafted
  test cases (isolated spike = strong, stacked touches = weak) but not
  validated against how a human NJAT trader would actually classify a
  real chart.

Treat backtest output as a rough approximation, not ground truth, and
validate directly against the specific market/period you care about
before risking capital.
