"""Launcher wrapper for the UI (keeps UI code in one place).

This module now uses the new controller/view split. It instantiates the view
from `src.ui.views` and wires `src.ui.controllers.AppController` around it.
"""
from src.ui.controllers import AppController
from src.ui.views import create_app


def run_app():
    app = create_app()
    # wire controller
    try:
        controller = AppController(app)
        # store reference to avoid GC
        app._controller = controller
    except Exception as e:
        print(f"[WARN] Failed to attach controller: {e}")

    app.mainloop()


if __name__ == "__main__":
    run_app()
