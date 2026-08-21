import io
import json
import logging
import os
import tempfile
import textwrap

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

FONT_BOLD = os.path.join(BASE_DIR, "fonts", "Poppins-Bold.ttf")
FONT_MEDIUM = os.path.join(BASE_DIR, "fonts", "Poppins-Medium.ttf")
LOGOS_DIR = os.path.join(BASE_DIR, "logos")

ALLOWED_USERS_FILE = os.path.join(BASE_DIR, "allowed_users.json")

# IMPORTANT :
# Définir ces variables dans l'environnement.
#
# Termux :
# export TELEGRAM_BOT_TOKEN="TON_NOUVEAU_TOKEN"
# export ADMIN_ID="TON_ID"
#
TOKEN = "5834194865:AAE17Q3b6MYioivnm_JlqbYR7kusikH0J2I"

try:
    ADMIN_ID = 5825526159
except ValueError:
    ADMIN_ID = 0


# ==============================================================
# LOGGING
# ==============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
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
GREY_LINE = (70, 72, 80)
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
# OUTILS
# ==============================================================

def _font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        logger.warning("Police introuvable : %s", path)
        return ImageFont.load_default()


def _text_size(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _draw_bold_text(draw, xy, text, font, fill):
    x, y = xy

    draw.text(
        (x, y),
        text,
        font=font,
        fill=fill,
    )


def normalize_platform(name):
    return (
        name.strip()
        .lower()
        .replace("_", " ")
        .replace("amazon prime", "prime video")
    )


def _platform_color(platform_name):
    key = normalize_platform(platform_name)
    return PLATFORM_COLORS.get(key, (90, 95, 105))


def _load_logo(platform_name, target_h):
    fname = (
        platform_name.strip()
        .lower()
        .replace(" ", "_")
        .replace("+", "plus")
    )

    path = os.path.join(LOGOS_DIR, f"{fname}.png")

    if not os.path.isfile(path):
        return None

    try:
        img = Image.open(path).convert("RGBA")

        if img.height <= 0:
            return None

        ratio = target_h / img.height

        new_w = max(1, int(img.width * ratio))

        img = img.resize(
            (new_w, target_h),
            Image.Resampling.LANCZOS,
        )

        return img

    except Exception:
        logger.exception("Impossible de charger le logo : %s", path)
        return None


def _load_background(path, target_w, target_h, darken=160):
    bg = Image.open(path).convert("RGB")

    src_w, src_h = bg.size

    target_ratio = target_w / target_h
    src_ratio = src_w / src_h

    if src_ratio > target_ratio:
        new_w = int(src_h * target_ratio)

        left = (src_w - new_w) // 2

        bg = bg.crop(
            (
                left,
                0,
                left + new_w,
                src_h,
            )
        )

    else:
        new_h = int(src_w / target_ratio)

        top = (src_h - new_h) // 2

        bg = bg.crop(
            (
                0,
                top,
                src_w,
                top + new_h,
            )
        )

    bg = bg.resize(
        (target_w, target_h),
        Image.Resampling.LANCZOS,
    )

    overlay = Image.new(
        "RGBA",
        (target_w, target_h),
        (18, 19, 23, darken),
    )

    bg = bg.convert("RGBA")

    bg = Image.alpha_composite(
        bg,
        overlay,
    )

    return bg.convert("RGB")


def fit_text(draw, text, font_path, max_width, start_size, min_size=18):
    """
    Réduit automatiquement la taille du texte jusqu'à ce qu'il entre
    dans la largeur disponible.
    """

    size = start_size

    while size >= min_size:
        font = _font(font_path, size)
        width, _ = _text_size(draw, text, font)

        if width <= max_width:
            return font

        size -= 2

    return _font(font_path, min_size)


def clean_title(title):
    title = " ".join(title.strip().split())

    if not title:
        return "ANIME"

    return title.upper()


def get_version_label(version):
    version = version.upper().strip()

    if version == "LES DEUX":
        return "VF + VO"

    return version


# ==============================================================
# GÉNÉRATION DE L'IMAGE
# ==============================================================

def generate_planning_image(
    date_str,
    entries,
    footer_text="ABONNEZ-VOUS À NOTRE COMPTE",
    footer_site="",
    background_path=None,
):

    W = W_BASE

    platforms_order = []
    by_platform = {}

    for entry in entries:

        version = entry.get("version", "").upper().strip()

        # Une entrée uniquement VF est affichée
        # uniquement dans "LES SORTIES VF".
        if version == "VF":
            continue

        platform = entry["platform"].strip()

        if platform not in by_platform:
            by_platform[platform] = []
            platforms_order.append(platform)

        by_platform[platform].append(entry)

    vf_entries = [
        e
        for e in entries
        if e["version"].upper() in ("VF", "LES DEUX")
    ]

    # ----------------------------------------------------------
    # POLICES
    # ----------------------------------------------------------

    f_title = _font(FONT_BOLD, 64)
    f_subtitle = _font(FONT_BOLD, 40)
    f_platform_badge = _font(FONT_BOLD, 26)

    f_row = _font(FONT_BOLD, 32)
    f_vf_title = _font(FONT_BOLD, 46)
    f_footer = _font(FONT_BOLD, 22)

    # ----------------------------------------------------------
    # DIMENSIONS
    # ----------------------------------------------------------

    row_h = 72
    platform_block_gap = 40

    header_h = 330

    y = header_h

    for platform in platforms_order:

        y += 90

        y += len(by_platform[platform]) * row_h

        y += platform_block_gap

    vf_header_h = 150 if vf_entries else 0

    y += vf_header_h

    y += len(vf_entries) * row_h

    y += 150

    H_content = max(H_MIN, y)

    # Ratio 3:4
    H_ratio = round(W * 4 / 3)

    if H_content <= H_ratio:

        H = H_ratio

    else:

        H = H_content
        W = round(H * 3 / 4)

    # ----------------------------------------------------------
    # CALQUE DU CONTENU
    # ----------------------------------------------------------

    content = Image.new(
        "RGBA",
        (W, H_content),
        (0, 0, 0, 0),
    )

    draw = ImageDraw.Draw(content)

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

    _draw_bold_text(
        draw,
        (PADDING_X + 70, cy - 8),
        "PLANNING",
        f_title,
        WHITE,
    )

    cy += 100

    # ----------------------------------------------------------
    # SOUS-TITRE
    # ----------------------------------------------------------

    prefix = "LES SORTIES ANIMES DU "

    _draw_bold_text(
        draw,
        (PADDING_X, cy),
        prefix,
        f_subtitle,
        WHITE,
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

    _draw_bold_text(
        draw,
        (
            PADDING_X + prefix_w + 10,
            cy,
        ),
        date_str.upper(),
        date_font,
        BLUE_ACCENT,
    )

    cy += 130

    # ----------------------------------------------------------
    # PLATEFORMES
    # ----------------------------------------------------------

    logo_h = 70

    for platform in platforms_order:

        color = _platform_color(platform)

        # trait gauche
        draw.rectangle(
            [
                0,
                cy,
                14,
                cy + logo_h,
            ],
            fill=(230, 90, 20),
        )

        platform_text = platform.upper()

        tw_badge, _ = _text_size(
            draw,
            platform_text,
            f_platform_badge,
        )

        badge_w = max(
            210,
            tw_badge + 80,
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

        logo_img = _load_logo(
            platform,
            logo_h - 20,
        )

        if logo_img:

            max_logo_w = badge_w - 30

            if logo_img.width > max_logo_w:

                ratio = max_logo_w / logo_img.width

                logo_img = logo_img.resize(
                    (
                        int(logo_img.width * ratio),
                        int(logo_img.height * ratio),
                    ),
                    Image.Resampling.LANCZOS,
                )

            content.paste(
                logo_img,
                (
                    PADDING_X
                    + (badge_w - logo_img.width) // 2,
                    cy
                    + (logo_h - logo_img.height) // 2,
                ),
                logo_img,
            )

        else:

            tw, th = _text_size(
                draw,
                platform_text,
                f_platform_badge,
            )

            draw.text(
                (
                    PADDING_X
                    + (badge_w - tw) // 2,
                    cy
                    + (logo_h - th) // 2
                    - 4,
                ),
                platform_text,
                font=f_platform_badge,
                fill=WHITE,
            )

        cy += logo_h + 30

        # ------------------------------------------------------
        # COLONNES
        # ------------------------------------------------------

        col_name_x = PADDING_X

        col_ep_x = int(W * 0.62)

        col_time_x = int(W * 0.84)

        for entry in by_platform[platform]:

            title = clean_title(entry["name"])

            available_width = (
                col_ep_x
                - col_name_x
                - 40
            )

            title_font = fit_text(
                draw,
                title,
                FONT_BOLD,
                available_width,
                32,
                20,
            )

            _draw_bold_text(
                draw,
                (
                    col_name_x,
                    cy,
                ),
                title,
                title_font,
                WHITE,
            )

            episode_text = f"EP {entry['episode']}"

            episode_font = fit_text(
                draw,
                episode_text,
                FONT_BOLD,
                col_time_x - col_ep_x - 30,
                30,
                20,
            )

            _draw_bold_text(
                draw,
                (
                    col_ep_x,
                    cy,
                ),
                episode_text,
                episode_font,
                WHITE,
            )

            time_text = entry["heure"].upper()

            time_font = fit_text(
                draw,
                time_text,
                FONT_BOLD,
                W - col_time_x - PADDING_X,
                30,
                20,
            )

            _draw_bold_text(
                draw,
                (
                    col_time_x,
                    cy,
                ),
                time_text,
                time_font,
                BLUE_ACCENT,
            )

            cy += row_h

        cy += platform_block_gap

    # ----------------------------------------------------------
    # SORTIES VF
    # ----------------------------------------------------------

    if vf_entries:

        cy += 10

        tw_vf, _ = _text_size(
            draw,
            "LES SORTIES VF",
            f_vf_title,
        )

        badge_w2 = max(
            560,
            tw_vf + 160,
        )

        badge_h2 = 90

        draw.rounded_rectangle(
            [
                PADDING_X,
                cy,
                PADDING_X + badge_w2,
                cy + badge_h2,
            ],
            radius=24,
            fill=ORANGE,
        )

        # drapeau français
        flag_x = PADDING_X + 30
        flag_y = cy + 25

        flag_w = 60
        flag_h = 40

        band_w = flag_w // 3

        draw.rectangle(
            [
                flag_x,
                flag_y,
                flag_x + band_w,
                flag_y + flag_h,
            ],
            fill=(0, 85, 164),
        )

        draw.rectangle(
            [
                flag_x + band_w,
                flag_y,
                flag_x + 2 * band_w,
                flag_y + flag_h,
            ],
            fill=WHITE,
        )

        draw.rectangle(
            [
                flag_x + 2 * band_w,
                flag_y,
                flag_x + flag_w,
                flag_y + flag_h,
            ],
            fill=(239, 65, 53),
        )

        _draw_bold_text(
            draw,
            (
                flag_x + flag_w + 20,
                cy + 20,
            ),
            "LES SORTIES VF",
            f_vf_title,
            WHITE,
        )

        cy += badge_h2 + 50

        col_name_x = PADDING_X + 65
        col_ep_x = int(W * 0.62)
        col_time_x = int(W * 0.84)

        for entry in vf_entries:

            color = _platform_color(
                entry["platform"]
            )

            # badge plateforme
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

            initial = entry["platform"][:1].upper()

            tw, th = _text_size(
                draw,
                initial,
                f_platform_badge,
            )

            draw.text(
                (
                    PADDING_X
                    + (44 - tw) // 2,
                    cy + 6
                    + (44 - th) // 2
                    - 2,
                ),
                initial,
                font=f_platform_badge,
                fill=WHITE,
            )

            available_width = (
                col_ep_x
                - col_name_x
                - 30
            )

            title = clean_title(
                entry["name"]
            )

            title_font = fit_text(
                draw,
                title,
                FONT_BOLD,
                available_width,
                32,
                20,
            )

            _draw_bold_text(
                draw,
                (
                    col_name_x,
                    cy,
                ),
                title,
                title_font,
                WHITE,
            )

            _draw_bold_text(
                draw,
                (
                    col_ep_x,
                    cy,
                ),
                f"ÉPISODE {entry['episode']}",
                f_row,
                WHITE,
            )

            _draw_bold_text(
                draw,
                (
                    col_time_x,
                    cy,
                ),
                entry["heure"].upper(),
                f_row,
                BLUE_ACCENT,
            )

            cy += row_h

    # ----------------------------------------------------------
    # FOND
    # ----------------------------------------------------------

    if background_path and os.path.isfile(background_path):

        try:

            img = _load_background(
                background_path,
                W,
                H,
            )

        except Exception:

            logger.exception(
                "Erreur chargement fond"
            )

            img = Image.new(
                "RGB",
                (W, H),
                BG_COLOR,
            )

    else:

        img = Image.new(
            "RGB",
            (W, H),
            BG_COLOR,
        )

        side_draw = ImageDraw.Draw(img)

        side_draw.rectangle(
            [
                0,
                0,
                260,
                H,
            ],
            fill=(38, 40, 47),
        )

    # ----------------------------------------------------------
    # CONTENU CENTRÉ
    # ----------------------------------------------------------

    offset_y = max(
        0,
        (H - H_content) // 2,
    )

    img.paste(
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

    final_draw = ImageDraw.Draw(img)

    footer_full = footer_text

    if footer_site:
        footer_full += (
            "  |  "
            + footer_site.upper()
        )

    fw, fh = _text_size(
        final_draw,
        footer_full,
        f_footer,
    )

    final_draw.text(
        (
            (W - fw) // 2,
            H - 70,
        ),
        footer_full,
        font=f_footer,
        fill=GREY_TEXT,
    )

    # ----------------------------------------------------------
    # SORTIE
    # ----------------------------------------------------------

    buf = io.BytesIO()

    img.save(
        buf,
        format="PNG",
        optimize=True,
    )

    buf.seek(0)

    return buf


# ==============================================================
# UTILISATEURS AUTORISÉS
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

    except (
        json.JSONDecodeError,
        OSError,
        ValueError,
    ):

        return set()


def _save_allowed_users(users):

    with open(
        ALLOWED_USERS_FILE,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            sorted(users),
            f,
            ensure_ascii=False,
            indent=2,
        )


def is_authorized(user_id):

    if ADMIN_ID == 0:
        return False

    if user_id == ADMIN_ID:
        return True

    return user_id in _load_allowed_users()


# ==============================================================
# ÉTATS
# ==============================================================

(
    DATE,
    BACKGROUND,
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
) = range(14)


# ==============================================================
# CLAVIERS
# ==============================================================

BACKGROUND_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["🚫 Pas d'image de fond"],
    ],
    one_time_keyboard=True,
    resize_keyboard=True,
)

VERSION_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["VF", "VO"],
        ["Les deux", "VOSTANG"],
    ],
    one_time_keyboard=True,
    resize_keyboard=True,
)

