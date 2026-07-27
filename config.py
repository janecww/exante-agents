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
