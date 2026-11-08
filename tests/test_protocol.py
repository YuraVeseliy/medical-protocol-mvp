"""Проверки границы между разметкой, формой и сохранением сеанса."""
from pathlib import Path
import unittest
import uuid

from audio_mvp.model import AppError, Document
from audio_mvp.protocol import incomplete_required, make_draft, set_field_value
from audio_mvp.session import Session
from audio_mvp.storage import export_protocol


class ProtocolTests(unittest.TestCase):
    def test_filter_and_normalize_source_replies(self):
        source = ("Что беспокоит? Жалоб нет. Какие реакции на лекарства? "
                  "Масса семьдесят восемь килограммов. Где парковка?")
        draft = make_draft(source, [(source, [
            {"field": "complaints", "question": "Что беспокоит?", "answer": "Жалоб нет."},
            {"field": "allergies", "question": "Какие реакции на лекарства?", "answer": ""},
            {"field": "weight", "question": "", "answer": "Масса семьдесят восемь килограммов."},
            {"field": "pressure", "question": "", "answer": "Давление 120/80."},
            {"field": "off_topic", "question": "Где парковка?", "answer": ""},
        ])])
        self.assertEqual(draft["fields"]["complaints"]["value"], "Жалобы отсутствуют.")
        self.assertEqual(draft["fields"]["allergies"]["status"], "unanswered")
        self.assertEqual(draft["fields"]["weight"]["value"], "78")
        self.assertEqual(draft["fields"]["pressure"]["status"], "review")
        self.assertIn("Аллергологический анамнез", incomplete_required(draft))
        self.assertEqual(draft["off_topic"][0]["question"], "Где парковка?")

    def test_protocol_survives_session_restore_and_stale_export_is_blocked(self):
        session = Session(None)
        source = "Давление 120 на 80. Давление 140 на 90."
        session.document = Document(transcript=source, text=source)
        draft = make_draft(source, [(source, [
            {"field": "pressure", "question": "", "answer": "Давление 120 на 80."},
            {"field": "pressure", "question": "", "answer": "Давление 140 на 90."},
        ])])
        self.assertEqual(draft["fields"]["pressure"]["status"], "review")
        set_field_value(draft, "pressure", "140/90")
        session.set_protocol(draft)
        folder = Path("tmp") / ("protocol-test-" + uuid.uuid4().hex)
        folder.mkdir(parents=True)
        self.addCleanup(folder.rmdir)
        path, export = folder / "session.json", folder / "protocol.txt"
        self.addCleanup(path.unlink, missing_ok=True)
        self.addCleanup(export.unlink, missing_ok=True)
        session.save(path)
        restored = Session(None)
        doc = restored.open(path)
        self.assertEqual(doc.protocol, draft)
        export_protocol(doc, export)
        self.assertIn("140/90 мм рт. ст.", export.read_text(encoding="utf-8"))
        restored.edit("Давление уточнено.")
        with self.assertRaises(AppError):
            export_protocol(doc, export)