CONTINUER_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["➕ Ajouter un anime"],
        ["✅ Terminer et générer l'image"],
    ],
    one_time_keyboard=True,
    resize_keyboard=True,
)

PLATFORM_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["Prime video", "Crunchyroll"],
        ["Netflix", "ADN"],
        ["Autre plateforme"],
    ],
    one_time_keyboard=True,
    resize_keyboard=True,
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
# OUTILS CONVERSATION
# ==============================================================

async def ask_platform(update, context, next_state=PLATFORM):

    await update.message.reply_text(
        "📡 Plateforme de diffusion ?",
        reply_markup=PLATFORM_KEYBOARD,
    )

    return next_state


async def send_planning(update, context):

    image_buf = generate_planning_image(
        date_str=context.user_data.get(
            "date",
            "",
        ),
        entries=context.user_data.get(
            "entries",
            [],
        ),
        background_path=context.user_data.get(
            "background_path"
        ),
    )

    await update.message.reply_photo(
        photo=image_buf,
        caption=(
            "📌 Planning des sorties animes du "
            f"{context.user_data.get('date', '')}"
        ),
    )


def cleanup_background(context):

    path = context.user_data.get(
        "background_path"
    )

    if path and os.path.isfile(path):

        try:
            os.remove(path)
        except OSError:
            pass


