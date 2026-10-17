"""Interface graphique (customtkinter) : un bouton par action de actions.ACTIONS."""

import threading
import traceback
from datetime import datetime

import customtkinter as ctk

from . import actions, browser


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title("Wiki Masters – Selenium")
        self.geometry("720x520")
        self.minsize(560, 400)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        sidebar = ctk.CTkFrame(self, width=220, corner_radius=12)
        sidebar.grid(row=0, column=0, padx=(16, 8), pady=16, sticky="ns")
        ctk.CTkLabel(
            sidebar, text="Actions", font=ctk.CTkFont(size=20, weight="bold")
        ).pack(padx=20, pady=(20, 10))

        self.buttons: list[ctk.CTkButton] = []
        for label, func in actions.ACTIONS:
            btn = ctk.CTkButton(
                sidebar, text=label, height=38, corner_radius=8,
                command=lambda f=func, n=label: self.run_action(n, f),
            )
            btn.pack(padx=20, pady=6, fill="x")
            self.buttons.append(btn)

        ctk.CTkButton(
            sidebar, text="Quitter", height=38, corner_radius=8,
            fg_color="#c0392b", hover_color="#962d22", command=self.on_close,
        ).pack(side="bottom", padx=20, pady=(6, 20), fill="x")
        log_frame = ctk.CTkFrame(self, corner_radius=12)
        log_frame.grid(row=0, column=1, padx=(8, 16), pady=16, sticky="nsew")
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(
            log_frame, text="Journal", font=ctk.CTkFont(size=20, weight="bold")
        ).grid(row=0, column=0, padx=16, pady=(16, 6), sticky="w")
        self.log_box = ctk.CTkTextbox(log_frame, state="disabled", wrap="word")
        self.log_box.grid(row=1, column=0, padx=16, pady=(0, 16), sticky="nsew")

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def log(self, message: str) -> None:
        stamp = f"{datetime.now():%H:%M:%S}"
        # after() rend l'appel sûr depuis un thread secondaire
        self.after(0, self._append, f"[{stamp}] {message}\n")

    def _append(self, text: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text)
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _set_busy(self, busy: bool) -> None:
        for b in self.buttons:
            b.configure(state="disabled" if busy else "normal")

    def run_action(self, name: str, func) -> None:
        self._set_busy(True)
        self.log(f"▶ {name}")

        def work() -> None:
            try:
                func(self.log)
                self.log(f"✔ {name} terminé")
            except NotImplementedError as e:
                self.log(f"⚠ {e}")
            except Exception as e:
                self.log(f"✖ Erreur : {e}")
                traceback.print_exc()
            finally:
                self.after(0, self._set_busy, False)

        threading.Thread(target=work, daemon=True).start()

    def on_close(self) -> None:
        browser.close_driver()
        self.destroy()


def run() -> None:
    App().mainloop()
