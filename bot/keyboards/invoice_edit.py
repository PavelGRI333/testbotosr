from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.schemas.invoice import InvoiceData


class InvCB(CallbackData, prefix="inv"):
    a: str
    i: int = -1
    f: str = ""


def _short(text: str | None, limit: int = 28) -> str:
    text = (text or "—").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def root_keyboard(inv: InvoiceData) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="📝 Шапка", callback_data=InvCB(a="hdr").pack())]
    ]
    for idx, item in enumerate(inv.items):
        mark = " ⚠️" if item.needs_review else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"📦 {idx + 1}. {_short(item.name)}{mark}",
                    callback_data=InvCB(a="item", i=idx).pack(),
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text="✅ Отправить в iiko", callback_data=InvCB(a="send").pack())]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def header_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="Поставщик", callback_data=InvCB(a="field", i=-1, f="sup").pack())],
        [InlineKeyboardButton(text="Номер", callback_data=InvCB(a="field", i=-1, f="num").pack())],
        [InlineKeyboardButton(text="Дата", callback_data=InvCB(a="field", i=-1, f="date").pack())],
        [InlineKeyboardButton(text="Адрес поставки", callback_data=InvCB(a="field", i=-1, f="addr").pack())],
        [InlineKeyboardButton(text="🔙 Назад", callback_data=InvCB(a="root").pack())],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def item_keyboard(i: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="Наименование", callback_data=InvCB(a="field", i=i, f="name").pack())],
        [
            InlineKeyboardButton(text="Кол-во", callback_data=InvCB(a="field", i=i, f="qty").pack()),
            InlineKeyboardButton(text="Ед.изм.", callback_data=InvCB(a="field", i=i, f="unit").pack()),
        ],
        [
            InlineKeyboardButton(text="Цена", callback_data=InvCB(a="field", i=i, f="price").pack()),
            InlineKeyboardButton(text="Сумма", callback_data=InvCB(a="field", i=i, f="amt").pack()),
        ],
        [InlineKeyboardButton(text="🔙 Назад", callback_data=InvCB(a="root").pack())],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)
