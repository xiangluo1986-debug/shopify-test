import json
import os
import re
import time
from html import escape
from html.parser import HTMLParser
from pathlib import Path

import requests
from django.core.management.base import BaseCommand, CommandError

from shopify_sync.models import ShopifyInstallation


SHOPIFY_API_VERSION = "2026-01"
OPENAI_MODEL = "gpt-4.1-mini"
TRANSLATABLE_KEYS = {"title", "body_html", "meta_title", "meta_description"}
FIELD_ORDER = ["title", "body_html", "meta_title", "meta_description"]
OPENAI_RETRY_DELAYS = [5, 15, 30]
ORIGIN_PATTERNS = [
    r"\borigin\b",
    r"\bmade\s+in\s+china\b",
    r"\bmainland\s+china\b",
    r"\bchina\s+origin\b",
    r"\bherkunft\b",
    r"\bursprung\b",
    r"\bhergestellt\s+in\s+(?:festlandchina|china)\b",
    r"\bfestlandchina\b",
]
ORIGIN_RE = re.compile("|".join(ORIGIN_PATTERNS), flags=re.IGNORECASE)
SHIPPING_ALT_PATTERNS = [
    r"\bworldwide\s+shipping\b",
    r"\bships\s+worldwide\b",
    r"\bshipping\b",
    r"\bdelivery\b",
    r"\bversand\b",
    r"\blieferung\b",
    r"\bweltweit\s+versandf[aä]hig\b",
    r"\bweltweiter\s+versand\b",
    r"\bversand\s+weltweit\b",
    r"\blieferung\s+weltweit\b",
]
SHIPPING_MARKETING_RE = re.compile("|".join(SHIPPING_ALT_PATTERNS), flags=re.IGNORECASE)
AI_CTA_RE = re.compile(
    r"\b(?:jetzt\s+kaufen|buy\s+now|shop\s+now|jetzt\s+shoppen)\b",
    flags=re.IGNORECASE,
)
KEYWORD_STUFFING_RE = re.compile(
    r"(?:\b(?:RC|Gyro|Kinder|ferngesteuert|bürstenlos|Brushless|Remote Control|RC Toy|RC Flugzeug|RC Auto)\b[\s,;/-]*){4,}",
    flags=re.IGNORECASE,
)
AWKWARD_3D_GERMAN_RE = re.compile(
    r"\b(?:3D-Flugdesign|3D-Stabilflug-Flügel|3D-Flügel)\b",
    flags=re.IGNORECASE,
)
MAX_IMG_ALT_CHARS = 120
MAX_PRODUCT_TITLE_CHARS = 65
MAX_META_TITLE_CHARS = 60
MAX_META_DESCRIPTION_CHARS = 160
GERMAN_QA_REPLACEMENTS = {
    "Produkhighlights": "Produkt-Highlights",
    "Produkthighlights": "Produkt-Highlights",
    "Produkt Highlights": "Produkt-Highlights",
    "Product Highlights": "Produkt-Highlights",
    "Paketinhalt": "Lieferumfang",
    "Packungsinhalt": "Lieferumfang",
    "Technische Spezifikationen": "Technische Daten",
    "Spezifikationen": "Technische Daten",
    "Technische Daten & Und Fotos": "Technische Daten & Fotos",
    "Technische Daten &amp; Und Fotos": "Technische Daten &amp; Fotos",
    "Montagetipps": "Montage-Tipps",
    "Installationstipps": "Montage-Tipps",
    "Support und Garantie": "Support & Garantie",
    "High-Torque Brushed Motor": "Hochdrehmoment-Bürstenmotor",
    "Brushed Motor": "Bürstenmotor",
    "Replacement": "Ersatzteil",
    "High-Torque": "Hochdrehmoment",
    "Wingspan": "",
    "Abbrechersystem": "Schutzsystem",
    "Abbruchsystem": "Schutzsystem",
    "Propellerhalterungswellenbasis": "Propellerhalterung",
    "Propellerhalterungswelle": "Propellerhalterung",
    "Propellerhalterungsbasis": "Propellerhalterung",
    "Prop Saver Welle Basis": "Propellerhalterung",
    "Prop-Saver-Wellenbasis": "Propellerhalterung",
    "Propellerhalterung-Basis": "Propellerhalterung",
    "RC Trainer RC Flugzeug": "RC Flugzeug",
    "RC Trainerflugzeug": "RC Flugzeug",
    "Trainigs-RC": "Trainings-RC",
    "Trainigsflugzeugs": "Trainingsflugzeugs",
    "Trainings-RC Flugzeuges": "RC-Trainingsflugzeugs",
    "Trainings-RC Flugzeug": "RC-Trainingsflugzeug",
    "Trainings-RC-Flugzeuges": "RC-Trainingsflugzeugs",
    "Trainings-RC-Flugzeug": "RC-Trainingsflugzeug",
    "Aufpralle": "Aufprälle",
    "Aufprällenergie": "Aufprallenergie",
    "Garantie Bei": "Garantie bei",
    "am Motorhaube": "an der Motorhaube",
    "Ausschließlich passend.": "Nur passend für dieses Modell.",
    "Intelligenter Akku": "Smart-Akku",
    "intelligenter Akku": "Smart-Akku",
    "Type-C-Ladung": "USB-C-Ladung",
    "USB Type-C": "USB-C",
    "maßstabsgetreuen Kampfeinsätze": "realistische Flugmanöver",
    "Kampfeinsätze": "Flugmanöver",
    "Kampfkraft": "Leistung",
    "militärische Einsätze": "realistische Flugmanöver",
    "den Himmel zu dominieren": "stabile Flugleistung zu erzielen",
    "Stellen Sie die Schubkraft Ihres Flugzeugs wieder her": "Stellt Schub und Flugleistung zuverlässig wieder her",
    "Stellen Sie die Kampfkraft Ihres Flugzeugs wieder her": "Zuverlässiger Ersatzmotor für Ihr BF109 RC Flugzeug",
    "Hochleistungs Hochdrehmoment-Bürstenmotor": "Hochdrehmoment-Bürstenmotor",
    "dominieren": "zuverlässig fliegen",
    "Garantie Auf": "Garantie auf",
    "eine Vibrationstest": "einen Vibrationstest",
    "auf den Motor-/Getriebewelle": "auf die Motor-/Getriebewelle",
}
GERMAN_AWKWARD_TERMS_RE = re.compile(
    r"\b(?:Produkhighlights|Produkthighlights|Abbrechersystem|Abbruchsystem|Propellerhalterungswellenbasis|Propellerhalterungswelle|Propellerhalterungsbasis|Prop-Saver-Wellenbasis|Propellerhalterung-Basis|Trainigs|Trainings-RC\s+Flugzeug(?:es)?|Aufpräll(?:energie|schaden|kraft|schutz)|Garantie Bei|Garantie Auf|am Motorhaube|Ausschließlich passend\.|Intelligenter Akku|Type-C-Ladung|Kampfeinsätze|Kampfkraft|dominieren|militärische Einsätze|Wingspan|Replacement|High-Torque|eine Vibrationstest|auf den Motor-/Getriebewelle)\b",
    flags=re.IGNORECASE,
)
GERMAN_COMMON_GRAMMAR_RE = re.compile(
    r"\b(?:eine\s+Vibrationstest|ein\s+Propellerbl[a盲]tter|einen\s+RC\s+Flugzeug|eine\s+Motor)\b",
    flags=re.IGNORECASE,
)
GERMAN_LONG_COMPOUND_RE = re.compile(
    r"\b[A-Za-z脽盲枚眉脛脰脺]{28,}\b",
    flags=re.IGNORECASE,
)
GERMAN_LOWERCASE_SENTENCE_START_RE = re.compile(
    r"(?:^|[.!?]\s+)([a-zäöüß][a-zäöüß-]*)",
)
HTML_INLINE_TAG_SPACING_RE = re.compile(
    r"(</(?:strong|b|em|i|span)>)([A-ZÄÖÜa-zäöüß0-9])",
    flags=re.IGNORECASE,
)
HTML_AMP_SPACING_RE = re.compile(r"\s*&amp;\s*")
URL_TEXT_NODE_RE = re.compile(r"^\s*(?:https?://|www\.)\S+\s*$", flags=re.IGNORECASE)
VISIBLE_URL_CAPS_RE = re.compile(r"\bHttps?://")
COMPATIBILITY_ALONE_RE = re.compile(
    r"\bF[üu]r\s+das\s+(.+?)\s+Allein\.",
    flags=re.IGNORECASE,
)
AUSSCHLIESSLICH_PASSEND_RE = re.compile(
    r"\bAusschlie[ßs]lich\s+passend\.",
    flags=re.IGNORECASE,
)
COMPATIBILITY_AUSSCHLIESSLICH_RE = re.compile(
    r"\bF[üu]r\s+das\s+(.+?)\s+Ausschlie[ßs]lich\.",
    flags=re.IGNORECASE,
)
BÜRSTENLOS_RE = re.compile(
    r"\bb[üu]rstenlos(?:er|es|e|en)?(?:\s+Kernlos-Design|\s+Motor)?\b",
    flags=re.IGNORECASE,
)
EMPTY_INLINE_TAG_RE = re.compile(
    r"<(?P<tag>strong|em|b|i|span)(?P<attrs>[^>]*)>\s*</(?P=tag)>",
    flags=re.IGNORECASE,
)
EMPTY_BLOCK_TAG_RE = re.compile(
    r"<(?P<tag>li|p|div|span)(?P<attrs>[^>]*)>\s*</(?P=tag)>",
    flags=re.IGNORECASE,
)


class VisibleTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.in_hidden = False

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.in_hidden = True

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.in_hidden = False

    def handle_data(self, data):
        if not self.in_hidden and data.strip():
            self.parts.append(data.strip())

    def text(self):
        return " ".join(self.parts)


class BodyHtmlTextNodeParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.tokens = []
        self.text_nodes = []
        self.alt_nodes = []
        self.hidden_depth = 0

    def handle_starttag(self, tag, attrs):
        raw = self.get_starttag_text()
        if tag.lower() == "img":
            raw = self._tokenize_img_alt(raw)
        self.tokens.append(("raw", raw))
        if tag.lower() in {"script", "style"}:
            self.hidden_depth += 1

    def handle_startendtag(self, tag, attrs):
        raw = self.get_starttag_text()
        if tag.lower() == "img":
            raw = self._tokenize_img_alt(raw)
        self.tokens.append(("raw", raw))

    def handle_endtag(self, tag):
        self.tokens.append(("raw", f"</{tag}>"))
        if tag.lower() in {"script", "style"} and self.hidden_depth:
            self.hidden_depth -= 1

    def handle_data(self, data):
        if self.hidden_depth or not data.strip():
            self.tokens.append(("raw", data))
            return
        node_id = len(self.text_nodes)
        self.text_nodes.append(data)
        self.tokens.append(("text", node_id))

    def handle_entityref(self, name):
        self.tokens.append(("raw", f"&{name};"))

    def handle_charref(self, name):
        self.tokens.append(("raw", f"&#{name};"))

    def handle_comment(self, data):
        self.tokens.append(("raw", f"<!--{data}-->"))

    def handle_decl(self, decl):
        self.tokens.append(("raw", f"<!{decl}>"))

    def handle_pi(self, data):
        self.tokens.append(("raw", f"<?{data}>"))

    def render(self, translated_nodes):
        rendered = []
        for token_type, value in self.tokens:
            if token_type == "raw":
                rendered.append(self._render_alt_tokens(value, translated_nodes))
            else:
                rendered.append(escape(translated_nodes[value], quote=False))
        return "".join(rendered)

    def _tokenize_img_alt(self, raw):
        match = re.search(r"""\salt=(["'])(.*?)\1""", raw or "", flags=re.IGNORECASE | re.DOTALL)
        if not match:
            return raw
        quote, alt_text = match.group(1), match.group(2)
        if not alt_text.strip():
            return raw
        node_id = len(self.text_nodes)
        self.text_nodes.append(alt_text)
        self.alt_nodes.append(node_id)
        return (
            raw[: match.start(2)]
            + f"__ALT_TEXT_NODE_{node_id}__"
            + raw[match.end(2) :]
        )

    def _render_alt_tokens(self, raw, translated_nodes):
        def replace(match):
            node_id = int(match.group(1))
            return escape(translated_nodes[node_id], quote=True)

        return re.sub(r"__ALT_TEXT_NODE_(\d+)__", replace, raw)


def html_visible_text(html):
    parser = VisibleTextExtractor()
    parser.feed(html or "")
    return parser.text()


def parse_body_html_text_nodes(html):
    parser = BodyHtmlTextNodeParser()
    parser.feed(html or "")
    return parser


def html_tag_sequence(html):
    return re.findall(r"</?\s*([a-zA-Z0-9:-]+)", html or "")


def is_ordered_subsequence(candidate, source):
    source_iter = iter(source)
    return all(any(item == source_item for source_item in source_iter) for item in candidate)


def html_attribute_values(html, attribute):
    pattern = rf"""\s{re.escape(attribute)}=(["'])(.*?)\1"""
    return re.findall(pattern, html or "", flags=re.IGNORECASE | re.DOTALL)


def html_img_alt_values(html):
    return [
        value
        for _, value in html_attribute_values(html, "alt")
    ]


def is_shipping_alt_text(text):
    return bool(SHIPPING_MARKETING_RE.search(text or ""))


def remove_shipping_alt_words(text):
    if not text:
        return text, 0
    cleaned, count = SHIPPING_MARKETING_RE.subn("", text)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    cleaned = re.sub(r"^[\s,.;:!?-]+|[\s,.;:!?-]+$", "", cleaned)
    return cleaned.strip(), count


def has_ai_cta(text):
    return bool(AI_CTA_RE.search(text or ""))


