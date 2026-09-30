from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import nubli  # noqa: E402


class OutputPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / "input.txt"
        self.original = b"synthetic secret\n"
        self.source.write_bytes(self.original)

    def run_cli(self, *arguments: str, source: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable, str(ROOT / "nubli.py"), str(source or self.source),
                "--replace", "secret=redacted", "--no-fuzzy", "--no-interactive",
                "--quiet", *arguments,
            ],
            capture_output=True,
            text=True,
            cwd=self.root,
        )

    def assert_refused(self, result: subprocess.CompletedProcess[str], message: str) -> None:
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(message, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(self.source.read_bytes(), self.original)

    def make_alias(self, alias: Path, target: Path, kind: str) -> None:
        try:
            if kind == "symlink":
                alias.symlink_to(target)
            else:
                os.link(target, alias)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"{kind} unavailable: {error}")

    def test_output_cannot_overwrite_input(self) -> None:
        for output in (str(self.source), "./input.txt"):
            for output_format in ("markdown", "text"):
                with self.subTest(output=output, format=output_format):
                    self.source.write_bytes(self.original)
                    result = self.run_cli("-o", output, "--format", output_format)
                    self.assert_refused(result, "output path must be different from the input file")

    def test_output_alias_cannot_overwrite_input(self) -> None:
        for kind in ("symlink", "hardlink"):
            with self.subTest(kind=kind):
                alias = self.root / f"{kind}.md"
                self.make_alias(alias, self.source, kind)
                self.assert_refused(self.run_cli("-o", str(alias)), "output path must be different")
                self.assertEqual(alias.read_bytes(), self.original)

    def test_default_output_cannot_overwrite_input(self) -> None:
        for output_format, suffix in (("markdown", ".md"), ("text", ".txt")):
            with self.subTest(format=output_format):
                source = self.root / f"document.nubli{suffix}"
                source.write_bytes(self.original)
                result = self.run_cli("--format", output_format, source=source)
                self.assert_refused(result, "output path must be different")
                self.assertEqual(source.read_bytes(), self.original)

    def test_report_cannot_overwrite_input_or_create_output(self) -> None:
        output = self.root / "new" / "output.md"
        for kind in ("same", "symlink", "hardlink"):
            with self.subTest(kind=kind):
                report = self.source if kind == "same" else self.root / f"report-{kind}.json"
                if kind != "same":
                    self.make_alias(report, self.source, kind)
                result = self.run_cli("-o", str(output), "--report", str(report))
                self.assert_refused(result, "report path must be different from the input file")
                self.assertFalse(output.parent.exists())
                self.assertEqual(report.read_bytes(), self.original)

    def test_report_cannot_replace_new_output(self) -> None:
        output = self.root / "new" / "output.md"
        result = self.run_cli("-o", str(output), "--report", str(output))
        self.assert_refused(result, "report path must be different from output files")
        self.assertFalse(output.parent.exists())

    def test_report_alias_cannot_replace_existing_output(self) -> None:
        for kind in ("symlink", "hardlink"):
            with self.subTest(kind=kind):
                output = self.root / f"output-{kind}.md"
                output.write_text("previous output", encoding="utf-8")
                report = self.root / f"report-{kind}.json"
                self.make_alias(report, output, kind)
                result = self.run_cli("-o", str(output), "--report", str(report))
                self.assert_refused(result, "report path must be different from output files")
                self.assertEqual(output.read_text(encoding="utf-8"), "previous output")
                self.assertEqual(report.read_text(encoding="utf-8"), "previous output")

    def test_distinct_output_and_report_still_work(self) -> None:
        output = self.root / "new" / "output.md"
        report = self.root / "reports" / "report.json"
        result = self.run_cli("-o", str(output), "--report", str(report))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(output.read_text(encoding="utf-8"), "synthetic redacted\n")
        self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["total_rule_matches"], 1)

    def test_generated_image_cannot_overwrite_input_before_ocr(self) -> None:
        source = self.root / "DOCUMENT-001-image.png"
        source.write_bytes(b"synthetic image sentinel")
        result = self.run_cli("--format", "images", "-o", str(self.root), source=source)
        self.assert_refused(result, "output path must be different from the input file")
        self.assertEqual(source.read_bytes(), b"synthetic image sentinel")

    def test_report_cannot_replace_generated_image_before_ocr(self) -> None:
        source = self.root / "source.png"
        source.write_bytes(b"synthetic image sentinel")
        output = self.root / "new"
        result = self.run_cli(
            "--format", "images", "-o", str(output),
            "--report", str(output / "DOCUMENT-001-image.png"), source=source,
        )
        self.assert_refused(result, "report path must be different from output files")
        self.assertEqual(source.read_bytes(), b"synthetic image sentinel")
        self.assertFalse(output.exists())

    def test_pdf_checks_all_destinations_before_rendering(self) -> None:
        source = self.root / "source.pdf"
        source.write_bytes(b"synthetic PDF sentinel")
        for collision in ("input", "report"):
            with self.subTest(collision=collision):
                output = self.root / f"pages-{collision}"
                output.mkdir()
                last_page = output / "DOCUMENT-001-page-0002.png"
                if collision == "input":
                    self.make_alias(last_page, source, "symlink")
                    report = None
                else:
                    report = last_page
                with mock.patch.object(nubli, "require_import") as require_import:
                    require_import.return_value.open.return_value = [object(), object()]
                    with mock.patch.object(nubli, "render_pdf_page_to_pil") as render_page:
                        with contextlib.redirect_stderr(io.StringIO()) as stderr:
                            with self.assertRaises(SystemExit) as raised:
                                nubli.render_images(
                                    source, output, nubli.ReplacementEngine([]),
                                    ocr=False, force_ocr=False, lang="eng", dpi=220,
                                    min_conf=45, image_fill="#ffffff", image_text="#111111",
                                    redact_header=0, header_text="REDACTED", redact_regions=None,
                                    report_path=report,
                                )
                        self.assertEqual(raised.exception.code, 2)
                        self.assertIn("must be different", stderr.getvalue())
                        render_page.assert_not_called()
                self.assertEqual(source.read_bytes(), b"synthetic PDF sentinel")
                self.assertFalse((output / "DOCUMENT-001-page-0001.png").exists())


if __name__ == "__main__":
    unittest.main()
