"""
Populate 'actual_answer' for each test case in code_qa_test_cases.json
by calling the running CodeQA Flask app.

Usage:
1. Make sure CodeQA app.py is running on http://localhost:5001
2. In this venv, ensure 'requests' is installed:
   pip install requests
3. Run:
   python populate_actual_answers.py
"""

import json
from pathlib import Path

import requests


ROOT_DIR = Path(__file__).parent
TEST_CASES_FILE = ROOT_DIR / "code_qa_test_cases.json"


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
    return data.get("response", "")


def main() -> int:
    if not TEST_CASES_FILE.exists():
        print(f"Test cases file not found: {TEST_CASES_FILE}")
        return 1

    with TEST_CASES_FILE.open("r", encoding="utf-8") as f:
        try:
            test_cases = json.load(f)
        except json.JSONDecodeError as e:
            print(f"Failed to parse JSON from {TEST_CASES_FILE}: {e}")
            return 1

    if not isinstance(test_cases, list):
        print("code_qa_test_cases.json must contain a list of objects.")
        return 1

    print(f"Loaded {len(test_cases)} test cases.")

    updated = 0
    for case in test_cases:
        query = case.get("query")
        case_id = case.get("id", "")

        if not query:
            print(f"Skipping case {case_id or '[no-id]'}: missing 'query'")
            continue

        print(f"\nFetching actual_answer for test case {case_id or '[no-id]'} ...")
        try:
            actual_answer = call_code_qa(query, rerank=False)
        except Exception as e:
            print(f"  ! Error calling CodeQA for query '{query}': {e}")
            continue

        case["actual_answer"] = actual_answer
        updated += 1
        print(f"  ✓ Updated 'actual_answer' ({len(actual_answer)} chars)")

    # Write back to the same JSON file
    with TEST_CASES_FILE.open("w", encoding="utf-8") as f:
        json.dump(test_cases, f, indent=2, ensure_ascii=False)

    print(f"\nUpdated {updated} test cases with 'actual_answer'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


