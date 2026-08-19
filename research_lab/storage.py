from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable


class JsonlStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: dict) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        records: list[dict] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    records.append({"status": "PARSE_ERROR", "raw": line[:300]})
        return records

    def replace_all(self, records: Iterable[dict]) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        tmp.replace(self.path)

