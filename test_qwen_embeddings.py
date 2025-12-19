import os

from dotenv import load_dotenv


def main() -> int:
    """Simple tester for DashScope/Qwen embedding models."""
    # Load env from the local .env
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

    try:
        from dashscope import embeddings
        import dashscope
    except ImportError as e:
        print("dashscope import failed:", e)
        print("Install with: pip install dashscope")
        return 1

    api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("QWEN_API_KEY")
    region = os.getenv("DASHSCOPE_REGION") or os.getenv("REGION")

    print("=== Qwen / DashScope Embedding Test ===")
    print("API key present:", bool(api_key))
    print("Region:", repr(region))

    if not api_key:
        print("No DASHSCOPE_API_KEY or QWEN_API_KEY found in environment.")
        return 1

    dashscope.api_key = api_key
    if region:
        dashscope.region = region

    models = ["text-embedding-v4", "text-embedding-v3"]
    test_text = "Test embedding from codebase_RAG"

    for model in models:
        print("\n============================")
        print(f"Testing embedding model: {model}")
        try:
            resp = embeddings.TextEmbedding.call(
                model=model,
                input=[test_text],
            )
            status = getattr(resp, "status_code", "<no status_code>")
            msg = getattr(resp, "message", None)
            print("Status code:", status)
            if status == 200:
                out = getattr(resp, "output", None)
                if isinstance(out, dict) and "embeddings" in out:
                    dim = len(out["embeddings"][0]["embedding"])
                    print("✓ Success. Dimension:", dim)
                else:
                    print("✓ Success but unexpected output format:", type(out), out)
            else:
                print("✗ Call did not succeed.")
                print("  Message:", msg)
        except Exception as e:
            print("✗ Exception while calling model", model)
            print("  ", repr(e))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


