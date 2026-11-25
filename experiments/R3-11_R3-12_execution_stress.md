# R3-11 / R3-12 execution stress
Frozen control: R5-07 P80 same-bar H1, 2024–2025, USD 1m, leverage 1, native funding curves, 80% gross portfolio cap. No fixed TradeCost.

R3-11A/B: submit spot first, defer perpetual opening by 1/2 elapsed hourly bars, with equal original quantity. If spot is not confirmed or fresh futures quote unavailable, wait up to the original 2-hour timeout after scheduled hedge time, then unwind. Normal paired exits unchanged. This is deliberate execution stress, not actual exchange latency.

R3-12A/B: portfolio-wide synthetic quote outage lasting 6/24 hours, triggered once per UTC month at the first feed callback with an already active hedge. No new orders or close submissions during outage; existing fills may still arrive. Resume normal rules using fresh quotes; missing history can reset the signal window. Platform market marks and funding may continue. This is not a real exchange outage.

Queue: 11A → 11B → 12A → 12B; stop on error to avoid duplicate submissions. Compare cost-adjusted returns, drawdown, holding, stop losses and observed hedge exposure. Results pending.
