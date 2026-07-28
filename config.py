import os
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
    """
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content
