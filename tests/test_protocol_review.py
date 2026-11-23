"""Проверки сверки вопросов и полноты для нового черновика и старых сеансов."""
import json
from pathlib import Path
import unittest
import uuid

from audio_mvp.model import AppError
from audio_mvp.protocol import FORM_ID, LEGACY_FORM_ID, LEGACY_KEYS, make_draft, set_field_value
from audio_mvp.protocol_inference import _lines
from audio_mvp.protocol_review import review_protocol
from audio_mvp.storage import load_document


class ProtocolReviewTests(unittest.TestCase):
    def test_reports_unanswered_and_incomplete_topics_independently_of_field_fill(self):
        source = (
            "Когда появилась боль? Вчера вечером. При глубоком вдохе она усиливается. "
            "Что беспокоит? Болит плечо. Насколько сильная боль? "
            "Есть ли аллергия? Да, аллергия есть."
        )
        draft = make_draft(source, [(source, [
            {"field": "illness", "question": "Когда появилась боль?",
             "answer": "Вчера вечером. При глубоком вдохе она усиливается."},
            {"field": "complaints", "question": "Что беспокоит?", "answer": "Болит плечо."},
            {"field": "complaints", "question": "Насколько сильная боль?", "answer": ""},
            {"field": "allergies", "question": "Есть ли аллергия?", "answer": "Да, аллергия есть."},
        ])])
        review = review_protocol(draft)
        self.assertEqual(review.questions_found, 4)
        self.assertEqual(review.filled, 3)
        self.assertEqual(review.empty + review.filled, review.total)
        self.assertAlmostEqual(review.filled_pct + review.empty_pct, 100)
        severity, onset, factors, allergy = (
            next(question for question in review.questions if question.prompt.startswith(prefix))
            for prefix in ("Если есть боль", "Когда появились", "Что усиливает", "Есть ли у вас аллергия")
        )
        self.assertEqual(severity.status, "Вопрос без ответа")
        self.assertTrue(onset.order_mismatch)
        self.assertEqual(factors.status, "Сведения есть без вопроса")
        self.assertFalse(factors.follow_up)
        self.assertEqual(allergy.status, "Нужно уточнить")
        self.assertTrue(allergy.follow_up)
        self.assertTrue(any(item.field_key == "pressure" and item.recipient == "Врачу"
                            for item in review.follow_ups))

        set_field_value(draft, "allergies", "Аллергии нет.")
        self.assertFalse(any(item.field_key == "allergies" for item in review_protocol(draft).follow_ups))

    def test_raw_asr_question_boundaries_keep_literal_fragments(self):
        raw = ("что вас сейчас беспокоит после операции болит справа под ребрами "
               "когда появилась боль вчера вечером при глубоком вдохе она усиливается "
               "насколько сильная боль по шкале от нуля до десяти примерно на шесть")
        lines = _lines(raw)
        self.assertEqual(lines[::2], [
            "что вас сейчас беспокоит",
            "когда появилась боль",
            "насколько сильная боль по шкале от нуля до десяти",
        ])
        self.assertEqual(" ".join(lines), raw)

    def test_legacy_session_keeps_values_and_rejects_unrecognized_shape(self):
        draft = make_draft("", [])
        set_field_value(draft, "complaints", "Учебный текст")
        draft["form"] = LEGACY_FORM_ID
        draft["fields"] = {key: item for key, item in draft["fields"].items() if key in LEGACY_KEYS}
        saved = {"format": "medical-audio-mvp", "version": 3, "document": {
            "transcript": "", "text": "", "source": "", "model_id": "",
            "segments": [], "metrics": {}, "protocol": draft,
        }}
        folder = Path("tmp") / ("legacy-protocol-test-" + uuid.uuid4().hex)
        folder.mkdir(parents=True)
        self.addCleanup(folder.rmdir)
        path = folder / "session.json"
        self.addCleanup(path.unlink, missing_ok=True)
        path.write_text(json.dumps(saved), encoding="utf-8")
        upgraded = load_document(path).protocol
        self.assertEqual(upgraded["form"], FORM_ID)
        self.assertEqual(upgraded["fields"]["complaints"]["value"], "Учебный текст")
        self.assertEqual(upgraded["fields"]["chart_number"]["value"], "")

        draft["fields"].pop("complaints")
        path.write_text(json.dumps(saved), encoding="utf-8")
        with self.assertRaises(AppError):
            load_document(path)
