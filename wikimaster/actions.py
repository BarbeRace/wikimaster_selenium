"""Fonctions utilitaires Wiki Masters.

Chaque fonction prend un `log` (callable str -> None) optionnel et retourne
un résultat simple. Pour ajouter une action : écrire la fonction ici, puis
l'ajouter à la liste ACTIONS en bas de fichier (un bouton apparaîtra dans l'UI).
"""

import re
import time
import unicodedata
from collections.abc import Callable
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


def tag_afrique(log: Log = _noop) -> int:
    """Étiquette « Afrique & co » les cartes de toutes les raretés contenant un mot-clé africain, sur toutes les pages."""
    return _tag_collection(None, "Toutes raretés", config.TAG_AFRIQUE_KEYWORDS_FILE, True, AFRIQUE_LABEL, log)


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
API_MAX_SWEEPS = 5
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
                        tags: tuple[str, ...], log: Log, dry_run: bool = False) -> int:
    """Étiquette `tags` via l'API les cartes sans étiquette selon la présence d'un mot-clé (titre ou description).

    Lit la collection sans étiquette (/api/my-collection) et pose les étiquettes (table Supabase user_card_tags).
    `rarities` : liste de (code rareté ou None pour toutes, nom affiché). Chaque balayage reprend après les cartes
    conservées ; on refait des balayages jusqu'à ce qu'un balayage n'étiquette plus rien.
    `dry_run` : compte sans rien écrire.
    """
    keywords = _load_keywords(keywords_file)
    go_to("/collection", log)  # session connectée et jeton à jour
    tag_ids = [_api_retry(api.get_tag_id, tag) for tag in tags]
    names = " + ".join(f"« {tag} »" for tag in tags)
    verb = "à étiqueter" if dry_run else "étiquetée(s)"
    total = 0
    for rarity, rarity_label in rarities:
        rarity_total = 0
        for _ in range(API_MAX_SWEEPS):
            labeled = _api_sweep(rarity, keywords, tag_if_match, tag_ids, dry_run, log)
            rarity_total += labeled
            if labeled == 0 or dry_run:
                break
        log(f"{rarity_label} : {rarity_total} carte(s) {verb} {names}")
        total += rarity_total
    log(f"Terminé (API) : {total} carte(s) {verb} {names} au total")
    return total


def defausse_api(log: Log = _noop, dry_run: bool = False) -> int:
    """Comme « Défausse » (communes, peu communes, rares), mais via l'API du site : sans clics ni pages à charger."""
    return _tag_collection_api(API_RARITIES, config.DEFAUSSE_KEYWORDS_FILE, False, (DEFAUSSE_LABEL,), log, dry_run)


def tag_afrique_api(log: Log = _noop, dry_run: bool = False) -> int:
    """Comme « Tag afrique », mais via l'API : étiquette « Afrique & co » les cartes sans étiquette (toutes raretés) à mot-clé."""
    return _tag_collection_api([(None, "Toutes raretés")], config.TAG_AFRIQUE_KEYWORDS_FILE, True, (AFRIQUE_LABEL,), log, dry_run)


def tag_oiseaux_api(log: Log = _noop, dry_run: bool = False) -> int:
    """Étiquette « Oiseau » et « Animal » via l'API les cartes sans étiquette (toutes raretés) contenant un mot-clé d'oiseaux."""
    return _tag_collection_api([(None, "Toutes raretés")], config.TAG_OISEAUX_KEYWORDS_FILE, True,
                               (OISEAUX_LABEL, ANIMAL_LABEL), log, dry_run)


def tag_reptiles_api(log: Log = _noop, dry_run: bool = False) -> int:
    """Étiquette « Reptiles » et « Animal » via l'API les cartes sans étiquette (toutes raretés) contenant un mot-clé de reptiles."""
    return _tag_collection_api([(None, "Toutes raretés")], config.TAG_REPTILES_KEYWORDS_FILE, True,
                               (REPTILES_LABEL, ANIMAL_LABEL), log, dry_run)


def tag_cuisine_api(log: Log = _noop, dry_run: bool = False) -> int:
    """Étiquette « Cuisine » via l'API les cartes sans étiquette (toutes raretés) contenant un mot-clé de cuisine."""
    return _tag_collection_api([(None, "Toutes raretés")], config.TAG_CUISINE_KEYWORDS_FILE, True,
                               (CUISINE_LABEL,), log, dry_run)


def _api_sweep(rarity: str | None, keywords: list[str], tag_if_match: bool, tag_ids: list[str], dry_run: bool,
               log: Log = _noop) -> int:
    labeled = 0
    kept = 0  # cartes conservées : elles occupent toujours le début de la liste
    for _ in range(MAX_ROUNDS):
        page, offset = kept // api.PAGE_SIZE, kept % api.PAGE_SIZE
        items = _api_retry(api.fetch_collection, rarity, page)
        if len(items) <= offset:
            break
        to_label = [i for i in items if _has_keyword(_normalize(api.card_text(i)), keywords) == tag_if_match]
        if to_label and not dry_run:
            for tag_id in tag_ids:
                _api_retry(api.apply_tag, tag_id, [i["id"] for i in to_label])
        for item in to_label:
            log(f"  • {api.card_title(item)}")
        labeled += len(to_label)
        tagged = 0 if dry_run else len(to_label)
        kept = page * api.PAGE_SIZE + len(items) - tagged
        time.sleep(api.REQUEST_PAUSE)
    return labeled


PACK_COUNT_RE = re.compile(r"(\d+)\s*/\s*\d+\s*paquets? disponibles?")
PACK_CARD_RE = re.compile(r"Carte\s+(\d+)\s*/\s*(\d+)\s+(\S+)\s+([^\n]+)")
PACK_OPEN_XPATH = "//button[normalize-space()='Ouvrir']"
PACK_NEXT_JS = "return [...document.querySelectorAll('button.w-12.h-12')].filter(b => b.offsetParent).pop() || null"
PACK_WAIT_AUTO = 20  # secondes d'attente automatique avant de demander l'aide de l'utilisateur
PACK_WAIT_USER = 180  # secondes laissées à l'utilisateur pour valider la vérification anti-bot
PACK_SCROLL_SECONDS = 2.0  # durée totale pour faire défiler les cartes d'un paquet
PACK_PAUSE_SECONDS = 1.0  # pause entre deux paquets


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


# (libellé du bouton, fonction)
ACTIONS: list[tuple[str, Callable[[Log], object]]] = [
    ("Se connecter", login),
    ("Cartes communes", cartes_communes),
    ("Défausse", defausse_tout),
    ("Défausse API", defausse_api),
    ("Tag afrique", tag_afrique),
    ("Tag afrique API", tag_afrique_api),
    ("Tag oiseaux API", tag_oiseaux_api),
    ("Tag reptiles API", tag_reptiles_api),
    ("Tag cuisine API", tag_cuisine_api),
    ("Ouvrir paquets", ouvrir_paquets),
    ("Fermer le navigateur", close_browser),
]

# Sous-actions repliables, indexées par le libellé du bouton principal dans ACTIONS
SUB_ACTIONS: dict[str, list[tuple[str, Callable[[Log], object]]]] = {
    "Défausse": [
        ("Communes", defausse_communes),
        ("Peu communes", defausse_peu_communes),
        ("Rares", defausse_rares),
    ],
}
