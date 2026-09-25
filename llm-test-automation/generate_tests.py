import argparse
import json
import os
import re
from pathlib import Path

import yaml
from dotenv import load_dotenv
from google import genai
from google.genai import types
from utils.logger import get_logger
from utils.constants import (
    API_BASE_URL,
    UI_BASE_URL,
    LOGIN_URL,
    DEFAULT_GEMINI_MODEL,
    DEFAULT_PROJECT_SLUG
)

logger = get_logger("generate_tests")

load_dotenv()


MANIFEST_START, MANIFEST_END = "### MANIFEST_JSON_START", "### MANIFEST_JSON_END"
CODE_START, CODE_END = "### TEST_CODE_START", "### TEST_CODE_END"


PLANNER_INSTRUCTION = """You are a senior QA Architect.
Analyze the provided application context (UI elements, API endpoints, and constraints) and generate a MASSIVE, exhaustive test plan.
DO NOT WRITE CODE. Output only a structured markdown list of test scenarios.

Categories to include:
1. API - Positive (Happy path)
2. API - Negative (Missing auth, bad payloads, 404s, 400s)
3. API - Edge Cases (Empty strings, zeroes, nulls)
4. UI - Authentication & Navigation
5. UI - Form Validation & Error States
6. UI - End-to-End Workflows

For each scenario, write a 1-sentence description (e.g., "- POST /bookings with quantity 0 should return 400").
Push for extremely high coverage. Generate at least 30-40 distinct test scenarios covering everything in the context.
"""


def load_system_instruction() -> str:
    prompt_file = Path("config/system_prompt.txt")
    if prompt_file.exists():
        base_instruction = prompt_file.read_text(encoding="utf-8").strip()
    else:
        base_instruction = "You are a senior QA automation engineer writing pytest suites."

    output_format = f"""
Output MUST follow this exact structure and nothing else:

{MANIFEST_START}
<a single JSON array - each item: {{"id": "...", "description": "...", "type": "ui"|"api", "expected_result": "..."}}>
{MANIFEST_END}
{CODE_START}
<complete, runnable Python test file content - imports included>
{CODE_END}

Do not include any prose, explanation, or markdown fences outside those markers."""

    return f"{base_instruction}\n\n{output_format}"


SYSTEM_INSTRUCTION = load_system_instruction()


def build_prompt(spec: dict, ui_context: dict | None, api_context: dict | None) -> str:
    parts = ["## TEST SPEC\n", yaml.dump(spec, sort_keys=False)]
    if ui_context:
        trimmed = {**ui_context}
        trimmed.pop("accessibility_tree", None)
        parts.append("\n## UI CONTEXT (interactive elements)\n")
        parts.append(json.dumps(trimmed, indent=2))
    if api_context:
        parts.append("\n## API CONTEXT (intercepted endpoints)\n")
        parts.append(json.dumps(api_context, indent=2))
    return "".join(parts)


def call_gemini(prompt: str, model_name: str, sys_inst: str, log_file_name: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise EnvironmentError("No Gemini API key found. Set GEMINI_API_KEY or GOOGLE_API_KEY.")

    client = genai.Client()
    config = types.GenerateContentConfig(
        system_instruction=sys_inst,
        temperature=0.2,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    try:
        response = client.models.generate_content(
            model=model_name, contents=[prompt], config=config,
        )
    except Exception as e:
        raise RuntimeError(f"Gemini API call failed ({type(e).__name__}): {e}") from e

    Path("generated/logs").mkdir(parents=True, exist_ok=True)
    raw_text = response.text or ""
    Path(f"generated/logs/{log_file_name}").write_text(raw_text, encoding="utf-8")

    if not raw_text.strip():
        raise ValueError(f"Gemini returned an empty response.")

    return raw_text


def sanitize_generated_code(code: str) -> str:
    def fix_import(match):
        names = [n.strip() for n in match.group(1).split(",")]
        had_page = "page" in names
        names = [n for n in names if n != "page"]
        if had_page and "Page" not in names:
            names.append("Page")
        return f"from playwright.sync_api import {', '.join(names)}"

    return re.sub(r"from playwright\.sync_api import ([^\n]+)", fix_import, code)


def parse_response(text: str) -> tuple[list, str]:
    manifest_match = re.search(rf"{MANIFEST_START}(.*?){MANIFEST_END}", text, re.DOTALL)
    code_match = re.search(rf"{CODE_START}(.*?){CODE_END}", text, re.DOTALL)

    if not manifest_match or not code_match:
        raise ValueError(
            "Model output did not follow the expected format. Raw output saved to logs for debugging."
        )

    manifest = json.loads(manifest_match.group(1).strip())
    code = code_match.group(1).strip()
    return manifest, code


def main():
    parser = argparse.ArgumentParser(description="Generate a pytest suite from spec + context using Planner Strategy")
    parser.add_argument("--spec", required=True, help="Path to the YAML test spec")
    parser.add_argument("--context", default="generated/context", help="Directory with gathered context")
    parser.add_argument("--out", default="generated/tests", help="Directory to write generated tests")
    parser.add_argument("--model", default=os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL))
    args = parser.parse_args()

    spec = yaml.safe_load(Path(args.spec).read_text(encoding="utf-8"))
    context_dir = Path(args.context)

    ui_context = None
    ui_path = context_dir / "ui_context.json"
    if ui_path.exists():
        ui_context = json.loads(ui_path.read_text(encoding="utf-8"))

    api_context = None
    api_path = context_dir / "api_context.json"
    if api_path.exists():
        api_context = json.loads(api_path.read_text(encoding="utf-8"))

    context_str = build_prompt(spec, ui_context, api_context)

    # --- PHASE 1: PLANNING ---
    logger.info(f"PHASE 1: Generating massive Test Plan using {args.model}")
    plan_prompt = f"Here is the application context:\n\n{context_str}\n\nGenerate the comprehensive Test Plan now."
    test_plan = call_gemini(plan_prompt, args.model, PLANNER_INSTRUCTION, "test_plan.md")
    logger.info("Test plan generated and saved to generated/logs/test_plan.md")

    # --- PHASE 2: CODING ---
    logger.info(f"PHASE 2: Generating Pytest Code from Plan using {args.model}")
    code_prompt = f"Here is the application context:\n\n{context_str}\n\nHere is the APPROVED TEST PLAN:\n\n{test_plan}\n\nYour task is to write the complete, executable pytest file that implements EVERY single scenario in the test plan exactly as described."
    raw_output = call_gemini(code_prompt, args.model, SYSTEM_INSTRUCTION, "raw_model_output.txt")

    manifest, code = parse_response(raw_output)
    code = sanitize_generated_code(code)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    project_meta = spec.get("project_metadata", {})
    project_name = project_meta.get("project_name") or spec.get("project_name", DEFAULT_PROJECT_SLUG)
    feature_slug = project_name.replace(" ", "_")
    test_file = out_dir / f"test_{feature_slug}.py"
    test_file.write_text(code, encoding="utf-8")
    manifest_file = out_dir / f"{feature_slug}_manifest.json"
    manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    logger.info(f"Wrote generated test suite to: {test_file}")
    logger.info(f"Wrote manifest file to: {manifest_file} ({len(manifest)} tests described)")
    logger.info("Review the generated file before running it!")

if __name__ == "__main__":
    main()
