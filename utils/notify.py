import platform
import threading
import time

try:
    from playsound import playsound
except Exception:
    playsound = None

try:
    from plyer import notification
except Exception:
    notification = None


def _play_sound_thread(file_or_none=None):
    try:
        if playsound and file_or_none:
            playsound(file_or_none)
        else:
            # fallback: use simple system beep
            if platform.system() == "Windows":
                try:
                    import winsound

                    winsound.MessageBeep()
                except Exception:
                    pass
            else:
                # bell character
                print("\a", end="")
    except Exception:
        pass


def notify_dm(title: str, message: str, sound_file: str = None):
    """Cross-platform notification for incoming DM.

    Attempts to show a desktop notification via plyer (if available) and play a short sound.
    """
    # Show desktop notification if possible
    try:
        if notification:
            notification.notify(
                title=title, message=message, app_name="PyChat", timeout=4
            )
    except Exception:
        pass

    # Play sound in a separate thread to avoid blocking UI
    try:
        threading.Thread(
            target=_play_sound_thread, args=(sound_file,), daemon=True
        ).start()
    except Exception:
        pass
