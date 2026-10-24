"""Accès direct à l'API de Wiki Masters, en réutilisant la session du navigateur Chrome déjà connecté.

- La collection est lue via `/api/my-collection` (appel same-origin depuis la page : cookies et Cloudflare OK).
- Les étiquettes sont posées via l'API REST Supabase (table `user_card_tags`), exactement comme le fait le site.
"""

import base64
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from . import browser, config

PAGE_SIZE = 50
UPSERT_CHUNK = 100
REQUEST_PAUSE = 0.2  # secondes entre deux appels, pour ne pas surcharger le site

_anon_key: str | None = None


@dataclass
class Session:
    access_token: str
    user_id: str
    supabase_url: str
    anon_key: str


class ApiError(RuntimeError):
    pass


def _read_auth_cookie(driver) -> tuple[str, str]:
    """Retourne (nom du projet Supabase, JSON de session) depuis les cookies `sb-<projet>-auth-token.N`."""
    chunks: dict[int, str] = {}
    project = ""
    for cookie in driver.get_cookies():
        match = re.fullmatch(r"sb-(.+)-auth-token(?:\.(\d+))?", cookie["name"])
        if match:
            project = match[1]
            chunks[int(match[2] or 0)] = cookie["value"]
    if not chunks:
        raise ApiError("Non connecté : aucun cookie de session (clique sur « Se connecter »)")
    raw = "".join(chunks[i] for i in sorted(chunks))
    if raw.startswith("base64-"):
        raw = raw[len("base64-"):]
        raw = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8")
    else:
        raw = urllib.parse.unquote(raw)
    return project, raw


def _find_anon_key(driver) -> str:
    """La clé publique (anon) Supabase est embarquée dans les scripts du site."""
    global _anon_key
    if _anon_key:
        return _anon_key
    sources = driver.execute_script("return [...document.scripts].map(s => s.src).filter(Boolean)")
    for src in sources:
        text = driver.execute_script("return fetch(arguments[0]).then(r => r.text()).catch(() => '')", src)
        for match in re.finditer(r"eyJ[\w-]{10,}\.([\w-]{10,})\.[\w-]{10,}", text):
            payload = match[1] + "=" * (-len(match[1]) % 4)
            try:
                if json.loads(base64.urlsafe_b64decode(payload)).get("role") == "anon":
                    _anon_key = match[0]
                    return _anon_key
            except (ValueError, UnicodeDecodeError):
                continue
    raise ApiError("Clé publique Supabase introuvable dans les scripts du site")


def get_session() -> Session:
    """Session courante (jeton relu à chaque appel : le site le rafraîchit tant que la page reste ouverte)."""
    driver = browser.get_driver()
    project, raw = _read_auth_cookie(driver)
    data = json.loads(raw)
    return Session(
        access_token=data["access_token"],
        user_id=data["user"]["id"],
        supabase_url=f"https://{project}.supabase.co",
        anon_key=_find_anon_key(driver),
    )


def fetch_collection(rarity: str | None, page: int) -> list[dict]:
    """Une page (50 cartes) de la collection sans étiquette (`rarity` None = toutes). Page vide = fin."""
    driver = browser.get_driver()
    params = {"untagged": "1", "page": page, "stats": "0"}
    if rarity:
        params["rarity"] = rarity
    query = urllib.parse.urlencode(params)
    result = driver.execute_async_script(
        "const done = arguments[arguments.length - 1];"
        "fetch(arguments[0], {credentials: 'same-origin'})"
        ".then(async r => done({status: r.status, body: await r.text()}))"
        ".catch(e => done({status: 0, body: String(e)}));",
        f"/api/my-collection?{query}",
    )
    if result["status"] == 401:
        raise ApiError("Session expirée : reconnecte-toi")
    if result["status"] != 200:
        raise ApiError(f"Collection : HTTP {result['status']} {result['body'][:120]}")
    return json.loads(result["body"]).get("collection") or []


def card_title(item: dict) -> str:
    """Titre de la carte (nom de la page Wikipédia), tel qu'affiché dans la collection."""
    card = item.get("card") or {}
    return card.get("wikipedia_title") or ""


def card_text(item: dict) -> str:
    """Titre + description (catégorie) de la carte, comme affiché dans la collection."""
    card = item.get("card") or {}
    return f"{card.get('wikipedia_title') or ''} {card.get('category') or ''}".strip()


def _supabase(session: Session, method: str, path: str, body=None, prefer: str | None = None):
    headers = {
        "apikey": session.anon_key,
        "Authorization": f"Bearer {session.access_token}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(f"{session.supabase_url}/rest/v1/{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read()
    except urllib.error.HTTPError as error:
        raise ApiError(f"Supabase HTTP {error.code} : {error.read()[:160].decode('utf-8', 'replace')}") from None
    return json.loads(payload) if payload else None


def get_tag_id(label: str) -> str:
    session = get_session()
    query = urllib.parse.urlencode({"select": "id,name", "user_id": f"eq.{session.user_id}"})
    for tag in _supabase(session, "GET", f"tags?{query}"):
        if tag["name"].strip().casefold() == label.casefold():
            return tag["id"]
    raise ApiError(f"Étiquette « {label} » introuvable dans tes étiquettes")


def apply_tag(tag_id: str, user_card_ids: list[str]) -> None:
    """Pose l'étiquette sur ces cartes (les doublons existants sont ignorés)."""
    for start in range(0, len(user_card_ids), UPSERT_CHUNK):
        rows = [{"user_card_id": cid, "tag_id": tag_id} for cid in user_card_ids[start:start + UPSERT_CHUNK]]
        _supabase(
            get_session(), "POST", "user_card_tags?on_conflict=user_card_id,tag_id", rows,
            prefer="resolution=ignore-duplicates,return=minimal",
        )
        time.sleep(REQUEST_PAUSE)
