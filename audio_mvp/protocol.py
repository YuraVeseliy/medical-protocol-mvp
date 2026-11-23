"""Формальная схема формы, связь с репликами и проверка черновика."""
from dataclasses import dataclass
from decimal import Decimal
import re

from .model import AppError


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    kind: str = "text"
    unit: str = ""


# Поля печатной формы и раздела «Объективный статус» экранного образца.
FORM_ID = "preoperative-anaesthesiology-v2"
FORM_TITLE = "Предоперационный осмотр врачом-анестезиологом-реаниматологом"
FIELDS = (
    Field("patient_name", "Пациент"),
    Field("chart_number", "№ карты"),
    Field("birth_date", "Дата рождения"),
    Field("sex", "Пол"),
    Field("exam_date", "Дата осмотра"),
    Field("complaints", "Жалобы"),
    Field("illness", "Анамнез болезни"),
    Field("life", "Анамнез жизни"),
    Field("medicines", "Принимаемые препараты"),
    Field("implants", "Имплантированные устройства"),
    Field("allergies", "Аллергологический анамнез"),
    Field("objective", "Объективный статус"),
    Field("weight", "Масса тела", "number", "кг"),
    Field("height", "Рост", "number", "см"),
    Field("patient_condition", "Состояние пациента"),
    Field("skin", "Кожные покровы"),
    Field("edema_cyanosis", "Отёки и цианоз"),
    Field("breathing", "Дыхание"),
    Field("respiratory_rate", "ЧДД", "number", "в мин"),
    Field("oxygen_saturation", "SpO₂", "number", "%"),
    Field("heart_sounds", "Тоны сердца"),
    Field("pressure", "Артериальное давление", "pressure", "мм рт. ст."),
    Field("pulse", "ЧСС", "number", "уд/мин"),
    Field("tongue", "Язык"),
    Field("abdomen", "Живот"),
    Field("past_diseases", "Перенесённые заболевания"),
    Field("tests", "Результаты исследований"),
    Field("mallampati", "Класс по Mallampati", "class"),
    Field("conclusion", "Заключение"),
    Field("assessment_scales", "Значения оценочных шкал"),
    Field("procedure", "Область вмешательства"),
    Field("anaesthesia", "Предполагаемый метод анестезии"),
    Field("manipulations", "Предполагаемые манипуляции"),
)
BY_KEY = {field.key: field for field in FIELDS}
LEGACY_FORM_ID = "preoperative-anaesthesiology-v1"
LEGACY_KEYS = frozenset((
    "complaints", "illness", "life", "medicines", "implants", "allergies", "objective", "weight",
    "height", "pulse", "pressure", "tests", "mallampati", "conclusion", "procedure", "anaesthesia",
    "manipulations",
))
STATUS_LABELS = {
    "missing": "Нет сведений",
    "unanswered": "Вопрос без ответа",
    "review": "Нужно уточнить",
    "filled": "Черновик заполнен",
    "edited": "Внесено вручную",
}
QUESTION_START = re.compile(
    r"^(?:а\s+)?(?:что|когда|как(?:ой|ая|ие|овы)?|сколько|насколько|где|какие|чем|"
    r"были ли|была ли|было ли|есть ли|принимаете ли|на какие|на что|давно ли|"
    r"назовите|укажите)\b",
    re.IGNORECASE,
)
NUMBER_WORDS = dict(zip(
    "ноль один два три четыре пять шесть семь восемь девять десять одиннадцать двенадцать "
    "тринадцать четырнадцать пятнадцать шестнадцать семнадцать восемнадцать девятнадцать "
    "двадцать тридцать сорок пятьдесят шестьдесят семьдесят восемьдесят девяносто "
    "сто двести триста четыреста пятьсот шестьсот семьсот восемьсот девятьсот".split(),
    (*range(20), *range(20, 100, 10), *range(100, 1000, 100)),
))


def is_question(text):
    return text.rstrip().endswith("?") or bool(QUESTION_START.match(text.lstrip()))


def _numbers(value):
    words = re.findall(r"\d+(?:[,.]\d+)?|[а-яё]+|[^\s]", value.lower())
    numbers, group = [], []
    for word in words + ["!"]:
        if word in NUMBER_WORDS:
            group.append(NUMBER_WORDS[word])
            continue
        if group:
            if any(a <= b or (10 <= a <= 19 and b < 10) for a, b in zip(group, group[1:])):
                return []
            numbers.append(str(sum(group)))
            group.clear()
        if re.fullmatch(r"\d+(?:[,.]\d+)?", word):
            numbers.append(word.replace(",", "."))
    return numbers


def normalize_value(field, value):
    """Преобразует явно названные значения в формат поля."""
    value = value.strip()
    if field.kind == "text":
        return value
    if re.search(r"(?<![а-я])(?:нет|не|или|около|примерно)(?![а-я])|[~≈–—-]", value.lower()):
        return ""
    if field.kind == "class":
        match = re.search(r"(?<!\w)(IV|III|II|I)(?!\w)", value.upper())
        if match:
            return match[1] if not _numbers(value) else ""
        named = re.search(r"\b(первый|второй|третий|четв[её]ртый)\b", value.lower())
        if named:
            return dict(первый="I", второй="II", третий="III", четвертый="IV",
                        четвёртый="IV")[named[1]] if not _numbers(value) else ""
    if field.kind == "pressure":
        parts = re.split(r"\s*(?:/|\bна\b)\s*", value)
        numbers = [_numbers(part) for part in parts]
        if len(numbers) == 2 and all(len(part) == 1 and part[0].isdigit() for part in numbers):
            top, bottom = (int(part[0]) for part in numbers)
            if top > bottom > 0:
                return f"{top}/{bottom}"
        return ""
    numbers = _numbers(value)
    if len(numbers) != 1:
        return ""
    number = Decimal(numbers[0])
    if field.kind == "class":
        return {1: "I", 2: "II", 3: "III", 4: "IV"}.get(number, "")
    # Сохраняем числа в единицах формы. Альтернативные единицы требуют сверки.
    if (field.key == "height" and re.search(r"\b(?:м|метр\w*|мм|миллиметр\w*)\b", value.lower())
            or field.key == "weight" and re.search(r"\b(?:г|грамм\w*|фунт\w*)\b", value.lower())):
        return ""
    if number <= 0 or (field.key in {"pulse", "respiratory_rate"} and number != number.to_integral_value()):
        return ""
    if field.key == "oxygen_saturation" and number > 100:
        return ""
    return format(number.normalize(), "f").replace(".", ",")


