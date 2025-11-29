import traceback
from typing import Optional

import pyrebase

import config


class AuthService:
    def __init__(self, firebase_config: Optional[dict] = None):
        self._config = firebase_config or config.FIREBASE_CONFIG
        self._firebase = None
        self._auth = None
        try:
            self._firebase = pyrebase.initialize_app(self._config)
            self._auth = self._firebase.auth()
        except Exception as e:
            print(f"[ERROR] AuthService initialization failed: {e}")
            traceback.print_exc()

    def get_auth(self):
        return self._auth

    def sign_in(self, email: str, password: str):
        if not self._auth:
            raise RuntimeError("Auth not initialized")
        return self._auth.sign_in_with_email_and_password(email, password)

    def create_user(self, email: str, password: str):
        if not self._auth:
            raise RuntimeError("Auth not initialized")
        return self._auth.create_user_with_email_and_password(email, password)
