import os
import time
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# Nemotron 3 Super (`nvidia/nemotron-3-super-120b-a12b:free`, used for
# the 27 Aug 2026 runs) was withdrawn from OpenRouter's free tier in
# Nov 2026; every scenario is re-run with this configuration instead.
MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
BASE_URL = "https://openrouter.ai/api/v1"

# Fixed sampling, to make runs as repeatable as the provider allows.
# Providers may still not be fully deterministic (and may ignore the
# seed), so this reduces run-to-run variability; it does not remove it.
TEMPERATURE = 0
SEED = 42

client = OpenAI(
    api_key=os.environ.get("OPENROUTER_API_KEY"),
    base_url=BASE_URL,
)


class LLMInvocationError(RuntimeError):
    """Raised by `invoke_llm` when the provider fails to return usable
    content -- e.g. `finish_reason='error'`, or an empty/`None` message
    with no other signal at all.

    This is a genuine provider-side failure, not a JSON-parsing
    problem: there is no response for a caller to save or parse in
    this case, so `invoke_llm` never returns `None` or an empty string
    for a caller to mistakenly treat as a real (if malformed) response.
    Never raised for a normal response, even a truncated one
    (`finish_reason='length'` with actual content) -- that is still a
    real string, returned as-is, exactly as before.
    """


def invoke_llm(prompt: str) -> str:
    """Send a single plain-text prompt to the configured LLM.

    Returns the model's raw reply text, unmodified and unparsed --
    this function never attempts to parse JSON or otherwise interpret
    the content; that is entirely the caller's responsibility. Callers
    should not need to know anything about OpenRouter, the OpenAI SDK,
    API keys, or the model name; they only need a `prompt -> str`
    callable -- this function never returns `None` or an empty string;
    a failed call raises `LLMInvocationError` instead (see below).

    `MODEL` is a large, free-tier reasoning model: even a modest prompt
    can legitimately take well over a minute to return (it generates an
    internal reasoning trace before its final answer, and free-tier
    throughput is shared/queued). That is normal, not a hang -- these
    prints exist so a slow-but-working call is visibly still in
    progress rather than indistinguishable from one that is stuck.

    Raises:
        LLMInvocationError: if the provider does not return usable
            content (e.g. `finish_reason='error'`, or no content at
            all). The message includes whatever diagnostic information
            is already available (elapsed time, `finish_reason`). Never
            retried, repaired, or silently treated as success here --
            that decision belongs to whoever runs the workflow.
    """
    print(
        "Invoking LLM... this can take a minute or more on this "
        "free-tier reasoning model; this is expected, not a hang."
    )
    started_at = time.monotonic()
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=TEMPERATURE,
        seed=SEED,
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

    if not content:
        # A genuine provider-side failure (e.g. finish_reason='error'):
        # there is no content to return. Raising here -- rather than
        # returning None -- is what keeps every caller (each agent's
        # `response = self.llm(prompt)`) from ever passing None on to
        # save_response()/json.loads(), which would otherwise fail with
        # an unrelated, misleading error of their own.
        raise LLMInvocationError(
            "LLM call did not return usable content after "
            f"{elapsed:.1f}s (finish_reason={finish_reason!r}). This is "
            "a provider-side failure, not a JSON-parsing problem -- "
            "there is nothing to save or parse. Not retried "
            "automatically; re-run the workflow once the underlying "
            "issue (e.g. a provider outage, rate limit, or content "
            "filter) has been resolved."
        )

    return content