# ==============================================================
# CRÉATION
# ==============================================================

async def createplanning(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not is_authorized(
        update.effective_user.id
    ):

        await update.message.reply_text(
            "⛔ Tu n'es pas autorisé à utiliser ce bot."
        )

        return ConversationHandler.END

    context.user_data.clear()

    context.user_data["entries"] = []

    await update.message.reply_text(
        "🗓️ Création d'un nouveau planning.\n\n"
        "Quelle est la date à afficher ?\n"
        "Exemple : Mardi 18 Août",
        reply_markup=ReplyKeyboardRemove(),
    )

    return DATE


async def recevoir_date(
    update,
    context,
):

    date = update.message.text.strip()

    if not date:

        await update.message.reply_text(
            "❌ La date ne peut pas être vide."
        )

        return DATE

    context.user_data["date"] = date

    context.user_data["background_path"] = None

    await update.message.reply_text(
        "🖼️ Veux-tu ajouter une image de fond ?\n\n"
        "Envoie-moi directement une photo, "
        "ou utilise le bouton ci-dessous.",
        reply_markup=BACKGROUND_KEYBOARD,
    )

    return BACKGROUND


async def recevoir_background(
    update,
    context,
):

    if update.message.photo:

        photo = update.message.photo[-1]

        file = await photo.get_file()

        tmp_path = os.path.join(
            tempfile.gettempdir(),
            f"planning_bg_{update.effective_chat.id}.jpg",
        )

        await file.download_to_drive(
            tmp_path
        )

        context.user_data[
            "background_path"
        ] = tmp_path

        await update.message.reply_text(
            "🖼️ Image de fond enregistrée !",
            reply_markup=ReplyKeyboardRemove(),
        )

    else:

        context.user_data[
            "background_path"
        ] = None

        await update.message.reply_text(
            "🚫 Pas d'image de fond.",
            reply_markup=ReplyKeyboardRemove(),
        )

    return await ask_platform(
        update,
        context,
    )


async def recevoir_platform(
    update,
    context,
):

    platform = update.message.text.strip()

    if platform == "Autre plateforme":

        await update.message.reply_text(
            "📡 Écris le nom de la plateforme :",
            reply_markup=ReplyKeyboardRemove(),
        )

        return CUSTOM_PLATFORM

    context.user_data["current"] = {
        "platform": platform
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
            "❌ Le nom de la plateforme ne peut pas être vide."
        )

        return CUSTOM_PLATFORM

    context.user_data["current"] = {
        "platform": platform
    }

    await update.message.reply_text(
        "📝 Nom de l'anime ?"
    )

    return NAME


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
            "❌ Indique un numéro d'épisode."
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
        "🎙️ Version ?",
        reply_markup=VERSION_KEYBOARD,
    )

    return VERSION


