# Shopify Product Translation and SEO Skill

Use this skill when translating Shopify products, editing translated product content, or reviewing Shopify SEO output.

## Existing Code

- Translation command: `backend/shopify_sync/management/commands/translate_shopify_product.py`
- German glossary: `backend/shopify_sync/translation_glossary_de.json`
- French glossary: `backend/shopify_sync/translation_glossary_fr.json`
- Spanish glossary: `backend/shopify_sync/translation_glossary_es.json`
- Italian glossary: `backend/shopify_sync/translation_glossary_it.json`
- Japanese glossary: `backend/shopify_sync/translation_glossary_ja.json`

## Required Workflow

- Use `translate_shopify_product.py` for Shopify product translations.
- Work on exactly one `product_id` and one `target_locale` at a time.
- Default to `--dry-run`; never start with a formal Shopify write.
- Do not enable or run batch translation until the single-product workflow is stable and the user explicitly asks for batch work.
- First-phase automatic translation supports dry-run previews for these locales: `de`, `fr`, `es`, `it`, and `ja`.
- The registered multi-locale task is `shopify_translation_multi_locale_dry_run`; it must remain dry-run only and must not become a write task.
- The registered batch multi-locale task is `shopify_translation_batch_multi_locale_dry_run`; it must remain dry-run only and must not become a write task.
- Multi-locale dry-run runs each locale independently. A single locale failure must not stop the remaining locales.
- Each locale writes its own command review file named `backend/logs/shopify_translation_command_review_<locale>.json`, and the task writes the summary review to `logs/shopify_translation_multi_locale_dry_run_review.json`.
- Each locale result must include `failure_type` and `no_shopify_writes_confirmed`. `no_shopify_writes_confirmed` is true only when the locale command succeeds and stdout contains `Dry run complete. No Shopify writes performed.`
- Supported multi-locale failure types include `docker_permission_denied`, `missing_product_id`, `missing_env`, `command_error`, `timeout`, `unknown`, `glossary_invalid`, and `unsupported_locale`.
- Batch multi-locale dry-run is limited to at most 3 configured products and at most 5 locales. It must never auto-scan the whole Shopify store.
- Batch multi-locale dry-run runs each product/locale independently. A single product/locale failure must not stop the remaining combinations.
- Batch per-combination review files are named `backend/logs/shopify_translation_command_review_<product_id>_<locale>.json`, and the summary review is `logs/shopify_translation_batch_multi_locale_dry_run_review.json`.
- Batch result `no_shopify_writes_confirmed` follows the same rule: the command must succeed and stdout must contain `Dry run complete. No Shopify writes performed.`
- Generate a `--review-file` for dry-run review before any formal write.
- Show or summarize the review output before asking for write confirmation.
- Formal Shopify translation writes require explicit user confirmation after review.
- After a formal write, verify `translationsRegister` returned `userErrors=[]`, then re-read `translatableResource` and confirm the written locale values exist and `outdated=false`.

## Fields

The translation workflow can include:

- `title`
- `body_html`
- `meta_title`
- `meta_description`
- image `alt` text inside product body HTML

## HTML Preservation

- Preserve the original HTML structure.
- Do not remove product sections, lists, tables, images, links, or attributes except for explicitly filtered origin/source or shipping-marketing content and empty nodes left by that filtering.
- Do not break image tags or alt attributes.
- Do not create empty tags.
- Preserve `href`, `src`, `class`, `style`, `id`, and `data-*` attributes exactly.
- If visible text is itself a URL, preserve it exactly. Do not translate it, change capitalization such as `https://` to `Https://`, or modify query parameters.
- Preserve specs, model names, battery counts, dimensions, compatibility notes, and package contents.

## Translation Quality

