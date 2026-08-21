import io
import json
import logging
import os
import random
import re
import tempfile
import urllib.parse
import urllib.request

from PIL import Image, ImageDraw, ImageFont

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


# ==============================================================
# CONFIGURATION
# ==============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

FONT_BOLD = os.path.join(
    BASE_DIR,
    "fonts",
    "Poppins-Bold.ttf",
)

FONT_MEDIUM = os.path.join(
    BASE_DIR,
    "fonts",
    "Poppins-Medium.ttf",
)

LOGOS_DIR = os.path.join(
    BASE_DIR,
    "logos",
)

ALLOWED_USERS_FILE = os.path.join(
    BASE_DIR,
    "allowed_users.json",
)

# --------------------------------------------------------------
# SÉCURITÉ
# --------------------------------------------------------------
# Ne mets PAS ton token directement dans le code.
#
# Linux / VPS :
# export TELEGRAM_BOT_TOKEN="TON_NOUVEAU_TOKEN"
# export ADMIN_ID="5825526159"
#
# Termux :
# export TELEGRAM_BOT_TOKEN="TON_NOUVEAU_TOKEN"
# export ADMIN_ID="5825526159"
#
# --------------------------------------------------------------

TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    "8419447165:AAFBB8Bq4QY85Nf_7WbPV1j_gxVBZCSJB8M",
).strip()

try:
    ADMIN_ID = int(
        os.getenv(
            "ADMIN_ID",
            "5825526159",
        )
    )
except ValueError:
    ADMIN_ID = 0


# ==============================================================
# LOGGING
# ==============================================================

logging.basicConfig(
    format=(
        "%(asctime)s - %(name)s - "
        "%(levelname)s - %(message)s"
    ),
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# ==============================================================
# PALETTE
# ==============================================================

BG_COLOR = (30, 32, 38)
WHITE = (255, 255, 255)
BLUE_ACCENT = (77, 163, 255)
ORANGE = (240, 128, 24)
GREY_TEXT = (210, 210, 215)

W_BASE = 1728
H_MIN = 900
PADDING_X = 60


PLATFORM_COLORS = {
    "prime video": (25, 118, 210),
    "amazon prime": (25, 118, 210),
    "prime": (25, 118, 210),
    "crunchyroll": (247, 148, 30),
    "netflix": (200, 20, 30),
    "adn": (139, 61, 216),
    "disney+": (17, 60, 145),
    "disney plus": (17, 60, 145),
    "adkami": (0, 150, 199),
}


# ==============================================================
# ÉTATS
# ==============================================================

(
    DATE,
    IMAGE_CHOICE,
    IMAGE_UPLOAD,
    PLATFORM,
    CUSTOM_PLATFORM,
    NAME,
    EPISODE,
    HEURE,
    VERSION,
    AJOUTER_OU_FIN,
    EDIT_MENU,
    EDIT_REMOVE,
    EDIT_SELECT,
    EDIT_FIELD,
    EDIT_VALUE,
) = range(15)


# ==============================================================
# CLAVIERS
# ==============================================================

MAIN_MENU = ReplyKeyboardMarkup(
    [
        ["🗓️ Créer un planning"],
        ["🆔 Mon ID", "👥 Utilisateurs"],
        ["❌ Annuler"],
    ],
    resize_keyboard=True,
)

BACKGROUND_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["🖼️ Envoyer une image"],
        ["🔎 Chercher sur Nautiljon"],
        ["🚫 Aucune image"],
    ],
    resize_keyboard=True,
    one_time_keyboard=True,
)

PLATFORM_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["Prime video", "Crunchyroll"],
        ["Netflix", "ADN"],
        ["Autre plateforme"],
    ],
    resize_keyboard=True,
    one_time_keyboard=True,
)

VERSION_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["VF", "VO"],
        ["Les deux", "VOSTANG"],
    ],
    resize_keyboard=True,
    one_time_keyboard=True,
)

CONTINUER_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["➕ Ajouter un anime"],
        ["✅ Terminer et générer l'image"],
    ],
    resize_keyboard=True,
    one_time_keyboard=True,
)

POST_GEN_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["➕ Ajouter un anime", "✏️ Modifier un anime"],
        ["➖ Supprimer un anime", "🖼️ Modifier le fond"],
        ["📅 Modifier la date", "🔁 Régénérer l'image"],
        ["🆕 Nouveau planning", "✅ Terminé"],
    ],
    resize_keyboard=True,
)

EDIT_FIELD_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["📝 Nom"],
        ["📺 Épisode", "🕐 Heure"],
        ["📡 Plateforme", "🎙️ Version"],
        ["↩️ Retour"],
    ],
    resize_keyboard=True,
)


# ==============================================================
# OUTILS
# ==============================================================

def _font(path, size):
    try:
        if os.path.isfile(path):
            return ImageFont.truetype(
                path,
                size,
            )

        logger.warning(
            "Police introuvable : %s",
            path,
        )

    except OSError:
        logger.warning(
            "Impossible de charger la police : %s",
            path,
        )

    return ImageFont.load_default()


def _text_size(draw, text, font):
    bbox = draw.textbbox(
        (0, 0),
        text,
        font=font,
    )

    return (
        bbox[2] - bbox[0],
        bbox[3] - bbox[1],
    )


def normalize_platform(name):
    value = (
        str(name)
        .strip()
        .lower()
        .replace("_", " ")
    )

    if value == "amazon prime":
        return "prime video"

    return value


def _platform_color(name):
    return PLATFORM_COLORS.get(
        normalize_platform(name),
        (90, 95, 105),
    )


def _load_logo(platform_name, target_h):
    fname = (
        platform_name
        .strip()
        .lower()
        .replace(" ", "_")
        .replace("+", "plus")
    )

    path = os.path.join(
        LOGOS_DIR,
        fname + ".png",
    )

    if not os.path.isfile(path):
        return None

    try:
        img = Image.open(
            path
        ).convert("RGBA")

        if img.height <= 0:
            return None

        ratio = target_h / img.height

        img = img.resize(
            (
                max(
                    1,
                    int(img.width * ratio),
                ),
                target_h,
            ),
            Image.Resampling.LANCZOS,
        )

        return img

    except Exception:
        logger.exception(
            "Logo impossible à charger : %s",
            path,
        )

        return None


def fit_text(
    draw,
    text,
    font_path,
    max_width,
    start_size,
    min_size=18,
):
    size = start_size

    while size >= min_size:

        font = _font(
            font_path,
            size,
        )

        width, _ = _text_size(
            draw,
            text,
            font,
        )

        if width <= max_width:
            return font

        size -= 2

    return _font(
        font_path,
        min_size,
    )


def clean_title(title):
    title = " ".join(
        str(title).strip().split()
    )

    return title.upper() or "ANIME"


def normalize_version(value):
    value = (
        str(value)
        .strip()
        .upper()
    )

    if value in (
        "LES DEUX",
        "VF + VO",
        "VF+VO",
    ):
        return "LES DEUX"

    if value in (
        "VOSTFR",
        "VOST",
        "VO",
    ):
        return "VO"

    return value


def get_version_label(version):
    version = normalize_version(
        version
    )

    if version == "LES DEUX":
        return "VF + VO"

    return version


