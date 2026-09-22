"""
generate_tests.py

Sends the structured spec file + gathered UI/API context to Gemini and asks
for a ready-to-run pytest test suite, plus a manifest describing each test.
The output is written to disk for human review - nothing here runs tests.

Model note: Google's model lineup moves fast and names change (see
https://ai.google.dev/gemini-api/docs/models for the current list). This
defaults to GEMINI_MODEL from the environment so you can update it in one
place without touching code. gemini-2.5-flash is used as a safe fallback,
but Google has scheduled it for shutdown on 16 Oct 2026 - check the docs
link above before relying on it.

Usage:
    python generate_tests.py --spec config/test_spec.yaml --context context/
"""

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

load_dotenv()

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 15  # doubles each retry: 15s, 30s, 60s

MANIFEST_START, MANIFEST_END = "### MANIFEST_JSON_START", "### MANIFEST_JSON_END"
CODE_START, CODE_END = "### TEST_CODE_START", "### TEST_CODE_END"

SYSTEM_INSTRUCTION = f"""You are a senior QA automation engineer. You write
Python test suites using pytest, and Playwright for UI tests or requests for
API tests, based on a structured spec and real page/API context provided by
the user - never invent locators, endpoints, or fields that aren't in the
supplied context.

Rules:
- This is PYTHON Playwright, not JavaScript/TypeScript Playwright. Assertion
  methods use snake_case: to_be_visible(), to_have_url(), to_have_value(),
  to_be_enabled(), etc. NEVER use camelCase JS-style names like
  toBeVisible(), toHaveURL(), toHaveValue() - these do not exist in the
  Python API and will crash with AttributeError.
- `page` is a FIXTURE, not an importable name. NEVER write
  `from playwright.sync_api import page` - this does not exist and will
  crash. The only real imports from playwright.sync_api are `Page` (the
  type, capital P, used only for type hints) and `expect`. A test receives
  the page fixture as a parameter: `def test_x(self, page: Page):`.
- expect(page).to_have_url() accepts a string or a compiled regex
  (re.compile(...)) - NEVER a lambda or predicate function. Import re if
  you use this.
- When you need a unique value (e.g. a unique test email), use the
  simplest possible expression: `int(time.time())` or
  `uuid.uuid4().hex[:8]`. Do not write nested or chained expressions you
  have not double-checked are syntactically valid Python - a malformed
  expression breaks the entire file, not just one test.
- If any endpoint in the API context is marked auth_required: true, OR if
  you cannot confirm an endpoint is public, write the test so it first
  obtains a token (via POST /auth/register or /auth/login) and sends it
  as an Authorization: Bearer <token> header. Do not assume an endpoint is
  public just because the API context doesn't explicitly say it requires
  auth - when in doubt, send the token anyway, since sending an unneeded
  token is harmless but omitting a required one causes a 401 failure that
  looks like a bug in the app rather than in the test.
- If the API context includes a "note" field on an endpoint describing a
  CONFIRMED response shape or behavior from a real test run, treat that
  as ground truth and write assertions that match it exactly - it is more
  reliable than the schema name alone.
- Some data-testid values appear MORE THAN ONCE in the context (e.g. a
  repeated card or button in a list). If you use a get_by_test_id() or
  similar locator whose testid appears more than once in the supplied
  element list, you MUST disambiguate it with .filter(has_text="...")
  using a specific piece of text from that one element, or .nth(index).
  Never use a plain get_by_test_id() call that would match multiple
  elements without doing this.
- Use ONLY the locators suggested in the context, or ones directly
  derivable from the accessibility tree / element list. Never guess a
  CSS selector that wasn't given to you.
- Use ONLY the endpoints, methods, and parameters present in the API
  context. Never invent an endpoint.
- Respect every item under "constraints" in the spec exactly (e.g. no real
  payments, no destructive actions outside staging). If the UI context
  shows admin-only controls (e.g. Add New Event, Manage Events, Delete),
  do not write tests that use them unless the spec explicitly asks for
  admin flow coverage - assume they are out of scope by default.
- Each test must have a clear docstring stating what it verifies and why.
- Group related tests into classes named Test<Feature>.
- Output MUST follow this exact structure and nothing else:

{MANIFEST_START}
<a single JSON array - each item: {{"id": "...", "description": "...",
  "type": "ui"|"api", "expected_result": "..."}}>
{MANIFEST_END}
{CODE_START}
<complete, runnable Python test file content - imports included>
{CODE_END}

Do not include any prose, explanation, or markdown fences outside those
markers."""


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
        ui_context = json.loads(ui_path.read_text())

    api_context = None
    api_path = context_dir / "api_context.json"
    if api_path.exists():
        api_context = json.loads(api_path.read_text())

    prompt = build_prompt(spec, ui_context, api_context)

    print(f"Calling {args.model} ...")
    raw_output = call_gemini(prompt, args.model)

    Path("logs").mkdir(exist_ok=True)
    Path("logs/raw_model_output.txt").write_text(raw_output)

    manifest, code = parse_response(raw_output)
    code = sanitize_generated_code(code)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    project_meta = spec.get("project_metadata", {})
    project_name = project_meta.get("project_name") or spec.get("project_name", "eventhub")
    feature_slug = project_name.replace(" ", "_")
    test_file = out_dir / f"test_{feature_slug}.py"
    test_file.write_text(code)
    (out_dir / f"{feature_slug}_manifest.json").write_text(json.dumps(manifest, indent=2))

    print(f"Wrote {test_file}")
    print(f"Wrote {out_dir}/{feature_slug}_manifest.json ({len(manifest)} tests described)")
    print("\nReview the generated file before running it - see README for the review checklist.")


if __name__ == "__main__":
    main()