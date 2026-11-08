"""Подготовить локальный llama.cpp и веса для черновика протокола."""
from datetime import datetime, timezone
import json
from pathlib import Path

from setup_model_3b import ARTIFACTS as QWEN_ARTIFACTS
from setup_models import ARTIFACTS, LICENSES, download, extract_zip


def main():
    runtime = Path(__file__).resolve().parents[1] / ".runtime"
    llama = next(item for item in ARTIFACTS if item.name == "llama.cpp Windows CPU x64")
    llama_license = next(item for item in LICENSES if item.name == "llama.cpp LICENSE")
    records = [download(item, runtime) for item in (llama, llama_license, *QWEN_ARTIFACTS)]
    extract_zip(runtime / llama.destination, runtime / "llama")
    if not any((runtime / "llama").rglob("llama-server.exe")):
        raise RuntimeError("В распакованном комплекте отсутствует llama-server.exe.")
    manifest = {
        "prepared_at_utc": datetime.now(timezone.utc).isoformat(),
        "artifacts": records,
    }
    (runtime / "manifest-protocol.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
