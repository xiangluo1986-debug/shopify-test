# Shopify Product Translation and SEO Skill

Use this skill when translating Shopify products, editing translated product content, or reviewing Shopify SEO output.

## Existing Code

- Translation command: `backend/shopify_sync/management/commands/translate_shopify_product.py`
- German glossary: `backend/shopify_sync/translation_glossary_de.json`

## Fields

The translation workflow can include:

- `title`
- `body_html`
- `meta_title`
- `meta_description`
- image `alt` text inside product body HTML

## HTML Preservation

- Preserve the original HTML structure.
- Do not remove product sections, lists, tables, images, links, or attributes.
- Do not break image tags or alt attributes.
- Do not create empty tags.
- Preserve specs, model names, battery counts, dimensions, compatibility notes, and package contents.

## Translation Quality

- Translation should be natural, customer-facing, and accurate.
- Do not invent features, certifications, warranty promises, local stock promises, or shipping promises.
- Avoid generic AI phrases and hard-sell CTA text such as "buy now" unless the source requires it.
- Avoid keyword stuffing.
- Avoid awkward literal translations; prefer idiomatic product language.
- For German, use the glossary and existing QA replacements in the command file.

## Sensitive / Avoided Content

- Avoid origin claims such as "Made in China", "China origin", "mainland China", or equivalent German wording unless explicitly requested.
- Avoid unnecessary shipping marketing such as "worldwide shipping" when it is not part of the product facts.

## SEO Rules

- Title should be concise and readable, not keyword-stuffed.
- Meta title should be useful for search and customers.
- Meta description should summarize the product clearly and honestly.
- Image alt text should describe the visible product or part.
- Do not hide irrelevant keywords in HTML or alt text.

## Safety

- Shopify publishing or translation writes require explicit user confirmation.
- Do not expose OpenAI or Shopify API keys.
- If only reviewing translation output, stay read-only.
