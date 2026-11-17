"""Fonctions utilitaires Wiki Masters.

Chaque fonction prend un `log` (callable str -> None) optionnel et retourne
un résultat simple. Pour ajouter une action : écrire la fonction ici, puis
l'ajouter à la liste ACTIONS en bas de fichier (un bouton apparaîtra dans l'UI).
"""

import csv
import json
import re
import statistics
import time
import unicodedata
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from . import api, browser, config

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


RARITY_RESET_XPATH = "//button[contains(normalize-space(), 'Réinitialiser rareté')]"


def cartes_rarete(rarity: str | None, rarity_label: str, log: Log = _noop) -> None:
    """Va sur la collection : rareté donnée (None = toutes les raretés), sans étiquette, mode sélection activé.

    `rarity` est le libellé de la pastille (C, PC, R...), `rarity_label` le nom affiché dans les logs.
    """
    driver = browser.get_driver()
    go_to("/collection", log)
    reset = driver.find_elements(By.XPATH, RARITY_RESET_XPATH)
    if reset:  # un filtre de rareté est déjà actif : on le réinitialise
        reset[0].click()
        WebDriverWait(driver, config.DEFAULT_TIMEOUT).until(
            lambda d: not d.find_elements(By.XPATH, RARITY_RESET_XPATH)
        )
    if rarity is not None:
        pill = _rarity_pill(rarity)
        if not _is_selected(pill):
            pill.click()
        WebDriverWait(driver, config.DEFAULT_TIMEOUT).until(
            lambda d: _is_selected(d.find_element(By.XPATH, _pill_xpath(rarity)))
            and d.find_elements(By.XPATH, RARITY_RESET_XPATH)
        )
    log(f"Filtre rareté : {rarity_label}")

    label_dropdown = wait_for((By.CSS_SELECTOR, "button[aria-haspopup=listbox]"))
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
AFRIQUE_LABEL = "Afrique & co"
OISEAUX_LABEL = "Oiseau"
REPTILES_LABEL = "Reptiles"
CUISINE_LABEL = "Cuisine"
ANIMAL_LABEL = "Animal"  # posée en plus de l'étiquette de sous-catégorie (oiseaux, reptiles)
CARD_SELECTOR = "[class*='glow-']"  # une carte de collection (classe glow-<rareté>, h3 = titre, p = description)
CARDS_PER_PAGE = 50
MAX_ROUNDS = 200  # garde-fou contre une boucle infinie
MAX_ATTEMPTS = 3  # nombre de passes (avec rafraîchissement) si le site ne répond plus pendant l'étiquetage