def _source_quote(block, quote):
    """Восстанавливает исходное написание, допуская разницу в регистре и пробелах."""
    if not quote or not quote.strip():
        return ""
    pattern = r"(?<!\w)" + r"\s+".join(re.escape(word) for word in quote.split()) + r"(?!\w)"
    match = re.search(pattern, block, flags=re.IGNORECASE)
    return match[0] if match else ""


def make_draft(transcript, responses):
    fields = {field.key: {"value": "", "status": "missing", "evidence": []} for field in FIELDS}
    ignored, warnings, seen = [], [], set()
    for block, items in responses:
        for row in items:
            key, question, answer = row["field"], row["question"], row["answer"]
            original_q = _source_quote(block, question)
            original_a = _source_quote(block, answer)
            if (question.strip() and not original_q) or (answer.strip() and not original_a):
                if key in fields and fields[key]["status"] == "missing":
                    fields[key]["status"] = "review"
                warnings.append("Фрагмент модели отклонён: не найден в расшифровке.")
                continue
            if not (original_q or original_a) or (key, original_q, original_a) in seen:
                continue
            seen.add((key, original_q, original_a))
            evidence = {"question": original_q, "answer": original_a}
            if key == "off_topic":
                ignored.append(evidence)
            elif key in fields:
                fields[key]["evidence"].append(evidence)
    for field in FIELDS:
        item = fields[field.key]
        if not item["evidence"]:
            continue
        answers = [row["answer"] for row in item["evidence"] if row["answer"]]
        if not answers:
            item["status"] = "unanswered"
            continue
        values = [normalize_value(field, value) for value in answers]
        if field.kind == "text":
            short = {"да", "нет", "не знаю", "не помню", "не уверен", "не уверена"}
            if any(value.lower().strip(" .!?…") in short for value in values):
                item["status"] = "review"
                continue
            if field.key == "complaints":
                values = ["Жалобы отсутствуют." if re.fullmatch(
                    r"(?:жалоб нет|нет жалоб|ничего не беспокоит)[.!]?", value.lower())
                    else value for value in values]
            item["value"] = "\n".join(dict.fromkeys(values))
        elif "" in values or len(set(values)) > 1:
            item["status"] = "review"
            continue
        else:
            item["value"] = values[0]
        item["status"] = "filled"
    return {"form": FORM_ID, "source_text": transcript, "fields": fields,
            "off_topic": ignored, "warnings": list(dict.fromkeys(warnings))}


def check_draft(draft):
    """В открытом сеансе проверяем структуру черновика и привязку цитат."""
    def valid_evidence(rows):
        return isinstance(rows, list) and all(
            isinstance(row, dict) and set(row) == {"question", "answer"}
            and all(isinstance(text, str) and (not text or text in source) for text in row.values())
            for row in rows
        )

    if not isinstance(draft, dict) or draft.get("form") != FORM_ID:
        raise ValueError("Неизвестная форма")
    source = draft.get("source_text")
    fields = draft.get("fields")
    if not isinstance(source, str) or not isinstance(fields, dict) or set(fields) != set(BY_KEY):
        raise ValueError("Неизвестные поля формы")
    for key, item in fields.items():
        if (not isinstance(item, dict) or not isinstance(item.get("value"), str)
                or item.get("status") not in STATUS_LABELS or not valid_evidence(item.get("evidence"))
                or bool(item["value"].strip()) != (item["status"] in {"filled", "edited"})
                or (item["value"] and normalize_value(BY_KEY[key], item["value"]) != item["value"])):
            raise ValueError("Некорректные данные поля")
    if not valid_evidence(draft.get("off_topic")) or not isinstance(draft.get("warnings"), list) or not all(
            isinstance(warning, str) for warning in draft["warnings"]):
        raise ValueError("Некорректные сведения о разметке")


def upgrade_legacy_draft(draft):
    """Добавляет новые пустые поля к существующему сеансу старой формы."""
    if not isinstance(draft, dict) or draft.get("form") != LEGACY_FORM_ID:
        return draft
    fields = draft.get("fields")
    if not isinstance(fields, dict) or set(fields) != LEGACY_KEYS:
        raise ValueError("Неизвестные поля старой формы")
    return {
        **draft,
        "form": FORM_ID,
        "fields": {
            field.key: fields[field.key] if field.key in fields else {
                "value": "", "status": "missing", "evidence": [],
            }
            for field in FIELDS
        },
    }


def incomplete_required(draft):
    return [field.label for field in FIELDS if not draft["fields"][field.key]["value"]]


def set_field_value(draft, key, value):
    field = BY_KEY[key]
    normalized = normalize_value(field, value)
    if value.strip() and not normalized:
        raise AppError("Проверьте формат поля" + (f" ({field.unit})." if field.unit else "."))
    item = draft["fields"][key]
    item["value"] = normalized
    item["status"] = "edited" if normalized else "missing"
