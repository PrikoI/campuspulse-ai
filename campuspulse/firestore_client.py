"""Process-local Firebase SDK lifecycle and bounded Firestore operations.

No initialization, credential reads or network calls occur at import time.
"""
from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from .lms_store import LmsError

_LOCK = threading.Lock()
_CLIENTS = {}
ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class FirebaseConfig:
    project: str
    database: str
    credentials: str
    emulator: str = ""
    test_namespace: str = ""

    @classmethod
    def from_environment(cls):
        project = os.getenv("CAMPUSPULSE_FIREBASE_PROJECT", "campuspulse-ai-1021")
        database = os.getenv("CAMPUSPULSE_FIRESTORE_DATABASE", "(default)")
        credential = os.getenv("CAMPUSPULSE_FIREBASE_CREDENTIALS", "")
        # Cloud runtimes must use their service identity, never a bundled key.
        cloud = any(os.getenv(key) for key in ("K_SERVICE", "GAE_ENV", "AIP_MODEL_DIR"))
        if not credential and not cloud and not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            local_key = ROOT / "firebase-key.json"
            credential = str(local_key) if local_key.is_file() else "adc"
        credential = credential or "adc"
        if credential != "adc":
            credential = str(Path(credential).resolve())
        namespace = os.getenv("CAMPUSPULSE_FIRESTORE_TEST_NAMESPACE", "")
        if namespace and not re.fullmatch(r"backend-[0-9a-f]{32}", namespace):
            raise LmsError("Некорректная тестовая область Firestore.", 503)
        return cls(project, database, credential, os.getenv("FIRESTORE_EMULATOR_HOST", ""), namespace)

    def environment(self):
        result = {"CAMPUSPULSE_FIREBASE_PROJECT": self.project,
                  "CAMPUSPULSE_FIRESTORE_DATABASE": self.database,
                  "CAMPUSPULSE_FIREBASE_CREDENTIALS": self.credentials}
        if self.test_namespace:
            result["CAMPUSPULSE_FIRESTORE_TEST_NAMESPACE"] = self.test_namespace
        for key in ("GOOGLE_APPLICATION_CREDENTIALS", "FIRESTORE_EMULATOR_HOST"):
            if os.getenv(key):
                value = os.environ[key]
                result[key] = str(Path(value).resolve()) if key == "GOOGLE_APPLICATION_CREDENTIALS" else value
        return result


def firebase_client(config: FirebaseConfig):
    """Reuse one named app/client per process; do not touch another app's setup."""
    import firebase_admin
    from firebase_admin import credentials, firestore

    with _LOCK:
        if config in _CLIENTS:
            return _CLIENTS[config]
        try:
            app = firebase_admin.get_app("campuspulse")
        except ValueError:
            credential = (credentials.ApplicationDefault() if config.credentials == "adc"
                          else credentials.Certificate(config.credentials))
            app = firebase_admin.initialize_app(credential, {"projectId": config.project}, name="campuspulse")
        if app.project_id != config.project:
            raise LmsError("Firebase уже инициализирован для другого проекта.", 503)
        client = firestore.client(app=app, database_id=config.database)
        _CLIENTS[config] = client
        return client


class FirestoreStorage:
    """Small injectable SDK boundary. No business permissions belong here."""
    timeout = 10

    def __init__(self, client, *, prefix=""):
        self.client = client
        if prefix and not re.fullmatch(r"system_tests/backend-[0-9a-f]{32}", prefix):
            raise LmsError("Разрешена только изолированная область system_tests.", 503)
        self.prefix = prefix

    def _path(self, path):
        self.validate_path(path)
        return self.prefix + "/" + path if self.prefix else path

    def ref(self, path):
        return self.client.document(self._path(path))

    @staticmethod
    def validate_path(path):
        if any(not part or part in {".", ".."} or part.startswith("__") and part.endswith("__")
               for part in path.split("/")):
            raise LmsError("Недопустимый идентификатор Firestore.")

    def get(self, path, transaction=None, *, fields=None):
        options = {"field_paths": fields} if fields is not None else {}
        snapshot = self.ref(path).get(transaction=transaction, retry=None, timeout=self.timeout, **options)
        return snapshot.to_dict() if snapshot.exists else None

    def get_many(self, paths, transaction=None, fields=None):
        paths = list(dict.fromkeys(paths))
        if not paths:
            return {}
        snapshots = self.client.get_all([self.ref(path) for path in paths], field_paths=fields,
                                        transaction=transaction, retry=None, timeout=self.timeout)
        result = {path: None for path in paths}
        for snapshot in snapshots:
            path = snapshot.reference.path.removeprefix(self.prefix + "/") if self.prefix else snapshot.reference.path
            if path not in result:
                raise LmsError("Firestore вернул незапрошенный документ.", 502)
            if snapshot.exists:
                result[path] = snapshot.to_dict()
        return result

    def scan(self, path, filters=(), transaction=None, limit=101, *, fields=None, after=None):
        from google.cloud.firestore_v1.base_query import FieldFilter
        query = self.client.collection(self._path(path))
        for field, op, value in filters:
            query = query.where(filter=FieldFilter(field, op, value))
        if fields is not None:
            query = query.select(fields)
        if after is not None:
            query = query.order_by("__name__").start_after({"__name__": self.ref(path + "/" + after)})
        return [(snapshot.id, snapshot.to_dict()) for snapshot in query.limit(limit).stream(
            transaction=transaction, retry=None, timeout=self.timeout)]

    def transaction(self, operation, *, read_only=False):
        from firebase_admin import firestore
        transaction = self.client.transaction(max_attempts=3, read_only=read_only)
        return firestore.transactional(operation)(transaction)

    def put(self, transaction, path, data):
        transaction.set(self.ref(path), data)

    def delete(self, transaction, path):
        transaction.delete(self.ref(path))
