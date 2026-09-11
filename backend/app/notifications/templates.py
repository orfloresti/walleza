"""en/es reminder email content (design D54, task 4.5/4.11).

The subject line MUST NOT include the amount (design D54, spec
"Reminder Content Is Useful Without Over-Exposing Data") — enforced
STRUCTURALLY here, not by convention: `_SUBJECTS` is a plain string with no
`{amount}` placeholder anywhere in it, so there is no interpolation slot
for a caller to accidentally fill with a number. The body MAY include
amount, account name, and category names.

Plain Python dicts, not the frontend's i18n JSON bundles (`frontend/public/
i18n/{en,es}.json`) — those files are not part of the Lambda deployment
zip, so email copy is its own small, self-contained surface (design D54's
explicit rejection of "reusing the frontend i18n bundles").
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

_SUBJECTS = {
    "en": "Upcoming {type} reminder",
    "es": "Recordatorio de {type} próximo",
}

_TYPE_LABELS = {
    "en": {"income": "income", "expense": "expense"},
    "es": {"income": "ingreso", "expense": "gasto"},
}

_BODY_TEMPLATES = {
    "en": (
        "Hi,\n\n"
        'A recurring {type} of {amount} {currency} on account "{account_name}" '
        "is due on {occurrence_date}.{category_line}\n\n"
        "Manage this recurrence: {web_app_url}\n"
    ),
    "es": (
        "Hola,\n\n"
        'Un {type} recurrente de {amount} {currency} en la cuenta "{account_name}" '
        "vence el {occurrence_date}.{category_line}\n\n"
        "Administra esta recurrencia: {web_app_url}\n"
    ),
}

_CATEGORY_LINE = {
    "en": " Category: {categories}.",
    "es": " Categoría: {categories}.",
}


def render_reminder(
    *,
    locale: str,
    type: str,
    amount: Decimal,
    currency: str,
    account_name: str,
    occurrence_date: date,
    web_app_url: str,
    category_names: list[str] | None = None,
) -> tuple[str, str]:
    """Returns `(subject, body)` for one due recurrence's reminder.
    `locale` falls back to `'en'` for any value other than `'en'`/`'es'` —
    the DB CHECK constraint `ck_recurring_transaction_reminder_locale`
    already restricts stored values to those two, so this fallback is
    defense-in-depth, never the expected path."""
    resolved_locale = locale if locale in _SUBJECTS else "en"
    type_label = _TYPE_LABELS[resolved_locale].get(type, type)
    subject = _SUBJECTS[resolved_locale].format(type=type_label)

    category_line = ""
    if category_names:
        category_line = _CATEGORY_LINE[resolved_locale].format(
            categories=", ".join(category_names)
        )

    body = _BODY_TEMPLATES[resolved_locale].format(
        type=type_label,
        amount=amount,
        currency=currency,
        account_name=account_name,
        occurrence_date=occurrence_date.isoformat(),
        category_line=category_line,
        web_app_url=web_app_url,
    )
    return subject, body
