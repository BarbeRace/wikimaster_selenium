import os
from pathlib import Path

BASE_URL = "https://www.wiki-masters.com/"

ROOT_DIR = Path(__file__).resolve().parent.parent
# Profil Chrome dédié : conserve cookies/session entre les lancements (reste connecté).
PROFILE_DIR = ROOT_DIR / "chrome_profile"
# Listes de mots-clés : un mot-clé par ligne (insensible à la casse et aux accents, recherche par sous-chaîne)
KEYWORDS_DIR = ROOT_DIR / "mots_cles"
DEFAUSSE_KEYWORDS_FILE = KEYWORDS_DIR / "mots_cles_defausse.txt"
TAG_AFRIQUE_KEYWORDS_FILE = KEYWORDS_DIR / "mots_cles_tag_afrique.txt"
TAG_OISEAUX_KEYWORDS_FILE = KEYWORDS_DIR / "mots_cles_oiseaux.txt"
TAG_REPTILES_KEYWORDS_FILE = KEYWORDS_DIR / "mots_cles_reptiles.txt"
TAG_CUISINE_KEYWORDS_FILE = KEYWORDS_DIR / "mots_cles_cuisine.txt"

DEFAULT_TIMEOUT = 15  # secondes, pour les attentes explicites
LABEL_LIST_TIMEOUT = 10  # secondes d'attente de la liste d'étiquettes ; au-delà, la page est rafraîchie et la défausse relancée
LOGIN_URL = BASE_URL + "login"


def get_credentials() -> tuple[str, str]:
    """Lit (email, mot de passe) dans ROOT_DIR/.env à chaque appel."""
    values: dict[str, str] = {}
    env_file = ROOT_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return (
        values.get("WIKIMASTER_EMAIL") or os.environ.get("WIKIMASTER_EMAIL", ""),
        values.get("WIKIMASTER_PASSWORD") or os.environ.get("WIKIMASTER_PASSWORD", ""),
    )
