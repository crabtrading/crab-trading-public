# Security Policy

## Supported Versions

This project is under active development. Use the latest `main` branch for security patches.

## Reporting a Vulnerability

Please report vulnerabilities privately to the project maintainer first.  
Do not open public issues for credential leaks, auth bypass, or data exposure findings.

## Secret Handling Rules

- Do not commit:
  - `.env*` (except `.env.example`)
  - token/credential files
  - private keys (`*.pem`, `*.key`, etc.)
  - runtime databases/state dumps (`runtime_state.db`, `runtime_state.json`)
- Use environment variables or server-local files outside git.
- Rotate credentials immediately if they were ever pasted into chats, logs, or commits.

## Production Hardening Checklist

1. Set `CRAB_STRICT_STARTUP_SECRETS=true`
2. Configure admin token via `CRAB_ADMIN_TOKEN_FILE` (preferred)
3. Configure admin IP allowlist (`CRAB_ADMIN_ALLOWLIST` or file)
4. Keep SSH locked down (no password auth, key-only, tunnel-only if applicable)
5. Keep Cloudflare/WAF and rate limits enabled
6. Use HTTPS-only ingress
7. Back up runtime DB and test restore

## Incident Response (Credential Leak)

1. Revoke exposed keys immediately
2. Generate new keys and deploy updated secrets
3. Restart services
4. Audit recent admin actions and suspicious traffic
5. Record timeline and remediation steps
