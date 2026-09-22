# LLM-driven test automation (Python + Playwright + pytest + Gemini)

A pipeline that turns a structured spec file into a reviewed, runnable
pytest suite: gather real page/API context -> generate tests with Gemini ->
you review -> run with pytest -> always get a structured log.

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
cp .env.example .env   # fill in GEMINI_API_KEY and test credentials
```

Get a Gemini API key from Google AI Studio (https://aistudio.google.com/apikey).

## Workflow

**1. Write the spec.** Copy `config/test_spec.example.yaml`, fill in your
target URL, test types, framework, coverage focus, and constraints
(destructive-action guardrails, environment limits, etc). This file is your
source of truth - keep it in version control.

**2. Gather context.**
```bash
python context_gatherer.py --url https://your-app.com/login \
    --openapi https://your-app.com/api/openapi.json \
    --out context/
```
This drives a headless Chromium browser to the page, extracts every visible
interactive element with a suggested Playwright locator (ranked
`data-testid` > role/aria-label > id > name > text), takes a full-page
screenshot, and pulls a compact summary of your OpenAPI spec if you have one.
Run it once per page/flow you want covered - `context/` fills up with a
`ui_context.json`, `api_context.json`, and `screenshot.png` you can inspect
directly.

**3. Generate tests.**
```bash
python generate_tests.py --spec config/test_spec.yaml --context context/
```
Sends the spec + context to Gemini and writes `tests/test_<project>.py`
plus a `_manifest.json` describing each generated test (id, description,
type, expected result). The raw model response is also saved to
`logs/raw_model_output.txt` for debugging if parsing fails.

**4. Review before running - this step is not optional.** Treat the output
like a pull request:
- [ ] Every locator actually came from the context file - nothing invented
- [ ] API assertions check status code *and* response shape, not just "no error"
- [ ] No destructive actions leaked in (real payments, prod deletes, etc)
- [ ] Test names and docstrings actually describe what's being verified
- [ ] Constraints from the spec are respected (account limits, environment)

**5. Run.**
```bash
python run_tests.py --path tests/test_your_project.py
```
This always writes `logs/report_<timestamp>.json` (structured, machine
readable) and `logs/summary_<timestamp>.txt` (human readable) - on a full
pass as well as a failure. `pytest.ini` is already configured to capture a
screenshot, video, and trace on any UI test failure, so most failures are
debuggable from the log alone.

**6. Optional: triage failures with Gemini.**
```bash
python run_tests.py --path tests/ --triage
```
Sends failure details back to Gemini to classify each as a real bug, a
flaky test, a stale locator, or an environment issue. This is a starting
point for debugging, not a verdict - it still goes through you.

## A note on the Gemini model name

Google renames and retires models fairly often. This code defaults to
`gemini-2.5-flash` via the `GEMINI_MODEL` env var, but Google has scheduled
that model's shutdown for 16 October 2026. Check
https://ai.google.dev/gemini-api/docs/models for the current recommended
model and set `GEMINI_MODEL` in `.env` accordingly - no code changes needed.

## CI

Both `context_gatherer.py` (if your context doesn't change often, you can
cache its output) and `run_tests.py` are plain scripts, so wiring this into
GitHub Actions/GitLab CI is just: install deps, install Playwright browsers,
run `run_tests.py`, upload `logs/` and `tests/` as artifacts. Test
*generation* is best kept as a manual/reviewed step rather than run on every
CI trigger, since it produces code a human should read before it's trusted.
