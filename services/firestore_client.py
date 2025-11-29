import os
import traceback
from typing import Optional

import config

try:
    from firebase_admin import credentials, firestore, initialize_app
except Exception:
    credentials = None
    initialize_app = None
    firestore = None

_firestore_db = None


def init_firestore(key_path: Optional[str] = None):
    """Initialize firebase-admin Firestore client using service account JSON.

    Returns the firestore client or None on failure.
    """
    global _firestore_db
    if _firestore_db is not None:
        return _firestore_db

    key = key_path or config.KEY_JSON_PATH
    if firestore is None:
        print("[WARN] firebase_admin not available in environment; Firestore disabled.")
        return None

    try:
        cred = credentials.Certificate(key)
        initialize_app(cred)
        _firestore_db = firestore.client()
        return _firestore_db
    except Exception as e:
        print(f"[ERROR] Firestore init failed: {e}")
        traceback.print_exc()
        _firestore_db = None
        return None


def get_db():
    return _firestore_db


def add_message(room_id: str, username: str, text: str, timestamp=None):
    db = get_db()
    if db is None:
        raise RuntimeError("Firestore is not initialized")
    data = {"room_id": room_id, "username": username, "text": text}
    if timestamp is not None:
        data["timestamp"] = timestamp
    else:
        # Server timestamp is set by caller using firestore.SERVER_TIMESTAMP when available
        try:
            data["timestamp"] = firestore.SERVER_TIMESTAMP
        except Exception:
            pass
    return db.collection("messages").add(data)


def get_history_paginated(
    room_id: str,
    limit: int = 50,
    start_after: Optional[object] = None,
    direction: str = "asc",
):
    """Return (docs, last_doc) for a paginated history query.

    - `start_after` should be a DocumentSnapshot or None.
    - `direction` can be 'asc' or 'desc'.
    - Returns a list of documents and the last DocumentSnapshot for paging.
    """
    db = get_db()
    if db is None:
        raise RuntimeError("Firestore is not initialized")

    try:
        dir_enum = (
            firestore.Query.ASCENDING
            if direction == "asc"
            else firestore.Query.DESCENDING
        )
        q = (
            db.collection("messages")
            .where("room_id", "==", room_id)
            .order_by("timestamp", direction=dir_enum)
            .limit(limit)
        )
        if start_after is not None:
            q = q.start_after(start_after)
        docs = list(q.get())
        last = docs[-1] if docs else None
        return docs, last
    except Exception as e:
        print(f"[ERROR] get_history_paginated failed: {e}")
        return [], None


def stream_room(room_id: str, callback):
    """Attach an on_snapshot listener for a specific room_id and return the watcher object.

    `callback` should accept (col_snapshot, changes, read_time) like on_snapshot.
    """
    db = get_db()
    if db is None:
        raise RuntimeError("Firestore is not initialized")

    try:
        query = db.collection("messages").where("room_id", "==", room_id)
        watcher = query.on_snapshot(callback)
        return watcher
    except Exception as e:
        print(f"[ERROR] stream_room failed: {e}")
        return None
