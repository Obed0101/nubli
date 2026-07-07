# Security Policy

Nubli is built for local-first document anonymization. Security reports are taken seriously because users may process confidential documents.

## Supported versions

| Version | Supported |
|---|---|
| `main` | yes |
| older local copies | best effort |

## Reporting a vulnerability

Please do **not** attach confidential documents, real client files, private PDFs, credentials, tokens or `.env` files to public issues.

If the project is hosted on GitHub, use private vulnerability reporting when available. If not, contact the maintainer privately and include:

- affected Nubli version or commit,
- operating system and Python version,
- minimal reproduction using synthetic data,
- expected behavior,
- actual behavior,
- impact.

## Sensitive data rules

Never commit:

- real customer PDFs or documents,
- generated anonymization outputs from private files,
- `.env` files,
- API keys or tokens,
- local virtual environments,
- OCR caches or temporary files.

Use synthetic fixtures in `examples/` and `tests/` only.

## Safety expectations

Nubli fails closed by default when no replacement/redaction is detected. Do not weaken this behavior without a clear reason and tests.

For high-risk documents, combine:

```bash
nubli input.pdf \
  --format images \
  --require-all-rules \
  --strict-pii \
  --redact-header 0.12 \
  --redact-region "x,y,w,h=REDACTED"
```

Then manually review the output before sharing.
