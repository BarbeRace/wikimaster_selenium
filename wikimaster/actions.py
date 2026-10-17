"""Fonctions utilitaires Wiki Masters.

Chaque fonction prend un `log` (callable str -> None) optionnel et retourne
un résultat simple. Pour ajouter une action : écrire la fonction ici, puis
l'ajouter à la liste ACTIONS en bas de fichier (un bouton apparaîtra dans l'UI).
"""

import unicodedata
from collections.abc import Callable

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from . import browser, config

Log = Callable[[str], None]


def _noop(_: str) -> None:
    pass


def wait_for(locator: tuple[str, str], timeout: float = config.DEFAULT_TIMEOUT) -> WebElement:
    """Attend qu'un élément soit visible et le retourne."""
    return WebDriverWait(browser.get_driver(), timeout).until(
        EC.visibility_of_element_located(locator)
    )


def click(locator: tuple[str, str], timeout: float = config.DEFAULT_TIMEOUT) -> None:
    WebDriverWait(browser.get_driver(), timeout).until(
        EC.element_to_be_clickable(locator)
    ).click()


def go_to(path: str, log: Log = _noop) -> None:
    """Navigue vers un chemin relatif du site (ex: '/collection')."""
    url = config.BASE_URL.rstrip("/") + "/" + path.lstrip("/")
    browser.get_driver().get(url)
    log(f"Navigation : {url}")


def login(log: Log = _noop, wait_user: float = 180) -> None:
    """Pré-remplit le formulaire de connexion (identifiants du .env).

    Cloudflare impose une case à cocher manuelle : l'utilisateur coche la case
    puis clique sur « Connexion ». On attend ensuite la redirection.
    """
    email_value, password_value = config.get_credentials()
    if not email_value or not password_value:
        raise RuntimeError("Identifiants manquants : renseigne le fichier .env")

    driver = browser.get_driver()
    driver.get(config.LOGIN_URL)
    try:
        email = wait_for((By.CSS_SELECTOR, "input[type=email]"), timeout=6)
    except TimeoutException:
        log("Déjà connecté, rien à faire")
        return
    email.clear()
    email.send_keys(email_value)
    password = driver.find_element(By.CSS_SELECTOR, "input[type=password]")
    password.clear()
    password.send_keys(password_value)
    log("Champs pré-remplis : coche la case Cloudflare puis clique sur « Connexion »")

    try:
        WebDriverWait(driver, wait_user).until(lambda d: "/login" not in d.current_url)
    except TimeoutException:
        raise RuntimeError("Connexion non effectuée dans le délai imparti") from None
    log("Connexion réussie")


def _rarity_pill(rarity: str):
    return wait_for((By.XPATH, f"//button[normalize-space()='{rarity}']"))


def _is_selected(pill) -> bool:
    # Les pastilles non sélectionnées sont atténuées (opacity-50)
    return "opacity-50" not in pill.get_attribute("class")


def cartes_communes(log: Log = _noop) -> None:
    """Va sur la collection : rareté Commune, sans étiquette, mode sélection activé."""
    driver = browser.get_driver()
    go_to("/collection", log)
    pill = _rarity_pill("C")

    reset = driver.find_elements(By.XPATH, "//button[contains(normalize-space(), 'Réinitialiser rareté')]")
    if reset:  # un autre filtre de rareté est déjà actif
        reset[0].click()
        pill = _rarity_pill("C")
    if not _is_selected(pill):
        pill.click()

    WebDriverWait(driver, config.DEFAULT_TIMEOUT).until(
        lambda d: _is_selected(_rarity_pill("C"))
        and d.find_elements(By.XPATH, "//button[contains(normalize-space(), 'Réinitialiser rareté')]")
    )
    log("Filtre rareté : Commune")

    label_dropdown = driver.find_element(By.CSS_SELECTOR, "button[aria-haspopup=listbox]")
    if label_dropdown.text.strip() != "Sans étiquette":
        label_dropdown.click()
        click((By.XPATH, "//*[@role='option'][contains(normalize-space(), 'Sans étiquette')]"))
        WebDriverWait(driver, config.DEFAULT_TIMEOUT).until(
            lambda d: d.find_element(By.CSS_SELECTOR, "button[aria-haspopup=listbox]").text.strip()
            == "Sans étiquette"
        )
    log("Filtre étiquette : Sans étiquette")

    if not driver.find_elements(By.XPATH, "//button[contains(normalize-space(), 'Quitter la sélection')]"):
        click((By.XPATH, "//button[normalize-space()='Sélectionner']"))
        wait_for((By.XPATH, "//button[contains(normalize-space(), 'Quitter la sélection')]"))
    log("Mode sélection activé")


