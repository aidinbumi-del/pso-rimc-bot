# Strategy Spec: "PSO + RIMC + 1-Minute Entry"

Reconstructed from YouTube transcripts of a forex trading channel. This is a
discretionary, chart-pattern strategy — the source videos never gave exact
numeric thresholds for "range," "slowdown," or "rejection." Every such
threshold below is my own reasonable default, clearly marked, and meant to be
tuned against real data, not treated as gospel.

## 1. Bias (Pre-Session Observation, "PSO")
- On a higher timeframe (config: `HTF_TIMEFRAME`, default 4H), detect a
  sideways range followed by a breakout ("initiation").
- Bias = direction of that breakout (long if broke up, short if broke down).
- If no clear breakout is currently active, there is **no bias** and the bot
  takes no trades that session.

## 2. Location filter (premium/discount)
- Take the most recent significant swing leg (A→B) on the working timeframe.
- Compute relative high, low, and 50% midpoint.
- Only shorts are allowed when price is in the **top 50% (premium)**.
- Only longs are allowed when price is in the **bottom 50% (discount)**.
- Price near the middle (config: `MID_ZONE_BUFFER_PCT`) = no trade.

## 3. Setup (RIMC — Range, Initiation, Mitigation, Continuation)
- Range: price consolidates (config: `RANGE_MIN_BARS`, `RANGE_MAX_ATR_MULT`).
- Initiation: breakout from that range (config: `BREAKOUT_ATR_MULT`).
- Mitigation: pullback into the broken range.
- Continuation: price resumes in the breakout direction — confirmed by
  taking out the prior internal swing high/low.

## 4. Entry trigger (1-minute execution model)
Two variants, both requiring price back inside/at the mitigation zone:
  a. **Edge entry** — price tags the extreme high/low of the location zone.
  b. **Continuation/mitigation entry** — price breaks a small range, pulls
     back into it, then resumes — entry inside that small range.

## 5. Entry filter — stop-size cap
- Reject any setup whose required stop distance exceeds `MAX_STOP_PIPS`
  (default 5 pips, source video showed a 7-pip stop being explicitly
  rejected).

## 6. Stop placement
- Short: just above the swing/range high (+ `STOP_BUFFER_PIPS`).
- Long: just below the swing/range low (− `STOP_BUFFER_PIPS`).

## 7. Target / R:R
- Minimum reward multiple `MIN_RR` (default 5), configurable up to
  `MAX_RR` (default 10) for stronger continuation setups.

## 8. Break-even management
- Once price takes out the prior internal swing low/high in the trade's
  favor, move stop to entry (break-even). This is the only in-trade
  management rule described in the source material.

## 9. Session & frequency
- Default session window: 08:00–10:00 London time (config: `SESSION_START`,
  `SESSION_END`).
- Max trades per session: `MAX_TRADES_PER_SESSION` (default 2).
- Optional trading days filter: `TRADING_DAYS` (default Mon–Thu, per one
  source video saying "4 days a week").

## 10. Risk sizing
- Risk per trade: `RISK_PER_TRADE_PCT` (default 0.75%, mid of the stated
  0.5–1% range).

## Known gaps / discretionary judgment calls in the source material
These were never given hard numeric rules on camera — they're visual
judgment calls by the trader, and are the main source of backtest
uncertainty:
- What exactly counts as "sideways" vs "trending" (range detection).
- What exactly counts as a "strong rejection" / "slowdown" V-formation.
- Exact break-even trigger candle-by-candle logic.
- Which timeframe to use for HTF bias on any given day (discretionary).

The code implements reasonable, documented proxies for all of these so you
have something testable — but expect real divergence from how the human
trader would read the same chart. Treat backtest output as a rough
approximation, not ground truth, and validate directly against the specific
market/period you care about before risking capital.