# ==============================================================
# UTILISATEURS
# ==============================================================

def _load_allowed_users():

    if not os.path.isfile(
        ALLOWED_USERS_FILE
    ):
        return set()

    try:
        with open(
            ALLOWED_USERS_FILE,
            "r",
            encoding="utf-8",
        ) as f:
            data = json.load(f)

        return {
            int(x)
            for x in data
        }

    except Exception:
        logger.exception(
            "Impossible de charger allowed_users.json"
        )

        return set()


def _save_allowed_users(users):

    try:
        with open(
            ALLOWED_USERS_FILE,
            "w",
            encoding="utf-8",
        ) as f:

            json.dump(
                sorted(users),
                f,
                indent=2,
            )

    except Exception:
        logger.exception(
            "Impossible de sauvegarder les utilisateurs"
        )


def is_authorized(user_id):

    if ADMIN_ID == 0:
        return False

    if user_id == ADMIN_ID:
        return True

    return user_id in _load_allowed_users()


# ==============================================================
# NAUTILJON
# ==============================================================

def _decode_html(data):

    if isinstance(data, bytes):

        return data.decode(
            "utf-8",
            errors="ignore",
        )

    return data


def _absolute_url(url):

    if not url:
        return None

    url = url.strip()

    if url.startswith("//"):
        return "https:" + url

    if url.startswith("/"):
        return (
            "https://www.nautiljon.com"
            + url
        )

    if url.startswith("http://"):
        return "https://" + url[7:]

    return url


def _clean_nautiljon_name(name):

    name = str(name).strip()

    name = re.sub(
        r"\bS\d+\b",
        "",
        name,
        flags=re.IGNORECASE,
    )

    name = re.sub(
        r"\bSaison\s*\d+\b",
        "",
        name,
        flags=re.IGNORECASE,
    )

    name = re.sub(
        r"\bSeason\s*\d+\b",
        "",
        name,
        flags=re.IGNORECASE,
    )

    name = re.sub(
        r"\s+",
        " ",
        name,
    )

    return name.strip()


def _extract_nautiljon_search_results(html):

    html = _decode_html(html)

    results = []

    link_patterns = [
        r'href=["\']([^"\']*/animes/[^"\']+)["\']',
        r'href=["\'](https?://[^"\']*nautiljon\.com/animes/[^"\']+)["\']',
    ]

    links = []

    for pattern in link_patterns:

        for match in re.findall(
            pattern,
            html,
            re.IGNORECASE,
        ):

            url = _absolute_url(
                match
            )

            if not url:
                continue

            if "/animes/" not in url:
                continue

            if url not in links:
                links.append(url)

    for anime_url in links[:15]:

        try:

            request = urllib.request.Request(
                anime_url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 "
                        "(Linux; Android 13) "
                        "AppleWebKit/537.36 "
                        "(KHTML, like Gecko) "
                        "Chrome/120 Mobile Safari/537.36"
                    ),
                    "Accept-Language": (
                        "fr-FR,fr;q=0.9"
                    ),
                },
            )

            with urllib.request.urlopen(
                request,
                timeout=15,
            ) as response:

                page = response.read()

            page = _decode_html(
                page
            )

            title = None

            title_patterns = [
                r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',
                r'<title[^>]*>(.*?)</title>',
                r'<h1[^>]*>(.*?)</h1>',
            ]

            for pattern in title_patterns:

                match = re.search(
                    pattern,
                    page,
                    re.IGNORECASE
                    | re.DOTALL,
                )

                if match:

                    title = re.sub(
                        r"<[^>]+>",
                        "",
                        match.group(1),
                    )

                    title = (
                        title
                        .replace(
                            "&amp;",
                            "&",
                        )
                        .replace(
                            "&#039;",
                            "'",
                        )
                        .strip()
                    )

                    if title:
                        break

            image = None

            image_patterns = [
                r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
                r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)',
                r'["\']([^"\']*?/images/anime/[^"\']+)["\']',
                r'["\']([^"\']*?/images/animes/[^"\']+)["\']',
            ]

            for pattern in image_patterns:

                match = re.search(
                    pattern,
                    page,
                    re.IGNORECASE,
                )

                if not match:
                    continue

                candidate = _absolute_url(
                    match.group(1)
                )

                if not candidate:
                    continue

                candidate_lower = (
                    candidate.lower()
                )

                if any(
                    word in candidate_lower
                    for word in (
                        "logo",
                        "favicon",
                        "sprite",
                        "avatar",
                        "icon",
                    )
                ):
                    continue

                image = candidate
                break

            if image:

                results.append(
                    {
                        "name": title or "",
                        "url": anime_url,
                        "image": image,
                    }
                )

        except Exception as exc:

            logger.debug(
                "Impossible de lire %s : %s",
                anime_url,
                exc,
            )

    return results


def search_nautiljon_image_sync(title):

    clean = _clean_nautiljon_name(
        title
    )

    if not clean:
        return None

    query = urllib.parse.quote_plus(
        clean
    )

    search_urls = [
        (
            "https://www.nautiljon.com/"
            "?q="
            + query
        ),
        (
            "https://www.nautiljon.com/"
            "rechercher.html?q="
            + query
        ),
    ]

    for search_url in search_urls:

        try:

            request = urllib.request.Request(
                search_url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 "
                        "(Linux; Android 13) "
                        "AppleWebKit/537.36 "
                        "(KHTML, like Gecko) "
                        "Chrome/120 Mobile Safari/537.36"
                    ),
                    "Accept-Language": (
                        "fr-FR,fr;q=0.9"
                    ),
                },
            )

            with urllib.request.urlopen(
                request,
                timeout=15,
            ) as response:

                html = response.read()

            results = (
                _extract_nautiljon_search_results(
                    html
                )
            )

            if not results:
                continue

            clean_lower = clean.lower()

            for result in results:

                result_name = (
                    result.get(
                        "name",
                        "",
                    )
                    .lower()
                )

                if clean_lower == result_name:

                    return result[
                        "image"
                    ]

            for result in results:

                result_name = (
                    result.get(
                        "name",
                        "",
                    )
                    .lower()
                )

                if (
                    clean_lower in result_name
                    or result_name in clean_lower
                ):

                    return result[
                        "image"
                    ]

            return results[0]["image"]

        except Exception as exc:

            logger.warning(
                "Recherche Nautiljon échouée "
                "pour '%s' : %s",
                clean,
                exc,
            )

    return None


async def search_nautiljon_image(
    title,
):

    import asyncio

    loop = asyncio.get_running_loop()

    return await loop.run_in_executor(
        None,
        search_nautiljon_image_sync,
        title,
    )


async def choose_nautiljon_background(
    context,
):

    entries = context.user_data.get(
        "entries",
        [],
    )

    if not entries:
        return None

    candidates = list(
        entries
    )

    random.shuffle(
        candidates
    )

    logger.info(
        "Recherche Nautiljon parmi %d anime.",
        len(candidates),
    )

    for entry in candidates:

        anime_name = entry.get(
            "name",
            "",
        ).strip()

        if not anime_name:
            continue

        logger.info(
            "Recherche affiche Nautiljon : %s",
            anime_name,
        )

        try:

            image_url = (
                await search_nautiljon_image(
                    anime_name
                )
            )

            if image_url:

                logger.info(
                    "Affiche trouvée pour : %s",
                    anime_name,
                )

                # IMPORTANT :
                # on retourne bien l'URL
                # dans un dictionnaire.
                return {
                    "url": image_url,
                    "anime": anime_name,
                }

        except Exception:

            logger.exception(
                "Erreur recherche Nautiljon : %s",
                anime_name,
            )

    logger.warning(
        "Aucune affiche Nautiljon trouvée."
    )

    return None


