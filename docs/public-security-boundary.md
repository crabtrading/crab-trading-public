# Crab Trading Public Security Boundary (v1.0)

This document defines mandatory boundary rules for the public runtime.

## Public Layer (Allowed)

- `Forum`
- `Discovery` (basic)
- `Simulation`
- `Follow`
- `Protocol/OpenAPI`
- `Synthetic seed/demo data`

## Private Layer (Forbidden in Public)

- real broker execution
- live order routing
- capital allocation logic
- risk engine internals
- anti-gaming internals
- production infra details
- secrets, tokens, private hostnames

## Ten Non-Negotiable Rules

1. Never commit real API key/token/secret.
2. Never import or reference `app.live` in public runtime.
3. Never expose `/web/live/*`, `/web/owner/*`, `/internal/*`.
4. Never ship real broker execution path.
5. Trading/follow/account/position/poly/kalshi responses must include `execution_mode: "mock"`.
6. Public market/trade demo data must be synthetic/mock.
7. Never expose risk engine parameters/weights.
8. Never expose capital routing or revenue logic.
9. Never expose production host/tunnel/internal network details.
10. Export and release must pass automated contract + leak verification.

## CI/Verification Hooks

- `python3 scripts/verify_public_contract.py`
- `bash verify_public_repo_ubuntu.sh <repo_dir>`
- `bash sync_public_safe.sh --dry-run`
