"""Interface graphique (customtkinter) : un bouton par action de actions.ACTIONS."""

import threading
import traceback
from datetime import datetime

import customtkinter as ctk

from . import actions, browser

UI_SCALE = 1.1  # taille des widgets et polices (1.0 = taille d'origine)
SUB_BUTTON_COLOR = "#2A78B5"  # sous-boutons de défausse, un ton plus clair que le bouton principal
SUB_BUTTON_HOVER_COLOR = "#3B8ED0"


class App(ctk.CTk):
    def __init__(self) -> None:
        ctk.set_widget_scaling(UI_SCALE)
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title("Wiki Masters – Selenium")
        self.geometry("1080x780")
        self.minsize(840, 600)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        sidebar = ctk.CTkFrame(self, width=220, corner_radius=12)
        sidebar.grid(row=0, column=0, padx=(16, 8), pady=16, sticky="ns")
        ctk.CTkLabel(
            sidebar, text="Actions", font=ctk.CTkFont(size=20, weight="bold")
        ).pack(padx=20, pady=(20, 10))

        self.buttons: list[ctk.CTkButton] = []
        for label, func in actions.ACTIONS:
            if label in actions.SUB_ACTIONS:
                self._add_group(sidebar, label, func, actions.SUB_ACTIONS[label])
            else:
                self._add_button(sidebar, label, label, func).pack(padx=20, pady=6, fill="x")

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

    def _add_button(self, parent, text: str, name: str, func, height: int = 38,
                    fg_color=None, hover_color=None) -> ctk.CTkButton:
        """Crée un bouton géré par l'interface (désactivé pendant l'exécution d'une action)."""
        btn = ctk.CTkButton(
            parent, text=text, height=height, corner_radius=8,
            fg_color=fg_color, hover_color=hover_color,
            command=lambda: self.run_action(name, func),
        )
        self.buttons.append(btn)
        return btn

    @staticmethod
    def _square_side(btn: ctk.CTkButton, side: str, bg) -> None:
        """Rend carrés les coins d'un côté du bouton (« right » ou « left ») pour le raccorder au voisin."""
        fg = btn.cget("fg_color")
        square_tags = (
            ("background_corner_top_right", "background_corner_bottom_right")
            if side == "right"
            else ("background_corner_top_left", "background_corner_bottom_left")
        )
        btn.configure(
            background_corner_colors=(bg, fg, fg, bg) if side == "right" else (fg, bg, bg, fg)
        )

        # Pas de configure() ici : il redessine le bouton et écrase la couleur de survol de CTk
        def paint(color) -> None:
            resolved = btn._apply_appearance_mode(color)
            for tag in square_tags:
                btn._canvas.itemconfig(tag, fill=resolved)

        btn.bind("<Enter>", lambda _e: paint(btn.cget("hover_color")))
        btn.bind("<Leave>", lambda _e: paint(fg))

    def _add_group(self, parent, label: str, func, subs) -> None:
        """Bouton principal suivi d'un chevron qui déplie la liste des sous-actions."""
        bg = parent.cget("fg_color")
        group = ctk.CTkFrame(parent, fg_color="transparent")
        group.pack(padx=20, pady=6, fill="x")
        row = ctk.CTkFrame(group, fg_color="transparent")
        row.pack(fill="x")
        # Le chevron est empaqueté en premier à droite, pour garder sa place quand le bouton principal s'étire
        chevron = ctk.CTkButton(
            row, text="▸", width=38, height=38, corner_radius=8,
            font=ctk.CTkFont(size=22),
        )
        chevron.pack(side="right", padx=(2, 0))
        self._square_side(chevron, "left", bg)
        self.buttons.append(chevron)
        main = self._add_button(row, label, label, func)
        main.pack(side="left", fill="x", expand=True)
        self._square_side(main, "right", bg)

        sub_frame = ctk.CTkFrame(group, fg_color="transparent")
        for sub_label, sub_func in subs:
            self._add_button(
                sub_frame, sub_label, f"{label} {sub_label.lower()}", sub_func, height=34,
                fg_color=SUB_BUTTON_COLOR, hover_color=SUB_BUTTON_HOVER_COLOR,
            ).pack(padx=(16, 0), pady=3, fill="x")

        opened = False

        def toggle() -> None:
            nonlocal opened
            opened = not opened
            if opened:
                sub_frame.pack(fill="x")
            else:
                sub_frame.pack_forget()
            chevron.configure(text="▾" if opened else "▸")

        chevron.configure(command=toggle)

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