async def download_image_url(
    url,
    destination,
):

    import asyncio

    if not url:
        raise RuntimeError(
            "URL image vide."
        )

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "(Linux; Android 13) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/120 Mobile Safari/537.36"
            ),
            "Accept": (
                "image/avif,image/webp,"
                "image/apng,image/*,*/*;q=0.8"
            ),
        },
    )

    loop = asyncio.get_running_loop()

    def download():

        with urllib.request.urlopen(
            request,
            timeout=30,
        ) as response:

            data = response.read()

        if not data:
            raise RuntimeError(
                "Image vide."
            )

        with open(
            destination,
            "wb",
        ) as f:

            f.write(data)

    await loop.run_in_executor(
        None,
        download,
    )

    try:

        with Image.open(
            destination
        ) as img:

            img.verify()

    except Exception:

        try:
            os.remove(
                destination
            )
        except OSError:
            pass

        raise RuntimeError(
            "Le fichier téléchargé "
            "n'est pas une image valide."
        )


# ==============================================================
# FOND
# ==============================================================

def _load_background(
    path,
    target_w,
    target_h,
    darken=160,
):

    bg = Image.open(
        path
    ).convert("RGB")

    src_w, src_h = bg.size

    target_ratio = (
        target_w / target_h
    )

    src_ratio = (
        src_w / src_h
    )

    if src_ratio > target_ratio:

        new_w = int(
            src_h * target_ratio
        )

        left = (
            src_w - new_w
        ) // 2

        bg = bg.crop(
            (
                left,
                0,
                left + new_w,
                src_h,
            )
        )

    else:

        new_h = int(
            src_w / target_ratio
        )

        top = (
            src_h - new_h
        ) // 2

        bg = bg.crop(
            (
                0,
                top,
                src_w,
                top + new_h,
            )
        )

    bg = bg.resize(
        (
            target_w,
            target_h,
        ),
        Image.Resampling.LANCZOS,
    )

    overlay = Image.new(
        "RGBA",
        (
            target_w,
            target_h,
        ),
        (
            18,
            19,
            23,
            darken,
        ),
    )

    bg = Image.alpha_composite(
        bg.convert("RGBA"),
        overlay,
    )

    return bg.convert("RGB")


# ==============================================================
# GÉNÉRATION IMAGE
# ==============================================================

