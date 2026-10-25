# TAE-004: exploratory benchmark and dependence diagnostics

This module **does not complete TAE-002F final validation**, accept TAE-003
performance, or implement thinkScript, OnDemand, paperMoney, or ORCH work.
Merged software, successful CI and independently accepted research evidence
are separate lifecycle states.

`validate_return_robustness(asset, benchmark, config)` recomputes TAE-003
outcomes against the same snapshot and setup rules. It scores only matured
**HOLDOUT** labels; censored observations are counted, never imputed. The
benchmark must use a different symbol, identical observation sessions, and
an identical adjustment policy. A matching raw time grid is a necessary
precondition, not proof of independent, unbiased benchmark selection.

For each event kind and horizon the report records counts, overlap-connected
clusters, largest-cluster concentration, backfilled events, directional
asset and matched benchmark returns, and excess returns. Dependencies are
conservatively clustered whenever return windows overlap or breakout IDs
match. This does **not** prove clusters are independent: shared regimes,
universe construction and hidden common factors can persist across clusters.

Inference is suppressed unless minimum independent-looking cluster count
and concentration gates are met. Otherwise fixed-seed cluster bootstrap
intervals and sign-flip screens are reported as **exploratory** with an
explicit assumption warning. Sign flips assume symmetric independent
cluster effects. Holm adjustments cover the complete pre-specified
kind-by-horizon family; suppressed rows contribute conservatively as p=1.
Numerical p-values and intervals do not establish validity of those
untestable assumptions or remedy hindsight model selection.

No automatic claim of statistical significance, predictive superiority,
actionable returns or profitability follows from these computations.
Close-to-close event-label returns are not trade returns. Research
governance must separately predeclare the benchmark, universe, horizons,
filters, samples, cost model and thresholds, then assess vintage validity,
selection/survivorship bias, corporate actions, event concentration, and
independent prospective evidence.

Run cross-platform pytest, Ruff and package builds. Final acceptance also
requires human review of the unimplemented TAE-002F gate and independent
research design, which passing CI cannot replace.
