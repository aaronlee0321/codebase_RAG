"""
DeepEval-based evaluator for the CodeQA app.

Usage:
1. Make sure the CodeQA Flask app is running on http://localhost:5001
2. Install DeepEval (in this venv):
   pip install deepeval
3. Ensure your Qwen/OpenAI-compatible environment is configured for DeepEval, e.g.:
   - OPENAI_API_KEY (your Qwen/DashScope key)
   - OPENAI_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
4. Manually populate `code_qa_test_cases.json` with your test set.
5. Run:
   python deepeval_evaluator.py
"""

import json
from pathlib import Path

import requests
from deepeval import evaluate
from deepeval.metrics import AnswerRelevancyMetric
from deepeval.test_case import LLMTestCase


ROOT_DIR = Path(__file__).parent
TEST_CASES_FILE = ROOT_DIR / "code_qa_test_cases.json"


def load_test_cases(path: Path):
    """Load test cases from JSON.

    Expected schema:
    [
      {
        "id": "GM-001",
        "query": "@codebase summarise GameManager",
        "expected_answer": "High-level description of GameManager..."
      },
      ...
    ]
    """
    if not path.exists():
        raise FileNotFoundError(
            f"Test cases file not found at {path}. "
            "Create it and populate with your questions and expected answers."
        )

    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    if not isinstance(raw, list):
        raise ValueError("code_qa_test_cases.json must contain a list of test cases.")

    return raw


def call_code_qa(query: str, rerank: bool = False, timeout: float = 60.0) -> str:
    """Call the running CodeQA Flask app and return the answer."""
    resp = requests.post(
        "http://localhost:5001/",
        json={"query": query, "rerank": rerank},
        headers={"X-Requested-With": "XMLHttpRequest"},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    # The Flask app returns {'response': answer}
    return data.get("response", "")


def main() -> int:
    # 1. Load test cases
    print(f"Loading test cases from {TEST_CASES_FILE} ...")
    raw_cases = load_test_cases(TEST_CASES_FILE)
    print(f"Loaded {len(raw_cases)} test cases.")

    # 2. Define metrics (using Qwen as the judge via OpenAI-compatible API)
    metrics = [
        AnswerRelevancyMetric(
            model="qwen-plus",  # Judge model; ensure DeepEval can reach this via OPENAI_BASE_URL
            threshold=0.7,
        )
    ]

    # 3. Build DeepEval test cases
    test_cases: list[LLMTestCase] = []

    for item in raw_cases:
        query = item["query"]
        expected_answer = item.get("expected_answer", "")
        case_id = item.get("id", "")

        print(f"\nQuerying CodeQA for test case {case_id or '[no-id]'} ...")
        try:
            generated_answer = call_code_qa(query, rerank=False)
        except Exception as e:
            print(f"  ! Error calling CodeQA for query '{query}': {e}")
            continue

        test_case = LLMTestCase(
            input=query,
            actual_output=generated_answer,
            expected_output=expected_answer,
            # You can optionally attach context here if you log it:
            # context="...", 
            metadata={"id": case_id},
        )
        test_cases.append(test_case)

    if not test_cases:
        print("No valid test cases to evaluate. Exiting.")
        return 1

    # 4. Run DeepEval evaluation
    print(f"\nRunning DeepEval on {len(test_cases)} test cases ...")
    eval_results = evaluate(
        test_cases=test_cases,
        metrics=metrics,
    )

    # 5. Save results
    output_file = ROOT_DIR / "deepeval_results.json"
    try:
        # eval_results may already be serializable, but we ensure a dict form
        if hasattr(eval_results, "to_dict"):
            payload = eval_results.to_dict()
        else:
            # Fallback: try naive conversion
            payload = json.loads(json.dumps(eval_results, default=str))

        with output_file.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

        print(f"\nDeepEval results saved to: {output_file}")
    except Exception as e:
        print(f"\nWarning: Failed to save results JSON: {e}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


