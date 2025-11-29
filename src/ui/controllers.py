"""Application controller: wires services to the UI view and provides pagination.

This controller wraps an existing `AuthApp` instance and adds pagination
capabilities and a "Load older" control. It keeps a per-room cache of fetched
messages and tracks the Firestore paging cursors (DocumentSnapshot objects).
"""
import threading
from typing import Dict, List, Optional

import services.firestore_client as fc


class AppController:
    def __init__(self, app, page_size: int = 50):
        self.app = app
        self.page_size = page_size
        # per-room paging state
        self._last_doc_map: Dict[str, Optional[object]] = {}
        # per-room cached messages (list of dicts in ascending order)
        self._cache: Dict[str, List[dict]] = {}

        # attach UI button
        try:
            header = getattr(self.app, "chat_title_label", None)
            if header is not None:
                parent = header.master
                # add a small button to load older messages
                import customtkinter as ctk

                self._load_older_btn = ctk.CTkButton(
                    parent,
                    text="Зареди по-стари",
                    width=120,
                    command=self.load_older_for_current,
                )
                self._load_older_btn.grid(row=1, column=0, sticky="w", pady=(4, 0))
        except Exception:
            pass

        # Monkey-patch the app.switch_channel to notify controller
        try:
            orig_switch = self.app.switch_channel

            def wrapped_switch(new_channel):
                orig_switch(new_channel)
                try:
                    self.on_channel_switched(new_channel)
                except Exception:
                    pass

            self.app.switch_channel = wrapped_switch
        except Exception:
            pass

    def on_channel_switched(self, new_channel: str):
        # reset pagination state for the channel
        if new_channel not in self._cache:
            self._cache[new_channel] = []
            self._last_doc_map[new_channel] = None
        # load initial page
        threading.Thread(
            target=self.load_initial_page, args=(new_channel,), daemon=True
        ).start()

    def _room_id_for_channel(self, channel: str) -> Optional[str]:
        if channel == "lobby":
            return "lobby"
        return self.app.dm_list.get(channel) or self.app.get_dm_room_id(
            self.app.username, channel
        )

    def load_initial_page(self, channel: str):
        room_id = self._room_id_for_channel(channel)
        if room_id is None:
            return
        # Fetch newest messages first (descending) and reverse to display oldest->newest
        docs, last = fc.get_history_paginated(
            room_id, limit=self.page_size, start_after=None, direction="desc"
        )
        if not docs:
            # clear UI
            self.app.after(
                0,
                lambda: (
                    self.app.chat_history.configure(state="normal"),
                    self.app.chat_history.delete("1.0", "end"),
                    self.app.chat_history.configure(state="disabled"),
                ),
            )
            self._cache[channel] = []
            self._last_doc_map[channel] = None
            return

        # convert docs to dicts and reverse order
        msgs = []
        for d in docs:
            try:
                dd = d.to_dict()
            except Exception:
                try:
                    dd = dict(d)
                except Exception:
                    dd = {}
            try:
                dd["_id"] = getattr(d, "id", None)
            except Exception:
                pass
            msgs.append(dd)

        msgs = list(reversed(msgs))
        self._cache[channel] = msgs
        self._last_doc_map[channel] = last

        # render messages on UI thread
        self.app.after(
            0,
            lambda: (
                self.app.chat_history.configure(state="normal"),
                self.app.chat_history.delete("1.0", "end"),
                self.app._update_ui_with_new_messages(self._cache[channel]),
            ),
        )

    def load_older_for_current(self):
        channel = getattr(self.app, "current_channel", None)
        if not channel:
            return
        threading.Thread(target=lambda: self.load_older(channel), daemon=True).start()

    def load_older(self, channel: str):
        room_id = self._room_id_for_channel(channel)
        if room_id is None:
            return
        last = self._last_doc_map.get(channel)
        # If last is None and we have cache, it means there were less than a page fetched; no older available
        if last is None:
            return

        docs, new_last = fc.get_history_paginated(
            room_id, limit=self.page_size, start_after=last, direction="desc"
        )
        if not docs:
            # no more older messages
            self._last_doc_map[channel] = None
            return

        msgs = []
        for d in docs:
            try:
                dd = d.to_dict()
            except Exception:
                try:
                    dd = dict(d)
                except Exception:
                    dd = {}
            try:
                dd["_id"] = getattr(d, "id", None)
            except Exception:
                pass
            msgs.append(dd)

        msgs = list(reversed(msgs))
        # prepend to cache
        self._cache[channel] = msgs + self._cache.get(channel, [])
        self._last_doc_map[channel] = new_last

        # re-render full cache on UI thread
        self.app.after(
            0,
            lambda: (
                self.app.chat_history.configure(state="normal"),
                self.app.chat_history.delete("1.0", "end"),
                self.app._update_ui_with_new_messages(self._cache[channel]),
            ),
        )
