"""Чтение и проверка загруженных файлов (CSV и Excel) по схемам из раздела 6.
Понимает русские, казахские и английские заголовки, находит строку заголовка не только в первой строке."""
import io
import re
import pandas as pd

SCHEMAS = {
    "sales": {"date", "sku", "name", "qty", "price", "cost"},
    "stock": {"sku", "qty"},
    "debts": {"client", "amount", "due_date"},
    "obligations": {"date", "name", "amount"},
    "bank": {"date", "description", "amount"},
}
TITLES = {"sales": "продажи", "stock": "остатки", "debts": "долги", "obligations": "плановые платежи",
          "bank": "банковская выписка"}
# порядок проверки: от самой специфичной схемы к самой общей
_ORDER = ["sales", "bank", "debts", "obligations", "stock"]

SYNONYMS = {
    "date": ["date", "дата", "дата продажи", "дата операции", "дата платежа", "күні", "дата документа"],
    "sku": ["sku", "код", "артикул", "код товара", "штрихкод", "штрих-код", "тауар коды"],
    "name": ["name", "название", "наименование", "товар", "номенклатура", "тауар", "атауы", "статья"],
    "category": ["category", "категория", "группа", "санат"],
    "qty": ["qty", "количество", "кол-во", "колво", "к-во", "остаток", "саны", "quantity"],
    "price": ["price", "цена", "цена продажи", "цена за единицу", "розничная цена", "баға"],
    "cost": ["cost", "себестоимость", "закупочная цена", "цена закупки", "себестоимость единицы", "өзіндік құны"],
    "client": ["client", "клиент", "контрагент", "покупатель", "должник", "тапсырыс беруші"],
    "amount": ["amount", "сумма", "долг", "сумма долга", "сумма платежа", "сумма операции", "сомасы", "итого"],
    "due_date": ["due_date", "срок оплаты", "срок", "дата оплаты", "срок погашения", "оплатить до", "төлеу мерзімі"],
    "issued_date": ["issued_date", "дата выдачи", "дата отгрузки"],
    "paid": ["paid", "оплачено", "оплата", "статус оплаты"],
    "description": ["description", "описание", "назначение платежа", "назначение", "комментарий", "детали"],
}
_LOOKUP = {v: k for k, vs in SYNONYMS.items() for v in vs}


class FileError(Exception):
    """Понятная пользователю ошибка чтения файла."""


def _clean_name(c) -> str:
    t = str(c).strip().lower().replace("ё", "е")
    t = re.sub(r"\(.*?\)", "", t)          # «Цена (тенге)» → «цена»
    t = t.split(",")[0]                     # «Сумма, ₸» → «сумма»
    return re.sub(r"\s+", " ", t).strip(" .:_")


def _canon(c) -> str:
    n = _clean_name(c)
    return _LOOKUP.get(n, n)


def _norm_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [_canon(c) for c in df.columns]
    return df.loc[:, ~pd.Index(df.columns).duplicated()]   # дубли после переименования: оставляем первый


def _with_header(raw: pd.DataFrame) -> pd.DataFrame:
    """Ищет в первых 20 строках строку заголовка (≥2 известных названий колонок)."""
    for i in range(min(20, len(raw))):
        hits = sum(1 for c in raw.iloc[i] if _clean_name(c) in _LOOKUP)
        if hits >= 2:
            df = raw.iloc[i + 1:].copy()
            df.columns = list(raw.iloc[i])
            return df.reset_index(drop=True)
    df = raw.iloc[1:].copy()
    df.columns = list(raw.iloc[0])
    return df.reset_index(drop=True)


def classify(df: pd.DataFrame) -> str | None:
    cols = set(df.columns)
    for kind in _ORDER:
        if SCHEMAS[kind] <= cols:
            return kind
    return None


def _to_num(s: pd.Series) -> pd.Series:
    if s.dtype == object or str(s.dtype).startswith("str"):
        s = (s.astype(str).str.replace("\u00a0", "", regex=False).str.replace(" ", "", regex=False)
             .str.replace(",", ".", regex=False).str.replace(r"[^\d.\-]", "", regex=True))
    return pd.to_numeric(s, errors="coerce")


