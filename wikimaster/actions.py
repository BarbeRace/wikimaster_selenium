"""Fonctions utilitaires Wiki Masters.

Chaque fonction prend un `log` (callable str -> None) optionnel et retourne
un résultat simple. Pour ajouter une action : écrire la fonction ici, puis
l'ajouter à la liste ACTIONS en bas de fichier (un bouton apparaîtra dans l'UI).
"""

import re
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


SELECTION_ON_XPATH = "//button[contains(normalize-space(), 'Quitter la sélection')]"


def _pill_xpath(rarity: str) -> str:
    return f"//button[normalize-space()='{rarity}']"


def _rarity_pill(rarity: str):
    # Sur une fenêtre étroite, les pastilles sont masquées derrière le menu « Rareté »
    if not any(p.is_displayed() for p in browser.get_driver().find_elements(By.XPATH, _pill_xpath(rarity))):
        click((By.XPATH, "//button[normalize-space()='Rareté']"))
    return wait_for((By.XPATH, _pill_xpath(rarity)))


def _is_selected(pill) -> bool:
    # Les pastilles non sélectionnées sont atténuées (opacity-50)
    return "opacity-50" not in pill.get_attribute("class")


def cartes_rarete(rarity: str, rarity_label: str, log: Log = _noop) -> None:
    """Va sur la collection : rareté donnée, sans étiquette, mode sélection activé.

    `rarity` est le libellé de la pastille (C, PC, R...), `rarity_label` le nom affiché dans les logs.
    """
    driver = browser.get_driver()
    go_to("/collection", log)
    pill = _rarity_pill(rarity)

    reset = driver.find_elements(By.XPATH, "//button[contains(normalize-space(), 'Réinitialiser rareté')]")
    if reset:  # un autre filtre de rareté est déjà actif
        reset[0].click()
        pill = _rarity_pill(rarity)
    if not _is_selected(pill):
        pill.click()

    WebDriverWait(driver, config.DEFAULT_TIMEOUT).until(
        lambda d: _is_selected(d.find_element(By.XPATH, _pill_xpath(rarity)))
        and d.find_elements(By.XPATH, "//button[contains(normalize-space(), 'Réinitialiser rareté')]")
    )
    log(f"Filtre rareté : {rarity_label}")

    label_dropdown = driver.find_element(By.CSS_SELECTOR, "button[aria-haspopup=listbox]")
    if label_dropdown.text.strip() != "Sans étiquette":
        label_dropdown.click()
        click((By.XPATH, "//*[@role='option'][contains(normalize-space(), 'Sans étiquette')]"))
        WebDriverWait(driver, config.DEFAULT_TIMEOUT).until(
            lambda d: d.find_element(By.CSS_SELECTOR, "button[aria-haspopup=listbox]").text.strip()
            == "Sans étiquette"
        )
    log("Filtre étiquette : Sans étiquette")

    _ensure_selection_mode()
    log("Mode sélection activé")


def cartes_communes(log: Log = _noop) -> None:
    """Va sur la collection : rareté Commune, sans étiquette, mode sélection activé."""
    cartes_rarete("C", "Commune", log)


def _ensure_selection_mode() -> None:
    # Le site désactive le mode sélection après un étiquetage : on le réactive si besoin
    driver = browser.get_driver()
    if not driver.find_elements(By.XPATH, SELECTION_ON_XPATH):
        click((By.XPATH, "//button[normalize-space()='Sélectionner']"))
        wait_for((By.XPATH, SELECTION_ON_XPATH))


def close_browser(log: Log = _noop) -> None:
    browser.close_driver()
    log("Navigateur fermé")


DEFAUSSE_LABEL = "Defausse"
CARD_SELECTOR = "[class*='glow-']"  # une carte de collection (classe glow-<rareté>, h3 = titre, p = description)
CARDS_PER_PAGE = 50
MAX_ROUNDS = 200  # garde-fou contre une boucle infinie


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


NAV_BUTTON_XPATH = "//button[contains(., 'Suivant') or contains(., 'Précédent')]"


def _page_info(driver) -> tuple[int, int] | None:
    """(page courante, nombre de pages) d'après « Page X / Y », None si rien n'est affiché.

    Avec une seule page, le site n'affiche ni « Page X / Y » ni boutons de navigation : on renvoie (1, 1).
    """
    match = re.search(r"Page (\d+) / (\d+)", driver.find_element(By.TAG_NAME, "body").text)
    if match:
        return int(match[1]), int(match[2])
    if driver.find_elements(By.XPATH, NAV_BUTTON_XPATH) or not _snapshot(driver):
        return None
    return 1, 1


def _go_to_page(driver, target: int) -> bool:
    """Va à la page `target` avec Suivant/Précédent. Retourne False si elle n'existe pas."""
    info = _page_info(driver)
    if info is None:
        return False
    current, last = info
    if not 1 <= target <= last:
        return False
    while current != target:
        step = 1 if target > current else -1
        keyword = "Suivant" if step > 0 else "Précédent"
        buttons = [b for b in driver.find_elements(By.TAG_NAME, "button") if keyword in b.text]
        if not buttons or not buttons[0].is_enabled():
            return False
        before = _snapshot(driver)
        _click_element(buttons[0])
        expected = current + step
        try:
            WebDriverWait(driver, config.DEFAULT_TIMEOUT).until(
                lambda d: (_page_info(d) or (0, 0))[0] == expected and _snapshot(d) != before
            )
        except TimeoutException:
            return False
        current = expected
    return True


def _click_element(element: WebElement) -> None:
    # Un élément en bas de la vue passe sous la barre d'outils fixe : on le recentre d'abord
    browser.get_driver().execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
    element.click()


