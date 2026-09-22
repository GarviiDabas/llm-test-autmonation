"""
run_tests.py

Runs the generated pytest suite and generates a self-contained HTML report saved in reports/.

Usage:
    python run_tests.py                     # run everything in tests/
    python run_tests.py --path tests/test_eventhub.py
"""

import argparse
import subprocess
import sys
from pathlib import Path


def run_pytest(test_path: str, html_report_path: Path) -> int:
    """Execute pytest with HTML report and custom CSS styling."""
    html_report_path.parent.mkdir(parents=True, exist_ok=True)
    css_path = Path("config/report_style.css")
    cmd = [
        sys.executable, "-m", "pytest", test_path,
        "-v",
        f"--html={html_report_path}", "--self-contained-html"
    ]
    if css_path.exists():
        cmd.append(f"--css={css_path}")
    result = subprocess.run(cmd)
    return result.returncode


def main():
    parser = argparse.ArgumentParser(description="Run pytest suite with HTML report")
    parser.add_argument("--path", default="tests/", help="Test file or directory to run")
    args = parser.parse_args()

    reports_dir = Path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    html_report_path = reports_dir / "report.html"

    exit_code = run_pytest(args.path, html_report_path)

    print(f"\n[+] HTML Report saved to: {html_report_path.resolve().as_posix()}")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