async def recevoir_version(
    update,
    context,
):

    version_txt = (
        update.message.text
        .strip()
        .upper()
    )

    valid_versions = {
        "VF",
        "VO",
        "VOSTANG",
        "LES DEUX",
    }

    if version_txt not in valid_versions:

        await update.message.reply_text(
            "❌ Choisis une version avec les boutons.",
            reply_markup=VERSION_KEYBOARD,
        )

        return VERSION

    context.user_data[
        "current"
    ]["version"] = version_txt

    context.user_data[
        "entries"
    ].append(
        context.user_data["current"]
    )

    recap = context.user_data[
        "entries"
    ][-1]

    context.user_data["current"] = {}

    await update.message.reply_text(
        "✅ Anime ajouté !\n\n"
        f"🎬 {recap['name']}\n"
        f"📺 Épisode : {recap['episode']}\n"
        f"🕐 Heure : {recap['heure']}\n"
        f"📡 Plateforme : {recap['platform']}\n"
        f"🎙️ Version : {get_version_label(recap['version'])}\n\n"
        "Que veux-tu faire ?",
        reply_markup=CONTINUER_KEYBOARD,
    )

    return AJOUTER_OU_FIN


# ==============================================================
# APRÈS AJOUT
# ==============================================================

async def ajouter_ou_fin(
    update,
    context,
):

    choix = (
        update.message.text
        .strip()
        .lower()
    )

    if "ajouter" in choix:

        return await ask_platform(
            update,
            context,
        )

    if (
        "terminer" in choix
        or "générer" in choix
        or "generer" in choix
    ):

        entries = context.user_data.get(
            "entries",
            [],
        )

        if not entries:

            await update.message.reply_text(
                "❌ Aucun anime n'a été ajouté.",
                reply_markup=ReplyKeyboardRemove(),
            )

            return ConversationHandler.END

        await update.message.reply_text(
            "🖼️ Génération de l'image...",
            reply_markup=ReplyKeyboardRemove(),
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
        "Choisis une option avec les boutons.",
        reply_markup=CONTINUER_KEYBOARD,
    )

    return AJOUTER_OU_FIN