def _normalize(text: str) -> str:
    """Minuscules sans accents, pour comparer les textes."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def _load_keywords(path: Path) -> list[str]:
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


def _apply_label(label: str, timeout: float = config.LABEL_LIST_TIMEOUT) -> None:
    click((By.XPATH, "//button[normalize-space()='Étiqueter']"), timeout)
    click((By.XPATH, f"//button[normalize-space()='{label}']"), timeout)
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


def _tag_collection(rarity: str | None, rarity_label: str, keywords_file: Path,
                    tag_if_match: bool, tag: str, log: Log = _noop) -> int:
    """Étiquette `tag` les cartes (titre ou description) selon la présence d'un mot-clé, sur toutes les pages.

    Si `tag_if_match` est True, on étiquette les cartes qui contiennent un mot-clé, sinon celles qui n'en contiennent pas.
    `rarity` None = toutes les raretés.

    Si le site ne répond plus pendant l'étiquetage (liste d'étiquettes absente, affichage figé), la page est
    rafraîchie et la fonction repart de la collection, jusqu'à MAX_ATTEMPTS passes. Les cartes déjà étiquetées
    ne sont plus dans « Sans étiquette », elles ne sont donc pas retraitées.
    Retourne le nombre de cartes étiquetées.
    """
    keywords = _load_keywords(keywords_file)
    total = 0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        labeled, finished = _tag_pass(rarity, rarity_label, keywords, tag_if_match, tag, log)
        total += labeled
        if finished:
            log(f"Terminé : {total} carte(s) étiquetée(s) « {tag} »")
            return total
        if attempt < MAX_ATTEMPTS:
            log(f"Rafraîchissement de la page, relance (tentative {attempt + 1}/{MAX_ATTEMPTS})")
            browser.get_driver().refresh()
    raise RuntimeError(f"Le site ne répond pas après {MAX_ATTEMPTS} tentatives")


def _tag_pass(rarity: str | None, rarity_label: str, keywords: list[str], tag_if_match: bool,
              tag: str, log: Log) -> tuple[int, bool]:
    """Une passe d'étiquetage depuis la collection. Retourne (cartes étiquetées, passe terminée).

    Les cartes conservées restent dans la vue « Sans étiquette » et la liste se raccourcit à chaque
    étiquetage : on ne passe donc pas simplement à la page suivante, on repart de la première carte
    non traitée (sinon des cartes seraient sautées). Pas de vérification de l'affichage après étiquetage.
    La passe s'arrête quand la page demandée n'existe plus.
    """
    cartes_rarete(rarity, rarity_label, log)
    driver = browser.get_driver()
    try:
        WebDriverWait(driver, config.DEFAULT_TIMEOUT).until(
            lambda d: _page_info(d) is not None and _snapshot(d)
        )
    except TimeoutException:
        log("Aucune carte affichée")
        return 0, True

    total = 0
    kept = 0  # cartes conservées : elles occupent toujours le début de la liste
    previous: list[str] | None = None  # liste avant le dernier étiquetage
    for _ in range(MAX_ROUNDS):
        if previous is not None:
            # Attend le rafraîchissement de la liste après étiquetage (la liste se raccourcit)
            try:
                WebDriverWait(driver, config.LABEL_LIST_TIMEOUT).until(lambda d: _snapshot(d) != previous)
            except TimeoutException:
                log("L'affichage ne s'est pas mis à jour après étiquetage")
                return total, False
        page, offset = kept // CARDS_PER_PAGE + 1, kept % CARDS_PER_PAGE
        if not _go_to_page(driver, page):
            log("Fin : la page suivante n'existe plus")
            break
        texts = _snapshot(driver)
        if len(texts) <= offset:
            log("Fin : plus de cartes à traiter")
            break
        to_label = [i for i, text in enumerate(texts) if _has_keyword(text, keywords) == tag_if_match]
        if to_label:
            try:
                _ensure_selection_mode()
                cards = driver.find_elements(By.CSS_SELECTOR, CARD_SELECTOR)
                for i in to_label:
                    _click_element(cards[i])
                    # Un clic peut ouvrir une modale d'étiquetage « 1 carte » : on la ferme, la sélection reste
                    if driver.find_elements(By.CSS_SELECTOR, ".fixed.inset-0"):
                        _close_overlay()
                if _selected_count(driver) != len(to_label):
                    raise RuntimeError("La sélection des cartes a échoué")
                _apply_label(tag)
            except TimeoutException:
                log("Le site ne répond pas (liste d'étiquettes absente)")
                return total, False
            previous = texts
            total += len(to_label)
            log(f"Page {page} : {len(to_label)} carte(s) étiquetée(s) « {tag} »")
        kept = (page - 1) * CARDS_PER_PAGE + len(texts) - len(to_label)
    return total, True


def defausse_rarete(rarity: str, rarity_label: str, log: Log = _noop) -> int:
    """Étiquette « Defausse » les cartes d'une rareté sans mot-clé, sur toutes les pages."""
    return _tag_collection(rarity, rarity_label, config.DEFAUSSE_KEYWORDS_FILE, False, DEFAUSSE_LABEL, log)


def defausse_communes(log: Log = _noop) -> int:
    """Défausse les cartes communes sans mot-clé, sur toutes les pages."""
    return defausse_rarete("C", "Commune", log)


def defausse_peu_communes(log: Log = _noop) -> int:
    """Défausse les cartes peu communes sans mot-clé, sur toutes les pages."""
    return defausse_rarete("PC", "Peu commune", log)


def defausse_rares(log: Log = _noop) -> int:
    """Défausse les cartes rares sans mot-clé, sur toutes les pages."""
    return defausse_rarete("R", "Rare", log)