def generate_planning_image(
    date_str,
    entries,
    background_path=None,
):

    W = W_BASE

    platform_entries = []
    vf_entries = []

    for entry in entries:

        version = normalize_version(
            entry.get(
                "version",
                "",
            )
        )

        if version in (
            "VO",
            "VOSTANG",
        ):

            platform_entries.append(
                entry
            )

        elif version == "VF":

            vf_entries.append(
                entry
            )

        elif version == "LES DEUX":

            platform_entries.append(
                entry
            )

            vf_entries.append(
                entry
            )

    platforms_order = []
    by_platform = {}

    for entry in platform_entries:

        platform = entry.get(
            "platform",
            "Autre",
        ).strip()

        if platform not in by_platform:

            by_platform[
                platform
            ] = []

            platforms_order.append(
                platform
            )

        by_platform[
            platform
        ].append(entry)

    row_h = 72
    header_h = 330

    content_h = header_h

    for platform in platforms_order:

        content_h += 120

        content_h += (
            len(
                by_platform[
                    platform
                ]
            )
            * row_h
        )

        content_h += 40

    if vf_entries:

        content_h += 150

        content_h += (
            len(vf_entries)
            * row_h
        )

    content_h += 150

    H_ratio = round(
        W * 4 / 3
    )

    if content_h < H_ratio:

        H = H_ratio

    else:

        H = content_h

        W = round(
            H * 3 / 4
        )

    content = Image.new(
        "RGBA",
        (
            W,
            content_h,
        ),
        (
            0,
            0,
            0,
            0,
        ),
    )

    draw = ImageDraw.Draw(
        content
    )

    f_title = _font(
        FONT_BOLD,
        64,
    )

    f_subtitle = _font(
        FONT_BOLD,
        40,
    )

    f_badge = _font(
        FONT_BOLD,
        26,
    )

    f_row = _font(
        FONT_BOLD,
        30,
    )

    f_vf = _font(
        FONT_BOLD,
        46,
    )

    cy = 70

    # ----------------------------------------------------------
    # TITRE
    # ----------------------------------------------------------

    draw.ellipse(
        [
            PADDING_X,
            cy,
            PADDING_X + 46,
            cy + 46,
        ],
        fill=WHITE,
    )

    draw.ellipse(
        [
            PADDING_X + 10,
            cy + 10,
            PADDING_X + 36,
            cy + 36,
        ],
        fill=BG_COLOR,
    )

    draw.text(
        (
            PADDING_X + 70,
            cy - 8,
        ),
        "PLANNING",
        font=f_title,
        fill=WHITE,
    )

    cy += 100

    prefix = "LES SORTIES ANIMES DU "

    draw.text(
        (
            PADDING_X,
            cy,
        ),
        prefix,
        font=f_subtitle,
        fill=WHITE,
    )

    prefix_w, _ = _text_size(
        draw,
        prefix,
        f_subtitle,
    )

    date_font = fit_text(
        draw,
        date_str.upper(),
        FONT_BOLD,
        W - PADDING_X - prefix_w - 20,
        40,
        24,
    )

    draw.text(
        (
            PADDING_X + prefix_w + 10,
            cy,
        ),
        date_str.upper(),
        font=date_font,
        fill=BLUE_ACCENT,
    )

    cy += 130

    # ----------------------------------------------------------
    # PLATEFORMES
    # ----------------------------------------------------------

    for platform in platforms_order:

        color = _platform_color(
            platform
        )

        logo_h = 70

        draw.rectangle(
            [
                0,
                cy,
                14,
                cy + logo_h,
            ],
            fill=ORANGE,
        )

        platform_text = platform.upper()

        tw, _ = _text_size(
            draw,
            platform_text,
            f_badge,
        )

        badge_w = max(
            210,
            tw + 80,
        )

        draw.rounded_rectangle(
            [
                PADDING_X,
                cy,
                PADDING_X + badge_w,
                cy + logo_h,
            ],
            radius=12,
            fill=color,
        )

        logo = _load_logo(
            platform,
            logo_h - 20,
        )

        if logo:

            max_w = badge_w - 30

            if logo.width > max_w:

                ratio = (
                    max_w / logo.width
                )

                logo = logo.resize(
                    (
                        int(
                            logo.width
                            * ratio
                        ),
                        int(
                            logo.height
                            * ratio
                        ),
                    ),
                    Image.Resampling.LANCZOS,
                )

            content.paste(
                logo,
                (
                    PADDING_X
                    + (
                        badge_w
                        - logo.width
                    )
                    // 2,
                    cy
                    + (
                        logo_h
                        - logo.height
                    )
                    // 2,
                ),
                logo,
            )

        else:

            draw.text(
                (
                    PADDING_X
                    + (
                        badge_w - tw
                    )
                    // 2,
                    cy + 17,
                ),
                platform_text,
                font=f_badge,
                fill=WHITE,
            )

        cy += 100

        col_ep = int(
            W * 0.62
        )

        col_time = int(
            W * 0.84
        )

        for entry in by_platform[
            platform
        ]:

            title = clean_title(
                entry.get(
                    "name",
                    "ANIME",
                )
            )

            title_font = fit_text(
                draw,
                title,
                FONT_BOLD,
                col_ep - PADDING_X - 40,
                32,
                18,
            )

            draw.text(
                (
                    PADDING_X,
                    cy,
                ),
                title,
                font=title_font,
                fill=WHITE,
            )

            draw.text(
                (
                    col_ep,
                    cy,
                ),
                f"EPISODE {entry.get('episode', '')}",
                font=f_row,
                fill=WHITE,
            )

            time_font = fit_text(
                draw,
                entry.get(
                    "heure",
                    "",
                ).upper(),
                FONT_BOLD,
                W - col_time - PADDING_X,
                30,
                18,
            )

            draw.text(
                (
                    col_time,
                    cy,
                ),
                entry.get(
                    "heure",
                    "",
                ).upper(),
                font=time_font,
                fill=BLUE_ACCENT,
            )

            cy += row_h

        cy += 40

    # ----------------------------------------------------------
    # SORTIES VF
    # ----------------------------------------------------------

    if vf_entries:

        tw, _ = _text_size(
            draw,
            "LES SORTIES VF",
            f_vf,
        )

        badge_w = max(
            560,
            tw + 160,
        )

        draw.rounded_rectangle(
            [
                PADDING_X,
                cy,
                PADDING_X + badge_w,
                cy + 90,
            ],
            radius=24,
            fill=ORANGE,
        )

        draw.text(
            (
                PADDING_X + 110,
                cy + 20,
            ),
            "🇫🇷  LES SORTIES VF",
            font=f_vf,
            fill=WHITE,
        )

        cy += 140

        col_name = PADDING_X + 65

        col_ep = int(
            W * 0.62
        )

        col_time = int(
            W * 0.84
        )

        for entry in vf_entries:

            color = _platform_color(
                entry.get(
                    "platform",
                    "",
                )
            )

            draw.rounded_rectangle(
                [
                    PADDING_X,
                    cy + 6,
                    PADDING_X + 44,
                    cy + 50,
                ],
                radius=8,
                fill=color,
            )

            initial = (
                entry.get(
                    "platform",
                    "?",
                )[:1]
                .upper()
            )

            iw, ih = _text_size(
                draw,
                initial,
                f_badge,
            )

            draw.text(
                (
                    PADDING_X
                    + (44 - iw) // 2,
                    cy + 6
                    + (44 - ih) // 2
                    - 2,
                ),
                initial,
                font=f_badge,
                fill=WHITE,
            )

            title = clean_title(
                entry.get(
                    "name",
                    "ANIME",
                )
            )

            title_font = fit_text(
                draw,
                title,
                FONT_BOLD,
                col_ep - col_name - 30,
                32,
                18,
            )

            draw.text(
                (
                    col_name,
                    cy,
                ),
                title,
                font=title_font,
                fill=WHITE,
            )

            draw.text(
                (
                    col_ep,
                    cy,
                ),
                f"ÉPISODE {entry.get('episode', '')}",
                font=f_row,
                fill=WHITE,
            )

            draw.text(
                (
                    col_time,
                    cy,
                ),
                entry.get(
                    "heure",
                    "",
                ).upper(),
                font=f_row,
                fill=BLUE_ACCENT,
            )

            cy += row_h

    # ----------------------------------------------------------
    # FOND
    # ----------------------------------------------------------

    if (
        background_path
        and os.path.isfile(
            background_path
        )
    ):

        try:

            background = _load_background(
                background_path,
                W,
                H,
            )

        except Exception:

            logger.exception(
                "Erreur fond"
            )

            background = Image.new(
                "RGB",
                (
                    W,
                    H,
                ),
                BG_COLOR,
            )

    else:

        background = Image.new(
            "RGB",
            (
                W,
                H,
            ),
            BG_COLOR,
        )

        side = ImageDraw.Draw(
            background
        )

        side.rectangle(
            [
                0,
                0,
                260,
                H,
            ],
            fill=(
                38,
                40,
                47,
            ),
        )

    offset_y = max(
        0,
        (H - content_h)
        // 2,
    )

    background.paste(
        content,
        (
            0,
            offset_y,
        ),
        content,
    )

    # ----------------------------------------------------------
    # FOOTER
    # ----------------------------------------------------------

    final_draw = ImageDraw.Draw(
        background
    )

    footer = (
        "ABONNEZ-VOUS À NOTRE COMPTE"
    )

    f_footer = _font(
        FONT_BOLD,
        22,
    )

    fw, fh = _text_size(
        final_draw,
        footer,
        f_footer,
    )

    final_draw.text(
        (
            (W - fw) // 2,
            H - 70,
        ),
        footer,
        font=f_footer,
        fill=GREY_TEXT,
    )

    buffer = io.BytesIO()

    background.save(
        buffer,
        format="PNG",
        optimize=True,
    )

    buffer.seek(0)

    return buffer


# ==============================================================
# NETTOYAGE
# ==============================================================

def cleanup_background(
    context,
):

    path = context.user_data.get(
        "background_path"
    )

    if (
        path
        and os.path.isfile(path)
    ):

        try:
            os.remove(path)

        except OSError:
            pass

    context.user_data[
        "background_path"
    ] = None


# ==============================================================
# MENU
# ==============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    await update.message.reply_text(
        "👋 Salut !\n\n"
        "Je suis ton générateur de planning anime.\n\n"
        "Utilise les boutons ci-dessous "
        "ou les commandes.",
        reply_markup=MAIN_MENU,
    )


async def cmd_id(
    update,
    context,
):

    await update.message.reply_text(
        f"🆔 Ton ID Telegram : "
        f"{update.effective_user.id}",
        reply_markup=MAIN_MENU,
    )


async def menu_id(
    update,
    context,
):

    return await cmd_id(
        update,
        context,
    )


async def menu_users(
    update,
    context,
):

    return await cmd_utilisateurs(
        update,
        context,
    )


async def menu_cancel(
    update,
    context,
):

    return await annuler(
        update,
        context,
    )


# ==============================================================
# CRÉATION
# ==============================================================

async def createplanning(
    update,
    context,
):

    if not is_authorized(
        update.effective_user.id
    ):

        await update.message.reply_text(
            "⛔ Tu n'es pas autorisé à utiliser ce bot.",
            reply_markup=MAIN_MENU,
        )

        return ConversationHandler.END

    cleanup_background(
        context
    )

    context.user_data.clear()

    context.user_data[
        "entries"
    ] = []

    context.user_data[
        "background_path"
    ] = None

    context.user_data[
        "image_mode"
    ] = None

    await update.message.reply_text(
        "🗓️ Création d'un nouveau planning.\n\n"
        "Quelle est la date à afficher ?\n\n"
        "Exemple :\n"
        "Vendredi 21 Août",
        reply_markup=ReplyKeyboardRemove(),
    )

    return DATE


