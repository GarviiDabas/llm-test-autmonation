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
from utils.logger import get_logger

logger = get_logger("run_tests")


def run_pytest(test_path: str, html_report_path: Path, headed: bool = False) -> int:
    """Execute pytest with HTML report and custom CSS styling."""
    html_report_path.parent.mkdir(parents=True, exist_ok=True)
    css_path = Path("config/report_style.css")
    cmd = [
        sys.executable, "-m", "pytest", test_path,
        "-v",
        f"--html={html_report_path}", "--self-contained-html"
    ]
    if headed:
        cmd.append("--headed")
    if css_path.exists():
        cmd.append(f"--css={css_path}")

    logger.info(f"Starting test execution: {' '.join(cmd)}")
    result = subprocess.run(cmd)

    # Post-process report to ensure lang="en" attribute is present for WCAG / Sonar compliance
    if html_report_path.exists():
        try:
            content = html_report_path.read_text(encoding="utf-8")
            if "<html>" in content:
                html_report_path.write_text(content.replace("<html>", '<html lang="en">', 1), encoding="utf-8")
        except Exception:
            pass

    return result.returncode


def main():
    parser = argparse.ArgumentParser(description="Run pytest suite with HTML report")
    parser.add_argument("--path", default="tests/", help="Test file or directory to run")
    parser.add_argument("--headed", action="store_true", help="Run Playwright UI tests in headed mode")
    args = parser.parse_args()

    reports_dir = Path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    html_report_path = reports_dir / "report.html"

    exit_code = run_pytest(args.path, html_report_path, headed=args.headed)


    if exit_code == 0:
        logger.info(f"All tests completed successfully. HTML report saved to: {html_report_path.resolve().as_posix()}")
    else:
        logger.warning(f"Test run finished with exit code {exit_code}. HTML report saved to: {html_report_path.resolve().as_posix()}")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
