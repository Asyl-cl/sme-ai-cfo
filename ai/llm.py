import os, base64, hashlib, json, logging
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)
MODEL = os.getenv("LLM_MODEL")
PROVIDER = os.getenv("LLM_PROVIDER", "openai").lower()   # openai (совместимый API, по умолчанию Gemini) | gemini | anthropic
BASE_URL = os.getenv("LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
FALLBACK = "Не удалось получить пояснение от ИИ. Расчёты выше актуальны, попробуйте повторить запрос."

_client = None
CACHE_FILE = os.getenv("LLM_CACHE", "data/llm_cache.json")


def _cache_load() -> dict:
    try:
        return json.load(open(CACHE_FILE, encoding="utf-8"))
    except Exception:
        return {}


def _cache_put(key: str, value: str):
    try:
        c = _cache_load(); c[key] = value
        os.makedirs(os.path.dirname(CACHE_FILE) or ".", exist_ok=True)
        json.dump(c, open(CACHE_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        log.exception("cache write failed")


def _get_client():
    """Клиент создаётся лениво: бот стартует даже без ключа, расчёты работают."""
    global _client
    if _client is None:
        if PROVIDER == "openai":
            from openai import OpenAI
            _client = OpenAI(api_key=os.getenv("LLM_API_KEY"), base_url=BASE_URL)
        elif PROVIDER == "gemini":
            from google import genai
            _client = genai.Client(api_key=os.getenv("LLM_API_KEY"))
        else:
            from anthropic import Anthropic
            _client = Anthropic(api_key=os.getenv("LLM_API_KEY"))
    return _client


def _anthropic_text(r) -> str:
    """Берёт только текстовые блоки: перед ними может идти ThinkingBlock без .text."""
    text = "".join(getattr(b, "text", "") for b in r.content if getattr(b, "type", "") == "text").strip()
    if not text:
        raise ValueError("Пустой ответ модели (нет текстового блока)")
    return text


def _generate(system: str, user: str, max_tokens: int, image: tuple[bytes, str] | None = None) -> str:
    """Единая точка вызова модели для всех провайдеров."""
    if PROVIDER == "openai":
        content = user
        if image:
            b64 = base64.b64encode(image[0]).decode()
            content = [{"type": "image_url", "image_url": {"url": f"data:{image[1]};base64,{b64}"}},
                       {"type": "text", "text": user}]
        r = _get_client().chat.completions.create(
            model=MODEL, max_tokens=max_tokens,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": content}])
        return r.choices[0].message.content or ""
    if PROVIDER == "gemini":
        from google.genai import types # type: ignore
        parts = []
        if image:
            parts.append(types.Part.from_bytes(data=image[0], mime_type=image[1]))
        parts.append(user)
        r = _get_client().models.generate_content(
            model=MODEL, contents=parts,
            config=types.GenerateContentConfig(system_instruction=system, max_output_tokens=max_tokens))
        return r.text or ""
    content = user
    if image:
        content = [{"type": "image", "source": {"type": "base64", "media_type": image[1],
                                                "data": base64.b64encode(image[0]).decode()}},
                   {"type": "text", "text": user}]
    # запас на «ойлану»: токены размышления входят в max_tokens, иначе текст может обрезаться
    r = _get_client().messages.create(model=MODEL, max_tokens=max_tokens + 3000, system=system,
                                      messages=[{"role": "user", "content": content}])
    return _anthropic_text(r)


def ask(system: str, user: str, max_tokens=900, fallback: str = FALLBACK) -> str:
    """Текстовый запрос. Любой сбой возвращает fallback, бот не падает."""
    key = hashlib.sha1((system + "\x00" + user).encode()).hexdigest()
    try:
        text = _generate(system, user, max_tokens)
        _cache_put(key, text)          # успешный ответ запоминаем: запасной вариант для демо
        return text
    except Exception:
        log.exception("LLM ask failed")
        return _cache_load().get(key, fallback)


def ask_image(system: str, user: str, image_bytes: bytes, media_type="image/jpeg") -> str | None:
    """Запрос с картинкой. При сбое возвращает None (вызывающий код решает, что ответить)."""
    try:
        return _generate(system, user, 1200, (image_bytes, media_type))
    except Exception:
        log.exception("LLM ask_image failed")
        return None
