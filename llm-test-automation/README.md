# LLM-Driven Test Automation (Playwright + Pytest + Gemini)

A fully autonomous pipeline that generates a comprehensive, robust test suite for your web application.

Instead of manually hardcoding elements or OpenAPI specs, this framework dynamically navigates your application, eavesdrops on the network to intercept API calls, and uses a Two-Phase LLM generation strategy to yield massive test coverage.

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
# Configure your .env file with your GEMINI_API_KEY and credentials
```

## How It Works

This project uses a **Two-Phase Generation Architecture**:
1. **Dynamic Context Gathering**: A headless browser navigates your UI, scrapes all interactive DOM elements, and intercepts backend API calls dynamically from the network tab.
2. **Phase 1 (The Planner)**: Gemini analyzes the gathered context and writes a comprehensive, bulleted Markdown test plan covering 30+ edge cases and happy paths.
3. **Phase 2 (The Coder)**: Gemini reads its own test plan and writes the exact Pytest code required to execute every single scenario.

## Usage

### 1. Configure the Target
Update `config/test_spec.yaml` with your target URLs and domain constraints. (Keep it minimal—the LLM will dynamically discover the endpoints and elements).

### 2. Run the Pipeline
Run the unified pipeline script to gather context and generate the tests in one go:
```bash
python pipeline.py
```
*(You can also use `--skip-gather` or `--skip-generate` if you only want to run a specific part of the pipeline).*

### 3. Review the Output
The pipeline generates three critical artifacts:
* `generated/logs/test_plan.md` - The comprehensive list of testing scenarios the LLM planned out.
* `generated/tests/test_<project>.py` - The executable Pytest suite.
* `generated/tests/<project>_manifest.json` - A machine-readable JSON summary of the generated tests (useful for CI/CD dashboards).

**Always review the generated Pytest file before running it.** Treat the output like a pull request from a junior engineer to ensure no destructive test actions leaked through.

### 4. Execute the Tests
Run the generated test suite using standard Pytest commands:
```bash
# Run tests headlessly in the background
python -m pytest generated/tests/

# Run tests with the browser UI visible
python -m pytest generated/tests/ --headed
```
HTML reports and test artifacts will automatically be saved to the `generated/reports/` directory.

## CI/CD Integration
Test *generation* is best kept as a manual, reviewed step to ensure safe code. Once generated, executing the tests in CI (GitHub Actions, GitLab CI) is straightforward: simply install dependencies and run `python -m pytest generated/tests/`.
