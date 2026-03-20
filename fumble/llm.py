import json
import os
import re
import time

from dotenv import load_dotenv

load_dotenv()

PROVIDER = os.getenv("LLM_PROVIDER", "ollama")
MODEL = os.getenv("LLM_MODEL", "qwen3.5:9b")

EXTRACT_PROVIDER = os.getenv("LLM_EXTRACT_PROVIDER", PROVIDER)
EXTRACT_MODEL = os.getenv("LLM_EXTRACT_MODEL", MODEL)

TRIAGE_PROVIDER = os.getenv("LLM_TRIAGE_PROVIDER", PROVIDER)
TRIAGE_MODEL = os.getenv("LLM_TRIAGE_MODEL", "llama3.2")

ASSESS_PROVIDER = os.getenv("LLM_ASSESS_PROVIDER", PROVIDER)
ASSESS_MODEL = os.getenv("LLM_ASSESS_MODEL", MODEL)
DEBUG = os.getenv("DEBUG_LLM", "").strip() == "1"


def call_llm(system: str, prompt: str, schema: dict, temperature: float | None = None, think: bool = True, model: str | None = None, provider: str | None = None, cached_prefix: str | None = None) -> str:
    """Call the configured LLM provider and return raw JSON string matching schema."""
    p = provider or PROVIDER
    if p == "ollama":
        return _call_ollama(system, prompt, schema, temperature, think, model or EXTRACT_MODEL)
    elif p == "openai":
        return _call_openai(system, prompt, schema, temperature, model or EXTRACT_MODEL)
    elif p == "anthropic":
        return _call_anthropic(system, prompt, schema, temperature, model or ASSESS_MODEL, cached_prefix=cached_prefix)
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {p!r}")


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
        debug_chars = int(os.getenv("DEBUG_LLM_CHARS", "300"))
        print(f"  [llm] raw: {(content or '')[:debug_chars]!r}")
    if not content:
        raise ValueError("LLM returned empty response")
    return content


def _call_openai(system: str, prompt: str, schema: dict, temperature: float | None, model: str) -> str:
    from openai import OpenAI

    client = OpenAI()
    response = client.chat.completions.create(
        model=model,
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


def _call_anthropic(system: str, prompt: str, schema: dict, temperature: float | None, model: str, cached_prefix: str | None = None) -> str:
    import anthropic

    client = anthropic.Anthropic()
    if cached_prefix:
        user_content = [
            {"type": "text", "text": cached_prefix, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": prompt},
        ]
    else:
        user_content = prompt
    kwargs = dict(
        model=model,
        max_tokens=4096,
        system=[{"type": "text", "text": system + f"\n\nRespond with a valid JSON object only. No prose, no markdown code fences.\n\nJSON schema:\n{json.dumps(schema)}", "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_content}],
    )
    if temperature is not None:
        kwargs["temperature"] = temperature
    response = client.messages.create(**kwargs)
    content = response.content[0].text
    if not content:
        raise ValueError("LLM returned empty response")
    return _extract_json(content)


def _extract_json(text: str) -> str:
    """Strip prose and code fences that Anthropic sometimes wraps around JSON."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        candidate = match.group(0)
        json.loads(candidate)  # raises if invalid
        return candidate
    raise ValueError(f"No valid JSON object found in response: {text[:200]}")
