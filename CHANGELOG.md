# Changelog

All notable changes to Nubli will be documented here.

## 0.1.0 - Unreleased

### Added

- Local-first CLI anonymizer for text, Markdown, CSV, DOCX, XLSX, PDF and images.
- Smart replacement rules for punctuation/spacing variants.
- Fuzzy matching for typo-like variants.
- Interactive menu when running `nubli` without arguments.
- Safety checks for zero replacements/redactions.
- PII suggestions for emails, phones, ID/RUC-like values and possible person names.
- Visual redaction helpers for headers, logos and manual regions.
- Pretty `install.sh` installer with Core, Full and OCR modes.

### Security

- Fail-closed behavior for zero-match anonymization attempts.
- `.gitignore` excludes generated outputs, local env files and virtual environments.
