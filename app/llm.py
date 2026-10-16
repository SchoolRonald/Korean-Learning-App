import json
import logging
import os
import threading
import time

import anthropic

MODEL = "claude-haiku-5-5"
CALL_CAP = int(os.environ.get("GONGBU_LLM_CAP", "50"))

log = logging.getLogger("gongbu.llm")
if not log.handlers:
    log.setLevel(logging.INFO)
    log.propagate = False
    for handler in (logging.FileHandler("llm_usage.log", delay=True), logging.StreamHandler()):
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        log.addHandler(handler)

# Totals since the server started; the cap resets on restart.
usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
_usage_lock = threading.Lock()
_client = None


class LLMError(Exception):
    """Raised with a message that is safe to show the user."""


def get_client():
    global _client
    if _client is None:
        client = anthropic.Anthropic()
        # Without credentials the SDK raises a plain TypeError at request time, so check up front.
        if not (client.api_key or client.auth_token or client.credentials):
            raise LLMError("No Anthropic API key found. Set ANTHROPIC_API_KEY and restart the server.")
        _client = client
    return _client


def usage_summary():
    return {"calls": usage["calls"], "cap": CALL_CAP}


def call_json(purpose, system, prompt, schema, max_tokens=2048, effort="low"):
    """One Claude call that must return a JSON object matching schema."""
    client = get_client()
    # Count before calling so failing requests also use up the cap. Locked because the
    # background prefetch can call at the same time as a request.
    with _usage_lock:
        if usage["calls"] >= CALL_CAP:
            raise LLMError(f"LLM call limit ({CALL_CAP}) reached for this session. Restart the server to reset it.")
        usage["calls"] += 1
        call_no = usage["calls"]
    start = time.perf_counter()
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            system=system,
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.AuthenticationError:
        raise LLMError("The API key was rejected. Check ANTHROPIC_API_KEY.")
    except anthropic.RateLimitError:
        raise LLMError("Rate limited by the API. Wait a moment and try again.")
    except anthropic.APIConnectionError:
        raise LLMError("Could not reach the Anthropic API.")
    except anthropic.APIStatusError as e:
        raise LLMError(f"The API returned an error ({e.status_code}).")
    except anthropic.AnthropicError as e:
        raise LLMError(f"LLM unavailable: {e}")

    seconds = time.perf_counter() - start
    with _usage_lock:
        usage["input_tokens"] += response.usage.input_tokens
        usage["output_tokens"] += response.usage.output_tokens
        totals = usage["input_tokens"], usage["output_tokens"]
    log.info(
        "%s call %d/%d: %.2fs in=%d out=%d (session total in=%d out=%d)",
        purpose, call_no, CALL_CAP, seconds, response.usage.input_tokens, response.usage.output_tokens, *totals,
    )

    if response.stop_reason == "refusal":
        raise LLMError("The model declined this request.")
    text = "".join(b.text for b in response.content if b.type == "text")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        log.warning("%s returned malformed JSON (stop_reason=%s): %r", purpose, response.stop_reason, text[:200])
        raise LLMError("The model returned output that could not be read.")
    if not isinstance(data, dict):
        raise LLMError("The model returned output that could not be read.")
    return data
