"""Сохранение пользовательского текста; атомарная замена файла после записи."""
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import uuid

from .model import AppError, Document, Segment


def _atomic_text(path, text):
    target = Path(path)
    temporary = target.with_name(target.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except OSError as exc:
        raise AppError("Не удалось сохранить файл. Текущий текст остался в приложении.") from exc
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def save_json(path, payload):
    _atomic_text(path, json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False))


def save_document(document, path):
    data = asdict(document)
    version = 3 if document.protocol is not None else 2
    if version == 2:
        data.pop("protocol")
    save_json(path, {"format": "medical-audio-mvp", "version": version, "document": data})


def load_document(path):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload.get("format") != "medical-audio-mvp" or payload.get("version") not in (2, 3):
            raise ValueError("Неизвестная версия сеанса")
        item = payload["document"]
        if not all(isinstance(item[key], str) for key in ("transcript", "text", "source", "model_id")):
            raise ValueError("Неверный текст")
        if not isinstance(item["segments"], list) or not isinstance(item["metrics"], dict):
            raise ValueError("Неверные данные распознавания")
        segments = []
        for row in item["segments"]:
            segment = Segment(**row)
            if (not isinstance(segment.text, str)
                    or type(segment.start) not in (float, int) or type(segment.end) not in (float, int)
                    or not math.isfinite(segment.start) or not math.isfinite(segment.end)
                    or segment.start < 0 or segment.end < segment.start):
                raise ValueError("Неверные временные границы")
            segments.append(segment)
        protocol = None
        if payload["version"] == 3:
            from .protocol import check_draft, upgrade_legacy_draft
            protocol = upgrade_legacy_draft(item["protocol"])
            check_draft(protocol)
        return Document(transcript=item["transcript"], text=item["text"], source=item["source"],
                        model_id=item["model_id"], segments=segments, metrics=item["metrics"], protocol=protocol)
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise AppError("Не удалось открыть сеанс: файл повреждён или имеет неизвестный формат.") from exc


def export_text(document, path):
    _atomic_text(path, document.text if document.text.endswith("\n") else document.text + "\n")


def export_protocol(document, path):
    from .protocol import FIELDS, FORM_TITLE, STATUS_LABELS
    draft = document.protocol
    if draft is None or draft["source_text"] != document.text:
        raise AppError("Сформируйте протокол для текущей расшифровки перед экспортом.")
    lines = [FORM_TITLE, "Черновик для проверки специалистом", ""]
    for field in FIELDS:
        item = draft["fields"][field.key]
        if item["value"]:
            value = item["value"] + (f" {field.unit}" if field.unit else "")
        else:
            value = "[" + STATUS_LABELS[item["status"]] + "]"
        lines.append(f"{field.label}: {value}")
    _atomic_text(path, "\n".join(lines) + "\n")
