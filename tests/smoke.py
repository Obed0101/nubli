from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_smoke() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "sample.nubli.md"
        report = Path(tmp) / "report.json"
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "nubli.py"),
                str(ROOT / "examples" / "sample.md"),
                "--replace",
                "Acme S A=Demo Company",
                "--replace",
                "legal@acme.example=person@example.local",
                "-o",
                str(output),
                "--report",
                str(report),
                "--quiet",
            ],
            check=True,
        )

        text = output.read_text(encoding="utf-8")
        assert "Acme" not in text
        assert "ACME" not in text
        assert "acme" not in text
        assert "Demo Company" in text
        assert "DEMO COMPANY" in text
        assert "demo company" in text
        assert "person@example.local" in text
        assert report.exists()


if __name__ == "__main__":
    run_smoke()
    print("smoke ok")
