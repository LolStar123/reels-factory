# SEEDING — the quantihack launch buffer

The prior-art repo (`portfolio/markets-backtesting/`) already holds **50 backtested,
paper-cited strategies with real metrics**- roughly 50 reels of material before the
harvester ever runs. That solves the day-one cold-start outright.

## Run it
```
python run.py --seed-from-quantihack
```
This ingests `seed/quantihack_alt_data_50_results.csv` into the SQLite ledger as
`seed-material` entries, routed per vertical (vol-surface/microstructure families →
`wannabe_quant`; calendar/behavioural/accessible families → `high_finance`).

## Building a reel from a seed
Seeds are strategy rows, not papers- to render one, write its rule as a
`StrategySpec` JSON (the CSV carries family + signal name; the 50 `signal()` functions in
`quantihack_alt_data_50.py` are the ground truth) and run the normal chain. The extractor's
few-shot examples come from these same 50, so live extraction converges on the same shapes.

## Dedup
Seed entries respect the same 30-day `used_topics.json` window as harvested papers-
the opening 9-grid (see LAUNCH.md) draws the 9 most visual seeds first.

## Honest framing
Seed metrics were computed on the quantihack engine- the same engine `backtest.py` lifts,
so the numbers regenerate identically. Anything rendered from a seed still passes the QC
honesty gate: the reel re-runs the backtest fresh, on the current data cache, and shows
THOSE numbers ("as of" stamped).