# ==============================================================
# DATE
# ==============================================================

async def recevoir_date_edit(
    update,
    context,
):

    date = update.message.text.strip()

    if not date:

        await update.message.reply_text(
            "❌ La date ne peut pas être vide."
        )

        return DATE

    # ----------------------------------------------------------
    # Modification de date
    # ----------------------------------------------------------

    if context.user_data.get(
        "changing_date"
    ):

        context.user_data[
            "date"
        ] = date

        context.user_data[
            "changing_date"
        ] = False

        await update.message.reply_text(
            "✅ Date modifiée.\n\n"
            "Tu peux maintenant régénérer l'image.",
            reply_markup=POST_GEN_KEYBOARD,
        )

        return EDIT_MENU

    context.user_data[
        "date"
    ] = date

    await update.message.reply_text(
        "🖼️ Que veux-tu faire pour l'image de fond ?\n\n"
        "🖼️ Envoyer une image : tu choisis l'image.\n"
        "🔎 Chercher sur Nautiljon : le bot choisit "
        "un anime du planning et cherche son affiche.\n"
        "🚫 Aucune image : fond uni.",
        reply_markup=BACKGROUND_KEYBOARD,
    )

    return IMAGE_CHOICE


# ==============================================================
# CHOIX IMAGE
# ==============================================================

async def image_choice(
    update,
    context,
):

    choice = update.message.text.strip().lower()

    # ----------------------------------------------------------
    # ENVOYER UNE IMAGE
    # ----------------------------------------------------------

    if "envoyer" in choice:

        context.user_data[
            "image_mode"
        ] = "upload"

        context.user_data[
            "changing_background"
        ] = False

        await update.message.reply_text(
            "🖼️ Envoie maintenant l'image "
            "que tu veux utiliser comme fond.",
            reply_markup=ReplyKeyboardRemove(),
        )

        return IMAGE_UPLOAD

    # ----------------------------------------------------------
    # NAUTILJON
    # ----------------------------------------------------------

    if "nautiljon" in choice:

        context.user_data[
            "image_mode"
        ] = "nautiljon"

        context.user_data[
            "background_path"
        ] = None

        # ------------------------------------------------------
        # Si on modifie le fond après génération
        # ------------------------------------------------------

        if context.user_data.get(
            "changing_background"
        ):

            context.user_data[
                "changing_background"
            ] = False

            entries = context.user_data.get(
                "entries",
                [],
            )

            if not entries:

                await update.message.reply_text(
                    "❌ Aucun anime dans le planning.",
                    reply_markup=POST_GEN_KEYBOARD,
                )

                return EDIT_MENU

            await update.message.reply_text(
                "🔎 Recherche d'une nouvelle affiche "
                "sur Nautiljon..."
            )

            try:

                result = (
                    await choose_nautiljon_background(
                        context
                    )
                )

                if result:

                    image_url = result[
                        "url"
                    ]

                    path = os.path.join(
                        tempfile.gettempdir(),
                        (
                            f"nautiljon_bg_"
                            f"{update.effective_chat.id}.jpg"
                        ),
                    )

                    await download_image_url(
                        image_url,
                        path,
                    )

                    context.user_data[
                        "background_path"
                    ] = path

                    await update.message.reply_text(
                        "✅ Nouvelle affiche trouvée !",
                        reply_markup=POST_GEN_KEYBOARD,
                    )

                else:

                    await update.message.reply_text(
                        "⚠️ Aucune affiche trouvée.",
                        reply_markup=POST_GEN_KEYBOARD,
                    )

            except Exception:

                logger.exception(
                    "Erreur modification fond Nautiljon"
                )

                await update.message.reply_text(
                    "⚠️ Impossible de récupérer "
                    "une nouvelle affiche.",
                    reply_markup=POST_GEN_KEYBOARD,
                )

            return EDIT_MENU

        await update.message.reply_text(
            "🔎 D'accord. Le bot cherchera automatiquement "
            "une affiche sur Nautiljon après que tu auras "
            "sélectionné les anime.",
            reply_markup=ReplyKeyboardRemove(),
        )

        return await ask_platform(
            update,
            context,
        )

    # ----------------------------------------------------------
    # AUCUNE IMAGE
    # ----------------------------------------------------------

    if "aucune" in choice:

        context.user_data[
            "image_mode"
        ] = "none"

        context.user_data[
            "background_path"
        ] = None

        # ------------------------------------------------------
        # Modification du fond après génération
        # ------------------------------------------------------

        if context.user_data.get(
            "changing_background"
        ):

            context.user_data[
                "changing_background"
            ] = False

            await update.message.reply_text(
                "🚫 Fond supprimé.",
                reply_markup=POST_GEN_KEYBOARD,
            )

            return EDIT_MENU

        await update.message.reply_text(
            "🚫 Aucun fond.",
            reply_markup=ReplyKeyboardRemove(),
        )

        return await ask_platform(
            update,
            context,
        )

    await update.message.reply_text(
        "❌ Choisis l'une des trois options.",
        reply_markup=BACKGROUND_KEYBOARD,
    )

    return IMAGE_CHOICE


# ==============================================================
# UPLOAD IMAGE
# ==============================================================

async def image_upload(
    update,
    context,
):

    if not update.message.photo:

        await update.message.reply_text(
            "📷 Envoie une photo."
        )

        return IMAGE_UPLOAD

    photo = update.message.photo[-1]

    telegram_file = await photo.get_file()

    path = os.path.join(
        tempfile.gettempdir(),
        (
            f"planning_bg_"
            f"{update.effective_chat.id}_"
            f"{random.randint(1000, 9999)}.jpg"
        ),
    )

    await telegram_file.download_to_drive(
        path
    )

    old = context.user_data.get(
        "background_path"
    )

    if (
        old
        and os.path.isfile(old)
    ):

        try:
            os.remove(old)

        except OSError:
            pass

    context.user_data[
        "background_path"
    ] = path

    context.user_data[
        "image_mode"
    ] = "upload"

    # ----------------------------------------------------------
    # Modification du fond
    # ----------------------------------------------------------

    if context.user_data.get(
        "changing_background"
    ):

        context.user_data[
            "changing_background"
        ] = False

        await update.message.reply_text(
            "✅ Nouveau fond enregistré !",
            reply_markup=POST_GEN_KEYBOARD,
        )

        return EDIT_MENU

    await update.message.reply_text(
        "✅ Image enregistrée !",
        reply_markup=ReplyKeyboardRemove(),
    )

    return await ask_platform(
        update,
        context,
    )


# ==============================================================
# PLATEFORME
# ==============================================================

async def ask_platform(
    update,
    context,
):

    await update.message.reply_text(
        "📡 Plateforme de diffusion ?",
        reply_markup=PLATFORM_KEYBOARD,
    )

    return PLATFORM