- Translation should be natural, customer-facing, and accurate.
- Do not invent features, certifications, warranty promises, local stock promises, or shipping promises.
- Avoid generic AI phrases and hard-sell CTA text such as "buy now" unless the source requires it.
- Avoid keyword stuffing.
- Avoid awkward literal translations; prefer idiomatic product language.
- For German, use the glossary and existing QA replacements in the command file.
- For non-German locales, use the matching glossary file and keep the same safety rules: preserve HTML, protect URLs/attributes, localize image alt text, avoid origin/shipping claims, and avoid exaggerated military/combat wording.
- Glossary files must be valid JSON, cover core RC product terminology, and must not include shipping origin or exaggerated marketing claims.
- German QA must prefer concise, natural German RC ecommerce wording, avoid overlong compounds, normalize headings such as `Produkt-Highlights`, `Lieferumfang`, `Technische Daten`, `Kompatibilität`, `Montage-Tipps`, and `Support & Garantie`, and warn on title/meta length problems.
- For battery/accessory product titles over 65 characters, keep the model plus voltage/capacity plus product type. Example: `YuXiang F112S 7,4V 1200mAh LiPo Akku`. Secondary aircraft names such as `AH-1 Cobra` or broad category terms such as `RC Helikopter` may be omitted when needed.
- German QA must fix common dry-run findings such as `Trainigs-RC` -> `Trainings-RC`, `Trainigsflugzeugs` -> `Trainingsflugzeugs`, `Trainings-RC Flugzeug` -> `RC-Trainingsflugzeug`, `Aufprällenergie` -> `Aufprallenergie`, `Propellerhalterungsbasis` -> `Propellerhalterung`, `am Motorhaube` -> `an der Motorhaube`, `Garantie Bei` -> `Garantie bei`, and `Für das ... Allein.` / `Ausschließlich passend.` -> natural compatibility wording such as `Nur passend für das VolantexRC Sport Cub 500 4-Kanal RC Flugzeug (761-4 Sport Cub).` or `Nur passend für dieses Modell.`. Do not warn on correct `Aufprälle`.
- German battery/accessory QA must prefer `Smart-Akku` or `Akku` over stiff `Intelligenter Akku`, use `USB-C-Ladung` instead of `Type-C-Ladung`, fix `Technische Daten &amp; Und Fotos` to `Technische Daten &amp; Fotos`, and avoid exaggerated military/combat wording such as `Kampfeinsätze`; prefer neutral wording like `längere Flugzeiten`, `realistische Flugmanöver`, or `zuverlässige Energieversorgung`.
- Brushed and brushless motors must not be mixed. Translate `Brushed Motor` as `Bürstenmotor`, `High-Torque Brushed Motor` as `Hochdrehmoment-Bürstenmotor`, and `Brushless Motor` as `bürstenloser Motor`. If source text contains `Brushed Motor`, German output must not contain `bürstenlos`, `bürstenloser`, or `bürstenloses`.
- German SEO/body output should not leave English motor/parts words such as `Wingspan`, `Replacement`, `High-Torque`, or `Brushed Motor`; localize them naturally. English words inside URLs, href/src attributes, or URL-like visible text do not count as English leftovers.
- German QA warnings should be based on the final output after automatic cleanup. If a Brushed/Brushless term was corrected successfully and the final output no longer contains `bürstenlos`, record it as info rather than warning.
- Avoid exaggerated military/combat phrasing such as `Kampfkraft`, `dominieren`, `Kampf`, `militärische Einsätze`, and `Kampfeinsätze`; prefer neutral ecommerce wording such as `Zuverlässige Leistung für Ihr RC Flugzeug`, `Stellt Schub und Flugleistung wieder her`, or `Für stabile Flugleistung und zuverlässigen Antrieb`.

## Sensitive / Avoided Content

- Avoid origin claims such as "Made in China", "China origin", "mainland China", or equivalent German wording unless explicitly requested.
- Avoid unnecessary shipping marketing such as "worldwide shipping" when it is not part of the product facts.
- Filter origin/source/manufacturing-origin wording from product translation output, including Origin, Herkunft, Made in China, Mainland China, and Hergestellt in Festlandchina.
- Filter shipping marketing phrases from title, meta fields, body HTML, and image alt text, including worldwide shipping, ships worldwide, Weltweiter Versand, Versand weltweit, and Lieferung weltweit.

## SEO Rules

- Title should be concise and readable, not keyword-stuffed.
- Meta title should be useful for search and customers.
- Meta description should summarize the product clearly and honestly.
- If a source SEO field is already over the recommended limit, warn and continue; source SEO length must not block translation.
- Translated SEO fields must pass limits before write: meta title <= 60 characters and meta description <= 160 characters.
- If a translated meta description is too long, compress it once while preserving core product keywords; for BF109 400mm motor products, preserve BF109, 400mm, RC Plane/RC Flugzeug, brushed motor/Brushed Motor, and replacement/Ersatzmotor.
- Image alt text should describe the visible product or part.
- Do not hide irrelevant keywords in HTML or alt text.

## Safety

- Shopify publishing or translation writes require explicit user confirmation.
- Multi-locale and batch multi-locale dry-run tasks must not call Shopify mutations, `translationsRegister`, publish translations, update products, update variants, update orders, update inventory, or modify the database.
- Any future real Shopify translation write must be a separate task with explicit second confirmation after review.
- Do not expose OpenAI or Shopify API keys.
- Do not print or copy `OPENAI_API_KEY`, Shopify access tokens, or other secrets into logs, prompts, docs, review files, shell output, or Git.
- If only reviewing translation output, stay read-only.
- If a new repeated Shopify translation rule appears, update this skill or create a new dedicated skill so the workflow stays reusable.
