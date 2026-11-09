"""Сверка реплик с учебным порядком осмотра и проверка заполнения формы."""
from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
import re

from .model import AppError
from .protocol import BY_KEY, FIELDS, is_question, normalize_value


QUESTIONNAIRE = Path(__file__).resolve().parents[1] / "configs" / "protocol-questionnaire.json"
UNCLEAR_ANSWER = re.compile(r"^(?:да|нет|не знаю|не помню|не уверен[а]?)\W*$", re.IGNORECASE)


@dataclass(frozen=True)
class QuestionCheck:
    number: int
    field_key: str
    prompt: str
    asked: str
    answer: str
    status: str
    order_mismatch: bool
    follow_up: str


@dataclass(frozen=True)
class FollowUp:
    field_key: str
    recipient: str
    text: str


@dataclass(frozen=True)
class ProtocolReview:
    questions: tuple[QuestionCheck, ...]
    question_source: str
    follow_ups: tuple[FollowUp, ...]
    filled: int
    empty: int

    @property
    def total(self):
        return self.filled + self.empty

    @property
    def filled_pct(self):
        return 100 * self.filled / self.total

    @property
    def empty_pct(self):
        return 100 * self.empty / self.total

    @property
    def question_count(self):
        return len(self.questions)

    @property
    def questions_found(self):
        return sum(bool(question.asked) for question in self.questions)


@dataclass(frozen=True)
class QuestionRule:
    field_key: str
    prompt: str
    patterns: tuple[re.Pattern, ...]
    when_value_contains: re.Pattern | None
    incomplete_answer: re.Pattern | None
    direct_answer: re.Pattern | None
    raw_question: re.Pattern | None
    include_in_review: bool


def _read_questionnaire(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data["source"], str) or not data["source"].strip() or not data["questions"]:
            raise ValueError("Нет описания или вопросов")
        rules = []
        for row in data["questions"]:
            key, prompt = row["field"], row["prompt"]
            if key not in BY_KEY or not isinstance(prompt, str) or not prompt.strip():
                raise ValueError("Неверное поле или текст вопроса")
            if not isinstance(row["patterns"], list) or not row["patterns"] or not all(
                    isinstance(pattern, str) and pattern.strip() for pattern in row["patterns"]):
                raise ValueError("Не заданы шаблоны сопоставления")
            when = row.get("when_value_contains")
            incomplete = row.get("incomplete_answer")
            direct = row.get("direct_answer")
            raw = row.get("raw_question")
            include_in_review = row.get("include_in_review", True)
            if type(include_in_review) is not bool:
                raise ValueError("Неверный признак участия в проверке")
            rules.append(QuestionRule(
                key, prompt, tuple(re.compile(pattern) for pattern in row["patterns"]),
                re.compile(when) if when is not None else None,
                re.compile(incomplete) if incomplete is not None else None,
                re.compile(direct) if direct is not None else None,
                re.compile(raw, re.IGNORECASE) if raw is not None else None,
                include_in_review,
            ))
        return data["source"], rules
    except (OSError, ValueError, KeyError, TypeError, re.error) as exc:
        raise AppError("Не удалось прочитать список вопросов осмотра. Проверьте настройки.") from exc


def _normalize(text):
    return text.lower().replace("ё", "е")


def split_unpunctuated_questions(text, questionnaire=QUESTIONNAIRE):
    """Выделяет дословные границы известных вопросительных конструкций."""
    _, rules = _read_questionnaire(questionnaire)
    spans = sorted(
        (match.start(), match.end()) for rule in rules if rule.raw_question is not None
        for match in rule.raw_question.finditer(text)
    )
    lines = []
    offset = 0
    for start, end in spans:
        if start < offset:
            continue
        if prefix := text[offset:start].strip():
            lines.append(prefix)
        lines.append(text[start:end])
        offset = end
    if tail := text[offset:].strip():
        lines.append(tail)
    return lines


def _matched_evidence(source, item, patterns):
    candidates = []
    for row in item["evidence"]:
        quote = row["question"].strip()
        normalized = _normalize(quote)
        if quote and any(pattern.search(normalized) for pattern in patterns):
            if is_question(quote) or re.search(r"\b(?:ли|есть)\b", normalized):
                position = source.find(row["question"])
                if position >= 0:
                    candidates.append((position, row))
    return sorted(candidates, key=lambda candidate: candidate[0])


def _usable_answer(field, answer, rule):
    return bool(answer and not is_question(answer) and not UNCLEAR_ANSWER.match(answer)
                and (rule.incomplete_answer is None or not rule.incomplete_answer.search(_normalize(answer)))
                and normalize_value(field, answer))


def review_protocol(draft, questionnaire=QUESTIONNAIRE):
    """Считает заполненные поля отдельно от вопросов, прозвучавших в записи."""
    title, configured_rules = _read_questionnaire(questionnaire)
    rules = [rule for rule in configured_rules if rule.include_in_review]
    fields = draft["fields"]
    question_checks = []
    follow_ups = []
    last_position = -1
    rules_per_field = Counter(rule.field_key for rule in rules)
    for rule in rules:
        key, prompt = rule.field_key, rule.prompt
        item = fields[key]
        field = BY_KEY[key]
        matched = _matched_evidence(draft["source_text"], item, rule.patterns)
        if not matched and rule.when_value_contains is not None and not rule.when_value_contains.search(
                _normalize(item["value"])):
            continue
        asked = answer = follow_up = ""
        out_of_order = False
        if matched:
            position = matched[0][0]
            out_of_order = position < last_position
            last_position = max(last_position, position)
            _, pair = next((candidate for candidate in matched
                            if _usable_answer(field, candidate[1]["answer"], rule)), matched[0])
            asked, answer = pair["question"], pair["answer"]
            if _usable_answer(field, answer, rule):
                status = "Ответ получен"
            elif answer:
                status = "Нужно уточнить"
                follow_up = "Уточните ответ. " + prompt
            else:
                status = "Вопрос без ответа"
                follow_up = prompt
        else:
            direct_answer = next((row["answer"] for row in item["evidence"]
                                  if _usable_answer(field, row["answer"], rule)
                                  and ((not row["question"] and rules_per_field[key] == 1)
                                       or (rule.direct_answer is not None
                                           and rule.direct_answer.search(_normalize(row["answer"]))))), "")
            if item["value"] and direct_answer:
                status = "Сведения есть без вопроса"
                answer = direct_answer
            else:
                status = "Вопрос не найден"
                follow_up = prompt
        if item["status"] == "edited" and item["value"]:
            follow_up = ""
        if follow_up:
            follow_ups.append(FollowUp(key, "Пациенту", follow_up))
        question_checks.append(QuestionCheck(
            len(question_checks) + 1, key, prompt, asked, answer, status, out_of_order, follow_up))

    for field in FIELDS:
        item = fields[field.key]
        if field.key not in rules_per_field and not item["value"]:
            follow_ups.append(FollowUp(field.key, "Врачу", f"Проверьте и заполните поле «{field.label}»."))

    filled = sum(bool(fields[field.key]["value"].strip()) for field in FIELDS)
    return ProtocolReview(tuple(question_checks), title, tuple(follow_ups), filled, len(FIELDS) - filled)