async def recevoir_platform(
    update,
    context,
):

    platform = update.message.text.strip()

    if platform == "Autre plateforme":

        await update.message.reply_text(
            "📡 Écris le nom de la plateforme.",
            reply_markup=ReplyKeyboardRemove(),
        )

        return CUSTOM_PLATFORM

    context.user_data[
        "current"
    ] = {
        "platform": platform,
    }

    await update.message.reply_text(
        "📝 Nom de l'anime ?",
        reply_markup=ReplyKeyboardRemove(),
    )

    return NAME


async def recevoir_custom_platform(
    update,
    context,
):

    platform = update.message.text.strip()

    if not platform:

        await update.message.reply_text(
            "❌ Le nom ne peut pas être vide."
        )

        return CUSTOM_PLATFORM

    context.user_data[
        "current"
    ] = {
        "platform": platform,
    }

    await update.message.reply_text(
        "📝 Nom de l'anime ?"
    )

    return NAME


# ==============================================================
# ANIME
# ==============================================================

async def recevoir_name(
    update,
    context,
):

    name = update.message.text.strip()

    if not name:

        await update.message.reply_text(
            "❌ Le nom ne peut pas être vide."
        )

        return NAME

    context.user_data[
        "current"
    ]["name"] = name

    await update.message.reply_text(
        "📺 Numéro de l'épisode ?"
    )

    return EPISODE


async def recevoir_episode(
    update,
    context,
):

    episode = update.message.text.strip()

    if not episode:

        await update.message.reply_text(
            "❌ Indique un numéro."
        )

        return EPISODE

    context.user_data[
        "current"
    ]["episode"] = episode

    await update.message.reply_text(
        "🕐 Heure de diffusion ?\n"
        "Exemple : 16H30"
    )

    return HEURE


async def recevoir_heure(
    update,
    context,
):

    heure = update.message.text.strip()

    if not heure:

        await update.message.reply_text(
            "❌ L'heure ne peut pas être vide."
        )

        return HEURE

    context.user_data[
        "current"
    ]["heure"] = heure

    await update.message.reply_text(
        "🎙️ Version ?\n\n"
        "VF = uniquement sortie VF\n"
        "VO = sortie plateforme\n"
        "Les deux = VF + VO",
        reply_markup=VERSION_KEYBOARD,
    )

    return VERSION


# ==============================================================
# VERSION
# ==============================================================

async def recevoir_version(
    update,
    context,
):

    value = normalize_version(
        update.message.text
    )

    valid = {
        "VF",
        "VO",
        "VOSTANG",
        "LES DEUX",
    }

    if value not in valid:

        await update.message.reply_text(
            "❌ Choisis une version avec les boutons.",
            reply_markup=VERSION_KEYBOARD,
        )

        return VERSION

    current = context.user_data[
        "current"
    ]

    current[
        "version"
    ] = value

    context.user_data[
        "entries"
    ].append(
        current.copy()
    )

    recap = current.copy()

    context.user_data[
        "current"
    ] = {}

    await update.message.reply_text(
        "✅ Anime ajouté !\n\n"
        f"🎬 {recap['name']}\n"
        f"📺 Épisode : {recap['episode']}\n"
        f"🕐 Heure : {recap['heure']}\n"
        f"📡 Plateforme : {recap['platform']}\n"
        f"🎙️ Version : "
        f"{get_version_label(recap['version'])}\n\n"
        "Que veux-tu faire ?",
        reply_markup=CONTINUER_KEYBOARD,
    )

    return AJOUTER_OU_FIN


# ==============================================================
# AJOUT / FIN
# ==============================================================

async def ajouter_ou_fin(
    update,
    context,
):

    choice = update.message.text.strip().lower()

    if "ajouter" in choice:

        return await ask_platform(
            update,
            context,
        )

    if (
        "terminer" in choice
        or "générer" in choice
        or "generer" in choice
    ):

        entries = context.user_data.get(
            "entries",
            [],
        )

        if not entries:

            await update.message.reply_text(
                "❌ Aucun anime ajouté."
            )

            return AJOUTER_OU_FIN

        # ------------------------------------------------------
        # NAUTILJON
        # ------------------------------------------------------

        if (
            context.user_data.get(
                "image_mode"
            )
            == "nautiljon"
        ):

            await update.message.reply_text(
                "🔎 Recherche d'une affiche sur Nautiljon..."
            )

            try:

                result = (
                    await choose_nautiljon_background(
                        context
                    )
                )

                if result:

                    # IMPORTANT :
                    # choose_nautiljon_background()
                    # renvoie un dictionnaire.
                    #
                    # On récupère l'URL ici.

                    image_url = result[
                        "url"
                    ]

                    anime_found = result.get(
                        "anime",
                        "",
                    )

                    path = os.path.join(
                        tempfile.gettempdir(),
                        (
                            f"nautiljon_bg_"
                            f"{update.effective_chat.id}.jpg"
                        ),
                    )

                    await download_image_url(
                        image_url,
                        path,
                    )

                    context.user_data[
                        "background_path"
                    ] = path

                    await update.message.reply_text(
                        "✅ Affiche trouvée sur Nautiljon"
                        + (
                            f" : {anime_found}"
                            if anime_found
                            else "."
                        )
                    )

                else:

                    await update.message.reply_text(
                        "⚠️ Aucune affiche trouvée sur "
                        "Nautiljon. Le planning sera généré "
                        "avec un fond uni."
                    )

            except Exception:

                logger.exception(
                    "Erreur Nautiljon"
                )

                await update.message.reply_text(
                    "⚠️ Recherche Nautiljon impossible. "
                    "Le planning sera généré sans image."
                )

        await update.message.reply_text(
            "🖼️ Génération du planning..."
        )

        await send_planning(
            update,
            context,
        )

        await update.message.reply_text(
            "Que veux-tu faire ensuite ?",
            reply_markup=POST_GEN_KEYBOARD,
        )

        return EDIT_MENU

    await update.message.reply_text(
        "Choisis une option.",
        reply_markup=CONTINUER_KEYBOARD,
    )

    return AJOUTER_OU_FIN


# ==============================================================
# ENVOYER PLANNING
# ==============================================================

async def send_planning(
    update,
    context,
):

    image = generate_planning_image(
        context.user_data.get(
            "date",
            "",
        ),
        context.user_data.get(
            "entries",
            [],
        ),
        context.user_data.get(
            "background_path"
        ),
    )

    await update.message.reply_photo(
        photo=image,
        caption=(
            "📌 Planning des sorties animes du "
            f"{context.user_data.get('date', '')}"
        ),
    )


# ==============================================================
# MENU APRÈS GÉNÉRATION
# ==============================================================