def close_browser(log: Log = _noop) -> None:
    browser.close_driver()
    log("Navigateur fermé")


DEFAUSSE_LABEL = "Defausse"
CARD_SELECTOR = ".glow-c"  # une carte de collection (h3 = titre, p = description)


def _normalize(text: str) -> str:
    """Minuscules sans accents, pour comparer les textes."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def _load_keywords() -> list[str]:
    path = config.DEFAUSSE_KEYWORDS_FILE
    if not path.exists():
        raise FileNotFoundError(f"Fichier de mots-clés introuvable : {path}")
    words = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            words.append(_normalize(line))
    if not words:
        raise RuntimeError(f"Aucun mot-clé dans {path.name}")
    return words


def _snapshot(driver) -> list[str]:
    """Titre + description de chaque carte affichée, normalisés."""
    texts = driver.execute_script(
        "return [...document.querySelectorAll(arguments[0])].map(c => "
        "[...c.querySelectorAll('h3, p')].map(e => e.textContent).join(' '))",
        CARD_SELECTOR,
    )
    return [_normalize(t) for t in texts]


def _has_keyword(text: str, keywords: list[str]) -> bool:
    return any(word in text for word in keywords)


def _selected_count(driver) -> int:
    # Une carte sélectionnée a un anneau (ring-4) dans son conteneur
    return driver.execute_script(
        "return [...document.querySelectorAll(arguments[0])]"
        ".filter(c => c.parentElement.querySelector('.ring-4')).length",
        CARD_SELECTOR,
    )


def _click_card(card: WebElement) -> None:
    # Une carte en bas de la vue passe sous la barre d'outils fixe : on la recentre d'abord
    browser.get_driver().execute_script("arguments[0].scrollIntoView({block: 'center'});", card)
    card.click()


def _apply_label() -> None:
    click((By.XPATH, "//button[normalize-space()='Étiqueter']"))
    click((By.XPATH, f"//button[normalize-space()='{DEFAUSSE_LABEL}']"))


def defausse_communes(log: Log = _noop) -> int:
    """Étiquette « Defausse » les cartes communes de la page affichée, sans mot-clé (titre ou description).

    Une exécution traite une seule page : pour la suivante, on relance l'action.
    Aucune vérification de l'affichage après étiquetage.
    Retourne le nombre de cartes étiquetées.
    """
    keywords = _load_keywords()
    cartes_communes(log)
    driver = browser.get_driver()
    try:
        WebDriverWait(driver, config.DEFAULT_TIMEOUT).until(lambda d: _snapshot(d))
    except TimeoutException:
        log("Aucune carte commune affichée")
        return 0

    texts = _snapshot(driver)
    to_label = [i for i, text in enumerate(texts) if not _has_keyword(text, keywords)]
    if not to_label:
        log("Aucune carte à défausser sur cette page")
        return 0

    cards = driver.find_elements(By.CSS_SELECTOR, CARD_SELECTOR)
    for i in to_label:
        _click_card(cards[i])
    if _selected_count(driver) != len(to_label):
        raise RuntimeError("La sélection des cartes a échoué")
    _apply_label()
    log(f"{len(to_label)} carte(s) étiquetée(s) « {DEFAUSSE_LABEL} »")
    return len(to_label)


# (libellé du bouton, fonction)
ACTIONS: list[tuple[str, Callable[[Log], object]]] = [
    ("Se connecter", login),
    ("Cartes communes", cartes_communes),
    ("Défausse communes", defausse_communes),
    ("Fermer le navigateur", close_browser),
]
