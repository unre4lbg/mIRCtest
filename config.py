import os

from dotenv import load_dotenv

# Load .env for local development (if present)
load_dotenv()

# Default Firebase Web config (falls back to env variables if provided)
FIREBASE_CONFIG = {
    "apiKey": os.getenv("FB_API_KEY", "AIzaSyD8f0YbrER0sOkWeBYhlVbcFliYNeL9LpA"),
    "authDomain": os.getenv("FB_AUTH_DOMAIN", "pythonchatapp-1848a.firebaseapp.com"),
    "projectId": os.getenv("FB_PROJECT_ID", "pythonchatapp-1848a"),
    "storageBucket": os.getenv(
        "FB_STORAGE_BUCKET", "pythonchatapp-1848a.firebasestorage.app"
    ),
    "messagingSenderId": os.getenv("FB_MESSAGING_SENDER_ID", "526459498391"),
    "appId": os.getenv("FB_APP_ID", "1:526459498391:web:9bec96117ffc850f589ed2"),
    "databaseURL": os.getenv(
        "FB_DATABASE_URL", "https://pythonchatapp-1848a-default-rtdb.firebaseio.com/"
    ),
}

# Path to service account key (for firebase-admin). Keep this out of version control.
KEY_JSON_PATH = os.getenv(
    "GOOGLE_APPLICATION_CREDENTIALS",
    os.path.join(os.path.dirname(__file__), "key.json"),
)
# --- COLORS ---
COLOR_PRIMARY = "#3498db"
COLOR_SECONDARY = "#2ecc71"
COLOR_TEXT = "white"
COLOR_BACKGROUND = "#2c3e50"

# --- APPEARANCE AND THEME ---
APPEARANCE_MODE = "Dark"
COLOR_THEME = "blue"

# --- WINDOW SETTINGS ---
WINDOW_TITLE_AUTH = "Chat App - Вход"
WINDOW_TITLE_CHAT = "Chat App - ЛОБИ"
WINDOW_GEOMETRY = "750x550"
SCALING_FACTOR = 0.9

# --- FONTS ---
FONT_FAMILY = "Arial"
FONT_HEADER_LARGE = (FONT_FAMILY, 24, "bold")
FONT_HEADER_MEDIUM = (FONT_FAMILY, 18, "bold")
FONT_HEADER_SMALL = (FONT_FAMILY, 14, "bold")
FONT_NORMAL = (FONT_FAMILY, 12)

# --- TEXT TAGS (FOR CTkTextbox) ---

CHAT_HISTORY_TAGS = {
    "me_message": {"foreground": COLOR_SECONDARY},
    "other_message": {"foreground": COLOR_PRIMARY},
}

USER_LIST_TAGS = {
    "me": {"foreground": COLOR_SECONDARY, "font": (FONT_FAMILY, 12, "bold")},
    "other": {"foreground": COLOR_TEXT, "font": (FONT_FAMILY, 12)},
    "header": {"foreground": "gray", "font": (FONT_FAMILY, 10, "italic")},
}
