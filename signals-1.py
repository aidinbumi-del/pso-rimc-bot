        # the edge of the broken range once price returns to it (we treat
        # the breakout bar itself as marking the setup; entry triggers on
        # this bar's close for simplicity of a vectorized-ish backtest —
        # a more precise version would watch subsequent bars for the
        # actual pullback fill).
        if d == 1:
            entry = b_high[i]  # buy back at top of broken range (discount side)
            stop = b_low[i] - stop_buf
            is_high_boundary = False  # the LOW of the range is the stop boundary
        else:
            entry = b_low[i]  # sell back at bottom of broken range (premium side)
            stop = b_high[i] + stop_buf
            is_high_boundary = True  # the HIGH of the range is the stop boundary

        stop_dist = abs(entry - stop)
        if stop_dist <= 0 or stop_dist > max_stop or stop_dist < min_stop:
            continue

        # Strong vs weak swing point filter (NJAT Telegram material):
        # only trust a tight stop beyond a range boundary that shows a
        # sharp, single rejection rather than multiple slow "stacked"
        # touches.
        strong = classify_swing_strength(
            out, i, int(b_range_start[i]), is_high_boundary, cfg
        )
        swing_strong[i] = strong
        if cfg.require_strong_swing_filter and not strong:
            continue

        target = entry + cfg.target_rr * stop_dist * d

        direction[i] = d
        entry_price[i] = entry
        stop_price[i] = stop
        target_price[i] = target
        setup_valid[i] = True

    out["direction"] = direction
    out["entry_price"] = entry_price
    out["stop_price"] = stop_price
    out["target_price"] = target_price
    out["setup_valid"] = setup_valid
    out["swing_strong"] = swing_strong
    return out
