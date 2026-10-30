"""Atomic local state, credential isolation and at-most-once write ledger."""

import json
import os
import time
from pathlib import Path


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.cookie_path = self.root / "cookie.txt"
        self.path = self.root / "journal.json"
        self.data = (
            json.loads(self.path.read_text())
            if self.path.exists()
            else {
                "operations": {},
                "observations": [],
                "decision_at": 0,
                "room": None,
            }
        )
        if not isinstance(self.data, dict) or not isinstance(
            self.data.get("operations"), dict
        ):
            raise ValueError("Invalid ledger; refusing to reset")
        # A restart never replays pending sends or claims interrupted audio completed.
        for row in self.data["operations"].values():
            if row["status"] == "pending":
                row["status"] = "unknown"
        self.save()

    @staticmethod
    def atomic(path, value):
        path = Path(path)
        tmp = path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        tmp.chmod(0o600)
        tmp.replace(path)

    def cookie(self):
        return self.cookie_path.read_text().strip() if self.cookie_path.exists() else ""

    def save_cookie(self, cookie):
        self.atomic(self.cookie_path, cookie)

    def save(self):
        # Retain bounded observations, but keep operation receipts for de-duplication.
        self.data["observations"] = self.data.get("observations", [])[-200:]
        self.atomic(self.path, json.dumps(self.data, ensure_ascii=False, indent=2))

    def reserve(self, key, kind, **metadata):
        if key in self.data["operations"]:
            return False
        self.data["operations"][key] = {
            "kind": kind,
            "at": time.time(),
            "status": "pending",
            **metadata,
        }
        self.save()
        return True

    def finish(self, key, status, **metadata):
        self.data["operations"][key].update(status=status, **metadata)
        self.save()

    def receipt(self, key):
        row = self.data["operations"].get(key)
        return (
            {"status": "duplicate", "previous_status": row["status"]} if row else None
        )
