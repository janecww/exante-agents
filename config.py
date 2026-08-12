import os
import time
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

MODEL = "nvidia/nemotron-3-super-120b-a12b:free"
BASE_URL = "https://openrouter.ai/api/v1"

client = OpenAI(
    api_key=os.environ.get("OPENROUTER_API_KEY"),
    base_url=BASE_URL,
)


def invoke_llm(prompt: str) -> str:
    """Send a single plain-text prompt to the configured LLM.

    Returns the model's raw reply text, unmodified and unparsed --
    this function never attempts to parse JSON or otherwise interpret
    the content; that is entirely the caller's responsibility. Callers
    should not need to know anything about OpenRouter, the OpenAI SDK,
    API keys, or the model name; they only need a `prompt -> str`
    callable.

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

    choice = response.choices[0]
    content = choice.message.content
    finish_reason = choice.finish_reason

    print(
        f"LLM responded after {elapsed:.1f}s "
        f"({len(content or '')} chars, finish_reason={finish_reason!r})"
    )
    if finish_reason == "length":
        # The provider's own signal that output was cut off at the max
        # token limit -- the most reliable truncation signal available,
        # since it comes from the API rather than being guessed from the
        # text afterward. Still just a print: this function returns the
        # string as-is either way and leaves what to do about it to the
        # caller.
        print(
            "Warning: finish_reason='length' -- the response was cut "
            "off at the model's output limit and is likely truncated "
            "(e.g. invalid/incomplete JSON)."
        )

    return content