def defausse_tout(log: Log = _noop) -> int:
    """Lance la défausse communes, puis peu communes, puis rares, avec un rafraîchissement entre chaque."""
    total = 0
    steps = [defausse_communes, defausse_peu_communes, defausse_rares]
    for index, step in enumerate(steps):
        if index > 0:
            time.sleep(1)
            browser.get_driver().refresh()
        total += step(log)
    log(f"Défausse complète terminée : {total} carte(s) étiquetée(s) au total")
    return total


API_RARITIES = [("C", "Commune"), ("PC", "Peu commune"), ("R", "Rare")]
API_MAX_SWEEPS = 5  # relectures maximum d'une collection pour une fonction
API_MAX_PAGES = 100  # garde-fou : pages lues par relecture
API_RETRIES = 3


def _api_retry(func, *args):
    """Rejoue un appel API en cas d'erreur réseau/serveur passagère."""
    for attempt in range(1, API_RETRIES + 1):
        try:
            return func(*args)
        except (api.ApiError, TimeoutException, OSError) as error:
            if attempt == API_RETRIES:
                raise
            time.sleep(2 * attempt)


def _tag_collection_api(rarities: list[tuple[str | None, str]], keywords_file: Path, tag_if_match: bool,
                        tags: tuple[str, ...], log: Log, dry_run: bool = False,
                        labeled_ids: set[str] | None = None) -> int:
    """Étiquette `tags` via l'API les cartes sans étiquette selon la présence d'un mot-clé (titre ou description).

    Lit la collection sans étiquette (/api/my-collection) et pose les étiquettes (table Supabase user_card_tags).
    `rarities` : liste de (code rareté ou None pour toutes, nom affiché).
    `labeled_ids` : cartes déjà étiquetées pendant la même exécution (partagé par « Tag » : une carte n'est jamais retouchée).
    `dry_run` : compte sans rien écrire.
    """
    keywords = _load_keywords(keywords_file)
    go_to("/collection", log)  # session connectée et jeton à jour
    tag_ids = [_api_retry(api.get_tag_id, tag) for tag in tags]
    names = " + ".join(f"« {tag} »" for tag in tags)
    verb = "à étiqueter" if dry_run else "étiquetée(s)"
    handled = set() if labeled_ids is None else labeled_ids
    kept: set[str] = set()  # cartes sans mot-clé pour cette fonction (restent disponibles pour les suivantes)
    total = 0
    for rarity, rarity_label in rarities:
        rarity_total = _api_sweep(rarity, keywords, tag_if_match, tag_ids, dry_run, handled, kept, log)
        log(f"{rarity_label} : {rarity_total} carte(s) {verb} {names}")
        total += rarity_total
    log(f"Terminé (API) : {total} carte(s) {verb} {names} au total")
    return total


def defausse_api(log: Log = _noop, dry_run: bool = False) -> int:
    """Comme « Défausse » (communes, peu communes, rares), mais via l'API du site : sans clics ni pages à charger."""
    return _tag_collection_api(API_RARITIES, config.DEFAUSSE_KEYWORDS_FILE, False, (DEFAUSSE_LABEL,), log, dry_run)


def tag_afrique_api(log: Log = _noop, dry_run: bool = False, labeled_ids: set[str] | None = None) -> int:
    """Étiquette « Afrique & co » via l'API les cartes sans étiquette (toutes raretés) à mot-clé africain."""
    return _tag_collection_api([(None, "Toutes raretés")], config.TAG_AFRIQUE_KEYWORDS_FILE, True, (AFRIQUE_LABEL,),
                               log, dry_run, labeled_ids)


def tag_oiseaux_api(log: Log = _noop, dry_run: bool = False, labeled_ids: set[str] | None = None) -> int:
    """Étiquette « Oiseau » et « Animal » via l'API les cartes sans étiquette (toutes raretés) contenant un mot-clé d'oiseaux."""
    return _tag_collection_api([(None, "Toutes raretés")], config.TAG_OISEAUX_KEYWORDS_FILE, True,
                               (OISEAUX_LABEL, ANIMAL_LABEL), log, dry_run, labeled_ids)