def _apply_label() -> None:
    click((By.XPATH, "//button[normalize-space()='Étiqueter']"))
    click((By.XPATH, f"//button[normalize-space()='{DEFAUSSE_LABEL}']"))
    _close_label_modal()
    _restart_selection_mode()


def _close_label_modal() -> None:
    # La modale « Appliquer une étiquette » peut rester ouverte : elle masquerait les cartes suivantes
    driver = browser.get_driver()
    overlay_gone = lambda d: not d.find_elements(By.CSS_SELECTOR, ".fixed.inset-0")
    try:
        WebDriverWait(driver, config.DEFAULT_TIMEOUT).until(overlay_gone)
    except TimeoutException:
        close = driver.find_elements(By.CSS_SELECTOR, ".fixed.inset-0 button[aria-label='Fermer']")
        if close:
            driver.execute_script("arguments[0].click();", close[0])
        WebDriverWait(driver, config.DEFAULT_TIMEOUT).until(overlay_gone)


def _close_overlay() -> None:
    driver = browser.get_driver()
    for button in driver.find_elements(By.CSS_SELECTOR, ".fixed.inset-0 button[aria-label='Fermer']"):
        button.click()
    WebDriverWait(driver, config.DEFAULT_TIMEOUT).until(
        lambda d: not d.find_elements(By.CSS_SELECTOR, ".fixed.inset-0")
    )


def _restart_selection_mode() -> None:
    # Après un étiquetage, « Quitter la sélection » reste affiché mais le mode est inactif :
    # un clic sur une carte ouvrirait alors la modale d'étiquetage. On le désactive puis réactive.
    driver = browser.get_driver()
    if driver.find_elements(By.XPATH, SELECTION_ON_XPATH):
        click((By.XPATH, SELECTION_ON_XPATH))
        WebDriverWait(driver, config.DEFAULT_TIMEOUT).until(
            lambda d: not d.find_elements(By.XPATH, SELECTION_ON_XPATH)
        )
    _ensure_selection_mode()


def defausse_rarete(rarity: str, rarity_label: str, log: Log = _noop) -> int:
    """Étiquette « Defausse » les cartes d'une rareté sans mot-clé (titre ou description), sur toutes les pages.

    Les cartes conservées restent dans la vue « Sans étiquette » et la liste se raccourcit à chaque
    étiquetage : on ne passe donc pas simplement à la page suivante, on repart de la première carte
    non traitée (sinon des cartes seraient sautées). Pas de vérification de l'affichage après étiquetage.
    La fonction s'arrête quand la page demandée n'existe plus. Retourne le nombre de cartes étiquetées.
    """
    keywords = _load_keywords()
    cartes_rarete(rarity, rarity_label, log)
    driver = browser.get_driver()
    try:
        WebDriverWait(driver, config.DEFAULT_TIMEOUT).until(
            lambda d: _page_info(d) is not None and _snapshot(d)
        )
    except TimeoutException:
        log("Aucune carte commune affichée")
        return 0

    total = 0
    kept = 0  # cartes conservées : elles occupent toujours le début de la liste
    previous: list[str] | None = None  # liste avant le dernier étiquetage
    for _ in range(MAX_ROUNDS):
        if previous is not None:
            # Attend le rafraîchissement de la liste après étiquetage (la liste se raccourcit)
            try:
                WebDriverWait(driver, config.DEFAULT_TIMEOUT).until(lambda d: _snapshot(d) != previous)
            except TimeoutException:
                log("L'affichage ne s'est pas mis à jour après étiquetage : relance le bouton")
                break
        page, offset = kept // CARDS_PER_PAGE + 1, kept % CARDS_PER_PAGE
        if not _go_to_page(driver, page):
            log("Fin : la page suivante n'existe plus")
            break
        texts = _snapshot(driver)
        if len(texts) <= offset:
            log("Fin : plus de cartes à traiter")
            break
        to_label = [i for i, text in enumerate(texts) if not _has_keyword(text, keywords)]
        if to_label:
            _ensure_selection_mode()
            cards = driver.find_elements(By.CSS_SELECTOR, CARD_SELECTOR)
            for i in to_label:
                _click_element(cards[i])
                # Un clic peut ouvrir une modale d'étiquetage « 1 carte » : on la ferme, la sélection reste
                if driver.find_elements(By.CSS_SELECTOR, ".fixed.inset-0"):
                    _close_overlay()
            if _selected_count(driver) != len(to_label):
                raise RuntimeError("La sélection des cartes a échoué")
            _apply_label()
            previous = texts
            total += len(to_label)
            log(f"Page {page} : {len(to_label)} carte(s) étiquetée(s) « {DEFAUSSE_LABEL} »")
        kept = (page - 1) * CARDS_PER_PAGE + len(texts) - len(to_label)
    log(f"Terminé : {total} carte(s) étiquetée(s) « {DEFAUSSE_LABEL} »")
    return total


def defausse_communes(log: Log = _noop) -> int:
    """Défausse les cartes communes sans mot-clé, sur toutes les pages."""
    return defausse_rarete("C", "Commune", log)


def defausse_peu_communes(log: Log = _noop) -> int:
    """Défausse les cartes peu communes sans mot-clé, sur toutes les pages."""
    return defausse_rarete("PC", "Peu commune", log)


def defausse_rares(log: Log = _noop) -> int:
    """Défausse les cartes rares sans mot-clé, sur toutes les pages."""
    return defausse_rarete("R", "Rare", log)


# (libellé du bouton, fonction)
ACTIONS: list[tuple[str, Callable[[Log], object]]] = [
    ("Se connecter", login),
    ("Cartes communes", cartes_communes),
    ("Défausse communes", defausse_communes),
    ("Défausse peu communes", defausse_peu_communes),
    ("Défausse rares", defausse_rares),
    ("Fermer le navigateur", close_browser),
]
