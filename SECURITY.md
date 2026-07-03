# Security policy

## Reporting a vulnerability

Please report security issues privately through GitHub Security Advisories
(the repository's **Security** tab → **Report a vulnerability**) rather than opening a public issue.

## Security overview

Meowtion's security controls and the evidence for each are documented in full in
[docs/security-and-testing.md](docs/security-and-testing.md). In brief:

- **Per-owner isolation** enforced by the Realtime Database and Cloud Storage rules
  (`app/firebase/database.rules.json`, `app/firebase/storage.rules`).
- **Scoped device tokens, not credentials** , a station holds a revocable per-device token; the
  collar holds nothing. A known token cannot be re-pointed to another account.
- **No direct client writes to Storage** , uploads go through the authenticated `upload_clip`
  function, which validates path segments (anti path-traversal) and reads the token from an
  `Authorization: Bearer` header.
- **Privileged training is gated** to verified developer accounts.
- **No secrets in the repository** , the Firebase web API key is a public client identifier;
  security is enforced by Authentication and the rules.

## Automated security checks

- **CodeQL** code scanning on every push and pull request , `.github/workflows/codeql.yml`.
- **Tests + coverage** CI on every push and pull request , `.github/workflows/test.yml`.
