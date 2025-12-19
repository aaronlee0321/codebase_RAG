"""
Custom G-Eval style evaluator for CodeQA using Qwen as judge.

This bypasses DeepEval's built-in metrics so we can use a custom rubric:

You are grading an answer to a question.

You are given:
- The question
- A reference answer (expected_answer)
- A candidate answer (actual_answer)

Grade from 0.0 to 1.0 according to this rubric:

1. Coverage (0.0–0.7):
   - Does the candidate answer cover all key points in the reference answer?
   - 0.7 if it clearly includes all key points from the reference (even if it has more detail).
   - Lower if it misses or misstates important points.

2. Correctness / No hallucinations (0.0–0.3):
   - Extra details are allowed and should NOT be penalized if they are relevant and correct.
   - Subtract if the candidate introduces incorrect or contradictory information.

Scoring rule:
- Start from 1.0 if all key points are covered and there are no contradictions.
- Reduce the score if coverage is incomplete or if you detect incorrect/hallucinated content.
- Output only a single number between 0.0 and 1.0.

Usage:
1. Make sure CodeQA is running on http://localhost:5001
2. Ensure QWEN_API_KEY or DASHSCOPE_API_KEY is set, and optionally:
   - DASHSCOPE_REGION or OPENAI_BASE_URL
3. Make sure code_qa_test_cases.json has:
   - id, query, expected_answer, actual_answer
4. Run:
   python g_eval_evaluator.py
"""

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List

import requests
from openai import OpenAI


ROOT_DIR = Path(__file__).parent
TEST_CASES_FILE = ROOT_DIR / "code_qa_test_cases.json"
OUTPUT_FILE = ROOT_DIR / "g_eval_results.json"


def load_test_cases(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Test cases file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("code_qa_test_cases.json must contain a list of objects.")
    return data


def call_code_qa(query: str, rerank: bool = False, timeout: float = 60.0) -> str:
    """Fallback: call CodeQA to get actual_answer if it's missing."""
    resp = requests.post(
        "http://localhost:5001/",
        json={"query": query, "rerank": rerank},
        headers={"X-Requested-With": "XMLHttpRequest"},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("response", "")


def make_judge_client() -> OpenAI:
    api_key = (
        os.environ.get("OPENAI_API_KEY")
        or os.environ.get("QWEN_API_KEY")
        or os.environ.get("DASHSCOPE_API_KEY")
    )
    if not api_key:
        raise ValueError("Set OPENAI_API_KEY, QWEN_API_KEY, or DASHSCOPE_API_KEY for the judge model.")

    base_url = os.environ.get(
        "OPENAI_BASE_URL",
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    )

    return OpenAI(api_key=api_key, base_url=base_url)


RUBRIC_SYSTEM_PROMPT = """You are grading an answer to a question.

You are given:
- The question
- A reference answer (expected_answer)
- A candidate answer (actual_answer)

Grade from 0.0 to 1.0 according to this rubric:

1. Coverage (0.0–0.7):
   - Does the candidate answer cover all key points in the reference answer?
   - 0.7 if it clearly includes all key points from the reference (even if it has more detail).
   - Lower if it misses or misstates important points.

2. Correctness / No hallucinations (0.0–0.3):
   - Extra details are allowed and should NOT be penalized if they are relevant and correct.
   - Subtract if the candidate introduces incorrect or contradictory information.

Scoring rule:
- Start from 1.0 if all key points are covered and there are no contradictions.
- Reduce the score if coverage is incomplete or if you detect incorrect/hallucinated content.
- Output only a single number between 0.0 and 1.0.
"""


def grade_with_g_eval(
    client: OpenAI,
    model: str,
    question: str,
    expected_answer: str,
    actual_answer: str,
) -> float:
    """Use Qwen judge with the custom rubric to produce a score in [0, 1]."""
    user_prompt = f"""Question:
\"\"\"{question}\"\"\"

Reference (expected_answer):
\"\"\"{expected_answer}\"\"\"

Candidate (actual_answer):
\"\"\"{actual_answer}\"\"\"

Now provide a score between 0.0 and 1.0 according to the rubric.
Output only the number."""

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": RUBRIC_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0,
    )
    content = resp.choices[0].message.content.strip()

    # Extract the first float between 0 and 1
    match = re.search(r"([01](?:\.\d+)?)", content)
    if not match:
        raise ValueError(f"Could not parse score from judge output: {content!r}")

    score = float(match.group(1))
    # Clamp just in case
    score = max(0.0, min(1.0, score))
    return score


def main() -> int:
    print(f"Loading test cases from {TEST_CASES_FILE} ...")
    cases = load_test_cases(TEST_CASES_FILE)
    print(f"Loaded {len(cases)} test cases.")

    client = make_judge_client()
    judge_model = os.environ.get("JUDGE_MODEL", "qwen-plus")
    print(f"Using judge model: {judge_model}")

    results: List[Dict[str, Any]] = []

    for case in cases:
        case_id = case.get("id", "")
        question = case.get("query", "")
        expected = case.get("expected_answer", "") or ""
        actual = case.get("actual_answer")

        if not question:
            print(f"Skipping case {case_id or '[no-id]'}: missing 'query'")
            continue

        if not expected:
            print(f"Skipping case {case_id or '[no-id]'}: missing 'expected_answer'")
            continue

        if not actual:
            print(f"No 'actual_answer' for {case_id or '[no-id]'}, calling CodeQA ...")
            try:
                actual = call_code_qa(question, rerank=False)
            except Exception as e:
                print(f"  ! Error calling CodeQA: {e}")
                continue

        print(f"\nGrading test case {case_id or '[no-id]'} ...")
        try:
            score = grade_with_g_eval(client, judge_model, question, expected, actual)
            print(f"  ✓ Score: {score:.3f}")
        except Exception as e:
            print(f"  ! Error grading case {case_id or '[no-id]'}: {e}")
            continue

        result = {
            "id": case_id,
            "query": question,
            "expected_answer": expected,
            "actual_answer": actual,
            "score": score,
        }
        results.append(result)

    with OUTPUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\nSaved {len(results)} graded results to {OUTPUT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())





