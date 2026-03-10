"""
claude_client.py — centralny klient Claude z retry, logowaniem tokenów i rate-limit.

Wszyscy agenci używają tej funkcji zamiast bezpośrednio anthropic.Anthropic().
Jedno miejsce do konfiguracji modelu, timeoutów i obsługi błędów.

Użycie:
    from src.utils.claude_client import claude_text, claude_json

    # Prosty tekst
    text = claude_text("Napisz opis produktu...", max_tokens=1024)

    # Odpowiedź JSON (automatyczny parsing + retry przy błędzie JSON)
    data = claude_json("Zwróć JSON z title i description...", max_tokens=2048)
"""
import json
import logging
import os
import re
import time

log = logging.getLogger(__name__)

# Modele domyślne
DEFAULT_MODEL   = "claude-sonnet-4-6"
FAST_MODEL      = "claude-haiku-4-5-20251001"
POWERFUL_MODEL  = "claude-opus-4-6"

# Retry settings
MAX_RETRIES    = 3
RETRY_BACKOFF  = 2.0   # sekundy między próbami (podwaja się)


def _client():
    """Tworzy klienta anthropic (lazy import)."""
    try:
        import anthropic
    except ImportError as e:
        raise ImportError("anthropic not installed. Run: pip install anthropic") from e

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill in the key."
        )
    return anthropic.Anthropic(api_key=api_key)


def claude_text(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 1024,
    system: str | None = None,
    retries: int = MAX_RETRIES,
) -> str:
    """
    Wysyła prompt do Claude i zwraca tekst odpowiedzi.

    Args:
        prompt:     Treść promptu (user message)
        model:      Model Claude (domyślnie claude-sonnet-4-6)
        max_tokens: Maksymalna liczba tokenów odpowiedzi
        system:     Opcjonalny system prompt
        retries:    Liczba prób przy błędach API

    Returns:
        Tekst odpowiedzi jako str

    Raises:
        EnvironmentError: Brak ANTHROPIC_API_KEY
        RuntimeError: Wszystkie próby nieudane
    """
    import anthropic

    client   = _client()
    messages = [{"role": "user", "content": prompt}]
    kwargs: dict = {"model": model, "max_tokens": max_tokens, "messages": messages}
    if system:
        kwargs["system"] = system

    last_exc: Exception | None = None
    backoff = RETRY_BACKOFF

    for attempt in range(1, retries + 1):
        try:
            response = client.messages.create(**kwargs)
            text = response.content[0].text

            # Loguj użycie tokenów
            usage = response.usage
            log.debug(
                "Claude response: model=%s in=%d out=%d attempt=%d",
                model, usage.input_tokens, usage.output_tokens, attempt,
            )
            return text

        except anthropic.RateLimitError as exc:
            log.warning("Rate limit hit (attempt %d/%d), retrying in %.1fs", attempt, retries, backoff)
            last_exc = exc
            time.sleep(backoff)
            backoff *= 2

        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500:
                log.warning("Anthropic server error %d (attempt %d/%d)", exc.status_code, attempt, retries)
                last_exc = exc
                time.sleep(backoff)
                backoff *= 2
            else:
                # 4xx — nie ma sensu ponawiać
                raise

        except anthropic.APIConnectionError as exc:
            log.warning("Connection error (attempt %d/%d): %s", attempt, retries, exc)
            last_exc = exc
            time.sleep(backoff)
            backoff *= 2

    raise RuntimeError(f"Claude API failed after {retries} attempts: {last_exc}") from last_exc


def claude_json(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 2048,
    system: str | None = None,
    retries: int = MAX_RETRIES,
) -> dict:
    """
    Wysyła prompt do Claude i parsuje odpowiedź jako JSON.

    Obsługuje odpowiedzi w markdown fences (```json ... ```).
    Przy błędzie parsowania JSON ponawia prompt z informacją o błędzie.

    Args:
        prompt:     Treść promptu (musi prosić o JSON)
        model:      Model Claude
        max_tokens: Maksymalna liczba tokenów
        system:     Opcjonalny system prompt
        retries:    Liczba prób całkowitych (API + JSON parse)

    Returns:
        dict sparsowany z odpowiedzi JSON

    Raises:
        ValueError: Nie udało się sparsować JSON po wszystkich próbach
    """
    json_system = (
        (system + "\n\n" if system else "")
        + "Always respond with valid JSON only. No markdown fences, no explanations outside JSON."
    )

    last_raw = ""
    for attempt in range(1, retries + 1):
        try:
            raw = claude_text(
                prompt,
                model=model,
                max_tokens=max_tokens,
                system=json_system,
                retries=1,  # inner retry handled here
            )
            last_raw = raw
            return _parse_json(raw)

        except (ValueError, json.JSONDecodeError) as exc:
            log.warning("JSON parse error (attempt %d/%d): %s", attempt, retries, exc)
            if attempt < retries:
                # Dodaj error do promptu i spróbuj ponownie
                prompt = (
                    f"{prompt}\n\n"
                    f"PREVIOUS RESPONSE WAS INVALID JSON. Error: {exc}\n"
                    f"Previous response: {last_raw[:200]}\n"
                    f"Please return ONLY valid JSON, no other text."
                )

    raise ValueError(
        f"Failed to parse Claude response as JSON after {retries} attempts. "
        f"Last response: {last_raw[:300]}"
    )


def _parse_json(raw: str) -> dict:
    """Parsuje JSON z opcjonalnymi markdown fences."""
    cleaned = raw.strip()
    # Usuń ```json ... ``` lub ``` ... ```
    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\n?```\s*$", "", cleaned.strip(), flags=re.MULTILINE)
    return json.loads(cleaned.strip())
