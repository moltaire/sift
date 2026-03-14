import json
import os
import re
import time

from dotenv import load_dotenv

load_dotenv()

PROVIDER = os.getenv("LLM_PROVIDER", "ollama")
MODEL = os.getenv("LLM_MODEL", "llama3.1:8b")
EXTRACT_MODEL = os.getenv("LLM_EXTRACT_MODEL", MODEL)
DEBUG = os.getenv("DEBUG_LLM", "").strip() == "1"


def call_llm(system: str, prompt: str, schema: dict, temperature: float | None = None, think: bool = True, model: str | None = None) -> str:
    """Call the configured LLM provider and return raw JSON string matching schema."""
    if PROVIDER == "ollama":
        return _call_ollama(system, prompt, schema, temperature, think, model or MODEL)
    elif PROVIDER == "openai":
        return _call_openai(system, prompt, schema, temperature)
    elif PROVIDER == "anthropic":
        return _call_anthropic(system, prompt, schema, temperature)
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {PROVIDER!r}")


def _call_ollama(system: str, prompt: str, schema: dict, temperature: float | None, think: bool, model: str) -> str:
    import ollama

    kwargs = dict(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        format=schema,
    )
    if temperature is not None:
        kwargs["options"] = {"temperature": temperature}
    if not think:
        kwargs["think"] = False
    t0 = time.monotonic()
    response = ollama.chat(**kwargs)
    elapsed = time.monotonic() - t0
    content = response.message.content
    if DEBUG:
        thinking = getattr(response.message, "thinking", None)
        think_len = len(thinking) if thinking else 0
        print(f"  [llm] {elapsed:.1f}s | think={think_len}chars | output={len(content or '')}chars")
        print(f"  [llm] raw: {(content or '')[:300]!r}")
    if not content:
        raise ValueError("LLM returned empty response")
    return content


def _call_openai(system: str, prompt: str, schema: dict, temperature: float) -> str:
    from openai import OpenAI

    client = OpenAI()
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=temperature,
    )
    content = response.choices[0].message.content
    if not content:
        raise ValueError("LLM returned empty response")
    return content


def _call_anthropic(system: str, prompt: str, schema: dict, temperature: float) -> str:
    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=system
        + "\n\nRespond with a valid JSON object only. No prose, no markdown code fences.",
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    content = response.content[0].text
    if not content:
        raise ValueError("LLM returned empty response")
    return _extract_json(content)


def _extract_json(text: str) -> str:
    """Strip prose and code fences that Anthropic sometimes wraps around JSON."""
    # Try to find a JSON object in the response
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        candidate = match.group(0)
        json.loads(candidate)  # raises if invalid
        return candidate
    raise ValueError(f"No valid JSON object found in response: {text[:200]}")