async def edit_menu(
    update,
    context,
):

    choice = update.message.text.strip().lower()

    if "ajouter" in choice:

        return await ask_platform(
            update,
            context,
        )

    if "modifier un anime" in choice:

        entries = context.user_data.get(
            "entries",
            [],
        )

        if not entries:

            await update.message.reply_text(
                "❌ Aucun anime.",
                reply_markup=POST_GEN_KEYBOARD,
            )

            return EDIT_MENU

        listing = "\n".join(
            f"{i + 1}. {e['name']} "
            f"(Ep. {e['episode']} — {e['heure']})"
            for i, e in enumerate(entries)
        )

        await update.message.reply_text(
            "✏️ Quel anime modifier ?\n\n"
            + listing
            + "\n\nTape le numéro.",
            reply_markup=ReplyKeyboardRemove(),
        )

        return EDIT_SELECT

    if "supprimer" in choice:

        entries = context.user_data.get(
            "entries",
            [],
        )

        if not entries:

            await update.message.reply_text(
                "❌ Aucun anime.",
                reply_markup=POST_GEN_KEYBOARD,
            )

            return EDIT_MENU

        listing = "\n".join(
            f"{i + 1}. {e['name']}"
            for i, e in enumerate(entries)
        )

        await update.message.reply_text(
            "➖ Quel anime supprimer ?\n\n"
            + listing
            + "\n\nTape le numéro.",
            reply_markup=ReplyKeyboardRemove(),
        )

        return EDIT_REMOVE

    if "modifier le fond" in choice:

        context.user_data[
            "changing_background"
        ] = True

        await update.message.reply_text(
            "🖼️ Choisis le nouveau fond :",
            reply_markup=BACKGROUND_KEYBOARD,
        )

        return IMAGE_CHOICE

    if "modifier la date" in choice:

        context.user_data[
            "changing_date"
        ] = True

        await update.message.reply_text(
            "📅 Nouvelle date ?",
            reply_markup=ReplyKeyboardRemove(),
        )

        return DATE

    if (
        "régénérer" in choice
        or "regenerer" in choice
    ):

        await send_planning(
            update,
            context,
        )

        return EDIT_MENU

    if "nouveau" in choice:

        cleanup_background(
            context
        )

        context.user_data.clear()

        context.user_data[
            "entries"
        ] = []

        await update.message.reply_text(
            "🆕 Nouveau planning.\n\n"
            "Quelle est la date ?",
            reply_markup=ReplyKeyboardRemove(),
        )

        return DATE

    if (
        "terminé" in choice
        or "termine" in choice
    ):

        cleanup_background(
            context
        )

        context.user_data.clear()

        await update.message.reply_text(
            "👍 Planning terminé !",
            reply_markup=MAIN_MENU,
        )

        return ConversationHandler.END

    await update.message.reply_text(
        "Choisis une option.",
        reply_markup=POST_GEN_KEYBOARD,
    )

    return EDIT_MENU


# ==============================================================
# SUPPRESSION
# ==============================================================

async def edit_remove(
    update,
    context,
):

    entries = context.user_data.get(
        "entries",
        [],
    )

    text = update.message.text.strip()

    if (
        not text.isdigit()
        or not (
            1 <= int(text) <= len(entries)
        )
    ):

        await update.message.reply_text(
            f"❌ Choisis un numéro entre "
            f"1 et {len(entries)}."
        )

        return EDIT_REMOVE

    removed = entries.pop(
        int(text) - 1
    )

    await update.message.reply_text(
        f"🗑️ Supprimé : {removed['name']}",
        reply_markup=POST_GEN_KEYBOARD,
    )

    return EDIT_MENU


# ==============================================================
# SÉLECTION MODIFICATION
# ==============================================================

async def edit_select(
    update,
    context,
):

    entries = context.user_data.get(
        "entries",
        [],
    )

    text = update.message.text.strip()

    if (
        not text.isdigit()
        or not (
            1 <= int(text) <= len(entries)
        )
    ):

        await update.message.reply_text(
            "❌ Numéro invalide."
        )

        return EDIT_SELECT

    index = int(text) - 1

    context.user_data[
        "edit_index"
    ] = index

    anime = entries[index]

    await update.message.reply_text(
        f"✏️ {anime['name']}\n\n"
        "Que veux-tu modifier ?",
        reply_markup=EDIT_FIELD_KEYBOARD,
    )

    return EDIT_FIELD


# ==============================================================
# CHAMP MODIFICATION
# ==============================================================

async def edit_field(
    update,
    context,
):

    choice = update.message.text.strip().lower()

    if "retour" in choice:

        return await edit_menu(
            update,
            context,
        )

    mapping = {
        "nom": "name",
        "épisode": "episode",
        "heure": "heure",
        "plateforme": "platform",
        "version": "version",
    }

    field = None

    for key, value in mapping.items():

        if key in choice:

            field = value

            break

    if field is None:

        await update.message.reply_text(
            "❌ Choisis un champ.",
            reply_markup=EDIT_FIELD_KEYBOARD,
        )

        return EDIT_FIELD

    context.user_data[
        "edit_field"
    ] = field

    context.user_data[
        "editing_custom_platform"
    ] = False

    if field == "version":

        await update.message.reply_text(
            "🎙️ Nouvelle version ?",
            reply_markup=VERSION_KEYBOARD,
        )

        return EDIT_VALUE

    if field == "platform":

        await update.message.reply_text(
            "📡 Nouvelle plateforme ?",
            reply_markup=PLATFORM_KEYBOARD,
        )

        return EDIT_VALUE

    prompts = {
        "name": "📝 Nouveau nom ?",
        "episode": "📺 Nouvel épisode ?",
        "heure": "🕐 Nouvelle heure ?",
    }

    await update.message.reply_text(
        prompts[field],
        reply_markup=ReplyKeyboardRemove(),
    )

    return EDIT_VALUE


# ==============================================================
# VALEUR MODIFICATION
# ==============================================================

async def edit_value(
    update,
    context,
):

    entries = context.user_data.get(
        "entries",
        [],
    )

    index = context.user_data.get(
        "edit_index"
    )

    field = context.user_data.get(
        "edit_field"
    )

    if (
        index is None
        or field is None
        or index >= len(entries)
    ):

        await update.message.reply_text(
            "❌ Erreur de modification.",
            reply_markup=POST_GEN_KEYBOARD,
        )

        return EDIT_MENU

    value = update.message.text.strip()

    # ----------------------------------------------------------
    # PLATEFORME PERSONNALISÉE
    # ----------------------------------------------------------

    if field == "platform":

        if (
            value == "Autre plateforme"
            and not context.user_data.get(
                "editing_custom_platform"
            )
        ):

            context.user_data[
                "editing_custom_platform"
            ] = True

            await update.message.reply_text(
                "📡 Écris le nom de la plateforme.",
                reply_markup=ReplyKeyboardRemove(),
            )

            return EDIT_VALUE

        if not value:

            await update.message.reply_text(
                "❌ Nom invalide."
            )

            return EDIT_VALUE

        context.user_data[
            "editing_custom_platform"
        ] = False

    # ----------------------------------------------------------
    # VERSION
    # ----------------------------------------------------------

    elif field == "version":

        value = normalize_version(
            value
        )

        if value not in {
            "VF",
            "VO",
            "VOSTANG",
            "LES DEUX",
        }:

            await update.message.reply_text(
                "❌ Version invalide.",
                reply_markup=VERSION_KEYBOARD,
            )

            return EDIT_VALUE

    # ----------------------------------------------------------
    # AUTRES CHAMPS
    # ----------------------------------------------------------

    elif field == "name":

        if not value:

            await update.message.reply_text(
                "❌ Le nom ne peut pas être vide."
            )

            return EDIT_VALUE

    elif field == "episode":

        if not value:

            await update.message.reply_text(
                "❌ L'épisode ne peut pas être vide."
            )

            return EDIT_VALUE

    elif field == "heure":

        if not value:

            await update.message.reply_text(
                "❌ L'heure ne peut pas être vide."
            )

            return EDIT_VALUE

    entries[index][
        field
    ] = value

    context.user_data.pop(
        "edit_field",
        None,
    )

    context.user_data.pop(
        "edit_index",
        None,
    )

    context.user_data.pop(
        "editing_custom_platform",
        None,
    )

    await update.message.reply_text(
        "✅ Modification enregistrée !",
        reply_markup=POST_GEN_KEYBOARD,
    )

    return EDIT_MENU


