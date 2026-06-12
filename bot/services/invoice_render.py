from __future__ import annotations

import html

from bot.schemas.invoice import InvoiceData


def _v(x: object) -> str:
    return "—" if x is None or x == "" else html.escape(str(x))


def render_overview(inv: InvoiceData) -> str:
    lines = [
        "<b>📋 Накладная</b>",
        "",
        f"<b>Контрагент:</b> {_v(inv.supplier.name)}",
        f"<b>ИНН:</b> {_v(inv.supplier.inn)}",
        f"<b>Номер:</b> {_v(inv.document_number)}",
        f"<b>Дата:</b> {_v(inv.document_date)}",
        f"<b>Адрес поставки:</b> {_v(inv.delivery_address)}",
        "",
        "<b>Позиции:</b>",
    ]
    if not inv.items:
        lines.append("—")
    for idx, it in enumerate(inv.items):
        mark = " ⚠️" if it.needs_review else ""
        lines.append(
            f"{idx + 1}. {_v(it.name)} — {_v(it.quantity)} {_v(it.unit)} "
            f"× {_v(it.price)} = {_v(it.amount)}{mark}"
        )
    if inv.needs_review:
        lines += ["", "⚠️ Есть позиции с непрочитанными значениями, проверьте перед отправкой."]
    return "\n".join(lines)


def render_item(inv: InvoiceData, i: int) -> str:
    it = inv.items[i]
    lines = [
        f"<b>Позиция {i + 1}</b>",
        "",
        f"<b>Наименование:</b> {_v(it.name)}",
        f"<b>Кол-во:</b> {_v(it.quantity)}",
        f"<b>Ед.изм.:</b> {_v(it.unit)}",
        f"<b>Цена:</b> {_v(it.price)}",
        f"<b>Сумма:</b> {_v(it.amount)}",
    ]
    if it.needs_review:
        lines += ["", "⚠️ Проверьте значения этой позиции."]
    return "\n".join(lines)
