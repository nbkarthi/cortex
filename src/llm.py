import logging
import os
import time
from openai import OpenAI
from config import (
    DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL,
    MINIMAX_API_KEY, MINIMAX_BASE_URL, MINIMAX_MODEL,
    OPENROUTER_API_KEY, OPENROUTER_BASE_URL, OPENROUTER_MODEL,
)

logger = logging.getLogger("cortex.llm")

# Select provider: set LLM_PROVIDER=deepseek to use DeepSeek, default is minimax
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "openrouter")

def _get_config() -> tuple[str, str, str]:
    """Return (api_key, base_url, model) for the active provider."""
    if LLM_PROVIDER == "deepseek":
        return DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
    if LLM_PROVIDER == "minimax":
        return MINIMAX_API_KEY, MINIMAX_BASE_URL, MINIMAX_MODEL
    return OPENROUTER_API_KEY, OPENROUTER_BASE_URL, OPENROUTER_MODEL


def get_client() -> OpenAI:
    api_key, base_url, _ = _get_config()
    return OpenAI(api_key=api_key, base_url=base_url)


def call_llm(system_prompt: str, user_prompt: str, label: str = "llm",
             max_retries: int = 2) -> str:
    api_key, base_url, model = _get_config()
    client = OpenAI(api_key=api_key, base_url=base_url)

    logger.info("[%s] Sending request to %s (model=%s)", label, base_url, model)
    logger.debug("[%s] System prompt: %.200s...", label, system_prompt)
    logger.debug("[%s] User prompt: %.500s...", label, user_prompt)

    for attempt in range(max_retries + 1):
        try:
            start = time.time()
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                max_tokens=4096,
            )
            elapsed = time.time() - start

            result = response.choices[0].message.content or ""
            tokens_in = response.usage.prompt_tokens if response.usage else 0
            tokens_out = response.usage.completion_tokens if response.usage else 0

            logger.info(
                "[%s] Response received in %.1fs | tokens: %d in / %d out | result length: %d chars",
                label, elapsed, tokens_in, tokens_out, len(result),
            )
            logger.debug("[%s] Result preview: %.300s...", label, result)

            return result
        except Exception as e:
            if attempt < max_retries:
                wait = 3 * (attempt + 1)
                logger.warning("[%s] Request failed (%s), retrying in %ds...", label, e, wait)
                time.sleep(wait)
            else:
                logger.error("[%s] Request failed after %d attempts: %s", label, max_retries + 1, e)
                return ""