# ==============================================================
# MENU APRÈS GÉNÉRATION
# ==============================================================

async def edit_menu(
    update,
    context,
):

    choix = (
        update.message.text
        .strip()
        .lower()
    )

    if "ajouter" in choix:

        return await ask_platform(
            update,
            context,
        )

    if "modifier un anime" in choix:

        entries = context.user_data.get(
            "entries",
            [],
        )

        if not entries:

            await update.message.reply_text(
                "❌ Aucun anime à modifier.",
                reply_markup=POST_GEN_KEYBOARD,
            )

            return EDIT_MENU

        liste = "\n".join(
            f"{i + 1}. {e['name']} "
            f"(Ep. {e['episode']} — {e['heure']})"
            for i, e in enumerate(entries)
        )

        await update.message.reply_text(
            "✏️ Quel anime veux-tu modifier ?\n\n"
            f"{liste}\n\n"
            "Tape son numéro.",
            reply_markup=ReplyKeyboardRemove(),
        )

        return EDIT_SELECT

    if "supprimer" in choix:

        entries = context.user_data.get(
            "entries",
            [],
        )

        if not entries:

            await update.message.reply_text(
                "❌ Aucun anime à supprimer.",
                reply_markup=POST_GEN_KEYBOARD,
            )

            return EDIT_MENU

        liste = "\n".join(
            f"{i + 1}. {e['name']} "
            f"(Ep. {e['episode']}, {e['heure']})"
            for i, e in enumerate(entries)
        )

        await update.message.reply_text(
            f"🗑️ Animes actuels :\n\n"
            f"{liste}\n\n"
            "Tape le numéro à supprimer.",
            reply_markup=ReplyKeyboardRemove(),
        )

        return EDIT_REMOVE

    if "modifier le fond" in choix:

        await update.message.reply_text(
            "🖼️ Envoie-moi la nouvelle image de fond.\n"
            "Ou tape « supprimer » pour revenir à un fond uni.",
            reply_markup=ReplyKeyboardRemove(),
        )

        context.user_data[
            "changing_background"
        ] = True

        return BACKGROUND

    if "modifier la date" in choix:

        await update.message.reply_text(
            "📅 Quelle nouvelle date veux-tu utiliser ?",
            reply_markup=ReplyKeyboardRemove(),
        )

        context.user_data[
            "changing_date"
        ] = True

        return DATE

    if (
        "régénérer" in choix
        or "regenerer" in choix
    ):

        await update.message.reply_text(
            "🔁 Régénération...",
            reply_markup=ReplyKeyboardRemove(),
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

    if "nouveau" in choix:

        cleanup_background(
            context
        )

        context.user_data.clear()

        context.user_data[
            "entries"
        ] = []

        await update.message.reply_text(
            "🆕 Nouveau planning.\n\n"
            "Quelle est la date à afficher ?",
            reply_markup=ReplyKeyboardRemove(),
        )

        return DATE

    if (
        "terminé" in choix
        or "termine" in choix
    ):

        cleanup_background(
            context
        )

        context.user_data.clear()

        await update.message.reply_text(
            "👍 Planning terminé !",
            reply_markup=ReplyKeyboardRemove(),
        )

        return ConversationHandler.END

    await update.message.reply_text(
        "Choisis une option avec les boutons.",
        reply_markup=POST_GEN_KEYBOARD,
    )

    return EDIT_MENU


# ==============================================================
# MODIFICATION DATE
# ==============================================================

async def recevoir_date_edit(
    update,
    context,
):

    if context.user_data.get(
        "changing_date"
    ):

        date = update.message.text.strip()

        if not date:

            await update.message.reply_text(
                "❌ Date invalide."
            )

            return DATE

        context.user_data[
            "date"
        ] = date

        context.user_data[
            "changing_date"
        ] = False

        await update.message.reply_text(
            "📅 Date modifiée.",
            reply_markup=POST_GEN_KEYBOARD,
        )

        return EDIT_MENU

    return await recevoir_date(
        update,
        context,
    )


# ==============================================================
# MODIFICATION FOND
# ==============================================================

async def recevoir_background_edit(
    update,
    context,
):

    # ==========================================================
    # CRÉATION D'UN NOUVEAU PLANNING
    # ==========================================================

    if not context.user_data.get("changing_background"):

        if update.message.photo:

            photo = update.message.photo[-1]

            file = await photo.get_file()

            tmp_path = os.path.join(
                tempfile.gettempdir(),
                f"planning_bg_{update.effective_chat.id}.jpg",
            )

            await file.download_to_drive(tmp_path)

            context.user_data[
                "background_path"
            ] = tmp_path

            await update.message.reply_text(
                "🖼️ Image de fond enregistrée !",
                reply_markup=ReplyKeyboardRemove(),
            )

        else:

            texte = update.message.text.strip().lower()

            if texte in (
                "🚫 pas d'image de fond",
                "pas d'image de fond",
            ):

                context.user_data[
                    "background_path"
                ] = None

                await update.message.reply_text(
                    "🚫 Pas d'image de fond.",
                    reply_markup=ReplyKeyboardRemove(),
                )

            else:

                await update.message.reply_text(
                    "📷 Envoie une photo ou utilise "
                    "« 🚫 Pas d'image de fond ».",
                    reply_markup=BACKGROUND_KEYBOARD,
                )

                return BACKGROUND

        # Après le fond → plateforme
        return await ask_platform(
            update,
            context,
        )

    # ==========================================================
    # MODIFICATION DU FOND APRÈS GÉNÉRATION
    # ==========================================================

    if update.message.photo:

        photo = update.message.photo[-1]

        file = await photo.get_file()

        old_path = context.user_data.get(
            "background_path"
        )

        if old_path and os.path.isfile(old_path):

            try:
                os.remove(old_path)
            except OSError:
                pass

        tmp_path = os.path.join(
            tempfile.gettempdir(),
            f"planning_bg_{update.effective_chat.id}.jpg",
        )

        await file.download_to_drive(tmp_path)

        context.user_data[
            "background_path"
        ] = tmp_path

        context.user_data[
            "changing_background"
        ] = False

        await update.message.reply_text(
            "🖼️ Fond modifié !",
            reply_markup=POST_GEN_KEYBOARD,
        )

        return EDIT_MENU

    texte = update.message.text.strip().lower()

    if texte in (
        "supprimer",
        "🚫 pas d'image de fond",
    ):

        cleanup_background(context)

        context.user_data[
            "background_path"
        ] = None

        context.user_data[
            "changing_background"
        ] = False

        await update.message.reply_text(
            "🖼️ Fond supprimé.",
            reply_markup=POST_GEN_KEYBOARD,
        )

        return EDIT_MENU

    await update.message.reply_text(
        "📷 Envoie une photo ou tape « supprimer ».",
        reply_markup=ReplyKeyboardRemove(),
    )

    return BACKGROUND


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

    texte = update.message.text.strip()

    if (
        not texte.isdigit()
        or not (
            1 <= int(texte) <= len(entries)
        )
    ):

        await update.message.reply_text(
            f"❌ Tape un numéro entre 1 et {len(entries)}."
        )

        return EDIT_REMOVE

    removed = entries.pop(
        int(texte) - 1
    )

    await update.message.reply_text(
        f"🗑️ Supprimé : {removed['name']}\n\n"
        "Que veux-tu faire ensuite ?",
        reply_markup=POST_GEN_KEYBOARD,
    )

    return EDIT_MENU


# ==============================================================
# SÉLECTION D'UN ANIME À MODIFIER
# ==============================================================

async def edit_select(
    update,
    context,
):

    entries = context.user_data.get(
        "entries",
        [],
    )

    texte = update.message.text.strip()

    if (
        not texte.isdigit()
        or not (
            1 <= int(texte) <= len(entries)
        )
    ):

        await update.message.reply_text(
            f"❌ Tape un numéro entre 1 et {len(entries)}."
        )

        return EDIT_SELECT

    index = int(texte) - 1

    context.user_data[
        "edit_index"
    ] = index

    anime = entries[index]

    await update.message.reply_text(
        f"✏️ Modification de :\n\n"
        f"🎬 {anime['name']}\n"
        f"📺 Épisode {anime['episode']}\n"
        f"🕐 {anime['heure']}\n"
        f"📡 {anime['platform']}\n"
        f"🎙️ {get_version_label(anime['version'])}\n\n"
        "Que veux-tu modifier ?",
        reply_markup=EDIT_FIELD_KEYBOARD,
    )

    return EDIT_FIELD


# ==============================================================
# CHOIX DU CHAMP
# ==============================================================

async def edit_field(
    update,
    context,
):

    choix = update.message.text.strip().lower()

    if "retour" in choix:

        await update.message.reply_text(
            "Retour.",
            reply_markup=POST_GEN_KEYBOARD,
        )

        return EDIT_MENU

    mapping = {
        "nom": "name",
        "épisode": "episode",
        "heure": "heure",
        "plateforme": "platform",
        "version": "version",
    }

    field = None

    for key, value in mapping.items():

        if key in choix:
            field = value
            break

    if field is None:

        await update.message.reply_text(
            "Choisis un champ avec les boutons.",
            reply_markup=EDIT_FIELD_KEYBOARD,
        )

        return EDIT_FIELD

    context.user_data[
        "edit_field"
    ] = field

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
        "name": "📝 Nouveau nom de l'anime ?",
        "episode": "📺 Nouveau numéro d'épisode ?",
        "heure": "🕐 Nouvelle heure ?",
    }

    await update.message.reply_text(
        prompts[field],
        reply_markup=ReplyKeyboardRemove(),
    )

    return EDIT_VALUE


