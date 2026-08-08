import os
import time
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
BASE_URL = "https://openrouter.ai/api/v1"

client = OpenAI(
    api_key=os.environ.get("OPENROUTER_API_KEY"),
    base_url=BASE_URL,
)


def invoke_llm(prompt: str) -> str:
    """Send a single plain-text prompt to the configured LLM.

    Returns the model's raw reply text. Callers should not need to know
    anything about OpenRouter, the OpenAI SDK, API keys, or the model
    name; they only need a `prompt -> str` callable.

    `MODEL` is a large, free-tier reasoning model: even a modest prompt
    can legitimately take well over a minute to return (it generates an
    internal reasoning trace before its final answer, and free-tier
    throughput is shared/queued). That is normal, not a hang -- these
    prints exist so a slow-but-working call is visibly still in
    progress rather than indistinguishable from one that is stuck.
    """
    print(
        "Invoking LLM... this can take a minute or more on this "
        "free-tier reasoning model; this is expected, not a hang."
    )
    started_at = time.monotonic()
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
    )
    elapsed = time.monotonic() - started_at
    print(f"LLM responded after {elapsed:.1f}s")

    return response.choices[0].message.content
