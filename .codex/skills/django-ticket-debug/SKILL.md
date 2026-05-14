---
name: django-ticket-debug
description: Debug and make small safe changes to the Django ticket system.
---

# Django Ticket Debug Skill

Use this skill when debugging or making small changes to the ticket system in this project.

## Safety

- Do not modify the ticket system unless the user explicitly asks.
- Do not modify Shopify sync while working on ticket-only tasks.
- Do not delete ticket data, attachments, comments, or related order data.
- Do not run destructive database commands.
- Inspect first, explain the plan, then make minimal changes.

## Files to Inspect

Typical ticket files:

- `backend/tickets/models.py`
- `backend/tickets/admin.py`
- `backend/tickets/views.py`
- `backend/tickets/templates/`
- `backend/tickets/migrations/`

## Debug Pattern

1. Reproduce or inspect the failing view/admin page.
2. Check model fields and nullable relationships.
3. Check admin methods, list display methods, and template assumptions.
4. Check queryset filtering and search logic.
5. Check migrations only when fields are added.
6. Make the smallest fix.
7. Ask the user to run Django check.

## Common Rules

- For admin search, extend existing `search_fields` or queryset logic.
- ID search should not break existing title, order number, customer, email, or description search.
- For pinned tickets, closed/resolved tickets should not remain pinned.
- Avoid updating `updated_at` when a purely display/order flag should not affect normal sorting.
- Do not change ticket status workflows unless requested.
- Do not touch ticket detail templates or models unless the task requires it.

## Validation

Ask before running:

```powershell
docker compose exec -T web python manage.py check
```

If migrations are added, tell the user to run:

```powershell
docker compose exec -T web python manage.py migrate
```