def tag_reptiles_api(log: Log = _noop, dry_run: bool = False, labeled_ids: set[str] | None = None) -> int:
    """Étiquette « Reptiles » et « Animal » via l'API les cartes sans étiquette (toutes raretés) contenant un mot-clé de reptiles."""
    return _tag_collection_api([(None, "Toutes raretés")], config.TAG_REPTILES_KEYWORDS_FILE, True,
                               (REPTILES_LABEL, ANIMAL_LABEL), log, dry_run, labeled_ids)


def tag_cuisine_api(log: Log = _noop, dry_run: bool = False, labeled_ids: set[str] | None = None) -> int:
    """Étiquette « Cuisine » via l'API les cartes sans étiquette (toutes raretés) contenant un mot-clé de cuisine."""
    return _tag_collection_api([(None, "Toutes raretés")], config.TAG_CUISINE_KEYWORDS_FILE, True,
                               (CUISINE_LABEL,), log, dry_run, labeled_ids)


def tag_tout_api(log: Log = _noop) -> int:
    """Lance successivement chaque « Tag xxx API » : afrique, oiseaux, reptiles, cuisine.

    Une carte étiquetée par une étape n'est plus retouchée par les suivantes.
    """
    labeled_ids: set[str] = set()
    total = 0
    steps = [tag_afrique_api, tag_oiseaux_api, tag_reptiles_api, tag_cuisine_api]
    for step in steps:
        total += step(log, labeled_ids=labeled_ids)
    log(f"Tags API terminés : {total} carte(s) étiquetée(s) au total")
    return total


def _fetch_untagged(rarity: str | None) -> list[dict]:
    """Toutes les cartes sans étiquette (toutes pages), lues en entier avant toute écriture."""
    items: list[dict] = []
    for page in range(API_MAX_PAGES):
        batch = _api_retry(api.fetch_collection, rarity, page)
        if not batch:
            break
        items.extend(batch)
        time.sleep(api.REQUEST_PAUSE)
    return items


def _api_sweep(rarity: str | None, keywords: list[str], tag_if_match: bool, tag_ids: list[str], dry_run: bool,
               labeled_ids: set[str], kept: set[str], log: Log = _noop) -> int:
    """Étiquette les cartes qui matchent, sans jamais retraiter une carte déjà vue.

    Le site peut renvoyer avec retard des cartes déjà étiquetées : `labeled_ids` et `kept` les filtrent.
    On relit la collection tant qu'une lecture apporte des cartes nouvelles (borné par API_MAX_SWEEPS).
    """
    labeled = 0
    for _ in range(API_MAX_SWEEPS):
        items = _fetch_untagged(rarity)
        fresh = [i for i in items if i["id"] not in labeled_ids and i["id"] not in kept]
        if not fresh:
            break
        to_label = [i for i in fresh if _has_keyword(_normalize(api.card_text(i)), keywords) == tag_if_match]
        if to_label and not dry_run:
            for tag_id in tag_ids:
                _api_retry(api.apply_tag, tag_id, [i["id"] for i in to_label])
        for item in to_label:
            log(f"  • {api.card_title(item)}")
        match_ids = {i["id"] for i in to_label}
        labeled_ids.update(match_ids)
        kept.update(i["id"] for i in fresh if i["id"] not in match_ids)
        labeled += len(to_label)
    return labeled


PACK_COUNT_RE = re.compile(r"(\d+)\s*/\s*\d+\s*paquets? disponibles?")
PACK_CARD_RE = re.compile(r"Carte\s+(\d+)\s*/\s*(\d+)\s+(\S+)\s+([^\n]+)")
PACK_OPEN_XPATH = "//button[normalize-space()='Ouvrir']"
PACK_NEXT_JS = "return [...document.querySelectorAll('button.w-12.h-12')].filter(b => b.offsetParent).pop() || null"
PACK_WAIT_AUTO = 20  # secondes d'attente automatique avant de demander l'aide de l'utilisateur
PACK_WAIT_USER = 180  # secondes laissées à l'utilisateur pour valider la vérification anti-bot
PACK_SCROLL_SECONDS = 1.0  # durée totale pour faire défiler les cartes d'un paquet
PACK_PAUSE_SECONDS = 0.5  # pause entre deux paquets