# ==============================================================
# VALEUR DU CHAMP
# ==============================================================

async def edit_value(
    update,
    context,
):

    field = context.user_data.get(
        "edit_field"
    )

    index = context.user_data.get(
        "edit_index"
    )

    entries = context.user_data.get(
        "entries",
        [],
    )

    if (
        field is None
        or index is None
        or index >= len(entries)
    ):

        await update.message.reply_text(
            "❌ Erreur de modification.",
            reply_markup=POST_GEN_KEYBOARD,
        )

        return EDIT_MENU

    value = update.message.text.strip()

    if field == "version":

        value = value.upper()

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

    elif field == "platform":

        if value == "Autre plateforme":

            context.user_data[
                "editing_custom_platform"
            ] = True

            await update.message.reply_text(
                "📡 Écris le nouveau nom de la plateforme :",
                reply_markup=ReplyKeyboardRemove(),
            )

            return EDIT_VALUE

    if (
        context.user_data.get(
            "editing_custom_platform"
        )
    ):

        value = update.message.text.strip()

        if not value:

            await update.message.reply_text(
                "❌ Nom invalide."
            )

            return EDIT_VALUE

        context.user_data[
            "editing_custom_platform"
        ] = False

    entries[index][field] = value

    # nettoyage
    context.user_data.pop(
        "edit_field",
        None,
    )

    context.user_data.pop(
        "edit_index",
        None,
    )

    await update.message.reply_text(
        "✅ Modification enregistrée !",
        reply_markup=POST_GEN_KEYBOARD,
    )

    return EDIT_MENU


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
        reply_markup=ReplyKeyboardRemove(),
    )

    return ConversationHandler.END


