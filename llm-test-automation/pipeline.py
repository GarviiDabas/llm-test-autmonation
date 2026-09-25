"""
pipeline.py — Runs the full LLM test generation and execution pipeline.

Steps:
  1. context_gatherer.py  — scrapes UI and fetches API context
  2. generate_tests.py        — calls Gemini to generate the test suite
  3. pytest                   — executes the generated tests

Usage:
    python pipeline.py                     # full run
    python pipeline.py --skip-gather       # skip context gathering (reuse existing)
    python pipeline.py --skip-generate     # skip LLM generation (reuse existing test file)
    python pipeline.py --headed            # run browser tests in headed mode
    python pipeline.py --model gemini-2.5-pro
"""

import argparse
import subprocess
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()


def run_step(cmd: list, step_name: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  STEP: {step_name}")
    print(f"{'=' * 60}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"\n[pipeline] '{step_name}' failed (exit code {result.returncode}). Aborting.")
        sys.exit(result.returncode)


def main():
    parser = argparse.ArgumentParser(description="LLM test generation + execution pipeline")
    parser.add_argument("--spec", default="config/test_spec.yaml", help="Path to test spec YAML")
    parser.add_argument("--skip-gather", action="store_true", help="Skip context gathering step")
    parser.add_argument("--skip-generate", action="store_true", help="Skip LLM generation step")
    parser.add_argument("--headed", action="store_true", help="Run browser tests in headed mode")
    parser.add_argument("--model", default=None, help="Gemini model override (e.g. gemini-2.5-pro)")
    args = parser.parse_args()

    spec = yaml.safe_load(Path(args.spec).read_text(encoding="utf-8"))
    target = spec.get("target", {})
    ui_url = target.get("ui_url", "")

    if not args.skip_gather:
        gather_cmd = [sys.executable, "context_gatherer.py", "--url", ui_url]
        run_step(gather_cmd, "Context Gathering (UI scrape + API context via Network)")

    if not args.skip_generate:
        gen_cmd = [sys.executable, "generate_tests.py", "--spec", args.spec]
        if args.model:
            gen_cmd += ["--model", args.model]
        run_step(gen_cmd, "Test Generation (Gemini API)")


if __name__ == "__main__":
    main()
