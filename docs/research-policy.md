# Research policy

This project produces research artifacts only. It does not place orders, connect
to a brokerage execution system, allocate capital or provide investment advice.
Phase 1 implements data validation and descriptive technical features. It makes
no claim about profitability, predictive power, robustness or investment suitability.

Keep the engine independently testable. The separate
`Systematic-Trading-Research-Platform` repository owns orchestration. Changes to
that repository, TMF V3, TMF V4 and TimesFM are outside this assignment.

## Evidence and reproducibility

- Preserve provider provenance, raw snapshots when available, availability times,
  adjustment policy and corporate-action metadata. Never label a corrected modern
  download as historically point-in-time without evidence.
- Preserve historical artifacts. Investigate failed quality checks rather than
  silently sorting, filling, dropping, overwriting or relaxing assertions.
- Make formula changes explicit and version them. Record model/configuration/input
  hashes and run timestamps. Keep enough provenance to reproduce every result.
- Use deterministic synthetic fixtures for unit tests. Passing these tests validates
  implementations; it does not validate a trading thesis or provider completeness.
- Respect market-data licensing and keep credentials and proprietary data out of Git.
  Runtime snapshots and reports belong in excluded `data/` and `reports/` paths.

## Temporal discipline

Every study must specify decision time, source availability, exchange sessions,
corporate-action treatment and universe construction. Current-session technical
features require the appropriate session observations to be available. Prior-window
features do not authorize acting on an unavailable current price or volume.

Future studies need predeclared hypotheses, chronological train/validation/test
boundaries, leakage controls, out-of-sample evaluation, transaction-cost assumptions
where relevant, multiple-testing controls and documented limitations before any
performance claim. No model training, scoring, ensemble integration or execution
integration is authorized in TAE-001.

## Review gates

Use a dedicated feature branch. Validate before preparing a pull request. The
Product Owner approves milestones; do not bypass approvals or merge into `main`
automatically. Follow-on work needs the next approved assignment. A failed or
unverified required acceptance criterion must remain visible in the sprint report.
