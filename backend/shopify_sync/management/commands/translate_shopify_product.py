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
GERMAN_QA_REPLACEMENTS = {
    "Produkhighlights": "Produkt-Highlights",
    "Produkt Highlights": "Produkt-Highlights",
    "Product Highlights": "Produkt-Highlights",
    "Paketinhalt": "Lieferumfang",
    "Technische Spezifikationen": "Technische Daten",
    "Montagetipps": "Montage-Tipps",
    "Abbrechersystem": "Schutzsystem",
    "Propellerhalterungswellenbasis": "Propellerhalterung",
    "Propellerhalterungswelle": "Propellerhalterung",
    "eine Vibrationstest": "einen Vibrationstest",
}
GERMAN_AWKWARD_TERMS_RE = re.compile(
    r"\b(?:Produkhighlights|Abbrechersystem|Propellerhalterungswellenbasis|Propellerhalterungswelle|eine Vibrationstest)\b",
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
    return bool(GERMAN_AWKWARD_TERMS_RE.search(text or ""))


def apply_german_qa_replacements(text):
    if not text:
        return text
    cleaned = text
    for wrong, right in GERMAN_QA_REPLACEMENTS.items():
        cleaned = re.sub(re.escape(wrong), right, cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bRC Trainer RC Flugzeug\b", "RC Flugzeug", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()


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
                "For German titles, prefer German RC ecommerce phrasing. Avoid long compound nouns. Example: Propellerhalterung für Sport Cub 500mm RC Flugzeug.",
                "For German titles, prefer RC Flugzeug, RC Auto, 4-Kanal RC-Steuerung, 6-Achsen-Gyro, bürstenloser Motor, ferngesteuert, Kinder. Avoid mechanical literal translation.",
                "Example German title style: 1/16 J3 WWII RC Flugzeug mit 4-Kanal & 6-Achsen-Gyro.",
                "German section headings must use: Produkt-Highlights, Lieferumfang, Technische Daten, Kompatibilität, Montage-Tipps.",
                "Avoid AI-like German compounds such as Abbrechersystem, Propellerhalterungswellenbasis, or Propellerhalterungswelle. Prefer Schutzsystem, Stoßschutzsystem, or Propellerhalterung.",
                "Run a German QA pass for article/noun gender, singular/plural, and common RC terms. Example: einen Vibrationstest, not eine Vibrationstest.",
                "Avoid awkward German phrases like 4-Kanal Fernsteuerung, 3D-Flugdesign, 3D-Stabilflug-Flügel, or hard-translated 3D-Flügel.",
                "For German 3D wording, prefer stabile Flugeigenschaften or ruhiges Flugverhalten. Use 3D-Flugfähig only when the source clearly describes 3D aerobatics or 3D flight.",
                "SEO title must be 60 characters or fewer.",
                "Meta description must be 160 characters or fewer.",
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
                "German section headings must use: Produkt-Highlights, Lieferumfang, Technische Daten, Kompatibilität, Montage-Tipps.",
                "Avoid AI-like German compounds such as Abbrechersystem, Propellerhalterungswellenbasis, or Propellerhalterungswelle. Prefer Schutzsystem, Stoßschutzsystem, or Propellerhalterung.",
                "Run a German QA pass for article/noun gender, singular/plural, and common RC terms. Example: einen Vibrationstest, not eine Vibrationstest.",
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

    def validate_translation(self, source_payload, translated, selected_fields):
        selected_text_fields = [
            key for key in ["title", "meta_title", "meta_description"] if key in selected_fields
        ]
        missing = [key for key in selected_text_fields if key not in translated]
        if missing:
            raise CommandError(f"OpenAI translation missing fields: {', '.join(missing)}")
        if "meta_title" in selected_fields and len(translated["meta_title"]) > 60:
            raise CommandError(f"meta_title exceeds 60 chars: {len(translated['meta_title'])}")
        if "meta_description" in selected_fields and len(translated["meta_description"]) > 160:
            raise CommandError(
                f"meta_description exceeds 160 chars: {len(translated['meta_description'])}"
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
            self.validate_translation(source_payload, translated, selected_fields)
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
            if has_ai_cta(translated[key]):
                raise CommandError(f"{key} contains AI-style CTA wording that must be removed.")

        body_node_count = 0
        translated_body_node_count = 0
        translated_img_alt_count = 0
        translated_img_alt_chars = []
        dry_run_warnings = []
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
                    for index, text in enumerate(body_parser.text_nodes):
                        if is_origin_text(text):
                            skipped_source_origin_ids.add(index)
                            text_nodes_for_translation.append("")
                            removed_origin_count += 1
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
                        translated_nodes[index] = apply_german_qa_replacements(
                            translated_nodes[index]
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
        self.log(f"removed/skipped origin field count: {removed_origin_count}")
        self.log(f"removed shipping marketing phrase count: {removed_shipping_phrase_count}")
        self.log(f"empty html nodes removed count: {empty_html_nodes_removed_count}")
        self.log(f"payload keys: {', '.join(payload_keys)}")
        self.log(f"glossary matches: {len(matched_glossary)}")
        self.log(f"title chars: {len(translated.get('title', '') or '')}")
        self.log(f"meta_title chars: {len(translated.get('meta_title', '') or '')}")
        self.log(f"meta_description chars: {len(translated.get('meta_description', '') or '')}")
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
            if is_shipping_alt_text(value):
                dry_run_warnings.append(f"Warning: {key} contains shipping marketing wording.")
            if has_ai_cta(value):
                dry_run_warnings.append(f"Warning: {key} contains AI-style CTA wording.")
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
            "warnings": dry_run_warnings + ([body_warning] if body_warning else []),
            "summary": {
                "payload_keys": payload_keys,
                "title_chars": len(translated.get("title", "") or ""),
                "meta_title_chars": len(translated.get("meta_title", "") or ""),
                "meta_description_chars": len(translated.get("meta_description", "") or ""),
                "translated_text_node_count": translated_body_node_count,
                "translated_img_alt_count": translated_img_alt_count,
                "img_alt_chars_list": translated_img_alt_chars,
                "removed_skipped_origin_field_count": removed_origin_count,
                "removed_shipping_marketing_phrase_count": removed_shipping_phrase_count,
                "empty_html_nodes_removed_count": empty_html_nodes_removed_count,
                "glossary_matches": matched_glossary,
            },
        }
        self.write_review_file(review_file, review_data)

        if dry_run:
            self.log("Dry run complete. No Shopify writes performed.")
            return

        result = self.register_translations(product_id, target_locale, source_items, translated)
        self.log("translationsRegister completed:")
        self.log(json_dumps(result))
        verification = self.verify_written_translations(product_id, target_locale, payload_keys)
        self.log("Post-write verification:")
        self.log(json_dumps(verification))


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
