import json
from datetime import datetime
from pathlib import Path

import firebase_admin
from firebase_admin import credentials, firestore

ROOT = Path(__file__).resolve().parents[1]
KEY = ROOT / "firebase-key.json"
BACKUP_DIR = ROOT / "backups"

if not firebase_admin._apps:
    firebase_admin.initialize_app(
        credentials.Certificate(str(KEY))
    )

db = firestore.client()

def export_collection(collection_ref):
    result = []

    for doc in collection_ref.stream():
        data = doc.to_dict() or {}

        # Сохраняем ID отдельно от полей документа
        entry = {
            "id": doc.id,
            "data": data,
        }

        subcollections = {}

        for subcol in doc.reference.collections():
            subcollections[subcol.id] = export_collection(subcol)

        if subcollections:
            entry["subcollections"] = subcollections

        result.append(entry)

    return result


def main():
    BACKUP_DIR.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output = BACKUP_DIR / f"firestore_{timestamp}.json"

    backup = {}

    for collection in db.collections():
        print(f"Экспорт: {collection.id}")
        backup[collection.id] = export_collection(collection)

    with output.open("w", encoding="utf-8") as f:
        json.dump(
            backup,
            f,
            ensure_ascii=False,
            indent=2,
            default=str,
        )

    print(f"\nБэкап сохранён: {output}")


if __name__ == "__main__":
    main()