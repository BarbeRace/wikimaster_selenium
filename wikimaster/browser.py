"""Gestion du navigateur Chrome (session unique, partagée par les actions).

Chrome est lancé comme un Chrome normal (sans les drapeaux d'automatisation),
puis Selenium s'y attache via le port de debug. Cela évite que Cloudflare
Turnstile détecte un navigateur piloté.
"""

import os
import shutil
import socket
import subprocess
import time

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.remote.webdriver import WebDriver

from . import config

DEBUG_PORT = 9222

_driver: WebDriver | None = None
_chrome_process: subprocess.Popen | None = None


def _find_chrome() -> str:
    candidates = [
        os.environ.get("CHROME_PATH", ""),
        shutil.which("chrome") or "",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    raise FileNotFoundError("Chrome introuvable : définis la variable CHROME_PATH")


def _is_alive(driver: WebDriver) -> bool:
    try:
        _ = driver.current_url
        return True
    except WebDriverException:
        return False


def _launch_chrome() -> None:
    global _chrome_process
    config.PROFILE_DIR.mkdir(exist_ok=True)
    _chrome_process = subprocess.Popen([
        _find_chrome(),
        f"--remote-debugging-port={DEBUG_PORT}",
        f"--user-data-dir={config.PROFILE_DIR}",
        "--start-maximized",
        "--no-first-run",
        "--no-default-browser-check",
    ])


def _debug_port_open() -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", DEBUG_PORT)) == 0


def get_driver() -> WebDriver:
    """Retourne le driver courant, en le (re)créant si nécessaire.

    Selenium Manager (intégré à Selenium) télécharge automatiquement le bon
    chromedriver : aucune installation manuelle requise.
    """
    global _driver
    if _driver is None or not _is_alive(_driver):
        close_driver()
        if not _debug_port_open():  # sinon on réutilise le Chrome déjà lancé
            _launch_chrome()
        options = Options()
        options.debugger_address = f"127.0.0.1:{DEBUG_PORT}"
        last_error: WebDriverException | None = None
        for _ in range(10):  # laisse le temps à Chrome d'ouvrir son port
            try:
                _driver = webdriver.Chrome(options=options)
                break
            except WebDriverException as e:
                last_error = e
                time.sleep(1)
        else:
            raise RuntimeError(f"Impossible de se connecter à Chrome : {last_error}")
    return _driver


def close_driver() -> None:
    global _driver, _chrome_process
    if _driver is not None:
        try:
            _driver.quit()
        except WebDriverException:
            pass
        _driver = None
    if _chrome_process is not None:
        if _chrome_process.poll() is None:
            _chrome_process.terminate()
        _chrome_process = None
