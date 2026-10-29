# TMF-PROV-001 — local byte-integrity evidence audit (review candidate)

**Status:** Candidate software only. **Research acceptance:** `NOT_ESTABLISHED`.
This is not a claim of thinkorswim execution attestation or independent bar equivalence.

## Local-only inspection

The read-only script `scripts/audit_tmf_evidence.py` checks exactly five local
files against the operator-reported SHA-256 digests already published in
`docs/tae-tos-001-tmf-diagnostic-evidence.md`. It prints filenames, byte sizes,
hashes and status, never raw CSV rows or market prices. Missing, changed or
symlinked files fail closed. It does not modify existing evidence.

From repository root on Windows Git Bash:

```bash
export UV_LINK_MODE=copy
uv run --locked python scripts/audit_tmf_evidence.py \
  --root parity/tmf_001
```

Optionally verify the separate immutable diagnostic run:

```bash
uv run --locked python scripts/audit_tmf_evidence.py \
  --root parity/tmf_001 \
  --run-dir parity/tmf_001/validated_exports/run-52ecce11c0a9aae55a8bcc2680dda66dbf96fd59f05da7beb1037fa781e78f9a \
  --study thinkscript/TAE_Confirmed_Swings_Parity.ts \
  --exporter thinkscript/TAE_Swing_Event_Export.ts
```

**Caution:** The operator's locally captured exporter used CRLF with no
final newline, while Git stores LF. That can produce an expected exporter-byte
hash mismatch even when source text is identical. The verifier intentionally
does not normalize line endings or rewrite the recorded manifest. Supply the
actual previously used local exporter bytes, if preserved. A mismatch is not
automatically proof of fabricated evidence; it does block byte-identical
reproduction until reconciled.

The diagnostic run ID is recalculated from the original input fingerprints.
The script checks the derived run directory name, the capture CSV hash, the
individual raw source hashes and the still-unattested status flags. All reported
hash matches establish only internal byte consistency with reported evidence.

## Independent review not supplied by this script

A qualified reviewer still must separately attest the captured platform study
and exporter settings, full OHLC/session alignment, adjustment methodology,
the 170 suspect fractional-volume bars, 18 sub-cent swing values, event
completeness and the source vintage/point-in-time limitations. Modern
downloads cannot prove historical availability. Even when this script exits
zero, full-bar equivalence and research acceptance stay NOT_ESTABLISHED.

Preserve `parity/tmf_001/` and actual source reports outside Git. Do not
publish raw vendor data or proprietary screenshots. Record a dated reviewer
disposition and hashes separately before closing issue #17.

## Software validation

```bash
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
uv build
```

Synthetic tests cover byte mutations, capture tampering, false platform
attestation, malformed manifests and unsafe filenames. Windows/Linux CI and
independent software review are required before merging.
