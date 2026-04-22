import logging
import time
from openai import OpenAI
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

logger = logging.getLogger("cortex.llm")


def get_client() -> OpenAI:
    return OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)


def call_llm(system_prompt: str, user_prompt: str, label: str = "llm") -> str:
    client = get_client()

    logger.info("[%s] Sending request to %s (model=%s)", label, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL)
    logger.debug("[%s] System prompt: %.200s...", label, system_prompt)
    logger.debug("[%s] User prompt: %.500s...", label, user_prompt)

    start = time.time()
    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        max_tokens=4096,
    )
    elapsed = time.time() - start

    result = response.choices[0].message.content
    tokens_in = response.usage.prompt_tokens if response.usage else 0
    tokens_out = response.usage.completion_tokens if response.usage else 0

    logger.info(
        "[%s] Response received in %.1fs | tokens: %d in / %d out | result length: %d chars",
        label, elapsed, tokens_in, tokens_out, len(result),
    )
    logger.debug("[%s] Result preview: %.300s...", label, result)

    return result
