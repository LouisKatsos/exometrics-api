# Security

## Reporting a problem

Please report security issues privately to the maintainers, not in a public
issue or pull request. Include what you found, how to reproduce it and the
API version (shown at `/openapi.json` when the docs are enabled).

Only the latest version on `main` (deployed by Render) receives fixes.

## Controls in this API

- Firebase ID tokens (RS256) verified on every data request; 401 without details.
- Every query and insert limited to the caller's own records.
- Pydantic validation of every field (type, range, length, format); unknown fields ignored.
- Rejection of `$`, `.` and NUL in free-form keys (NoSQL injection); no server-side JavaScript.
- Rate limits per user and per IP, 1 MB request bodies, 500 entries per batch.
- No browser origins allowed by default (CORS); credentials never allowed cross-origin.
- Security headers: CSP, HSTS (production), X-Frame-Options, nosniff, Referrer-Policy,
  Permissions-Policy, COOP, CORP, Cache-Control: no-store.
- Generic 500 responses; tracebacks only in server logs; validation errors never echo values.
- Interactive docs off in production.
- Secrets only in environment variables or secret files, never in git.
- Container runs as an unprivileged user.
- CI on every push: tests, Bandit, pip-audit, CycloneDX SBOM, Gitleaks; CodeQL; Dependabot.

Configuration and deployment details are in [README.md](README.md).