def _packs_available(driver) -> int:
    """Nombre de paquets disponibles affiché sur /pulls (0 si introuvable)."""
    match = PACK_COUNT_RE.search(driver.find_element(By.TAG_NAME, "body").text)
    return int(match[1]) if match else 0


def _open_one_pack(driver, log: Log) -> None:
    """Ouvre un paquet depuis /pulls, parcourt ses cartes et clique sur « Continuer »."""
    click((By.XPATH, PACK_OPEN_XPATH))
    cards_shown = lambda d: PACK_CARD_RE.search(d.find_element(By.TAG_NAME, "body").text)
    # Le détecteur de bots peut retarder l'ouverture : courte attente automatique, puis aide de l'utilisateur
    try:
        WebDriverWait(driver, PACK_WAIT_AUTO, poll_frequency=1).until(cards_shown)
    except TimeoutException:
        log("Vérification anti-bot : valide-la dans Chrome (coche la case si besoin), la suite reprendra seule")
        try:
            WebDriverWait(driver, PACK_WAIT_USER, poll_frequency=1).until(cards_shown)
        except TimeoutException:
            raise RuntimeError("Le paquet ne s'est pas ouvert dans le délai imparti") from None

    while True:
        text = driver.find_element(By.TAG_NAME, "body").text
        match = PACK_CARD_RE.search(text)
        if match:
            log(f"  Carte {match[1]}/{match[2]} : {match[3]} {match[4].strip()}")
        arrow = driver.execute_script(PACK_NEXT_JS)
        if arrow is None or arrow.get_attribute("disabled") is not None:
            break
        current = match[1] if match else None
        total = int(match[2]) if match else 5
        time.sleep(PACK_SCROLL_SECONDS / max(total - 1, 1))
        driver.execute_script("arguments[0].click();", arrow)
        WebDriverWait(driver, config.DEFAULT_TIMEOUT).until(
            lambda d: (m := PACK_CARD_RE.search(d.find_element(By.TAG_NAME, "body").text)) is None
            or m[1] != current
        )
    click((By.XPATH, "//button[normalize-space()='Continuer']"))
    WebDriverWait(driver, config.DEFAULT_TIMEOUT).until(
        lambda d: not PACK_CARD_RE.search(d.find_element(By.TAG_NAME, "body").text)
    )


def ouvrir_paquets(log: Log = _noop) -> int:
    """Va sur /pulls et ouvre tous les paquets disponibles. Retourne le nombre de paquets ouverts."""
    driver = browser.get_driver()
    go_to("/pulls", log)
    try:
        wait_for((By.XPATH, PACK_OPEN_XPATH))
    except TimeoutException:
        log("Bouton « Ouvrir » introuvable (non connecté ?)")
        return 0

    opened = 0
    while _packs_available(driver) > 0:
        available = _packs_available(driver)
        log(f"Paquets disponibles : {available}, ouverture du suivant...")
        _open_one_pack(driver, log)
        opened += 1
        time.sleep(PACK_PAUSE_SECONDS)
        WebDriverWait(driver, config.DEFAULT_TIMEOUT).until(lambda d: PACK_COUNT_RE.search(d.find_element(By.TAG_NAME, "body").text))
    log(f"Terminé : {opened} paquet(s) ouvert(s)")
    return opened


PACK_API_PAUSE_SECONDS = 3.0  # pause entre deux ouvertures par l'API (le site refuse en dessous de ~3 s)
PACK_API_MAX_WAIT = 120  # secondes : au-delà, on s'arrête plutôt que d'attendre un `retry_after` très lointain


def _retry_after_seconds(result: dict) -> float:
    """Délai demandé par le site (`retry_after`, date ISO) avant la prochaine ouverture."""
    try:
        target = datetime.fromisoformat(result["retry_after"].replace("Z", "+00:00"))
        return max((target - datetime.now(timezone.utc)).total_seconds(), 0) + 0.5
    except (KeyError, AttributeError, ValueError):
        return PACK_API_PAUSE_SECONDS


def _pack_card_label(card: dict) -> str:
    inner = card.get("card") if isinstance(card.get("card"), dict) else card
    title = inner.get("wikipedia_title") or inner.get("title") or inner.get("name") or "?"
    return f"{inner.get('rarity') or ''} {title}".strip()