# ==============================================================
# AUTORISATION
# ==============================================================

async def cmd_autoriser(
    update,
    context,
):

    if update.effective_user.id != ADMIN_ID:

        await update.message.reply_text(
            "⛔ Réservé à l'administrateur."
        )

        return

    if not context.args:

        await update.message.reply_text(
            "Usage : /autoriser ID"
        )

        return

    try:

        user_id = int(
            context.args[0]
        )

    except ValueError:

        await update.message.reply_text(
            "❌ ID invalide."
        )

        return

    users = _load_allowed_users()

    users.add(
        user_id
    )

    _save_allowed_users(
        users
    )

    await update.message.reply_text(
        f"✅ Utilisateur {user_id} autorisé."
    )


async def cmd_revoquer(
    update,
    context,
):

    if update.effective_user.id != ADMIN_ID:

        await update.message.reply_text(
            "⛔ Réservé à l'administrateur."
        )

        return

    if not context.args:

        await update.message.reply_text(
            "Usage : /revoquer ID"
        )

        return

    try:

        user_id = int(
            context.args[0]
        )

    except ValueError:

        await update.message.reply_text(
            "❌ ID invalide."
        )

        return

    users = _load_allowed_users()

    users.discard(
        user_id
    )

    _save_allowed_users(
        users
    )

    await update.message.reply_text(
        f"🚫 Utilisateur {user_id} révoqué."
    )


async def cmd_utilisateurs(
    update,
    context,
):

    if update.effective_user.id != ADMIN_ID:

        await update.message.reply_text(
            "⛔ Réservé à l'administrateur."
        )

        return

    users = _load_allowed_users()

    if not users:

        await update.message.reply_text(
            f"👑 Administrateur : {ADMIN_ID}\n"
            "Aucun utilisateur autorisé."
        )

        return

    listing = "\n".join(
        f"• {user_id}"
        for user_id in sorted(users)
    )

    await update.message.reply_text(
        f"👑 Administrateur : {ADMIN_ID}\n\n"
        f"👥 Utilisateurs :\n{listing}"
    )


# ==============================================================
# ANNULER
# ==============================================================

async def annuler(
    update,
    context,
):

    cleanup_background(
        context
    )

    context.user_data.clear()

    await update.message.reply_text(
        "❌ Création annulée.",
        reply_markup=MAIN_MENU,
    )

    return ConversationHandler.END


# ==============================================================
# ERREURS
# ==============================================================

async def error_handler(
    update,
    context,
):

    logger.error(
        "Erreur Telegram : %s",
        context.error,
        exc_info=context.error,
    )


# ==============================================================
# MAIN
# ==============================================================

def main():

    # ----------------------------------------------------------
    # Vérification TOKEN
    # ----------------------------------------------------------

    if not TOKEN:

        raise RuntimeError(
            "TOKEN TELEGRAM MANQUANT.\n\n"
            "Définis la variable :\n"
            "TELEGRAM_BOT_TOKEN"
        )

    # ----------------------------------------------------------
    # Vérification ADMIN
    # ----------------------------------------------------------

    if ADMIN_ID == 0:

        raise RuntimeError(
            "ADMIN_ID MANQUANT.\n\n"
            "Définis la variable :\n"
            "ADMIN_ID"
        )

    # ----------------------------------------------------------
    # Application
    # ----------------------------------------------------------

    application = (
        Application
        .builder()
        .token(TOKEN)
        .build()
    )

    # ==========================================================
    # CONVERSATION
    # ==========================================================

    conv_handler = ConversationHandler(

        entry_points=[
            CommandHandler(
                "createplanning",
                createplanning,
            ),

            MessageHandler(
                filters.Regex(
                    r"^🗓️ Créer un planning$"
                ),
                createplanning,
            ),
        ],

        states={

            DATE: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    recevoir_date_edit,
                )
            ],

            IMAGE_CHOICE: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    image_choice,
                )
            ],

            IMAGE_UPLOAD: [
                MessageHandler(
                    filters.PHOTO,
                    image_upload,
                )
            ],

            PLATFORM: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    recevoir_platform,
                )
            ],

            CUSTOM_PLATFORM: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    recevoir_custom_platform,
                )
            ],

            NAME: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    recevoir_name,
                )
            ],

            EPISODE: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    recevoir_episode,
                )
            ],

            HEURE: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    recevoir_heure,
                )
            ],

            VERSION: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    recevoir_version,
                )
            ],

            AJOUTER_OU_FIN: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    ajouter_ou_fin,
                )
            ],

            EDIT_MENU: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    edit_menu,
                )
            ],

            EDIT_REMOVE: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    edit_remove,
                )
            ],

            EDIT_SELECT: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    edit_select,
                )
            ],

            EDIT_FIELD: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    edit_field,
                )
            ],

            EDIT_VALUE: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    edit_value,
                )
            ],
        },

        fallbacks=[
            CommandHandler(
                "annuler",
                annuler,
            ),

            MessageHandler(
                filters.Regex(
                    r"^❌ Annuler$"
                ),
                annuler,
            ),
        ],

        allow_reentry=True,
    )

    # ==========================================================
    # COMMANDES
    # ==========================================================

    application.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    application.add_handler(
        CommandHandler(
            "id",
            cmd_id,
        )
    )

    application.add_handler(
        CommandHandler(
            "autoriser",
            cmd_autoriser,
        )
    )

    application.add_handler(
        CommandHandler(
            "revoquer",
            cmd_revoquer,
        )
    )

    application.add_handler(
        CommandHandler(
            "utilisateurs",
            cmd_utilisateurs,
        )
    )

    # ==========================================================
    # BOUTON MON ID
    # ==========================================================

    application.add_handler(
        MessageHandler(
            filters.Regex(
                r"^🆔 Mon ID$"
            ),
            menu_id,
        )
    )

    # ==========================================================
    # BOUTON UTILISATEURS
    # ==========================================================

    application.add_handler(
        MessageHandler(
            filters.Regex(
                r"^👥 Utilisateurs$"
            ),
            menu_users,
        )
    )

    # ==========================================================
    # CONVERSATION
    # ==========================================================

    application.add_handler(
        conv_handler
    )

    # ==========================================================
    # ERREURS
    # ==========================================================

    application.add_error_handler(
        error_handler
    )

    # ==========================================================
    # DÉMARRAGE
    # ==========================================================

    logger.info(
        "🤖 Bot démarré..."
    )

    application.run_polling(
        drop_pending_updates=True
    )


# ==============================================================
# LANCEMENT
# ==============================================================

if __name__ == "__main__":
    main()