# ==============================================================
# COMMANDES
# ==============================================================

async def start(
    update,
    context,
):

    await update.message.reply_text(
        "👋 Salut !\n\n"
        "Je suis le générateur de planning anime.\n\n"
        "Utilise :\n"
        "🗓️ /createplanning — créer un planning\n"
        "🆔 /id — afficher ton ID Telegram\n"
        "❌ /annuler — annuler"
    )


async def cmd_id(
    update,
    context,
):

    await update.message.reply_text(
        f"🆔 Ton ID Telegram : "
        f"{update.effective_user.id}"
    )


async def cmd_autoriser(
    update,
    context,
):

    if update.effective_user.id != ADMIN_ID:

        await update.message.reply_text(
            "⛔ Seul l'administrateur peut faire ça."
        )

        return

    if not context.args:

        await update.message.reply_text(
            "Usage : /autoriser <id_telegram>"
        )

        return

    try:

        new_id = int(
            context.args[0]
        )

    except ValueError:

        await update.message.reply_text(
            "❌ L'ID doit être un nombre."
        )

        return

    users = _load_allowed_users()

    users.add(new_id)

    _save_allowed_users(
        users
    )

    await update.message.reply_text(
        f"✅ Utilisateur {new_id} autorisé."
    )


async def cmd_revoquer(
    update,
    context,
):

    if update.effective_user.id != ADMIN_ID:

        await update.message.reply_text(
            "⛔ Seul l'administrateur peut faire ça."
        )

        return

    if not context.args:

        await update.message.reply_text(
            "Usage : /revoquer <id_telegram>"
        )

        return

    try:

        old_id = int(
            context.args[0]
        )

    except ValueError:

        await update.message.reply_text(
            "❌ L'ID doit être un nombre."
        )

        return

    users = _load_allowed_users()

    users.discard(old_id)

    _save_allowed_users(
        users
    )

    await update.message.reply_text(
        f"🚫 Utilisateur {old_id} révoqué."
    )