def ouvrir_paquets_api(log: Log = _noop) -> int:
    """Ouvre tous les paquets via l'API du site (sans cliquer). Retourne le nombre de paquets ouverts.

    La vérification anti-bot Cloudflare (environ tous les 10 paquets) reste à valider dans Chrome :
    on rouvre alors un paquet par l'interface, où le site affiche sa case à cocher, puis on reprend par l'API.
    """
    driver = browser.get_driver()
    go_to("/pulls", log)
    try:
        wait_for((By.XPATH, PACK_OPEN_XPATH))
    except TimeoutException:
        log("Bouton « Ouvrir » introuvable (non connecté ?)")
        return 0

    opened = 0
    while True:
        result = _api_retry(api.open_pack)
        if result["_status"] == 200 and result.get("cards"):
            opened += 1
            log(f"Paquet {opened} : " + ", ".join(_pack_card_label(c) for c in result["cards"])
                + f" ({result.get('packs_remaining', '?')} restant(s))")
            if result.get("packs_remaining") == 0:
                break
            time.sleep(PACK_API_PAUSE_SECONDS)
        elif result.get("human_verification_required"):
            log("Vérification anti-bot demandée : valide-la dans Chrome, la suite reprendra seule")
            driver.get(config.BASE_URL.rstrip("/") + "/pulls")
            wait_for((By.XPATH, PACK_OPEN_XPATH))
            if _packs_available(driver) == 0:
                break
            _open_one_pack(driver, log)
            opened += 1
            driver.get(config.BASE_URL.rstrip("/") + "/pulls")
            wait_for((By.XPATH, PACK_OPEN_XPATH))
        elif result.get("rate_limited") and not result.get("rate_limit_daily") \
                and (wait := _retry_after_seconds(result)) <= PACK_API_MAX_WAIT:
            log(f"Ouverture trop rapide : attente de {wait:.0f} s")
            time.sleep(wait)
        else:
            log(f"Arrêt : {result.get('error') or result}")
            break
    log(f"Terminé : {opened} paquet(s) ouvert(s)")
    return opened


# Analyse Q-Score : fonctions conservées mais retirées de ACTIONS (peu pertinent)
QSCORE_TOP = 30


def analyse_qscore_rarete(rarity: str, rarity_label: str, log: Log = _noop) -> list[tuple[str, int]]:
    """Classe par Q-Score décroissant les cartes d'une rareté (toute la collection) et logue le top 30."""
    go_to("/collection", log)
    cards: dict[str, tuple[str, int]] = {}
    for page in range(API_MAX_PAGES):
        batch = _api_retry(api.fetch_collection, rarity, page, False)
        if not batch:
            break
        for item in batch:
            card = item.get("card") or {}
            cards[item["id"]] = (api.card_title(item) or "(sans titre)", card.get("q_score") or 0)
        time.sleep(api.REQUEST_PAUSE)
    ranking = sorted(cards.values(), key=lambda c: c[1], reverse=True)
    log(f"{rarity_label} : {len(ranking)} carte(s) analysée(s), top {min(QSCORE_TOP, len(ranking))} par Q-Score")
    for rank, (title, score) in enumerate(ranking[:QSCORE_TOP], start=1):
        log(f"{rank}. {title} qscore = {score}")
    return ranking[:QSCORE_TOP]


def analyse_qscore_ultra_rares(log: Log = _noop) -> int:
    return len(analyse_qscore_rarete("UR", "Ultra rare", log))


def analyse_qscore_super_rares(log: Log = _noop) -> int:
    return len(analyse_qscore_rarete("SR", "Super rare", log))


def analyse_qscore_rares(log: Log = _noop) -> int:
    return len(analyse_qscore_rarete("R", "Rare", log))


def analyse_qscore_tout(log: Log = _noop) -> int:
    """Analyse Q-Score des ultra rares, super rares puis rares."""
    return sum(step(log) for step in (analyse_qscore_ultra_rares, analyse_qscore_super_rares, analyse_qscore_rares))