def _to_date(s: pd.Series) -> pd.Series:
    """ISO (2026-02-01) читаем как есть, всё остальное (01.02.2026) — день первым."""
    txt = s.astype(str).str.strip()
    iso = txt.str.match(r"^\d{4}-\d{2}-\d{2}")
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    out[iso] = pd.to_datetime(txt[iso].str[:10], format="%Y-%m-%d", errors="coerce")
    out[~iso] = pd.to_datetime(txt[~iso], errors="coerce", dayfirst=True, format="mixed")
    return out.dt.strftime("%Y-%m-%d")


def _clean(kind: str, df: pd.DataFrame) -> pd.DataFrame:
    df = df.dropna(how="all").copy()
    num = {"sales": ["qty", "price", "cost"], "stock": ["qty"], "debts": ["amount"],
           "obligations": ["amount"], "bank": ["amount"]}[kind]
    for c in num:
        df[c] = _to_num(df[c])
    dates = {"sales": ["date"], "stock": [], "debts": ["due_date", "issued_date"],
             "obligations": ["date"], "bank": ["date"]}[kind]
    for c in dates:
        if c in df.columns:
            df[c] = _to_date(df[c])
    required = [c for c in SCHEMAS[kind] if c in df.columns]
    before = len(df)
    df = df.dropna(subset=required)
    if len(df) == 0:
        raise FileError(f"В файле «{TITLES[kind]}» не осталось корректных строк. "
                        f"Проверьте даты и числа в колонках: {', '.join(sorted(SCHEMAS[kind]))}.")
    if kind == "debts":
        if "paid" in df.columns:
            p = df["paid"].astype(str).str.strip().str.lower()
            df["paid"] = p.isin(["1", "1.0", "да", "yes", "true", "оплачено", "оплачен"]).astype(int)
        else:
            df["paid"] = 0
        if "issued_date" not in df.columns:
            df["issued_date"] = df["due_date"]
    if kind == "sales":
        df["sku"] = df["sku"].astype(str)
        if "category" not in df.columns:
            df["category"] = "Без категории"
    if kind == "stock":
        df["sku"] = df["sku"].astype(str)
    df.attrs["dropped"] = before - len(df)
    return df.reset_index(drop=True)


def _read_csv(data: bytes) -> pd.DataFrame:
    for enc in ("utf-8-sig", "cp1251"):
        for sep in (",", ";", "\t"):
            try:
                t = pd.read_csv(io.BytesIO(data), encoding=enc, sep=sep, header=None, dtype=str)
            except Exception:
                continue
            if t.shape[1] > 1:
                return t
    raise FileError("Не удалось прочитать CSV. Сохраните файл в UTF-8 с разделителем «запятая».")


def read_upload(data: bytes, filename: str) -> dict[str, pd.DataFrame]:
    """Возвращает {тип: DataFrame}. Excel может содержать несколько листов с разными таблицами."""
    name = (filename or "").lower()
    raws: list[pd.DataFrame] = []
    try:
        if name.endswith(".csv"):
            raws.append(_read_csv(data))
        elif name.endswith((".xlsx", ".xlsm")):
            raws.extend(pd.read_excel(io.BytesIO(data), sheet_name=None, header=None).values())
        elif name.endswith(".xls"):
            raise FileError("Старый формат .xls не поддерживается. Сохраните файл как .xlsx.")
        else:
            raise FileError("Поддерживаются файлы .csv и .xlsx.")
    except FileError:
        raise
    except Exception:
        raise FileError("Файл не открывается. Проверьте, что он не повреждён и не защищён паролем.")

    found: dict[str, pd.DataFrame] = {}
    for raw in raws:
        raw = raw.dropna(how="all")
        if len(raw) < 2:
            continue
        f = _norm_cols(_with_header(raw.reset_index(drop=True)))
        kind = classify(f)
        if kind and kind not in found:
            found[kind] = _clean(kind, f)
    if not found:
        need = "; ".join(f"{TITLES[k]}: {', '.join(sorted(v))}" for k, v in SCHEMAS.items())
        raise FileError("Не узнал таблицу по названиям колонок. Можно писать по-русски "
                        "(Дата, Товар, Количество, Цена, Себестоимость, Клиент, Сумма, Срок оплаты…). "
                        "Нужны колонки — " + need + ".")
    return found
