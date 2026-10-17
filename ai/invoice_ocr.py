import json
from ai import llm, prompts


def _extract_json(raw: str) -> dict:
    """Достаёт JSON-объект из ответа, даже если модель добавила ```json или пояснение."""
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("JSON не найден")
    return json.loads(raw[start:end + 1])


def parse_invoice(image_bytes: bytes, media_type: str = "image/jpeg") -> dict:
    raw = llm.ask_image(prompts.INVOICE_SYSTEM, "Извлеки данные накладной.", image_bytes, media_type)
    if raw is None:
        return {"error": "Сервис распознавания сейчас недоступен. Попробуйте позже."}
    try:
        return _extract_json(raw)
    except Exception:
        return {"error": "Не удалось распознать накладную", "raw": raw[:300]}


def format_invoice(data: dict) -> str:
    """Человекочитаемый вид накладной для Telegram."""
    if "error" in data:
        return data["error"]
    lines = [f"Поставщик: {data.get('supplier') or 'не распознан'}",
             f"Дата: {data.get('date') or 'не распознана'}"]
    for it in data.get("items") or []:
        lines.append(f"• {it.get('name')}: {it.get('qty')} × {it.get('unit_price')} = {it.get('total')}")
    lines.append(f"Итого: {data.get('total')}")
    lines.append(f"Уверенность: {data.get('confidence')}. {data.get('notes') or ''}".strip())
    lines.append("Проверьте цифры вручную перед использованием.")
    return "\n".join(lines)
