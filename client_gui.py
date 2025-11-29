import os
import sys
import threading
import time
import tkinter as tk
import traceback
from datetime import datetime, timezone
from tkinter import messagebox

import customtkinter as ctk
import pyrebase
from firebase_admin import firestore
from PIL import Image, ImageTk

import config
from services.auth_service import AuthService
from services.firestore_client import get_db as get_firestore_db
from services.firestore_client import (get_history_paginated, init_firestore,
                                       stream_room)
from utils.notify import notify_dm

# --- 1. КОНФИГУРАЦИЯ И ИНИЦИАЛИЗАЦИЯ ---

# Дефолтни настройки (тъй като config.py не е наличен)
SCALING_FACTOR = 1.0
APPEARANCE_MODE = "System"
COLOR_THEME = "blue"
WINDOW_TITLE_AUTH = "САМО НАШИ Чат"
WINDOW_GEOMETRY = "900x800"
FONT_HEADER_LARGE = ("Arial", 24, "bold")
FONT_HEADER_MEDIUM = ("Arial", 16, "bold")
# Color palette (dark theme)
COLOR_PRIMARY = "#1E90FF"  # main accent blue
COLOR_PRIMARY_DARK = "#176fbf"  # darker accent for hover/active
COLOR_TEXT = "#E6EEF3"  # light text color
COLOR_BG = "#2b2b2b"  # background (not applied everywhere automatically)
COLOR_MUTED = "#9AA6B2"  # muted / secondary text
COLOR_USER_MSG = "#4DA6FF"  # color for user's messages
COLOR_OTHER_MSG = "#DDDDDD"  # color for other users' messages
COLOR_CHANNEL_INACTIVE = "transparent"  # Прозрачен цвят за неактивни бутони

# Initialize AuthService (pyrebase) using config
try:
    auth_service = AuthService(config.FIREBASE_CONFIG)
    auth = auth_service.get_auth()
    print("[LOG] Pyrebase Auth initialized successfully.")
except Exception as e:
    print(f"[CRITICAL ERROR] Pyrebase Auth failed: {e}")
    sys.exit()

# Initialize Firestore via services wrapper
firestore_db = init_firestore(config.KEY_JSON_PATH)
if firestore_db is None:
    print("[CRITICAL ERROR] Firestore initialization failed! Check key.json.")
else:
    print("[LOG] Firestore Client initialized successfully (DB Active).")

# --- 2. GUI SETUP (CustomTkinter) ---

ctk.set_widget_scaling(SCALING_FACTOR)
ctk.set_window_scaling(SCALING_FACTOR)
ctk.set_appearance_mode(APPEARANCE_MODE)
ctk.set_default_color_theme(COLOR_THEME)


class AuthApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(WINDOW_TITLE_AUTH)
        self.geometry(WINDOW_GEOMETRY)
        # Make the window fixed-size (non-resizable) based on WINDOW_GEOMETRY
        try:
            gw, gh = map(int, WINDOW_GEOMETRY.split("x"))
            # Prevent user from resizing the window
            self.resizable(False, False)
            # Also set min/max size to exactly the geometry to block maximize/resize
            self.minsize(gw, gh)
            self.maxsize(gw, gh)
        except Exception:
            # If parsing fails, still disable resizing as a fallback
            try:
                self.resizable(False, False)
            except Exception:
                pass

        self.username = None
        self._heartbeat_running = False
        self._message_stop_watcher = None
        self._global_message_stop_watcher = None
        self._presence_stop_watcher = None
        # track unread DM channels (usernames)
        self._unread_channels = set()
        # track displayed message ids to avoid duplicates (optimistic insert + listener)
        self._displayed_message_ids = set()
        self.current_channel = "lobby"
        # dm_list съдържа активните DM стаи: {'otheruser': 'dm_admin_otheruser'}
        self.dm_list = {}

        # Дефиниране на CTkFont обекти за избягване на грешката със скалирането при tag_config
        self.chat_font_normal = ctk.CTkFont(family="Arial", size=11)
        self.chat_font_bold = ctk.CTkFont(family="Arial", size=11, weight="bold")
        # Header fonts (use CTkFont to avoid "font option forbidden" with scaling)
        self.font_header_large = ctk.CTkFont(family="Arial", size=24, weight="bold")
        self.font_header_medium = ctk.CTkFont(family="Arial", size=16, weight="bold")
        # Small bold for section labels
        self.font_small_bold = ctk.CTkFont(family="Arial", size=10, weight="bold")

        # Фреймове
        self.login_frame = ctk.CTkFrame(self)
        self.chat_frame = ctk.CTkFrame(self)
        self.login_frame.pack(fill="both", expand=True)

        self.setup_login_register_ui()

        if firestore_db is None:
            messagebox.showwarning(
                "ПРЕДУПРЕЖДЕНИЕ",
                "Чат функционалността е неактивна! Моля, проверете key.json.",
            )

        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    # --- 3. UI BUILDERS ---

    def setup_login_register_ui(self):
        """Създава елементи за вход и регистрация."""
        container = ctk.CTkFrame(self.login_frame)
        container.grid(row=0, column=0, sticky="nsew", padx=20, pady=20)
        self.login_frame.grid_columnconfigure(0, weight=1)
        self.login_frame.grid_rowconfigure(0, weight=1)

        # Попитваме за лого (logo.png) в работната директория. Ако липсва, просто продължаваме без изображение.
        try:
            logo_path = os.path.join(os.path.dirname(__file__), "logo.png")
            if os.path.exists(logo_path):
                img = Image.open(logo_path)
                # Ограничаваме ширината до 220px, запазвайки аспектното съотношение
                max_w = 220
                w, h = img.size
                if w > max_w:
                    ratio = max_w / float(w)
                    # Pillow 10 removed Image.ANTIALIAS; use Resampling.LANCZOS when available
                    try:
                        resample_filter = Image.Resampling.LANCZOS
                    except Exception:
                        # fallback for older Pillow versions
                        resample_filter = getattr(Image, "LANCZOS", Image.BICUBIC)
                    img = img.resize((int(w * ratio), int(h * ratio)), resample_filter)
                # Try to create a CTkImage first (if available), otherwise fall back to ImageTk.PhotoImage
                try:
                    # ctk.CTkImage accepts a PIL image via the 'light_image' argument
                    self.logo_image = ctk.CTkImage(light_image=img, size=img.size)
                except Exception:
                    self.logo_image = ImageTk.PhotoImage(img)
                ctk.CTkLabel(container, image=self.logo_image, text="").pack(
                    pady=(10, 10)
                )
            else:
                print(
                    f"[INFO] Лого файлът не е намерен: {logo_path} (продължавам без изображение)"
                )
        except Exception as e:
            print(f"[WARN] Неуспех при зареждане на лого: {e}")

        ctk.CTkLabel(
            container, text="ВХОД / РЕГИСТРАЦИЯ", font=self.font_header_large
        ).pack(pady=(30, 20))

        self.email_entry = ctk.CTkEntry(container, placeholder_text="Имейл", width=300)
        self.email_entry.pack(pady=10)

        self.pass_entry = ctk.CTkEntry(
            container, placeholder_text="Парола", show="*", width=300
        )
        self.pass_entry.pack(pady=10)

        ctk.CTkButton(
            container, text="ВХОД", command=self.attempt_login, width=300
        ).pack(pady=10)
        ctk.CTkButton(
            container, text="РЕГИСТРАЦИЯ", command=self.attempt_register, width=300
        ).pack(pady=5)
        ctk.CTkLabel(
            container, text="Добре дошли в чат лобито!", text_color=COLOR_MUTED
        ).pack(pady=20)

    def setup_chat_ui(self):
        """Създава елементите на чат лобито."""

        # Grid config: | Channels (0) | Chat Area (1) | Users (2) |
        self.chat_frame.columnconfigure(1, weight=1)
        self.chat_frame.rowconfigure(1, weight=1)

        # Лява лента (Канали)
        self.channels_frame = ctk.CTkFrame(self.chat_frame, width=180, corner_radius=0)
        self.channels_frame.grid(row=0, column=0, rowspan=3, sticky="nsew")
        ctk.CTkLabel(
            self.channels_frame, text="КАНАЛИ", font=self.font_header_medium
        ).pack(pady=(10, 5))
        self.channel_scroll_frame = ctk.CTkScrollableFrame(
            self.channels_frame, fg_color="transparent"
        )
        self.channel_scroll_frame.pack(fill="both", expand=True, padx=5, pady=(0, 5))

        # Дясна лента (Потребители)
        user_list_frame = ctk.CTkFrame(self.chat_frame, width=220)
        user_list_frame.grid(
            row=0, column=2, rowspan=3, padx=(0, 10), pady=10, sticky="nsew"
        )
        ctk.CTkLabel(
            user_list_frame, text="ПОТРЕБИТЕЛИ ONLINE", font=self.font_header_medium
        ).pack(pady=5)
        self.user_list_container = ctk.CTkScrollableFrame(
            user_list_frame, fg_color="transparent"
        )
        self.user_list_container.pack(fill="both", expand=True, padx=5, pady=(0, 5))

        # ЦЕНТЪР: Хедър (Row 0, Col 1)
        header_frame = ctk.CTkFrame(self.chat_frame, fg_color="transparent")
        header_frame.grid(row=0, column=1, sticky="ew", padx=10, pady=10)
        header_frame.columnconfigure(0, weight=1)
        self.chat_title_label = ctk.CTkLabel(
            header_frame,
            text=f"Чат Лоби: #{self.current_channel}",
            font=self.font_header_medium,
        )
        self.chat_title_label.grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            header_frame,
            text="Изход",
            command=self.logout,
            width=100,
            fg_color=COLOR_MUTED,
        ).grid(row=0, column=1, sticky="e")

        # ЦЕНТЪР: История (Row 1, Col 1)
        self.chat_history = ctk.CTkTextbox(
            self.chat_frame, state="disabled", wrap="word"
        )
        self.chat_history.grid(row=1, column=1, padx=10, pady=5, sticky="nsew")

        # Настройки на таговете (CustomTkinter's CTkTextbox does not allow per-tag fonts)
        # Remove font= to avoid "font option forbidden" with scaling; keep colors only.
        self.chat_history.tag_config("user_msg", foreground=COLOR_USER_MSG)
        self.chat_history.tag_config("other_msg", foreground=COLOR_OTHER_MSG)

        # ЦЕНТЪР: Вход за съобщение (Row 2, Col 1)
        input_frame = ctk.CTkFrame(self.chat_frame)
        input_frame.grid(row=2, column=1, sticky="ew", padx=10, pady=10)
        input_frame.columnconfigure(0, weight=1)
        self.message_entry = ctk.CTkEntry(
            input_frame, placeholder_text="Въведете съобщение...", height=30
        )
        self.message_entry.grid(row=0, column=0, sticky="ew", padx=(0, 10), pady=0)
        self.message_entry.bind("<Return>", lambda event: self.send_message())
        ctk.CTkButton(
            input_frame, text="Изпрати", command=self.send_message, width=100
        ).grid(row=0, column=1, pady=0)

        self.update_channel_list_ui()
        # start global message listener to detect incoming DMs for channels we're not viewing
        if firestore_db is not None and not getattr(
            self, "_global_message_stop_watcher", None
        ):
            try:
                threading.Thread(
                    target=self._global_message_listener_loop, daemon=True
                ).start()
            except Exception as e:
                print(
                    f"[WARN] Неуспешно стартиране на глобален слушател за съобщения: {e}"
                )

    # --- 4. CHANNEL LIST LOGIC ---

    def update_channel_list_ui(self):
        """Обновява списъка с канали и DM стаи."""
        for widget in self.channel_scroll_frame.winfo_children():
            widget.destroy()

        # 1. Лоби канал
        is_lobby_active = self.current_channel == "lobby"
        lobby_color = COLOR_PRIMARY if is_lobby_active else COLOR_CHANNEL_INACTIVE
        btn = ctk.CTkButton(
            self.channel_scroll_frame,
            text="# Лоби",
            command=lambda: self.switch_channel("lobby"),
            anchor="w",
            fg_color=lobby_color,
            hover_color=COLOR_PRIMARY if not is_lobby_active else COLOR_PRIMARY_DARK,
        )
        btn.pack(fill="x", pady=2, padx=2)
        # bind right-click for context menu (but disable delete actions for lobby)
        try:
            btn.bind(
                "<Button-3>", lambda e, ch="lobby": self._on_channel_right_click(e, ch)
            )
        except Exception:
            pass

        # 2. Активни DM стаи
        if self.dm_list:
            ctk.CTkLabel(
                self.channel_scroll_frame,
                text="ЛИЧНИ СЪОБЩЕНИЯ",
                font=self.font_small_bold,
            ).pack(pady=(10, 5))
            dm_users = sorted(self.dm_list.keys(), key=str.lower)
            for user in dm_users:
                is_dm_active = self.current_channel == user
                dm_color = COLOR_PRIMARY if is_dm_active else COLOR_CHANNEL_INACTIVE
                btn = ctk.CTkButton(
                    self.channel_scroll_frame,
                    text=f"• {user}",
                    command=lambda u=user: self.switch_channel(u),
                    anchor="w",
                    fg_color=dm_color,
                    hover_color=COLOR_PRIMARY
                    if not is_dm_active
                    else COLOR_PRIMARY_DARK,
                    text_color=(
                        COLOR_USER_MSG if user in self._unread_channels else COLOR_TEXT
                    ),
                )
                btn.pack(fill="x", pady=2, padx=2)
                try:
                    btn.bind(
                        "<Button-3>",
                        lambda e, ch=user: self._on_channel_right_click(e, ch),
                    )
                except Exception:
                    pass

    def _on_channel_right_click(self, event, channel_name):
        """Показва контекстно меню при десен бутон върху канал/DM.

        Options:
        - Изтрий история: изтрива всички съобщения за този room_id
        - Изтрий чат: изтрива история и премахва DM от локалния списък
        """
        # Build a simple tk.Menu
        menu = tk.Menu(self, tearoff=0)

        # If lobby, disable destructive actions
        if channel_name == "lobby":
            menu.add_command(label="(Не може да се изтрие лоби)", state="disabled")
        else:
            menu.add_command(
                label="Изтрий история",
                command=lambda ch=channel_name: self._confirm_delete_history(ch),
            )
            menu.add_command(
                label="Изтрий чат",
                command=lambda ch=channel_name: self._confirm_delete_chat(ch),
            )

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _confirm_delete_history(self, channel_name):
        if not messagebox.askyesno(
            "Потвърждение",
            f"Сигурни ли сте, че искате да изтриете историята на {channel_name}?",
        ):
            return
        # Determine room_id
        if channel_name == "lobby":
            messagebox.showinfo("Инфо", "Не може да се изтрие историята на лоби.")
            return
        room_id = self.dm_list.get(channel_name) or self.get_dm_room_id(
            self.username, channel_name
        )
        # delete in background; pass channel_name so UI can refresh when done
        threading.Thread(
            target=lambda: self._delete_messages_for_room(
                room_id, notify=True, channel_name=channel_name
            ),
            daemon=True,
        ).start()

    def _confirm_delete_chat(self, channel_name):
        if not messagebox.askyesno(
            "Потвърждение",
            f"Сигурни ли сте, че искате да изтриете чата с {channel_name}? Това ще изтрие и историята.",
        ):
            return
        if channel_name == "lobby":
            messagebox.showinfo("Инфо", "Лобито не може да бъде изтрито.")
            return
        room_id = self.dm_list.get(channel_name) or self.get_dm_room_id(
            self.username, channel_name
        )

        # delete messages and remove DM locally
        def _job():
            self._delete_messages_for_room(
                room_id, notify=False, channel_name=channel_name
            )
            # remove dm locally and update UI on main thread
            try:
                if channel_name in self.dm_list:
                    del self.dm_list[channel_name]
            except Exception:
                pass
            # after deleting chat, switch back to lobby and refresh UI
            self.after(
                0,
                lambda: (
                    self.switch_channel("lobby"),
                    self.update_channel_list_ui(),
                    messagebox.showinfo(
                        "Изтриване", f"Чатът с {channel_name} е изтрит."
                    ),
                ),
            )

        threading.Thread(target=_job, daemon=True).start()

    def _delete_messages_for_room(self, room_id, notify=True, channel_name=None):
        """Deletes all messages with given room_id using batched deletes."""
        if firestore_db is None:
            self.after(
                0, lambda: messagebox.showerror("Грешка", "Firestore не е наличен.")
            )
            return
        try:
            print(f"[LOG] Изтриване на съобщения за room_id={room_id} ...")
            query = firestore_db.collection("messages").where("room_id", "==", room_id)
            # stream() or get()
            try:
                docs = list(query.get())
            except Exception:
                docs = list(query.stream())

            batch = firestore_db.batch()
            count = 0
            batch_count = 0
            for d in docs:
                try:
                    batch.delete(
                        firestore_db.collection("messages").document(
                            getattr(d, "id", None)
                        )
                    )
                    count += 1
                    batch_count += 1
                except Exception:
                    # fallback: try using d.reference if available
                    try:
                        ref = getattr(d, "reference", None)
                        if ref is not None:
                            batch.delete(ref)
                            count += 1
                            batch_count += 1
                    except Exception:
                        continue

                # commit every 400 deletes to avoid large batches
                if batch_count >= 400:
                    batch.commit()
                    batch = firestore_db.batch()
                    batch_count = 0

            if batch_count > 0:
                batch.commit()

            print(f"[LOG] Изтриване приключи. Изтрити документи: {count}")
            if notify:
                self.after(
                    0,
                    lambda: messagebox.showinfo(
                        "Изтриване завършено",
                        f"Изтрити {count} съобщения за {room_id}.",
                    ),
                )
            # If we deleted history for the current channel, clear the chat UI
            try:
                if channel_name and channel_name == self.current_channel:
                    self.after(
                        0,
                        lambda: (
                            self.chat_history.configure(state="normal"),
                            self.chat_history.delete("1.0", tk.END),
                            self.chat_history.configure(state="disabled"),
                            self._displayed_message_ids.clear(),
                        ),
                    )
                # Also remove unread marker if present
                if channel_name:
                    try:
                        self._unread_channels.discard(channel_name)
                        self.after(0, self.update_channel_list_ui)
                    except Exception:
                        pass
            except Exception:
                pass
        except Exception as e:
            print(f"[ERROR] Неуспешно изтриване на съобщения за {room_id}: {e}")
            self.after(0, lambda: messagebox.showerror("Грешка при изтриване", str(e)))

    # --- 5. AUTH & NAVIGATION ---

    def attempt_login(self):
        """Опитва да влезе в системата."""
        email = self.email_entry.get().strip()
        password = self.pass_entry.get().strip()
        try:
            auth.sign_in_with_email_and_password(email, password)
            self.username = email.split("@")[0]
            print(f"[LOG] Успешен вход като {self.username}.")
            self.show_chat_lobby()
        except Exception as e:
            # Print full traceback to help locate the source of font/scaling errors
            print(f"[ERROR] Грешка при вход от Pyrebase: {e}")
            traceback.print_exc()
            messagebox.showerror(
                "Грешка при вход",
                "Невалиден имейл/парола или вътрешна грешка. Проверете конзолата за подробности.",
            )

    def attempt_register(self):
        """Опитва да регистрира нов потребител."""
        email = self.email_entry.get().strip()
        password = self.pass_entry.get().strip()
        try:
            auth.create_user_with_email_and_password(email, password)
            messagebox.showinfo("Успех", "Регистрацията е успешна!")
        except Exception as e:
            print(f"[ERROR] Грешка при регистрация от Pyrebase: {e}")
            messagebox.showerror(
                "Грешка при регистрация",
                "Имейлът вече съществува или паролата е твърде слаба (мин. 6 символа).",
            )

    def show_chat_lobby(self):
        """Превключва към основния чат екран и стартира слушателите."""
        self.login_frame.pack_forget()
        self.setup_chat_ui()
        self.chat_frame.pack(fill="both", expand=True)
        # switch_channel извиква update_channel_list_ui отново, което е ОК
        self.switch_channel("lobby")

        # If we returned early because the channel was already 'lobby', ensure listeners/history are started
        if firestore_db is not None and not self._message_stop_watcher:
            try:
                self.start_chat_listeners()
            except Exception as e:
                print(f"[WARN] Неуспешно стартиране на слушател за чат при show: {e}")

        if firestore_db is not None:
            self.set_online_status(True)
            self.start_presence_heartbeat()
            self.start_presence_listener()
            # Fetch current presence and history once to populate UI immediately
            try:
                self._fetch_presence_once()
            except Exception as e:
                print(f"[WARN] Неуспешно еднократно извличане на присъствие: {e}")

    # --- 6. CLEANUP И LOGOUT (АГРЕСИВНО СПИРАНЕ НА НИШКИ) ---
    def _stop_listeners(self, clean_exit=False):
        """Спира heartbeat и отписва всички snapshot слушатели.

        If `clean_exit` is True, the presence document will be deleted from Firestore.
        """
        print(f"[LOG] Stopping listeners (clean_exit={clean_exit})")
        # Stop heartbeat first so set_online_status knows we're stopping
        self._heartbeat_running = False

        # Unsubscribe message watcher
        if self._message_stop_watcher:
            try:
                if hasattr(self._message_stop_watcher, "unsubscribe"):
                    self._message_stop_watcher.unsubscribe()
                elif callable(self._message_stop_watcher):
                    self._message_stop_watcher()
                else:
                    print(
                        "[WARN] Unknown message watcher type; cannot unsubscribe cleanly."
                    )
            except Exception as e:
                print(f"[ERROR] Грешка при unsubscribe на съобщения: {e}")
            self._message_stop_watcher = None

        # Unsubscribe presence watcher
        if self._presence_stop_watcher:
            try:
                if hasattr(self._presence_stop_watcher, "unsubscribe"):
                    self._presence_stop_watcher.unsubscribe()
                elif callable(self._presence_stop_watcher):
                    self._presence_stop_watcher()
                else:
                    print(
                        "[WARN] Unknown presence watcher type; cannot unsubscribe cleanly."
                    )
            except Exception as e:
                print(f"[ERROR] Грешка при unsubscribe на присъствие: {e}")
            self._presence_stop_watcher = None

        # Remove presence document on clean exit
        if clean_exit and self.username and firestore_db is not None:
            try:
                firestore_db.collection("presence").document(self.username).delete()
            except Exception as e:
                print(f"[ERROR] Грешка при изтриване на presence при clean exit: {e}")

    def on_closing(self):
        """Изпълнява се при затваряне на прозореца. Осигурява чисто прекратяване."""
        print("[LOG] Започва процес на затваряне...")
        # Stop listeners and remove presence (clean exit)
        self._stop_listeners(clean_exit=True)
        print("[LOG] Heartbeat и онлайн статус изключени.")
        print("[LOG] Унищожаване на прозореца.")
        self.destroy()

    def logout(self):
        """Излиза от системата, обновява статуса и връща към екрана за вход."""
        # Stop listeners (but do not destroy window) and return to login UI
        self._stop_listeners(clean_exit=False)
        # Remove presence doc for this user when logging out
        try:
            self.set_online_status(False)
        except Exception as e:
            print(f"[WARN] Неуспешно изтриване на presence при logout: {e}")
        # Clear any displayed message ids cache
        try:
            self._displayed_message_ids.clear()
        except Exception:
            pass
        try:
            self.chat_frame.pack_forget()
        except Exception:
            pass
        self.login_frame.pack(fill="both", expand=True)
        self.username = None
        messagebox.showinfo("Изход", "Излязохте успешно.")

    # --- 7. CHAT LOGIC (THREADS И LISTENERS) ---

    def get_dm_room_id(self, user1, user2):
        """Генерира уникален, сортиран идентификатор за DM стая."""
        return f"dm_{'_'.join(sorted([user1, user2]))}"

    def set_online_status(self, is_online=True):
        """Обновява статуса на присъствие във Firestore."""
        if not self.username or firestore_db is None:
            return

        doc_ref = firestore_db.collection("presence").document(self.username)
        try:
            if is_online:
                doc_ref.set(
                    {"username": self.username, "last_seen": firestore.SERVER_TIMESTAMP}
                )
            elif not self._heartbeat_running:  # Изтрива само при clean exit
                doc_ref.delete()
        except Exception as e:
            print(f"[ERROR] Грешка при обновяване на присъствието: {e}")

    def start_presence_heartbeat(self):
        """Стартира таймер за периодично обновяване на 'last_seen'."""
        if firestore_db is None:
            return
        self._heartbeat_running = True
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()

    def _heartbeat_loop(self):
        """Цикъл, който изпраща 'heartbeat' към сървъра."""
        while self._heartbeat_running:
            time.sleep(15)
            if self._heartbeat_running:
                # Използва after за безопасно изпълнение в главната нишка
                self.after(0, lambda: self.set_online_status(True))

    def start_presence_listener(self):
        """Стартира Realtime слушател за присъствие."""
        if firestore_db is None:
            return
        query = firestore_db.collection("presence")
        # Стартира в отделна нишка, за да не блокира главната
        threading.Thread(
            target=lambda: self._presence_listener_loop(query), daemon=True
        ).start()

    def _presence_listener_loop(self, query):
        """Слуша за промени в колекцията 'presence'."""
        try:
            # .on_snapshot връща Watch обекта, който запазваме
            self._presence_stop_watcher = query.on_snapshot(
                self._handle_presence_change
            )
        except Exception as e:
            print(f"[ERROR] Грешка при стартиране на слушателя за присъствие: {e}")

    def _handle_presence_change(self, col_snapshot, changes, read_time):
        """Обновява списъка с потребители онлайн."""

        # Събира всички потребители онлайн (включително текущия)
        online_users = sorted(
            [
                doc.to_dict().get("username")
                for doc in col_snapshot
                if doc.to_dict().get("username")
            ],
            key=str.lower,
        )

        # Обновяване на UI чрез self.after за безопасност
        self.after(0, lambda: self._update_user_list_ui(online_users))

    def _update_user_list_ui(self, online_users):
        """Финално обновяване на UI елементите за присъствие."""
        for widget in self.user_list_container.winfo_children():
            widget.destroy()

        for idx, user in enumerate(online_users):
            # Командата превключва към DM стая с този потребител
            if user == self.username:
                # Don't allow DM to self: render a disabled button / label indicating current user
                btn = ctk.CTkButton(
                    self.user_list_container,
                    text=f"@{user} (You)",
                    state="disabled",
                    anchor="w",
                    text_color=COLOR_MUTED,
                    fg_color="transparent",
                )
            else:
                cmd = lambda u=user: self.switch_channel(u)
                btn = ctk.CTkButton(
                    self.user_list_container,
                    text=f"@{user} (Online)",
                    command=cmd,
                    anchor="w",
                    text_color=COLOR_USER_MSG,
                    fg_color="transparent",
                    hover_color=COLOR_PRIMARY_DARK,
                )
            btn.grid(row=idx, column=0, sticky="ew", pady=2, padx=2)

    def _channel_name_for_room(self, room_id):
        """Return channel username (or 'lobby') for given room_id, or None."""
        if not room_id:
            return None
        if room_id == "lobby":
            return "lobby"
        # Look in dm_list first
        try:
            for user, rid in self.dm_list.items():
                if rid == room_id:
                    return user
        except Exception:
            pass
        # Fallback: parse dm_ format
        if room_id.startswith("dm_"):
            parts = room_id.split("_")[1:]
            try:
                for p in parts:
                    if p != self.username:
                        return p
            except Exception:
                return None
        return None

    def send_message(self):
        """Изпраща съобщение към Firestore."""
        message = self.message_entry.get().strip()
        if not message or firestore_db is None:
            return

        # Определя room_id
        room_id = "lobby"
        if self.current_channel != "lobby":
            # Ако не е лоби, използва DM room_id, който вече е в dm_list след switch_channel
            room_id = self.dm_list.get(self.current_channel)
            if room_id is None:
                # В малко вероятния случай, че dm_list е празен при switch, пресмятаме го сега
                room_id = self.get_dm_room_id(self.username, self.current_channel)
                self.dm_list[self.current_channel] = room_id

        try:
            # Firestore .add() can return different shapes depending on SDK/version.
            add_result = firestore_db.collection("messages").add(
                {
                    "room_id": room_id,
                    "username": self.username,
                    "text": message,
                    "timestamp": firestore.SERVER_TIMESTAMP,
                }
            )

            # Determine DocumentReference from the returned value(s)
            doc_ref = None
            if hasattr(add_result, "id"):
                # direct DocumentReference
                doc_ref = add_result
            else:
                try:
                    # iterable return (tuple/list) - find first item with .id
                    for item in add_result:
                        if hasattr(item, "id"):
                            doc_ref = item
                            break
                except Exception:
                    doc_ref = None

            if doc_ref is not None:
                print(
                    f"[LOG] Съобщение ИЗПРАТЕНО успешно към Room ID: {room_id}, Doc ID: {doc_ref.id}"
                )
            else:
                print(
                    f"[LOG] Съобщение ИЗПРАТЕНО успешно към Room ID: {room_id} (Doc ID неизвестен)"
                )
            # Optimistic UI update: insert the sent message locally so user sees it immediately
            try:
                # Only optimistic-insert if we have the server doc id to avoid duplicates
                if doc_ref is not None and getattr(doc_ref, "id", None):
                    local_msg = {
                        "room_id": room_id,
                        "username": self.username,
                        "text": message,
                        "timestamp": datetime.now(),
                        "_id": doc_ref.id,
                    }
                    # Schedule UI insert on main thread
                    self.after(
                        0, lambda: self._update_ui_with_new_messages([local_msg])
                    )
            except Exception as e:
                print(f"[WARN] Неуспешно локално вмъкване на съобщението: {e}")
            self.message_entry.delete(0, tk.END)
        except Exception as e:
            # По-добро прихващане на грешки
            print(f"[ERROR] Неуспешно изпращане на съобщение към Firestore: {e}")
            messagebox.showerror(
                "Грешка", f"Неуспешно изпращане: {e}. Проверете правата за запис."
            )

    def switch_channel(self, new_channel):
        """Превключва активния канал/DM стая и рестартира слушателя."""
        # Prevent switching to a DM with self
        if new_channel != "lobby" and self.username and new_channel == self.username:
            messagebox.showinfo(
                "Инфо", "Не можете да изпращате лично съобщение на себе си."
            )
            return

        if self.current_channel == new_channel:
            return

        # Ако превключваме към потребител (DM), добавяме го към dm_list (но не към себе си)
        if (
            new_channel != "lobby"
            and new_channel not in self.dm_list
            and new_channel != self.username
        ):
            self.dm_list[new_channel] = self.get_dm_room_id(self.username, new_channel)

        self.current_channel = new_channel
        # Clear displayed message ids when switching channels to avoid cross-room dedupe
        try:
            self._displayed_message_ids.clear()
        except Exception:
            pass
        # Clear unread marker for the channel we switched to
        try:
            if new_channel in self._unread_channels:
                self._unread_channels.discard(new_channel)
        except Exception:
            pass
        self.chat_history.configure(state="normal")
        self.chat_history.delete("1.0", tk.END)
        self.chat_history.configure(state="disabled")
        print(f"[LOG] Превключване към канал/потребител: {self.current_channel}")

        # Първо отписваме стария слушател, ако съществува
        if self._message_stop_watcher:
            try:
                if hasattr(self._message_stop_watcher, "unsubscribe"):
                    self._message_stop_watcher.unsubscribe()
                elif callable(self._message_stop_watcher):
                    self._message_stop_watcher()
                else:
                    print(
                        "[WARN] Unknown message watcher type; cannot unsubscribe cleanly."
                    )
                print("[LOG] Предишен слушател за съобщения СПРЯН успешно.")
            except Exception as e:
                print(f"[ERROR] Грешка при unsubscribe на предишни съобщения: {e}")
            self._message_stop_watcher = None

        if firestore_db is not None:
            self.start_chat_listeners()

        title = (
            f"Чат Лоби: #{self.current_channel}"
            if self.current_channel == "lobby"
            else f"Лично с: @{self.current_channel}"
        )
        self.chat_title_label.configure(text=title)

        # Обновява списъка с канали за да маркира активния
        self.update_channel_list_ui()

    def start_chat_listeners(self):
        """Стартира Realtime слушател за съобщения за активния канал/DM."""
        if firestore_db is None:
            return
        room_id = (
            "lobby"
            if self.current_channel == "lobby"
            else self.dm_list.get(self.current_channel)
        )
        if room_id is None:
            print("[ERROR] Не може да се намери Room ID за слушане.")
            return

        print(f"[LOG] Стартиране на слушател за Room ID: {room_id}")
        # Avoid server-side ordering that may require a composite index.
        # We'll fetch documents by room_id and sort client-side by timestamp.
        query = (
            firestore_db.collection("messages")
            .where("room_id", "==", room_id)
            .limit(100)
        )

        # Load history once (synchronous read) to ensure UI has messages immediately
        try:
            self._load_history_once(query)
            # suppress the immediate initial snapshot's duplicate load (we already loaded once)
            self._suppress_next_initial_snapshot = True
        except Exception as e:
            print(f"[WARN] Неуспешно еднократно зареждане на история: {e}")

        threading.Thread(
            target=lambda: self._message_listener_loop(query), daemon=True
        ).start()

    def _load_history_once(self, query):
        """Извлича историята за даден query веднъж и обновява UI.

        Expects a Query object.
        """
        docs = None
        # Try common ways to fetch documents from a Query across SDKs
        try:
            docs = list(query.get())
        except Exception:
            try:
                docs = list(query.stream())
            except Exception as e:
                print(f"[DEBUG] Неуспех при извличане на история (get/stream): {e}")
                # As a last resort, try re-constructing a query by collection and filtering by room_id
                try:
                    # attempt to extract room_id from the original query by re-querying by current channel
                    room_id = (
                        "lobby"
                        if self.current_channel == "lobby"
                        else self.dm_list.get(self.current_channel)
                    )
                    docs = list(
                        firestore_db.collection("messages")
                        .where("room_id", "==", room_id)
                        .order_by("timestamp", direction=firestore.Query.ASCENDING)
                        .limit(100)
                        .get()
                    )
                except Exception as e2:
                    print(f"[ERROR] Неуспешно извличане на история чрез fallback: {e2}")
                    docs = []

        if not docs:
            print("[DEBUG] _load_history_once: няма намерени документи за query.")
            return

        # Debug print: show doc ids and small preview
        try:
            doc_ids = [getattr(d, "id", None) for d in docs]
            print(
                f"[DEBUG] _load_history_once: намерени документи: {len(docs)}, ids={doc_ids}"
            )
            sample = [
                (
                    getattr(d, "id", None),
                    d.to_dict() if hasattr(d, "to_dict") else dict(d),
                )
                for d in docs[:5]
            ]
            print(f"[DEBUG] _load_history_once: sample docs={sample}")
        except Exception as e:
            print(f"[DEBUG] Грешка при логване на намерените документи: {e}")

        # Convert to dicts and sort by timestamp client-side when possible
        def _timestamp_for_sort(item):
            try:
                d = item.to_dict() if hasattr(item, "to_dict") else dict(item)
                ts = d.get("timestamp")
                if not ts:
                    return 0
                if hasattr(ts, "timestamp"):
                    # python datetime
                    return ts.timestamp()
                if hasattr(ts, "ToDatetime"):
                    return ts.ToDatetime().timestamp()
                if hasattr(ts, "seconds"):
                    return float(ts.seconds)
                return 0
            except Exception:
                return 0

        history_docs = sorted(docs, key=_timestamp_for_sort)
        # Attach document ids for deduplication and convert to dicts
        history_data = []
        for doc in history_docs:
            try:
                d = doc.to_dict()
            except Exception:
                try:
                    d = dict(doc)
                except Exception:
                    d = {}
            try:
                d["_id"] = getattr(doc, "id", None)
            except Exception:
                pass
            history_data.append(d)

        # Ensure UI update runs on main thread
        self.after(0, lambda: self._update_ui_with_new_messages(history_data))

    def _fetch_presence_once(self):
        """One-time fetch of presence documents to populate the online users list."""
        try:
            col = firestore_db.collection("presence")
            docs = list(col.get())
            # Include current user as well
            online_users = sorted(
                [
                    d.to_dict().get("username")
                    for d in docs
                    if d.to_dict().get("username")
                ],
                key=str.lower,
            )
            self.after(0, lambda: self._update_user_list_ui(online_users))
        except Exception as e:
            print(f"[WARN] Грешка при еднократно извличане на присъствие: {e}")

    def _message_listener_loop(self, query):
        """Слуша за нови съобщения за активния room_id."""
        try:
            self._message_stop_watcher = query.on_snapshot(self._handle_message_change)
        except Exception as e:
            print(
                f"[ERROR] Критична грешка при стартиране на слушателя за съобщения (on_snapshot): {e}"
            )

    def _global_message_listener_loop(self):
        """Global listener for new messages so we can detect incoming DMs when not focused on them."""
        try:
            self._global_message_stop_watcher = firestore_db.collection(
                "messages"
            ).on_snapshot(self._handle_global_message_change)
        except Exception as e:
            print(
                f"[ERROR] Неуспешно стартиране на глобален слушател за съобщения: {e}"
            )

    def _handle_global_message_change(self, col_snapshot, changes, read_time):
        """Handle new messages globally and mark unread DM rooms + play sound."""
        if not changes:
            return
        for change in changes:
            try:
                if change.type.name == "ADDED":
                    d = change.document.to_dict()
                    room_id = d.get("room_id")
                    sender = d.get("username")
                    if not room_id or not sender:
                        continue
                    # Only care about DM rooms (format 'dm_user1_user2')
                    if not room_id.startswith("dm_"):
                        continue
                    # If this message is from me, ignore
                    if sender == self.username:
                        continue
                    # If my username is part of the room_id, it's a DM for me
                    if self.username and self.username in room_id:
                        # derive other username
                        parts = room_id.split("_")[1:]
                        other = None
                        try:
                            for p in parts:
                                if p != self.username:
                                    other = p
                                    break
                        except Exception:
                            other = None

                        if other is None:
                            continue

                        # ensure DM exists in left list
                        try:
                            if other not in self.dm_list:
                                self.dm_list[other] = room_id
                                # update channel UI on main thread
                                self.after(0, self.update_channel_list_ui)
                        except Exception:
                            pass

                        # If not currently viewing that channel, mark unread and play sound
                        try:
                            if other != self.current_channel:
                                self._unread_channels.add(other)
                                # cross-platform notification + sound
                                try:
                                    self.after(
                                        0,
                                        lambda: notify_dm(
                                            "Новo лично съобщение", f"От: {sender}"
                                        ),
                                    )
                                except Exception:
                                    pass
                                # refresh channel list UI to show unread marker
                                self.after(0, self.update_channel_list_ui)
                        except Exception:
                            pass
            except Exception:
                continue

    def _handle_message_change(self, col_snapshot, changes, read_time):
        """Обработва промените в съобщенията и ги добавя в чат историята."""
        try:
            docs_len = len(col_snapshot)
        except Exception:
            docs_len = "unknown"
        print(
            f"[DEBUG] _handle_message_change called: changes={len(changes) if changes is not None else 'None'}, docs={docs_len}"
        )

        # Първоначално зареждане (ако няма промени, но има документи)
        try:
            total_docs = len(col_snapshot)
        except Exception:
            # some snapshot types are iterable but don't implement __len__
            total_docs = sum(1 for _ in col_snapshot)

        if not changes and total_docs:
            print(
                f"[LOG] Listener: Първоначално зареждане. Общо документи: {total_docs}"
            )
            # If we've already loaded history once via _load_history_once, skip this initial snapshot
            if getattr(self, "_suppress_next_initial_snapshot", False):
                print(
                    "[DEBUG] Skipping initial snapshot because history was loaded synchronously."
                )
                self._suppress_next_initial_snapshot = False
                return
            self.after(0, lambda: self._load_initial_history(col_snapshot))
            return

        # Обработка на промените
        print(f"[LOG] Listener: Получени нови промени: {len(changes)}")

        # Филтрираме само НОВИ ДОБАВЕНИ съобщения и прикачваме doc id за дедупликация
        new_messages = []
        for change in changes:
            try:
                if change.type.name == "ADDED":
                    d = change.document.to_dict()
                    # attach document id if available
                    try:
                        d["_id"] = change.document.id
                    except Exception:
                        pass
                    new_messages.append(d)
            except Exception:
                continue

        if new_messages:
            # Изпълняваме UI обновяването в главната нишка
            self.after(0, lambda: self._update_ui_with_new_messages(new_messages))

    def _update_ui_with_new_messages(self, messages):
        """Безопасно вмъква нови съобщения в UI и принудително обновява."""

        self.chat_history.configure(state="normal")

        for data in messages:
            # Deduplicate by document id when available
            msg_id = data.get("_id") or data.get("id")
            if msg_id and msg_id in self._displayed_message_ids:
                # already displayed (optimistic insert or previous load)
                continue

            # Използваме skip_scroll=True за бързо вмъкване
            self._insert_message_to_history(data, skip_scroll=True)

            # Mark as displayed if id available
            if msg_id:
                try:
                    self._displayed_message_ids.add(msg_id)
                except Exception:
                    pass

        self.chat_history.configure(state="disabled")

        # Принудително обновяване, за да се гарантира, че съобщенията се показват
        self.chat_history.update_idletasks()
        self.chat_history.see(tk.END)
        print(f"[LOG] UI Update: Успешно вмъкнати {len(messages)} нови съобщения.")

    def _load_initial_history(self, col_snapshot):
        """Зарежда цялата история еднократно."""
        try:
            total = len(col_snapshot)
        except Exception:
            total = sum(1 for _ in col_snapshot)

        print(f"[LOG] UI Update: Започва зареждане на {total} съобщения в историята.")
        self.chat_history.configure(state="normal")
        self.chat_history.delete("1.0", tk.END)
        count = 0

        # Normalize snapshot items to dicts and sort by timestamp when possible
        docs = list(col_snapshot)

        def _ts_for(d):
            try:
                item = d.to_dict() if hasattr(d, "to_dict") else dict(d)
                ts = item.get("timestamp")
                if not ts:
                    return 0
                if hasattr(ts, "timestamp"):
                    return ts.timestamp()
                if hasattr(ts, "ToDatetime"):
                    return ts.ToDatetime().timestamp()
                if hasattr(ts, "seconds"):
                    return float(ts.seconds)
                return 0
            except Exception:
                return 0

        docs_sorted = sorted(docs, key=_ts_for)
        history_data = []
        for doc in docs_sorted:
            try:
                d = doc.to_dict()
            except Exception:
                try:
                    d = dict(doc)
                except Exception:
                    d = {}
            try:
                d["_id"] = getattr(doc, "id", None)
            except Exception:
                pass
            history_data.append(d)

        # Insert all messages via the UI updater so deduplication and tracking run consistently
        if history_data:
            self._update_ui_with_new_messages(history_data)
            count = len(history_data)

        self.chat_history.configure(state="disabled")
        self.chat_history.update_idletasks()  # Принудително обновяване
        self.chat_history.see(tk.END)
        print(
            f"[LOG] UI Update: Успешно заредени {count} съобщения. Скролиране до края."
        )

    def _insert_message_to_history(self, data, skip_scroll=False):
        """Вмъква съобщение в текстовото поле на чата."""
        username = data.get("username", "???")
        message_text = data.get("text", "")

        # Определяме тага за форматиране
        tag = "user_msg" if username == self.username else "other_msg"

        timestamp = data.get("timestamp")
        time_str = "[--:--]"

        # Handle various timestamp representations from Firestore
        if timestamp:
            try:
                # native python datetime
                if hasattr(timestamp, "strftime"):
                    dt = timestamp
                # protobuf Timestamp (google.protobuf.Timestamp)
                elif hasattr(timestamp, "ToDatetime"):
                    dt = timestamp.ToDatetime()
                # some SDKs return an object with .seconds
                elif hasattr(timestamp, "seconds"):
                    dt = datetime.fromtimestamp(timestamp.seconds, tz=timezone.utc)
                else:
                    dt = None

                if dt:
                    # display local time if possible (UTC fallback)
                    time_str = f"[{dt.strftime('%H:%M')}]"
            except Exception:
                time_str = "[--:--]"

        # --- ДОБАВЕН ЛОГ ---
        print(
            f"[LOG] UI Insert: Вмъкване на съобщение от {username}: '{message_text[:20]}...'"
        )
        # --- КРАЙ НА ДОБАВЕН ЛОГ ---

        # Вмъкваме частта с времето и името с тага
        self.chat_history.insert(tk.END, f"{time_str} {username}: ", tag)
        # Вмъкваме текста на съобщението без таг (за да остане в основния цвят)
        self.chat_history.insert(tk.END, f"{message_text}\n")

        if not skip_scroll:
            self.chat_history.update_idletasks()
            self.chat_history.see(tk.END)


if __name__ == "__main__":
    app = AuthApp()
    try:
        app.mainloop()
    except Exception as e:
        print(f"Критична грешка в основния цикъл: {e}")
        app.on_closing()