MARKET_PAUSE = 2.0  # secondes entre deux lectures d'historique : le site refuse les rafales (« automation_limit »)
MARKET_MAX_PER_RUN = 400  # cartes lues par clic ; les suivantes sont reprises au clic suivant (cache)
MARKET_CACHE_HOURS = 24  # une carte lue depuis moins longtemps n'est pas relue
MARKET_CACHE_SAVE_EVERY = 25
MARKET_TOP = 50
MARKET_CACHE_FILE = config.RESULTS_DIR / "market_cache.json"


def _load_market_cache() -> dict[str, dict]:
    try:
        return json.loads(MARKET_CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_market_cache(cache: dict[str, dict]) -> None:
    config.RESULTS_DIR.mkdir(exist_ok=True)
    MARKET_CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def _market_entry_fresh(entry: dict | None, rarity: str, now: datetime) -> bool:
    if not entry or entry.get("rarity") != rarity:
        return False
    age = now - datetime.fromisoformat(entry["fetched_at"])
    return age.total_seconds() < MARKET_CACHE_HOURS * 3600


def _market_entry(title: str, rarity: str, sales: list[dict], now: datetime) -> dict:
    """Prix moyen/médian des ventes de la carte à cette rareté (les ventes sous une autre rareté sont ignorées)."""
    prices = [s["final_price"] for s in sales
              if s.get("rarity") == rarity and isinstance(s.get("final_price"), (int, float))]
    return {
        "title": title, "rarity": rarity, "count": len(prices), "fetched_at": now.isoformat(),
        "avg": round(statistics.fmean(prices), 1) if prices else None,
        "median": round(statistics.median(prices), 1) if prices else None,
    }


def _fetch_sales(card_id: str) -> list[dict]:
    for attempt in range(1, API_RETRIES + 1):
        try:
            return api.fetch_card_sales(card_id)
        except api.AutomationLimitError:
            raise
        except (api.ApiError, TimeoutException, OSError):
            if attempt == API_RETRIES:
                raise
            time.sleep(2 * attempt)
    return []


def _collection_cards(rarity: str) -> dict[str, str]:
    """{id de la carte: titre} pour toute la collection d'une rareté (étiquetées ou non)."""
    cards: dict[str, str] = {}
    for page in range(API_MAX_PAGES):
        batch = _api_retry(api.fetch_collection, rarity, page, False)
        if not batch:
            break
        for item in batch:
            card_id = (item.get("card") or {}).get("id")
            if card_id:
                cards[card_id] = api.card_title(item) or "(sans titre)"
        time.sleep(api.REQUEST_PAUSE)
    return cards


def market_rarete(rarity: str, rarity_label: str, log: Log = _noop) -> tuple[int, bool]:
    """Prix de vente moyen des cartes d'une rareté (historique des enchères, infos marché Pro).

    Lit l'historique de chaque carte de la collection à rythme lent, au plus MARKET_MAX_PER_RUN par appel ;
    les lectures sont conservées dans un cache, donc relancer reprend là où on s'est arrêté.
    Logue le top MARKET_TOP par prix moyen et écrit la liste complète dans resultats/market_<rareté>.csv.
    Retourne (cartes restant à lire, True si le site a refusé les requêtes).
    """
    go_to("/collection", log)
    cards = _collection_cards(rarity)
    cache = _load_market_cache()
    now = datetime.now(timezone.utc)
    todo = [cid for cid in cards if not _market_entry_fresh(cache.get(cid), rarity, now)]
    batch = todo[:MARKET_MAX_PER_RUN]
    log(f"{rarity_label} : {len(cards)} carte(s), {len(cards) - len(todo)} déjà lue(s) récemment, "
        f"{len(batch)} à lire maintenant (≈ {len(batch) * MARKET_PAUSE / 60:.0f} min)")

    blocked = False
    try:
        for done, card_id in enumerate(batch, start=1):
            try:
                sales = _fetch_sales(card_id)
            except api.AutomationLimitError as error:
                log(f"⚠ Le site refuse les requêtes : {error} Analyse interrompue, relance plus tard pour continuer.")
                blocked = True
                break
            cache[card_id] = _market_entry(cards[card_id], rarity, sales, datetime.now(timezone.utc))
            if done % MARKET_CACHE_SAVE_EVERY == 0:
                _save_market_cache(cache)
                log(f"  … {done}/{len(batch)} carte(s) lue(s)")
            time.sleep(MARKET_PAUSE)
    finally:
        _save_market_cache(cache)

    entries = [(cid, cache[cid]) for cid in cards if cache.get(cid, {}).get("rarity") == rarity]
    ranking = sorted((e for _, e in entries if e["count"]), key=lambda e: e["avg"], reverse=True)
    remaining = sum(1 for cid in cards if not cache.get(cid) or cache[cid].get("rarity") != rarity)
    _write_market_csv(rarity, [e for _, e in entries])
    log(f"{rarity_label} : {len(entries)}/{len(cards)} carte(s) analysée(s), {len(ranking)} avec des ventes "
        f"— top {min(MARKET_TOP, len(ranking))} par prix moyen de vente")
    for rank, entry in enumerate(ranking[:MARKET_TOP], start=1):
        log(f"{rank}. {entry['title']} : moyenne = {entry['avg']:g} (médiane {entry['median']:g}, {entry['count']} vente(s))")
    log(f"Liste complète : {config.RESULTS_DIR / f'market_{rarity}.csv'}")
    if remaining:
        log(f"{remaining} carte(s) pas encore analysée(s) : relance pour continuer")
    return remaining, blocked


def _write_market_csv(rarity: str, entries: list[dict]) -> None:
    config.RESULTS_DIR.mkdir(exist_ok=True)
    rows = sorted(entries, key=lambda e: (e["avg"] is None, -(e["avg"] or 0)))
    with open(config.RESULTS_DIR / f"market_{rarity}.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["Carte", "Prix moyen", "Prix médian", "Nb ventes", "Lu le"])
        for e in rows:
            writer.writerow([e["title"], e["avg"], e["median"], e["count"], e["fetched_at"][:16]])


def market_ultra_rares(log: Log = _noop) -> int:
    return market_rarete("UR", "Ultra rare", log)[0]


def market_super_rares(log: Log = _noop) -> int:
    return market_rarete("SR", "Super rare", log)[0]


def market_rares(log: Log = _noop) -> int:
    return market_rarete("R", "Rare", log)[0]


def market_peu_communes(log: Log = _noop) -> int:
    return market_rarete("PC", "Peu commune", log)[0]


def market_communes(log: Log = _noop) -> int:
    return market_rarete("C", "Commune", log)[0]


def market_tout(log: Log = _noop) -> int:
    """Market des ultra rares, super rares, rares puis peu communes (les communes : bouton dédié, très longues)."""
    total = 0
    for rarity, label in (("UR", "Ultra rare"), ("SR", "Super rare"), ("R", "Rare"), ("PC", "Peu commune")):
        remaining, blocked = market_rarete(rarity, label, log)
        total += remaining
        if blocked:
            break
    return total


# (libellé du bouton, fonction)
ACTIONS: list[tuple[str, Callable[[Log], object]]] = [
    ("Se connecter", login),
    ("Cartes communes", cartes_communes),
    ("Défausse", defausse_tout),
    ("Défausse API", defausse_api),
    ("Tag", tag_tout_api),
    ("Market", market_tout),
    ("Ouvrir paquets", ouvrir_paquets),
    ("Ouvrir paquets API", ouvrir_paquets_api),
    ("Fermer le navigateur", close_browser),
]

# Sous-actions repliables, indexées par le libellé du bouton principal dans ACTIONS
SUB_ACTIONS: dict[str, list[tuple[str, Callable[[Log], object]]]] = {
    "Défausse": [
        ("Communes", defausse_communes),
        ("Peu communes", defausse_peu_communes),
        ("Rares", defausse_rares),
    ],
    "Tag": [
        ("Afrique", tag_afrique_api),
        ("Oiseaux", tag_oiseaux_api),
        ("Reptiles", tag_reptiles_api),
        ("Cuisine", tag_cuisine_api),
    ],
    "Market": [
        ("Ultra rares", market_ultra_rares),
        ("Super rares", market_super_rares),
        ("Rares", market_rares),
        ("Peu communes", market_peu_communes),
        ("Communes", market_communes),
    ],
}