def remove_shipping_marketing_phrases(text):
    if not text:
        return text, 0
    cleaned, shipping_count = SHIPPING_MARKETING_RE.subn("", text)
    cleaned, cta_count = AI_CTA_RE.subn("", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    cleaned = re.sub(r"^[\s,.;:!?-]+|[\s,.;:!?-]+$", "", cleaned)
    return cleaned.strip(), shipping_count + cta_count


def has_keyword_stuffing(text):
    return bool(KEYWORD_STUFFING_RE.search(text or ""))


def has_awkward_3d_german(text):
    return bool(AWKWARD_3D_GERMAN_RE.search(text or ""))


def has_german_qa_issue(text):
    return bool(
        GERMAN_AWKWARD_TERMS_RE.search(text or "")
        or GERMAN_COMMON_GRAMMAR_RE.search(text or "")
    )


def has_lowercase_sentence_start(text):
    return bool(GERMAN_LOWERCASE_SENTENCE_START_RE.search(text or ""))


def has_html_spacing_issue(html):
    if not html:
        return False
    text_parts = [
        part
        for part in re.split(r"(<[^>]+>)", html)
        if not (part.startswith("<") and part.endswith(">"))
    ]
    return bool(
        HTML_INLINE_TAG_SPACING_RE.search(html)
        or any(
            re.search(r"[A-Za-zÄÖÜäöüß0-9]&amp;|&amp;[A-Za-zÄÖÜäöüß0-9]", part)
            for part in text_parts
        )
    )


def is_url_text_node(text):
    return bool(URL_TEXT_NODE_RE.match(text or ""))


def has_visible_url_case_issue(text):
    return bool(VISIBLE_URL_CAPS_RE.search(text or ""))


def has_compatibility_alone_issue(text):
    return bool(
        re.search(r"\sAllein\.", text or "", flags=re.IGNORECASE)
        or re.search(r"\sAusschlie[ßs]lich\.", text or "", flags=re.IGNORECASE)
    )


def source_has_brushed_motor(source_payload):
    haystack = "\n".join(str(source_payload.get(key, "") or "") for key in FIELD_ORDER)
    return bool(re.search(r"\bBrushed\s+Motor\b", haystack, flags=re.IGNORECASE))


def contains_brushless_german(text):
    return bool(BÜRSTENLOS_RE.search(text or ""))


def strip_url_text(text):
    if not text:
        return text
    return re.sub(r"\b(?:https?://|www\.)\S+", "", text, flags=re.IGNORECASE)


def visible_output_text_without_urls(translated):
    parts = []
    for key in ["title", "meta_title", "meta_description"]:
        parts.append(strip_url_text(translated.get(key, "") or ""))
    if translated.get("body_html"):
        parts.append(strip_url_text(html_visible_text(translated["body_html"])))
    return "\n".join(parts)


def enforce_brushed_motor_terms(text, source_has_brushed):
    if not text or not source_has_brushed:
        return text, False
    cleaned, count = BÜRSTENLOS_RE.subn("Bürstenmotor", text)
    return cleaned, bool(count)


def long_german_compounds(text):
    if not text:
        return []
    candidates = []
    for match in GERMAN_LONG_COMPOUND_RE.finditer(text):
        word = match.group(0)
        if word.startswith(("http", "www")):
            continue
        if word.isupper():
            continue
        candidates.append(word)
    return candidates


def apply_german_qa_replacements(text):
    if not text:
        return text
    cleaned = text
    for wrong, right in GERMAN_QA_REPLACEMENTS.items():
        cleaned = re.sub(re.escape(wrong), right, cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bRC Trainer RC Flugzeug\b", "RC Flugzeug", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()


def fix_german_sentence_starts(text):
    if not text:
        return text

    def replace(match):
        whole = match.group(0)
        word = match.group(1)
        return whole[: -len(word)] + word[:1].upper() + word[1:]

    return GERMAN_LOWERCASE_SENTENCE_START_RE.sub(replace, text)


def apply_german_body_node_qa(text):
    if not text:
        return text
    leading = re.match(r"^\s*", text).group(0)
    trailing = re.search(r"\s*$", text).group(0)
    cleaned = apply_german_qa_replacements(text)
    cleaned = COMPATIBILITY_ALONE_RE.sub(r"Nur für das \1 geeignet.", cleaned)
    cleaned = COMPATIBILITY_AUSSCHLIESSLICH_RE.sub(r"Nur passend für das \1.", cleaned)
    cleaned = AUSSCHLIESSLICH_PASSEND_RE.sub(
        "Nur passend für dieses Modell.",
        cleaned,
    )
    cleaned = fix_german_sentence_starts(cleaned)
    if leading and not cleaned.startswith(leading):
        cleaned = leading + cleaned.lstrip()
    if trailing and not cleaned.endswith(trailing):
        cleaned = cleaned.rstrip() + trailing
    return cleaned


def normalize_translated_body_html_spacing(html):
    if not html:
        return html
    parts = re.split(r"(<[^>]+>)", html)
    for index, part in enumerate(parts):
        if part.startswith("<") and part.endswith(">"):
            continue
        parts[index] = HTML_AMP_SPACING_RE.sub(" &amp; ", part)
    cleaned = "".join(parts)
    cleaned = HTML_INLINE_TAG_SPACING_RE.sub(r"\1 \2", cleaned)
    cleaned = re.sub(
        r"(\b(?:Technische Daten|Support)\s+)&amp;\s+(Fotos|Garantie)\b",
        r"\1&amp; \2",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\bTechnische\s+Daten\s+&amp;\s+Und\s+Fotos\b",
        "Technische Daten &amp; Fotos",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"((?:</(?:strong|b|em|i|span)>\s*)+)Bei\b",
        r"\1bei",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\bAusschlie[ßs]lich\s+passend\s+f[üu]r\s+dieses\s+Modell\.",
        "Nur passend für dieses Modell.",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\bGarantie\s+Auf\b",
        "Garantie auf",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = COMPATIBILITY_AUSSCHLIESSLICH_RE.sub(r"Nur passend für das \1.", cleaned)
    return cleaned


def polish_german_product_title(title):
    if not title:
        return title
    cleaned = apply_german_qa_replacements(title)
    cleaned = compress_german_battery_title(cleaned)
    if re.search(r"\bBF109\b", cleaned, flags=re.IGNORECASE) and re.search(
        r"\b400\s*mm\b", cleaned, flags=re.IGNORECASE
    ):
        if re.search(r"\b(?:Brushed Motor|Bürstenmotor|Hochdrehmoment)\b", cleaned, flags=re.IGNORECASE):
            compact = "Hochdrehmoment-Bürstenmotor für BF109 400mm RC Flugzeug"
            if len(compact) <= MAX_PRODUCT_TITLE_CHARS:
                cleaned = compact
    cleaned = re.sub(
        r"\bPropellerhalterung\s+f[眉u]r\s+([A-Za-z0-9 -]*Sport Cub\s+\d+mm)\s+RC\s+Flugzeug\b",
        r"Propellerhalterung f眉r \1 RC Flugzeug",
        cleaned,
        flags=re.IGNORECASE,
    )
    if len(cleaned) > MAX_PRODUCT_TITLE_CHARS and re.search(r"\bSport Cub\b", cleaned, re.IGNORECASE):
        cleaned = re.sub(r"\bVolantexRC\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bRC\s+Trainer\s+RC\s+Flugzeug\b", "RC Flugzeug", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bRC\s+Trainerflugzeug\b", "RC Flugzeug", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()


def compress_german_battery_title(title):
    if not title or len(title) <= MAX_PRODUCT_TITLE_CHARS:
        return title
    if not re.search(r"\bAkku\b", title, flags=re.IGNORECASE):
        return title

    voltage_match = re.search(r"\b\d+(?:[,.]\d+)?\s*V\b", title, flags=re.IGNORECASE)
    capacity_match = re.search(r"\b\d+\s*mAh\b", title, flags=re.IGNORECASE)
    model_match = re.search(r"\b(?:YuXiang\s+)?F\d+[A-Z]?\b", title)
    chemistry_match = re.search(r"\bLiPo\b", title, flags=re.IGNORECASE)
    if not (voltage_match and capacity_match and model_match):
        return title

    chemistry = chemistry_match.group(0) if chemistry_match else ""
    parts = [
        model_match.group(0),
        voltage_match.group(0).replace(" ", ""),
        capacity_match.group(0).replace(" ", ""),
        chemistry,
        "Akku",
    ]
    compact = " ".join(part for part in parts if part)
    if len(compact) <= MAX_PRODUCT_TITLE_CHARS:
        return compact

    fallback = (
        f"{voltage_match.group(0).replace(' ', '')} "
        f"{capacity_match.group(0).replace(' ', '')} "
        f"{chemistry + ' ' if chemistry else ''}Akku für {model_match.group(0)}"
    )
    return fallback if len(fallback) <= MAX_PRODUCT_TITLE_CHARS else title


def polish_german_meta_title(meta_title):
    if not meta_title:
        return meta_title
    cleaned = apply_german_qa_replacements(meta_title)
    if re.search(r"\bBF109\b", cleaned, flags=re.IGNORECASE) and re.search(
        r"\b400\s*mm\b", cleaned, flags=re.IGNORECASE
    ):
        if re.search(r"\b(?:Motor|Bürstenmotor|Brushed|Wingspan)\b", cleaned, flags=re.IGNORECASE):
            compact = "BF109 400mm Bürstenmotor | RC Flugzeug Ersatzteil"
            if len(compact) <= MAX_META_TITLE_CHARS:
                cleaned = compact
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+\|", " |", cleaned)
    return cleaned.strip(" |")


def _meta_title_core_patterns(source_text):
    core_patterns = [
        r"\bRC\b",
        r"\bMoFly\b",
        r"\bP-?51D\b",
        r"\b690\s*mm\b",
        r"\bBF109\b",
        r"\b400\s*mm\b",
        r"\b(?:Motor|Brushed|B.rstenmotor)\b",
        r"\b(?:Akku|LiPo)\b",
        r"\bPropeller\b",
        r"\bErsatzteil\b",
    ]
    return [
        pattern
        for pattern in core_patterns
        if re.search(pattern, source_text or "", flags=re.IGNORECASE)
    ]


def _preserves_meta_title_core(candidate, source_text):
    return all(
        re.search(pattern, candidate or "", flags=re.IGNORECASE)
        for pattern in _meta_title_core_patterns(source_text)
    )


def _word_boundary_trim(text, max_chars):
    if len(text) <= max_chars:
        return text
    trimmed = text[:max_chars].rstrip(" ,.;:-|")
    trimmed = re.sub(r"\s+\S*$", "", trimmed).rstrip(" ,.;:-|")
    return trimmed if trimmed else text[:max_chars].rstrip(" ,.;:-|")


def compress_meta_title(meta_title, source_payload=None):
    if not meta_title:
        return meta_title
    cleaned = polish_german_meta_title(meta_title)
    cleaned, _ = remove_shipping_marketing_phrases(cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" |")
    if len(cleaned) <= MAX_META_TITLE_CHARS:
        return cleaned

    source_payload = source_payload or {}
    source_text = "\n".join(str(source_payload.get(key, "") or "") for key in FIELD_ORDER)
    combined_text = f"{source_text}\n{cleaned}"
    candidates = []

    if (
        re.search(r"\bMoFly\b", combined_text, flags=re.IGNORECASE)
        and re.search(r"\bP-?51D\b", combined_text, flags=re.IGNORECASE)
        and re.search(r"\b690\s*mm\b", combined_text, flags=re.IGNORECASE)
    ):
        candidates.extend(
            [
                "MoFly P-51D 690mm RC Flugzeug Ersatzteil",
                "MoFly P-51D 690mm RC Flugzeug",
            ]
        )

    if re.search(r"\bBF109\b", combined_text, flags=re.IGNORECASE) and re.search(
        r"\b400\s*mm\b", combined_text, flags=re.IGNORECASE
    ):
        candidates.extend(
            [
                "BF109 400mm Buerstenmotor | RC Flugzeug Ersatzteil",
                "BF109 400mm RC Flugzeug Ersatzteil",
            ]
        )

    simplified = re.sub(r"\s*\|\s*.*$", "", cleaned).strip()
    simplified = re.sub(
        r"\b(?:hochwertig|leistungsstark|perfekt|ideal|optimal|zuverl[a.]ssig|original)\b",
        "",
        simplified,
        flags=re.IGNORECASE,
    )
    simplified = re.sub(r"\s{2,}", " ", simplified).strip(" |")
    candidates.append(simplified)
    candidates.append(_word_boundary_trim(simplified, MAX_META_TITLE_CHARS))

    for candidate in candidates:
        candidate = re.sub(r"\s{2,}", " ", candidate).strip(" |")
        if (
            candidate
            and len(candidate) <= MAX_META_TITLE_CHARS
            and _preserves_meta_title_core(candidate, combined_text)
        ):
            return candidate

    return cleaned


def compress_meta_description(meta_description):
    if not meta_description or len(meta_description) <= MAX_META_DESCRIPTION_CHARS:
        return meta_description

    cleaned = apply_german_qa_replacements(meta_description)
    cleaned, _ = remove_shipping_marketing_phrases(cleaned)
    cleaned = re.sub(
        r"\b(?:hochwertig|leistungsstark|perfekt|ideal|optimal|zuverl[aä]ssig)\b",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    if len(cleaned) <= MAX_META_DESCRIPTION_CHARS:
        return cleaned

    has_bf109 = re.search(r"\bBF109\b", cleaned, flags=re.IGNORECASE)
    has_400mm = re.search(r"\b400\s*mm\b", cleaned, flags=re.IGNORECASE)
    has_motor = re.search(r"\b(?:motor|brushed)\b", cleaned, flags=re.IGNORECASE)
    if has_bf109 and has_400mm and has_motor:
        compact = (
            "Hochdrehmoment-Bürstenmotor für BF109 Warbird 400mm RC Flugzeug. "
            "Ersatzteil für 4-Kanal RTF Modelle mit XPilot Stabilisierung."
        )
        if len(compact) <= MAX_META_DESCRIPTION_CHARS:
            return compact

    sentence = re.split(r"(?<=[.!?])\s+", cleaned)[0].strip()
    if 0 < len(sentence) <= MAX_META_DESCRIPTION_CHARS:
        return sentence
    return cleaned[:MAX_META_DESCRIPTION_CHARS].rstrip(" ,.;:-")


def is_origin_text(text):
    return bool(ORIGIN_RE.search(text or ""))


def remove_origin_text(text):
    if not text:
        return text, False
    if is_origin_text(text):
        return "", True
    return text, False


def remove_empty_html_nodes(html):
    if not html:
        return html, 0
    total_removed = 0
    previous = None
    cleaned = html
    while previous != cleaned:
        previous = cleaned
        for pattern in [EMPTY_INLINE_TAG_RE, EMPTY_BLOCK_TAG_RE]:
            cleaned, removed = pattern.subn("", cleaned)
            total_removed += removed
    return cleaned, total_removed


def json_dumps(data):
    return json.dumps(data, ensure_ascii=False, indent=2)


def terminal_beep():
    print("\a", end="", flush=True)


def parse_fields(fields_value):
    fields_value = (fields_value or "all").strip()
    if fields_value == "all":
        return set(FIELD_ORDER)
    fields = {field.strip() for field in fields_value.split(",") if field.strip()}
    invalid = sorted(fields - TRANSLATABLE_KEYS)
    if invalid:
        raise CommandError(f"Invalid --fields value(s): {', '.join(invalid)}")
    return fields


def load_glossary(path):
    if not path:
        path = Path(__file__).resolve().parents[2] / "translation_glossary_de.json"
    else:
        path = Path(path)
    if not path.exists():
        raise CommandError(f"Glossary file not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CommandError(f"Glossary file must be valid JSON: {path}: {exc}") from exc


def glossary_matches(glossary, source_payload):
    haystack = "\n".join(str(value or "") for value in source_payload.values())
    return [
        {"source": source, "target": target}
        for source, target in glossary.items()
        if re.search(re.escape(source), haystack, flags=re.IGNORECASE)
    ]


class ShopifyProductTranslationTool:
    def __init__(self, installation, stdout):
        self.installation = installation
        self.stdout = stdout

    def log(self, message):
        self.stdout.write(message)

    def write_review_file(self, review_file, review_data):
        if not review_file:
            return
        path = Path(review_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix.lower() == ".html":
            html = (
                "<!doctype html><html><head><meta charset='utf-8'>"
                "<title>Shopify Translation Review</title>"
                "<style>body{font-family:Arial,sans-serif;margin:24px;line-height:1.5}"
                "pre{white-space:pre-wrap;background:#f6f8fa;padding:12px;border:1px solid #ddd}"
                "section{margin-bottom:24px} h2{border-bottom:1px solid #ddd;padding-bottom:6px}"
                ".warn{color:#9a6700}</style></head><body>"
                "<h1>Shopify Product Translation Review</h1>"
                f"<p><strong>Product:</strong> {escape(str(review_data.get('product_id', '')))}</p>"
                f"<p><strong>Locale:</strong> {escape(str(review_data.get('target_locale', '')))}</p>"
                "<section><h2>Summary</h2><pre>"
                f"{escape(json_dumps(review_data.get('summary', {})))}"
                "</pre></section><section><h2>Info</h2><pre>"
                f"{escape(json_dumps(review_data.get('infos', [])))}"
                "</pre></section><section><h2>Warnings</h2><pre class='warn'>"
                f"{escape(json_dumps(review_data.get('warnings', [])))}"
                "</pre></section><section><h2>Source</h2><pre>"
                f"{escape(json_dumps(review_data.get('source', {})))}"
                "</pre></section><section><h2>Translation</h2><pre>"
                f"{escape(json_dumps(review_data.get('translation', {})))}"
                "</pre></section><section><h2>Payload Preview</h2><pre>"
                f"{escape(json_dumps(review_data.get('payload_preview', [])))}"
                "</pre></section></body></html>"
            )
            path.write_text(html, encoding="utf-8")
        else:
            path.write_text(json_dumps(review_data), encoding="utf-8")
        self.log(f"Review file written: {path}")

    def shopify_graphql(self, query, variables=None):
        url = f"https://{self.installation.shop}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"
        response = requests.post(
            url,
            headers={
                "X-Shopify-Access-Token": self.installation.access_token,
                "Content-Type": "application/json",
            },
            json={"query": query, "variables": variables or {}},
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("errors"):
            raise CommandError(f"Shopify GraphQL errors: {json_dumps(data['errors'])}")
        return data["data"]

    def openai_translate(self, product_id, target_locale, source_payload, selected_fields, glossary):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise CommandError("OPENAI_API_KEY is not configured.")

        prompt = {
            "task": "Translate Shopify product fields for ecommerce SEO.",
            "product_id": product_id,
            "target_locale": target_locale,
            "selected_fields": sorted(selected_fields),
            "glossary": glossary,
            "seo_rules": [
                "The glossary is mandatory. Prefer glossary translations over your own wording when the source term appears.",
                "Product title must be natural, localized, searchable, and conversion-friendly.",
                f"Product title should be {MAX_PRODUCT_TITLE_CHARS} characters or fewer when possible. If longer, shorten non-core words and remove repeated phrases like RC Trainer RC Flugzeug.",
                "For battery/accessory titles over 65 characters, keep model + voltage/capacity + product type. Example: YuXiang F112S 7,4V 1200mAh LiPo Akku. Secondary aircraft names like AH-1 Cobra or RC Helikopter may be omitted.",
                "For German titles, prefer German RC ecommerce phrasing. Avoid long compound nouns. Example: Propellerhalterung für Sport Cub 500mm RC Flugzeug.",
                "For German accessory titles, shorten over-compounded names. Example: Propellerhalterungswelle für VolantexRC Sport Cub 500mm RC Trainerflugzeug -> Propellerhalterung für Sport Cub 500mm RC Flugzeug.",
                "For German titles, prefer RC Flugzeug, RC Auto, 4-Kanal RC-Steuerung, 6-Achsen-Gyro, bürstenloser Motor, ferngesteuert, Kinder. Avoid mechanical literal translation.",
                "Brushed Motor and Brushless Motor are different. Translate Brushed Motor as Bürstenmotor and High-Torque Brushed Motor as Hochdrehmoment-Bürstenmotor. Only translate Brushless Motor as bürstenloser Motor.",
                "If the source contains Brushed Motor, the German output must not contain bürstenlos, bürstenloser, or bürstenloses.",
                "Avoid English leftovers in German SEO such as Wingspan, Replacement, High-Torque, or Brushed Motor.",
                "Example German title style: 1/16 J3 WWII RC Flugzeug mit 4-Kanal & 6-Achsen-Gyro.",
                "German section headings must use: Produkt-Highlights, Lieferumfang, Technische Daten, Kompatibilität, Montage-Tipps, Support & Garantie.",
                "Avoid AI-like German compounds such as Abbrechersystem, Propellerhalterungswellenbasis, Propellerhalterungsbasis, or Propellerhalterungswelle. Prefer Schutzsystem, Stoßschutzsystem, or Propellerhalterung.",
                "Avoid Propellerhalterung-Basis unless the source explicitly needs a base; prefer Propellerhalterung or Prop-Saver-Basis.",
                "Run a German QA pass for sentence capitalization, spelling, article/noun gender, singular/plural, and common RC terms. Examples: Landungen, not landungen; RC-Trainingsflugzeug, not Trainings-RC Flugzeug; Aufprallenergie, not Aufprällenergie; an der Motorhaube, not am Motorhaube; Garantie bei, not Garantie Bei; Smart-Akku or Akku, not Intelligenter Akku; USB-C-Ladung, not Type-C-Ladung; einen Vibrationstest, not eine Vibrationstest; auf die Motor-/Getriebewelle, not auf den Motor-/Getriebewelle.",
                "Avoid exaggerated military/combat wording on accessories. Replace Kampfkraft, dominieren, Kampf, militärische Einsätze, or Kampfeinsätze with neutral ecommerce phrasing such as zuverlässige Leistung, Schub und Flugleistung, stabile Flugleistung, or zuverlässiger Antrieb.",
                "For compatibility wording, avoid fragments like 'Für das ... Allein.' or 'Ausschließlich passend.' Prefer 'Nur passend für das VolantexRC Sport Cub 500 4-Kanal RC Flugzeug (761-4 Sport Cub).' or 'Nur passend für dieses Modell.'.",
                "Avoid awkward German phrases like 4-Kanal Fernsteuerung, 3D-Flugdesign, 3D-Stabilflug-Flügel, or hard-translated 3D-Flügel.",
                "For German 3D wording, prefer stabile Flugeigenschaften or ruhiges Flugverhalten. Use 3D-Flugfähig only when the source clearly describes 3D aerobatics or 3D flight.",
                "SEO title must be 60 characters or fewer.",
                "Meta description must be 160 characters or fewer.",
                "If the source meta description is over 160 characters, do not copy its length; write a concise target meta description within 160 characters.",
                "For BF109 400mm motor products, preserve core keywords naturally: BF109, 400mm, RC Flugzeug or RC Plane, Brushed Motor, Ersatzmotor or replacement motor.",
                "Preserve core commercial keywords naturally in the target language, such as RC Toy, RC Airplane, RC Helicopter, Remote Control, Kids, Brushless, Gyro.",
                "Do not keyword-stuff and do not repeat brand names.",
                "Do not translate full body_html here; it is translated separately as visible text nodes.",
                "Do not change URLs, image URLs, class, style, href, src, SKU, model numbers, battery specs, dimensions, numeric values, or units.",
                "Alt text must be fully localized and descriptive if present.",
                "Tone should fit ecommerce product pages: clear, natural, and persuasive.",
                "Do not add AI-style ecommerce CTAs such as Jetzt kaufen, Buy now, Shop now, or Jetzt shoppen.",
                "Do not mention shipping origin, product origin, China origin, Mainland China, Made in China, Origin, Herkunft, or Hergestellt in Festlandchina.",
                "Do not mention shipping marketing phrases such as worldwide shipping, ships worldwide, Weltweiter Versand, Versand weltweit, or Lieferung weltweit.",
            ],
            "output_contract": {
                "type": "JSON object only",
                "fields": {
                    key: value
                    for key, value in {
                        "title": "translated product title",
                        "meta_title": "SEO title <= 60 chars",
                        "meta_description": "meta description <= 160 chars",
                    }.items()
                    if key in selected_fields
                },
            },
            "source": {
                key: source_payload.get(key, "")
                for key in ["title", "meta_title", "meta_description"]
                if key in selected_fields
            } | {
                "body_html_visible_text_summary": html_visible_text(
                    source_payload.get("body_html", "")
                )[:2000]
                if "body_html" in selected_fields
                else "",
            },
        }

        response = self.openai_responses_request(api_key, prompt)
        data = response.json()
        output_text = data.get("output_text")
        if not output_text:
            for item in data.get("output", []):
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        output_text = content.get("text")
                        break
                if output_text:
                    break
        if not output_text:
            raise CommandError(f"OpenAI response did not include output text: {json_dumps(data)}")
        try:
            translated = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise CommandError(f"OpenAI returned invalid JSON: {exc}\n{output_text}") from exc
        return translated

    def openai_translate_body_text_nodes(self, product_id, target_locale, text_nodes, alt_node_ids, glossary):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise CommandError("OPENAI_API_KEY is not configured.")

        prompt = {
            "task": "Translate visible Shopify product body_html text nodes only.",
            "product_id": product_id,
            "target_locale": target_locale,
            "glossary": glossary,
            "rules": [
                "The glossary is mandatory. Prefer glossary translations over your own wording when the source term appears.",
                "Translate each text node naturally for ecommerce product pages.",
                "Do not translate URLs, SKU, model numbers, dimensions, battery specs, numeric values, or units.",
                "If a text node is itself a URL, preserve it exactly with original capitalization and query parameters.",
                "Do not preserve or translate origin/source/manufacturing origin fields. Remove content such as Origin, Made in China, Mainland China, Herkunft, or Hergestellt in Festlandchina.",
                "Preserve leading/trailing whitespace within each node when possible.",
                "Do not add HTML tags. Return plain translated text nodes only.",
                "Do not add AI-style ecommerce CTAs such as Jetzt kaufen, Buy now, Shop now, or Jetzt shoppen.",
                "For nodes marked is_alt_text=true, write localized SEO-friendly image alt text describing the product image naturally.",
                "For image alt text, describe only the image content. Do not include shipping, worldwide shipping, ships worldwide, Versand, Lieferung, or marketing slogans.",
                "Keep each image alt text at 120 characters or fewer.",
                "Do not keyword-stuff image alt text or end it with comma-separated keywords like ferngesteuert, Kinder.",
                "German alt text example: J3 WWII RC Flugzeug im Maßstab 1/16 mit 4-Kanal Steuerung.",
                "For German RC terms, prefer RC Flugzeug, RC Auto, 4-Kanal RC-Steuerung, 6-Achsen-Gyro, bürstenloser Motor, ferngesteuert, Kinder.",
                "Brushed Motor and Brushless Motor are different. Translate Brushed Motor as Bürstenmotor and High-Torque Brushed Motor as Hochdrehmoment-Bürstenmotor. Only translate Brushless Motor as bürstenloser Motor.",
                "If the source contains Brushed Motor, the German output must not contain bürstenlos, bürstenloser, or bürstenloses.",
                "Avoid English leftovers in German SEO/body text such as Wingspan, Replacement, High-Torque, or Brushed Motor.",
                "German section headings must use: Produkt-Highlights, Lieferumfang, Technische Daten, Kompatibilität, Montage-Tipps, Support & Garantie.",
                "Avoid AI-like German compounds such as Abbrechersystem, Propellerhalterungswellenbasis, Propellerhalterungsbasis, or Propellerhalterungswelle. Prefer Schutzsystem, Stoßschutzsystem, or Propellerhalterung.",
                "Avoid Propellerhalterung-Basis unless the source explicitly needs a base; prefer Propellerhalterung or Prop-Saver-Basis.",
                "Run a German QA pass for sentence capitalization, spelling, article/noun gender, singular/plural, and common RC terms. Examples: Landungen, not landungen; RC-Trainingsflugzeug, not Trainings-RC Flugzeug; Aufprallenergie, not Aufprällenergie; an der Motorhaube, not am Motorhaube; Garantie bei, not Garantie Bei; Smart-Akku or Akku, not Intelligenter Akku; USB-C-Ladung, not Type-C-Ladung; einen Vibrationstest, not eine Vibrationstest; auf die Motor-/Getriebewelle, not auf den Motor-/Getriebewelle.",
                "Avoid exaggerated military/combat wording on accessories. Replace Kampfkraft, dominieren, Kampf, militärische Einsätze, or Kampfeinsätze with neutral ecommerce phrasing such as zuverlässige Leistung, Schub und Flugleistung, stabile Flugleistung, or zuverlässiger Antrieb.",
                "For compatibility wording, avoid fragments like 'Für das ... Allein.' or 'Ausschließlich passend.' Prefer 'Nur passend für das VolantexRC Sport Cub 500 4-Kanal RC Flugzeug (761-4 Sport Cub).' or 'Nur passend für dieses Modell.'.",
                "Avoid awkward German phrases like 4-Kanal Fernsteuerung, 3D-Flugdesign, 3D-Stabilflug-Flügel, or hard-translated 3D-Flügel.",
                "For German 3D wording, prefer stabile Flugeigenschaften or ruhiges Flugverhalten. Use 3D-Flugfähig only when the source clearly describes 3D aerobatics or 3D flight.",
                "Do not mention shipping origin, product origin, China origin, Mainland China, Made in China, Origin, Herkunft, or Hergestellt in Festlandchina.",
                "Do not mention shipping marketing phrases such as worldwide shipping, ships worldwide, Weltweiter Versand, Versand weltweit, or Lieferung weltweit.",
            ],
            "output_contract": {
                "type": "JSON object only",
                "fields": {
                    "translations": [
                        {"index": "same index as input", "text": "translated text node"}
                    ]
                },
            },
            "text_nodes": [
                {
                    "index": index,
                    "text": text,
                    "is_alt_text": index in alt_node_ids,
                }
                for index, text in enumerate(text_nodes)
            ],
        }

        response = self.openai_responses_request(api_key, prompt)
        data = response.json()
        output_text = data.get("output_text")
        if not output_text:
            for item in data.get("output", []):
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        output_text = content.get("text")
                        break
                if output_text:
                    break
        if not output_text:
            raise CommandError(f"OpenAI body response did not include output text: {json_dumps(data)}")
        try:
            parsed = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise CommandError(f"OpenAI returned invalid body JSON: {exc}\n{output_text}") from exc

        translations = parsed.get("translations")
        if not isinstance(translations, list):
            raise CommandError("OpenAI body translation missing translations list.")

        translated_nodes = list(text_nodes)
        seen = set()
        for item in translations:
            index = item.get("index")
            text = item.get("text")
            if not isinstance(index, int) or index < 0 or index >= len(text_nodes):
                raise CommandError(f"Invalid body text node index returned: {item}")
            if not isinstance(text, str):
                raise CommandError(f"Invalid body text node translation returned: {item}")
            translated_nodes[index] = text
            seen.add(index)
        if len(seen) != len(text_nodes):
            raise CommandError(
                f"OpenAI body translation returned {len(seen)} nodes; expected {len(text_nodes)}."
            )
        return translated_nodes

    def openai_responses_request(self, api_key, prompt):
        payload = {
            "model": OPENAI_MODEL,
            "input": [
                {
                    "role": "system",
                    "content": (
                        "You are an expert ecommerce localization translator. "
                        "Return valid JSON only. Preserve Shopify HTML attributes exactly."
                    ),
                },
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            "text": {"format": {"type": "json_object"}},
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        last_response = None
        for attempt in range(len(OPENAI_RETRY_DELAYS) + 1):
            response = requests.post(
                "https://api.openai.com/v1/responses",
                headers=headers,
                json=payload,
                timeout=120,
            )
            last_response = response
            if response.ok:
                return response

            should_retry = response.status_code == 429 or 500 <= response.status_code < 600
            if not should_retry or attempt >= len(OPENAI_RETRY_DELAYS):
                raise CommandError(
                    "OpenAI API request failed. "
                    f"status_code={response.status_code} response_text={response.text}"
                )

            delay = OPENAI_RETRY_DELAYS[attempt]
            self.log(
                "OpenAI API request failed; retrying. "
                f"status_code={response.status_code} wait_seconds={delay} "
                f"response_text={response.text}"
            )
            time.sleep(delay)

        raise CommandError(
            "OpenAI API request failed after retries. "
            f"status_code={last_response.status_code if last_response else 'unknown'} "
            f"response_text={last_response.text if last_response else ''}"
        )

    def read_translatable_resource(self, product_id, target_locale):
        query = """
        query($id: ID!, $locale: String!) {
          translatableResource(resourceId: $id) {
            resourceId
            translatableContent {
              key
              value
              digest
              locale
            }
            translations(locale: $locale) {
              key
              value
              locale
              outdated
            }
          }
        }
        """
        data = self.shopify_graphql(query, {"id": product_id, "locale": target_locale})
        resource = data.get("translatableResource")
        if not resource:
            raise CommandError(f"No translatableResource found for {product_id}")
        return resource

    def validate_translation(self, source_payload, translated, selected_fields, dry_run=False):
        selected_text_fields = [
            key for key in ["title", "meta_title", "meta_description"] if key in selected_fields
        ]
        missing = [key for key in selected_text_fields if key not in translated]
        if missing:
            raise CommandError(f"OpenAI translation missing fields: {', '.join(missing)}")
        if (
            "meta_title" in selected_fields
            and len(translated["meta_title"]) > MAX_META_TITLE_CHARS
            and not dry_run
        ):
            raise CommandError(
                f"meta_title exceeds {MAX_META_TITLE_CHARS} chars: "
                f"{len(translated['meta_title'])}"
            )
        if (
            "meta_description" in selected_fields
            and len(translated["meta_description"]) > MAX_META_DESCRIPTION_CHARS
        ):
            raise CommandError(
                f"meta_description exceeds {MAX_META_DESCRIPTION_CHARS} chars: "
                f"{len(translated['meta_description'])}"
            )
        for key in selected_text_fields:
            if is_origin_text(translated.get(key, "")):
                raise CommandError(f"{key} contains origin/source wording that must be removed.")
        if translated.get("body_html"):
            self.validate_body_html_structure(source_payload, translated["body_html"])

    def validate_body_html_structure(self, source_payload, translated_body_html):
        source_html = source_payload.get("body_html", "")
        target_html = translated_body_html or ""
        source_tags = html_tag_sequence(source_html)
        target_tags = html_tag_sequence(target_html)
        if target_tags != source_tags and not is_ordered_subsequence(target_tags, source_tags):
            raise CommandError("body_html HTML tag structure changed during translation.")

        for attribute in ["href", "src", "class", "style", "id"]:
            source_values = html_attribute_values(source_html, attribute)
            target_values = html_attribute_values(target_html, attribute)
            if target_values != source_values and not is_ordered_subsequence(
                target_values, source_values
            ):
                raise CommandError(f"body_html {attribute} attributes changed during translation.")

        source_alts = html_img_alt_values(source_html)
        target_alts = html_img_alt_values(target_html)
        if len(source_alts) != len(target_alts):
            raise CommandError("body_html img alt attribute count changed during translation.")
        if any(not alt.strip() for alt in target_alts):
            raise CommandError("body_html img alt translation is empty.")
        if any(is_shipping_alt_text(alt) for alt in target_alts):
            raise CommandError("body_html img alt contains shipping/delivery wording.")

        source_data_attrs = sorted(set(re.findall(r"\s(data-[\w:-]+)=", source_html)))
        target_data_attrs = sorted(set(re.findall(r"\s(data-[\w:-]+)=", target_html)))
        if not set(target_data_attrs).issubset(set(source_data_attrs)):
            raise CommandError("body_html data-* attributes changed during translation.")
        for attribute in source_data_attrs:
            source_values = html_attribute_values(source_html, attribute)
            target_values = html_attribute_values(target_html, attribute)
            if target_values != source_values and not is_ordered_subsequence(
                target_values, source_values
            ):
                raise CommandError(f"body_html {attribute} attributes changed during translation.")

    def register_translations(self, product_id, target_locale, source_items, translated):
        translations = []
        for key in FIELD_ORDER:
            source_item = source_items.get(key)
            if not source_item:
                continue
            value = translated.get(key, "")
            if not value:
                continue
            translations.append(
                {
                    "locale": target_locale,
                    "key": key,
                    "value": value,
                    "translatableContentDigest": source_item["digest"],
                }
            )

        mutation = """
        mutation($resourceId: ID!, $translations: [TranslationInput!]!) {
          translationsRegister(resourceId: $resourceId, translations: $translations) {
            userErrors {
              field
              message
            }
            translations {
              key
              value
              locale
              outdated
            }
          }
        }
        """
        data = self.shopify_graphql(
            mutation,
            {"resourceId": product_id, "translations": translations},
        )
        result = data["translationsRegister"]
        if result.get("userErrors"):
            raise CommandError(f"translationsRegister userErrors: {json_dumps(result['userErrors'])}")
        return result

    def verify_written_translations(self, product_id, target_locale, payload_keys):
        resource = self.read_translatable_resource(product_id, target_locale)
        translations_by_key = {
            item.get("key"): item
            for item in resource.get("translations", [])
        }
        verification = {}
        for key in payload_keys:
            item = translations_by_key.get(key)
            verification[key] = {
                "exists": bool(item and item.get("value")),
                "locale": item.get("locale") if item else None,
                "outdated": item.get("outdated") if item else None,
                "ok": bool(
                    item
                    and item.get("value")
                    and item.get("locale") == target_locale
                    and item.get("outdated") is False
                ),
            }
        return verification

    def run(self, product_id, target_locale, dry_run, review_file=None, fields=None, skip_existing=False, glossary=None):
        self.log("Shopify Product Translation Tool v1")
        self.log(f"Shop: {self.installation.shop}")
        self.log(f"Product ID: {product_id}")
        self.log(f"Target locale: {target_locale}")
        self.log(f"Dry run: {dry_run}")
        selected_fields = fields or set(FIELD_ORDER)
        glossary = glossary or {}
        self.log(f"Fields: {', '.join(field for field in FIELD_ORDER if field in selected_fields)}")
        self.log(f"Skip existing: {skip_existing}")
        self.log(f"Glossary terms: {len(glossary)}")

        resource = self.read_translatable_resource(product_id, target_locale)
        existing_current_keys = {
            item.get("key")
            for item in resource.get("translations", [])
            if item.get("key") in TRANSLATABLE_KEYS
            and item.get("value")
            and item.get("outdated") is False
        }
        if skip_existing and existing_current_keys:
            selected_fields = selected_fields - existing_current_keys
            self.log(
                "Skipping existing current translations: "
                f"{', '.join(key for key in FIELD_ORDER if key in existing_current_keys)}"
            )
        if not selected_fields:
            self.log("All selected fields already have current translations; nothing to do.")
            terminal_beep()
            return

        source_items = {
            item["key"]: item
            for item in resource.get("translatableContent", [])
            if item.get("key") in TRANSLATABLE_KEYS and item.get("key") in selected_fields
        }
        missing = sorted(selected_fields - set(source_items.keys()))
        if missing:
            self.log(f"Warning: missing translatable fields: {', '.join(missing)}")

        source_payload = {
            key: source_items.get(key, {}).get("value", "")
            for key in FIELD_ORDER
        }
        matched_glossary = glossary_matches(glossary, source_payload)
        dry_run_warnings = []
        qa_infos = []
        has_brushed_source = source_has_brushed_motor(source_payload)
        source_meta_description_chars = len(source_payload.get("meta_description", "") or "")
        source_meta_description_over_limit = (
            "meta_description" in selected_fields
            and source_meta_description_chars > MAX_META_DESCRIPTION_CHARS
        )
        if source_meta_description_over_limit:
            dry_run_warnings.append(
                "Warning: source meta_description exceeds "
                f"{MAX_META_DESCRIPTION_CHARS} chars ({source_meta_description_chars}); "
                "continuing because source SEO limits do not block translation."
            )
        self.log("Source summary:")
        self.log(f"- title: {source_payload.get('title', '')}")
        self.log(f"- body_html visible chars: {len(html_visible_text(source_payload.get('body_html', '')))}")
        self.log(f"- meta_title chars: {len(source_payload.get('meta_title', '') or '')}")
        self.log(f"- meta_description chars: {len(source_payload.get('meta_description', '') or '')}")

        text_fields = selected_fields & {"title", "meta_title", "meta_description"}
        if text_fields:
            translated = self.openai_translate(
                product_id,
                target_locale,
                source_payload,
                selected_fields,
                glossary,
            )
        else:
            translated = {}
        removed_shipping_phrase_count = 0
        for key in ["title", "meta_title", "meta_description"]:
            if key not in translated:
                continue
            cleaned_value, shipping_removed = remove_shipping_marketing_phrases(translated[key])
            if shipping_removed:
                translated[key] = cleaned_value
                removed_shipping_phrase_count += shipping_removed
            translated[key] = apply_german_qa_replacements(translated[key])
            if key == "title":
                translated[key] = polish_german_product_title(translated[key])
            if key == "meta_title":
                before_compress = translated[key]
                translated[key] = compress_meta_title(translated[key], source_payload)
                if translated[key] != before_compress:
                    dry_run_warnings.append(
                        "Warning: translated meta_title was compressed to fit "
                        f"{MAX_META_TITLE_CHARS} chars."
                    )
            translated[key], brushed_fixed = enforce_brushed_motor_terms(
                translated[key],
                has_brushed_source,
            )
            if brushed_fixed:
                qa_infos.append(
                    f"Info: corrected Brushed/Brushless term in {key}; replaced bürstenlos with Bürstenmotor."
                )
            if has_ai_cta(translated[key]):
                raise CommandError(f"{key} contains AI-style CTA wording that must be removed.")
        if "meta_description" in translated:
            before_compress = translated["meta_description"]
            translated["meta_description"] = compress_meta_description(
                translated["meta_description"]
            )
            if translated["meta_description"] != before_compress:
                dry_run_warnings.append(
                    "Warning: translated meta_description was compressed to fit "
                    f"{MAX_META_DESCRIPTION_CHARS} chars."
                )
        if text_fields:
            if (
                dry_run
                and "meta_title" in selected_fields
                and len(translated.get("meta_title", "") or "") > MAX_META_TITLE_CHARS
            ):
                dry_run_warnings.append(
                    "Warning: translated meta_title still exceeds "
                    f"{MAX_META_TITLE_CHARS} chars "
                    f"({len(translated.get('meta_title', '') or '')}); review before any write."
                )
            self.validate_translation(source_payload, translated, selected_fields, dry_run=dry_run)

        body_node_count = 0
        translated_body_node_count = 0
        translated_img_alt_count = 0
        translated_img_alt_chars = []
        skipped_url_text_node_count = 0
        removed_origin_count = 0
        empty_html_nodes_removed_count = 0
        body_warning = ""
        if "body_html" in selected_fields and source_payload.get("body_html") and source_items.get("body_html"):
            body_parser = parse_body_html_text_nodes(source_payload["body_html"])
            body_node_count = len(body_parser.text_nodes)
            self.log(f"body_html text nodes to translate: {body_node_count}")
            if body_node_count:
                try:
                    text_nodes_for_translation = []
                    skipped_source_origin_ids = set()
                    skipped_url_text_node_ids = set()
                    for index, text in enumerate(body_parser.text_nodes):
                        if is_origin_text(text):
                            skipped_source_origin_ids.add(index)
                            text_nodes_for_translation.append("")
                            removed_origin_count += 1
                        elif is_url_text_node(text):
                            skipped_url_text_node_ids.add(index)
                            text_nodes_for_translation.append("")
                            skipped_url_text_node_count += 1
                        else:
                            text_nodes_for_translation.append(text)
                    if skipped_source_origin_ids:
                        self.log(
                            "Warning: skipped origin/source text nodes before translation: "
                            f"{len(skipped_source_origin_ids)}"
                        )

                    translated_nodes = self.openai_translate_body_text_nodes(
                        product_id,
                        target_locale,
                        text_nodes_for_translation,
                        set(body_parser.alt_nodes),
                        glossary,
                    )
                    for index, text in enumerate(translated_nodes):
                        if index in skipped_url_text_node_ids:
                            translated_nodes[index] = body_parser.text_nodes[index]
                            continue
                        cleaned_text, removed = remove_origin_text(text)
                        if removed:
                            translated_nodes[index] = cleaned_text
                            removed_origin_count += 1
                        cleaned_text, shipping_removed = remove_shipping_marketing_phrases(
                            translated_nodes[index]
                        )
                        if shipping_removed:
                            translated_nodes[index] = cleaned_text
                            removed_shipping_phrase_count += shipping_removed
                        translated_nodes[index] = apply_german_body_node_qa(
                            translated_nodes[index]
                        )
                        translated_nodes[index], brushed_fixed = enforce_brushed_motor_terms(
                            translated_nodes[index],
                            has_brushed_source,
                        )
                        if brushed_fixed:
                            qa_infos.append(
                                f"Info: corrected Brushed/Brushless term in body text node {index}; replaced bürstenlos with Bürstenmotor."
                            )
                    for index in body_parser.alt_nodes:
                        if index >= len(translated_nodes):
                            continue
                        cleaned_alt, shipping_removed = remove_shipping_alt_words(translated_nodes[index])
                        if cleaned_alt != translated_nodes[index]:
                            translated_nodes[index] = cleaned_alt
                            removed_shipping_phrase_count += shipping_removed
                        if is_shipping_alt_text(translated_nodes[index]):
                            raise CommandError(
                                "body_html img alt contains shipping/delivery wording."
                            )
                        if len(translated_nodes[index]) > MAX_IMG_ALT_CHARS:
                            dry_run_warnings.append(
                                f"Warning: img alt node {index} exceeds {MAX_IMG_ALT_CHARS} chars "
                                f"({len(translated_nodes[index])})."
                            )
                        if has_keyword_stuffing(translated_nodes[index]):
                            dry_run_warnings.append(
                                f"Warning: img alt node {index} may contain keyword stuffing."
                            )
                        if has_awkward_3d_german(translated_nodes[index]):
                            dry_run_warnings.append(
                                f"Warning: img alt node {index} contains awkward 3D German wording."
                            )
                        if has_german_qa_issue(translated_nodes[index]):
                            dry_run_warnings.append(
                                f"Warning: img alt node {index} may contain German QA issue."
                            )
                    translated_body_node_count = sum(1 for text in translated_nodes if text.strip())
                    translated_img_alt_count = sum(
                        1
                        for index in body_parser.alt_nodes
                        if index < len(translated_nodes) and translated_nodes[index].strip()
                    )
                    translated_img_alt_chars = [
                        len(translated_nodes[index])
                        for index in body_parser.alt_nodes
                        if index < len(translated_nodes) and translated_nodes[index].strip()
                    ]
                    translated_body_html = body_parser.render(translated_nodes)
                    translated_body_html, empty_html_nodes_removed_count = remove_empty_html_nodes(
                        translated_body_html
                    )
                    translated_body_html = normalize_translated_body_html_spacing(
                        translated_body_html
                    )
                    self.validate_body_html_structure(source_payload, translated_body_html)
                    translated["body_html"] = translated_body_html
                except CommandError as exc:
                    body_warning = f"Warning: body_html translation skipped: {exc}"
                    translated.pop("body_html", None)
                    self.log(body_warning)
            else:
                translated.pop("body_html", None)
                self.log("Warning: body_html has no visible text nodes; skipped.")
        else:
            translated.pop("body_html", None)
            self.log("Warning: body_html source field is missing or empty; skipped.")

        self.log("Translation preview:")
        self.log(json_dumps(translated))
        payload_keys = [
            key
            for key in FIELD_ORDER
            if key in source_items and translated.get(key)
        ]
        self.log(f"translated text node count: {translated_body_node_count}")
        self.log(f"translated img alt count: {translated_img_alt_count}")
        self.log(f"img alt chars list: {translated_img_alt_chars}")
        self.log(f"url text nodes skipped count: {skipped_url_text_node_count}")
        self.log(f"removed/skipped origin field count: {removed_origin_count}")
        self.log(f"removed shipping marketing phrase count: {removed_shipping_phrase_count}")
        self.log(f"empty html nodes removed count: {empty_html_nodes_removed_count}")
        self.log(f"payload keys: {', '.join(payload_keys)}")
        self.log(f"glossary matches: {len(matched_glossary)}")
        self.log(f"title chars: {len(translated.get('title', '') or '')}")
        self.log(f"meta_title chars: {len(translated.get('meta_title', '') or '')}")
        self.log(f"meta_description chars: {len(translated.get('meta_description', '') or '')}")
        self.log(f"source meta_description chars: {source_meta_description_chars}")
        if len(translated.get("title", "") or "") > MAX_PRODUCT_TITLE_CHARS:
            dry_run_warnings.append(
                f"Warning: title exceeds recommended {MAX_PRODUCT_TITLE_CHARS} chars "
                f"({len(translated.get('title', '') or '')})."
            )
        for key in ["title", "meta_title", "meta_description"]:
            value = translated.get(key, "") or ""
            if has_keyword_stuffing(value):
                dry_run_warnings.append(f"Warning: {key} may contain keyword stuffing.")
            if has_awkward_3d_german(value):
                dry_run_warnings.append(f"Warning: {key} contains awkward 3D German wording.")
            if has_german_qa_issue(value):
                dry_run_warnings.append(f"Warning: {key} may contain German QA issue.")
            long_compounds = long_german_compounds(value)
            if long_compounds:
                dry_run_warnings.append(
                    f"Warning: {key} may contain overlong German compound(s): "
                    f"{', '.join(long_compounds[:5])}."
                )
            if is_shipping_alt_text(value):
                dry_run_warnings.append(f"Warning: {key} contains shipping marketing wording.")
            if has_ai_cta(value):
                dry_run_warnings.append(f"Warning: {key} contains AI-style CTA wording.")
        if translated.get("body_html"):
            body_text = html_visible_text(translated["body_html"])
            body_text_no_urls = strip_url_text(body_text)
            body_long_compounds = long_german_compounds(body_text)
            if body_long_compounds:
                dry_run_warnings.append(
                    "Warning: body_html may contain overlong German compound(s): "
                    f"{', '.join(body_long_compounds[:10])}."
                )
            if has_lowercase_sentence_start(body_text):
                dry_run_warnings.append("Warning: body_html may contain lowercase sentence starts.")
            if has_html_spacing_issue(translated["body_html"]):
                dry_run_warnings.append(
                    "Warning: body_html may contain missing spaces around inline tags or &amp;."
                )
            if "Propellerhalterung-Basis" in translated["body_html"]:
                dry_run_warnings.append(
                    "Warning: body_html contains Propellerhalterung-Basis; prefer Propellerhalterung."
                )
            if re.search(r"\bauf\s+den\s+Motor-/Getriebewelle\b", body_text, flags=re.IGNORECASE):
                dry_run_warnings.append(
                    "Warning: body_html contains 'auf den Motor-/Getriebewelle'; prefer 'auf die Motor-/Getriebewelle'."
                )
            if re.search(r"\bTrainigs\b", body_text, flags=re.IGNORECASE):
                dry_run_warnings.append("Warning: body_html contains Trainigs; prefer Trainings.")
            if has_visible_url_case_issue(body_text):
                dry_run_warnings.append(
                    "Warning: body_html contains visible URL text with Https:// or Http:// capitalization."
                )
            if has_compatibility_alone_issue(body_text):
                dry_run_warnings.append(
                    "Warning: body_html contains compatibility fragment ending with 'Allein.'."
                )
            if re.search(r"\bGarantie\s+Bei\b", body_text):
                dry_run_warnings.append("Warning: body_html contains Garantie Bei; prefer Garantie bei.")
            if re.search(r"\bAufpräll(?:energie|schaden|kraft|schutz)\b", body_text, flags=re.IGNORECASE):
                dry_run_warnings.append("Warning: body_html contains an incorrect Aufpräll compound; prefer Aufprall.")
            if re.search(r"\bam\s+Motorhaube\b", body_text, flags=re.IGNORECASE):
                dry_run_warnings.append("Warning: body_html contains am Motorhaube; prefer an der Motorhaube.")
            if re.search(r"\bAusschlie[ßs]lich\s+passend\.", body_text, flags=re.IGNORECASE):
                dry_run_warnings.append(
                    "Warning: body_html contains standalone 'Ausschließlich passend.'."
                )
            if re.search(r"\bTrainings-RC\s+Flugzeug(?:es)?\b", body_text, flags=re.IGNORECASE):
                dry_run_warnings.append(
                    "Warning: body_html contains Trainings-RC Flugzeug; prefer RC-Trainingsflugzeug."
                )
            if re.search(r"\bTechnische\s+Daten\s+&amp;\s+Und\s+Fotos\b", translated["body_html"], flags=re.IGNORECASE):
                dry_run_warnings.append(
                    "Warning: body_html contains Technische Daten &amp; Und Fotos; prefer Technische Daten &amp; Fotos."
                )
            if re.search(r"\bKampfeinsätze\b", body_text, flags=re.IGNORECASE):
                dry_run_warnings.append(
                    "Warning: body_html contains Kampfeinsätze; prefer neutral accessory wording."
                )
            if re.search(r"\bIntelligenter\s+Akku\b", body_text, flags=re.IGNORECASE):
                dry_run_warnings.append(
                    "Warning: body_html contains Intelligenter Akku; prefer Smart-Akku or Akku."
                )
            if re.search(r"\bType-C-Ladung\b", body_text, flags=re.IGNORECASE):
                dry_run_warnings.append(
                    "Warning: body_html contains Type-C-Ladung; prefer USB-C-Ladung."
                )
            if has_brushed_source and contains_brushless_german(body_text):
                dry_run_warnings.append(
                    "Warning: source contains Brushed Motor but body_html still contains bürstenlos."
                )
            if re.search(r"\bWingspan\b", body_text_no_urls, flags=re.IGNORECASE):
                dry_run_warnings.append("Warning: body_html contains English leftover Wingspan.")
            if re.search(r"\b(?:Kampfkraft|dominieren|militärische Einsätze|Kampf)\b", body_text, flags=re.IGNORECASE):
                dry_run_warnings.append(
                    "Warning: body_html contains exaggerated military/combat wording."
                )
            if re.search(r"\bGarantie\s+Auf\b", body_text):
                dry_run_warnings.append("Warning: body_html contains Garantie Auf; prefer Garantie auf.")
        combined_text_output = visible_output_text_without_urls(translated)
        if has_brushed_source and contains_brushless_german(combined_text_output):
            dry_run_warnings.append(
                "Warning: source contains Brushed Motor but translated output still contains bürstenlos."
            )
        if re.search(r"\bWingspan\b", combined_text_output, flags=re.IGNORECASE):
            dry_run_warnings.append("Warning: translated output contains English leftover Wingspan.")
        if re.search(r"\b(?:Replacement|High-Torque|Brushed Motor)\b", combined_text_output, flags=re.IGNORECASE):
            dry_run_warnings.append("Warning: translated output contains English motor/parts wording.")
        for info in qa_infos:
            self.log(info)
        for warning in dry_run_warnings:
            self.log(warning)
        if body_warning:
            self.log(body_warning)

        translations_preview = [
            {
                "locale": target_locale,
                "key": key,
                "value": translated.get(key, ""),
                "digest": source_items[key]["digest"],
            }
            for key in FIELD_ORDER
            if key in source_items and translated.get(key)
        ]
        self.log("translationsRegister payload preview:")
        self.log(json_dumps(translations_preview))

        review_data = {
            "product_id": product_id,
            "target_locale": target_locale,
            "dry_run": dry_run,
            "selected_fields": [field for field in FIELD_ORDER if field in selected_fields],
            "skipped_existing_fields": [
                field for field in FIELD_ORDER if field in existing_current_keys and field not in selected_fields
            ],
            "source": source_payload,
            "translation": translated,
            "payload_preview": translations_preview,
            "infos": qa_infos,
            "warnings": dry_run_warnings + ([body_warning] if body_warning else []),
            "summary": {
                "payload_keys": payload_keys,
                "title_chars": len(translated.get("title", "") or ""),
                "meta_title_chars": len(translated.get("meta_title", "") or ""),
                "meta_description_chars": len(translated.get("meta_description", "") or ""),
                "source_meta_description_chars": source_meta_description_chars,
                "translated_meta_description_chars": len(translated.get("meta_description", "") or ""),
                "source_meta_description_over_limit": source_meta_description_over_limit,
                "qa_info_count": len(qa_infos),
                "translated_text_node_count": translated_body_node_count,
                "translated_img_alt_count": translated_img_alt_count,
                "img_alt_chars_list": translated_img_alt_chars,
                "url_text_nodes_skipped_count": skipped_url_text_node_count,
                "removed_skipped_origin_field_count": removed_origin_count,
                "removed_shipping_marketing_phrase_count": removed_shipping_phrase_count,
                "empty_html_nodes_removed_count": empty_html_nodes_removed_count,
                "glossary_matches": matched_glossary,
            },
        }
        self.write_review_file(review_file, review_data)

        if dry_run:
            self.log("Dry run complete. No Shopify writes performed.")
            terminal_beep()
            return

        result = self.register_translations(product_id, target_locale, source_items, translated)
        self.log("translationsRegister completed:")
        self.log(json_dumps(result))
        verification = self.verify_written_translations(product_id, target_locale, payload_keys)
        self.log("Post-write verification:")
        self.log(json_dumps(verification))
        terminal_beep()


class Command(BaseCommand):
    help = "Translate Shopify product fields with OpenAI and write them via translationsRegister."

    def add_arguments(self, parser):
        parser.add_argument("--product-id", required=True, help="Shopify product GID or numeric product ID.")
        parser.add_argument("--target-locale", required=True, help="Target locale, e.g. de, fr, zh-TW.")
        parser.add_argument(
            "--shop",
            default="kidstoylover.myshopify.com",
            help="Shop domain (default: kidstoylover.myshopify.com).",
        )
        parser.add_argument("--dry-run", action="store_true", help="Preview only; do not write to Shopify.")
        parser.add_argument(
            "--review-file",
            help="Write dry-run/review details to a local .json or .html file.",
        )
        parser.add_argument(
            "--glossary-file",
            help="JSON glossary file. Defaults to shopify_sync/translation_glossary_de.json.",
        )
        parser.add_argument(
            "--fields",
            default="all",
            help="Fields to translate: all, body_html, or comma list such as title,meta_title,meta_description.",
        )
        parser.add_argument(
            "--skip-existing",
            action="store_true",
            help="Skip fields that already have a current translation for the target locale.",
        )

    def handle(self, *args, **options):
        try:
            self._handle(*args, **options)
        except CommandError:
            terminal_beep()
            raise

    def _handle(self, *args, **options):
        product_id = options["product_id"].strip()
        if product_id.isdigit():
            product_id = f"gid://shopify/Product/{product_id}"
        target_locale = options["target_locale"].strip()

        try:
            installation = ShopifyInstallation.objects.get(shop=options["shop"])
        except ShopifyInstallation.DoesNotExist as exc:
            raise CommandError(f"Shopify installation not found for {options['shop']}") from exc

        selected_fields = parse_fields(options["fields"])
        glossary = load_glossary(options.get("glossary_file"))

        tool = ShopifyProductTranslationTool(installation, self.stdout)
        tool.run(
            product_id,
            target_locale,
            options["dry_run"],
            review_file=options.get("review_file"),
            fields=selected_fields,
            skip_existing=options["skip_existing"],
            glossary=glossary,
        )
