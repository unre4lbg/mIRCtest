"""UI views module: creates the AuthApp instance (keeps UI code centralized).

This module currently wraps the existing `client_gui.AuthApp` so the controller
can operate on a stable view object during migration. Later we can move UI
components here and remove `client_gui.py`.
"""
from client_gui import AuthApp


def create_app():
    """Instantiate and return the main application view (AuthApp)."""
    app = AuthApp()
    return app
