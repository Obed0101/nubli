# Nubli

```
 _   _       _     _ _
| \ | |_   _| |__ | (_)
|  \| | | | | '_ \| | |
| |\  | |_| | |_) | | |
|_| \_|\__,_|_.__/|_|_|
```

**Nubli** is a lightweight, local-first document anonymizer for people who need to share private files with AI tools without leaking company names, emails, phones, IDs, client names, logos, headers or other sensitive details.

Nubli runs on your machine. No cloud service. No hidden API call. No document leaves your computer.

> Status: early alpha. Useful today, but still treat high-risk documents with care and review outputs before sharing.

---

## Why Nubli exists

When you want to ask an AI about private PDFs, reports, spreadsheets or contracts, you often need to anonymize them first.

Nubli helps you:

- replace company names with neutral names,
- replace people names with placeholders,
- detect emails, phones, ID/RUC-like strings and possible names,
- render PDF/image pages with visual redactions,
- redact logos, stamps or headers using manual zones,
- fail safely when no replacement was found,
- keep the entire process offline.

---

## Install

### Plug-and-play installer

```bash
./install.sh
```

The installer shows a small ASCII menu with a tiny Nubli cat mascot and creates a local virtual environment plus a `~/.local/bin/nubli` command.

If you want a plain installer without the mascot:

```bash
NUBLI_NO_PET=1 ./install.sh
# or
./install.sh --no-pet
```

Install modes:

| Mode | Good for | Installs |
|---|---|---|
| Core | Text, Markdown, CSV | No heavy extras |
| Full | PDF/images/DOCX/XLSX | Python document libraries |
| OCR too | Scanned PDFs/images | Full mode + Tesseract helper when available |

If `~/.local/bin` is not in your PATH, the installer prints the exact command to add it.

### Python direct use

```bash
python nubli.py --help
```

### Editable Python package

```bash
python -m pip install -e .
# or with all extras
python -m pip install -e '.[all]'
```

---

## Quick start

### 30-second example

Create a tiny local file, anonymize it and inspect the generated copy:

```bash
printf 'Acme S A hired Juan Pérez. Contact legal@acme.test.' > sample.txt
nubli sample.txt \
  --replace "Acme S A=Demo Company" \
  --replace "Juan Pérez=Person 001" \
  --replace "legal@acme.test=contact@example.test" \
  --format markdown \
  -o sample-anonymized.md
```

The source file stays unchanged, and the anonymized copy is created locally.

### Interactive mode

```bash
nubli
```

Nubli opens a small wizard/menu:

1. anonymize a file,
2. show install/download help,
3. show quick examples,
4. exit.

When anonymizing, it asks for the file, output format, output path, rules, safety mode and optional PDF/image redaction settings.

Install help from the CLI:

```bash
nubli --help-install
```

### Replace multiple values

```bash
nubli contrato.pdf \
  --replace "Acme S A=Demo Company" \
  --replace "Juan Pérez=Persona Demo" \
  --replace "507-6000-0000=TEL-0000" \
  --format markdown \
  -o salida.md
```

### Use a JSON rules file

```json
{
  "Acme S A": "Demo Company",
  "Juan Pérez": "Persona Demo",
  "legal@empresa.com": "persona@demo.local",
  "507-6000-0000": "TEL-0000"
}
```

```bash
nubli archivo.docx --rules rules.json -o anonimo.md
```

Advanced JSON rules:

```json
[
  {
    "source": "Acme S A",
    "target": "Demo Company",
    "fuzzy_threshold": 0.86,
    "preserve_case": false
  }
]
```

---

## Visual PDF/image redaction

Text extraction is not enough for every PDF. Some files contain logos, scanned headers or text rendered as images. For those cases, use image output plus visual redaction.

### Redact a top header/logo area

```bash
nubli estados.pdf \
  --format images \
  --replace "Acme S A=Demo Company" \
  --redact-header 0.12 \
  --header-text "DEMO COMPANY" \
  -o salida_paginas
```

`--redact-header 0.12` means redact the top 12% of each rendered page. You can also pass pixels, for example `--redact-header 160`.

### Redact manual regions

```bash
nubli estados.pdf \
  --format images \
  --replace "Acme S A=Demo Company" \
  --redact-region "40,30,220,90=LOGO REDACTED" \
  --redact-region "900,20,260,80=CLIENTE" \
  -o salida_paginas
```

Region format:

```text
x,y,width,height=Label
```

---

## Safety defaults

Nubli is intentionally conservative.

By default it refuses to keep output when it finds **zero replacements/redactions**. If running in a terminal, it asks before keeping risky output. In non-interactive mode it fails closed.

Direct CLI runs show an ASCII banner, progress steps and match counts by default. Use `--quiet` for scripts or `--no-pet` to hide only the mascot.

Useful flags:

| Flag | Purpose |
|---|---|
| `--require-all-rules` | Ask/fail if any replacement rule had zero matches. |
| `--strict-pii` | Ask/fail if possible emails, phones, IDs or names remain. |
| `--allow-zero-replacements` | Override zero-match protection intentionally. |
| `--no-interactive` | Never ask; fail closed instead. |
| `--no-suggest-pii` | Disable sensitive-data suggestions. |
| `--quiet` | Hide banner/progress and print only paths/errors. |
| `--no-pet` | Hide only the ASCII mascot. |
| `--fuzzy-threshold 0.86` | Adjust typo matching sensitivity. |
| `--no-fuzzy` | Disable fuzzy matching. |

---

## Matching behavior

Nubli uses smart matching by default.

```bash
--replace "Acme S A=Demo Company"
```

Matches variants like:

- `Acme S.A.`
- `ACME, S. A.`
- `acme - s a`
- typo-like variants when fuzzy matching is enabled

Case is preserved unless the replacement has custom casing such as `DemoXYZ`.

---

## Supported inputs

| Input | Markdown/Text output | Image output |
|---|---:|---:|
| `.md`, `.txt`, `.html`, `.json`, `.xml`, `.yml`, `.log` | yes | no |
| `.csv`, `.tsv` | yes | no |
| `.docx` | yes | no |
| `.xlsx`, `.xlsm` | yes | no |
| `.pdf` with text layer | yes | yes |
| scanned `.pdf` | yes with OCR | yes with OCR |
| `.png`, `.jpg`, `.tiff`, `.webp` | yes with OCR | yes with OCR |

---

## Privacy model

Nubli does not call the web. It reads local files, applies local replacement/redaction rules and writes local outputs.

OCR is local only when Tesseract is installed. No OCR or redaction workflow can guarantee 100% accuracy on scanned PDFs, bad photos, logos or stylized text. For sensitive documents, combine:

```bash
--strict-pii --require-all-rules --redact-header --redact-region
```

Then manually review the output before sharing.

---

## Branching model for maintainers

Recommended repo setup:

- `main`: stable releases only.
- `dev`: integration branch for new features.
- feature branches: `feature/<short-name>`.
- fixes: `fix/<short-name>`.

Do not publish from local dirty state. Before releasing:

```bash
python -m py_compile nubli.py
python tests/smoke.py
python -m build
```

No secrets, `.env`, private PDFs, generated outputs, caches or local virtual environments should be committed.

---

## Security

Please see [`SECURITY.md`](SECURITY.md).

Short version:

- Do not upload confidential documents to issues.
- Do not commit sample files containing real client data.
- Report vulnerabilities privately when possible.

---

## Contributing

Please see [`CONTRIBUTING.md`](CONTRIBUTING.md).

---

## License

MIT. See [`LICENSE`](LICENSE).
