import argparse
import json
import os
import re
import time
from pathlib import Path

import yaml
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai import errors as genai_errors
from utils.logger import get_logger
from utils.constants import API_BASE_URL, UI_BASE_URL, LOGIN_URL

logger = get_logger("generate_tests")

load_dotenv()


MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 15  # doubles each retry: 15s, 30s, 60s

MANIFEST_START, MANIFEST_END = "### MANIFEST_JSON_START", "### MANIFEST_JSON_END"
CODE_START, CODE_END = "### TEST_CODE_START", "### TEST_CODE_END"

def load_system_instruction() -> str:
    prompt_file = Path("config/system_prompt.txt")
    if prompt_file.exists():
        base_instruction = prompt_file.read_text().strip()
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
        trimmed.pop("accessibility_tree", None)  # keep prompt lean; element list is usually enough
        parts.append("\n## UI CONTEXT (interactive elements with suggested locators)\n")
        parts.append(json.dumps(trimmed, indent=2))
    if api_context:
        parts.append("\n## API CONTEXT (endpoints from OpenAPI spec)\n")
        parts.append(json.dumps(api_context, indent=2))
    return "".join(parts)


def call_gemini(prompt: str, model_name: str) -> str:
    client = genai.Client()  # reads GEMINI_API_KEY from the environment

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        temperature=0.2,  # low temperature - we want consistent, boring test code
        automatic_function_calling=types.AutomaticFunctionCallingConfig(
            disable=True
        ),
    )

    backoff = RETRY_BACKOFF_SECONDS
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=model_name, contents=[prompt], config=config,
            )
            return response.text
        except genai_errors.ServerError as e:
            # 503/overload and similar are transient - worth retrying.
            # 4xx-style client errors (bad key, bad request) are not - fail fast.
            if attempt == MAX_RETRIES:
                raise
            print(f"  Gemini server error ({e}). Retrying in {backoff}s "
                  f"(attempt {attempt}/{MAX_RETRIES})...")
            time.sleep(backoff)
            backoff *= 2


def sanitize_generated_code(code: str) -> str:
    """Belt-and-suspenders fixes for mistakes the model has made repeatedly
    despite prompt instructions saying not to. `page` is a pytest-playwright
    FIXTURE, not an importable name from playwright.sync_api - strip it from
    any import line here rather than relying solely on the prompt, since
    that hasn't been 100% reliable in practice."""
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
            "Model output did not follow the expected format. Raw output saved "
            "to logs/raw_model_output.txt for debugging."
        )

    manifest = json.loads(manifest_match.group(1).strip())
    code = code_match.group(1).strip()
    return manifest, code


def main():
    parser = argparse.ArgumentParser(description="Generate a pytest suite from spec + context")
    parser.add_argument("--spec", required=True, help="Path to the YAML test spec")
    parser.add_argument("--context", default="context", help="Directory with gathered context")
    parser.add_argument("--out", default="tests", help="Directory to write generated tests")
    parser.add_argument("--model", default=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))
    args = parser.parse_args()

    spec = yaml.safe_load(Path(args.spec).read_text())
    context_dir = Path(args.context)

    ui_context = None
    ui_path = context_dir / "ui_context.json"
    if ui_path.exists():
        ui_context = json.loads(ui_path.read_text(encoding="utf-8"))

    api_context = None
    api_path = context_dir / "api_context.json"
    if api_path.exists():
        api_context = json.loads(api_path.read_text(encoding="utf-8"))

    prompt = build_prompt(spec, ui_context, api_context)

    logger.info(f"Calling Gemini model: {args.model}")
    raw_output = call_gemini(prompt, args.model)

    Path("logs").mkdir(exist_ok=True)
    Path("logs/raw_model_output.txt").write_text(raw_output, encoding="utf-8")

    manifest, code = parse_response(raw_output)
    code = sanitize_generated_code(code)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    project_meta = spec.get("project_metadata", {})
    project_name = project_meta.get("project_name") or spec.get("project_name", "eventhub")
    feature_slug = project_name.replace(" ", "_")
    test_file = out_dir / f"test_{feature_slug}.py"
    test_file.write_text(code, encoding="utf-8")
    manifest_file = out_dir / f"{feature_slug}_manifest.json"
    manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


    logger.info(f"Wrote generated test suite to: {test_file}")
    logger.info(f"Wrote manifest file to: {manifest_file} ({len(manifest)} tests described)")
    logger.info("Review the generated file before running it - see README for the review checklist.")



if __name__ == "__main__":
    main()