async def cmd_utilisateurs(
    update,
    context,
):

    if update.effective_user.id != ADMIN_ID:

        await update.message.reply_text(
            "⛔ Seul l'administrateur peut faire ça."
        )

        return

    users = _load_allowed_users()

    if not users:

        await update.message.reply_text(
            f"👑 Administrateur : {ADMIN_ID}\n"
            "Aucun autre utilisateur autorisé."
        )

        return

    liste = "\n".join(
        f"• {user_id}"
        for user_id in sorted(users)
    )

    await update.message.reply_text(
        f"👑 Administrateur : {ADMIN_ID}\n\n"
        f"👥 Utilisateurs autorisés :\n{liste}"
    )


# ==============================================================
# MAIN
# ==============================================================

def main():

    if not TOKEN:

        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN n'est pas défini.\n\n"
            "Exemple Termux :\n"
            'export TELEGRAM_BOT_TOKEN="TON_TOKEN"\n'
            'export ADMIN_ID="TON_ID"'
        )

    if ADMIN_ID == 0:

        raise RuntimeError(
            "ADMIN_ID n'est pas défini.\n\n"
            "Exemple :\n"
            'export ADMIN_ID="5825526159"'
        )

    application = (
        Application
        .builder()
        .token(TOKEN)
        .build()
    )

    conv_handler = ConversationHandler(

        entry_points=[
            CommandHandler(
                "createplanning",
                createplanning,
            )
        ],

        states={

            DATE: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    recevoir_date_edit,
                )
            ],

            BACKGROUND: [
                MessageHandler(
                    filters.PHOTO
                    | (
                        filters.TEXT
                        & ~filters.COMMAND
                    ),
                    recevoir_background_edit,
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
            )
        ],

        allow_reentry=True,
    )

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

    application.add_handler(
        conv_handler
    )

    logger.info(
        "🤖 Bot démarré..."
    )

    application.run_polling()


# ==============================================================
# LANCEMENT
# ==============================================================

if __name__ == "__main__":
    main()