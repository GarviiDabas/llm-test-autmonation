"""
run_tests.py

Runs the (human-reviewed) generated pytest suite and always writes a log -
whether everything passed or something failed. Playwright screenshots/video/
trace on failure are enabled via pytest.ini, so failure logs are usually
self-contained enough to debug without rerunning.

Usage:
    python run_tests.py                     # run everything in tests/
    python run_tests.py --path tests/test_example_shop.py
    python run_tests.py --triage            # also ask Gemini to explain failures
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def run_pytest(test_path: str, report_path: Path) -> int:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, "-m", "pytest", test_path,
        "-v",
        f"--json-report", f"--json-report-file={report_path}",
    ]
    result = subprocess.run(cmd)
    return result.returncode


def summarize(report_path: Path, summary_path: Path) -> dict:
    data = json.loads(report_path.read_text())
    summary = data.get("summary", {})
    failures = [
        {
            "test": t["nodeid"],
            "outcome": t["outcome"],
            "message": t.get("call", {}).get("longrepr", "")[:2000],
        }
        for t in data.get("tests", []) if t["outcome"] not in ("passed", "skipped")
    ]

    lines = [
        f"Test run: {datetime.now(timezone.utc).isoformat()}",
        f"Total: {summary.get('total', 0)}  "
        f"Passed: {summary.get('passed', 0)}  "
        f"Failed: {summary.get('failed', 0)}  "
        f"Errors: {summary.get('error', 0)}  "
        f"Skipped: {summary.get('skipped', 0)}",
        "",
    ]
    if failures:
        lines.append("FAILURES:")
        for f in failures:
            lines.append(f"  - {f['test']} [{f['outcome']}]")
            lines.append(f"    {f['message'].splitlines()[-1] if f['message'] else ''}")
    else:
        lines.append("All tests passed.")

    summary_path.write_text("\n".join(lines))
    return {"summary": summary, "failures": failures}


def triage_failures(failures: list, model_name: str) -> str | None:
    """Ask Gemini to classify failures as real bugs / flaky / stale locators."""
    if not failures:
        return None
    from google import genai

    client = genai.Client()
    prompt = (
        "Here are pytest failure details from an automated UI/API test suite.\n"
        "For each failure, classify it as one of: REAL_BUG, FLAKY_TEST, "
        "STALE_LOCATOR, ENVIRONMENT_ISSUE, and give a one-line reason. "
        "Do not suggest code changes - only classify and explain.\n\n"
        f"{json.dumps(failures, indent=2)}"
    )
    response = client.models.generate_content(model=model_name, contents=prompt)
    return response.text


def main():
    parser = argparse.ArgumentParser(description="Run the reviewed test suite and log results")
    parser.add_argument("--path", default="tests/", help="Test file or directory to run")
    parser.add_argument("--triage", action="store_true", help="Send failures to Gemini for triage")
    parser.add_argument("--model", default=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))
    args = parser.parse_args()

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    logs_dir = Path("logs")
    report_path = logs_dir / f"report_{ts}.json"
    summary_path = logs_dir / f"summary_{ts}.txt"

    exit_code = run_pytest(args.path, report_path)
    result = summarize(report_path, summary_path)

    print(f"\nStructured report: {report_path}")
    print(f"Human-readable summary: {summary_path}")

    if args.triage and result["failures"]:
        triage_text = triage_failures(result["failures"], args.model)
        triage_path = logs_dir / f"triage_{ts}.txt"
        triage_path.write_text(triage_text or "")
        print(f"Triage notes: {triage_path}")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
