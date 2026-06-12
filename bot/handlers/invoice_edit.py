from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.invoice_edit import (
    InvCB,
    header_keyboard,
    item_keyboard,
    root_keyboard,
)
from bot.schemas.invoice import InvoiceData, InvoiceItem, _to_decimal
from bot.services.invoice_render import render_item, render_overview
from bot.states.invoice import InvoiceEdit

logger = logging.getLogger(__name__)

router = Router(name="invoice_edit")

_FIELD_LABELS = {
    "sup": "Контрагент",
    "num": "Номер",
    "date": "Дата (дд.мм.гггг)",
    "addr": "Адрес поставки",
    "name": "Наименование",
    "qty": "Кол-во",
    "unit": "Ед. изм.",
    "price": "Цена",
    "amt": "Сумма",
}

_NUMERIC_FIELDS = {"qty", "price", "amt"}

_ITEM_KEYS = {"name": "name", "qty": "quantity", "unit": "unit", "price": "price", "amt": "amount"}


async def _load(state: FSMContext) -> InvoiceData:
    data = await state.get_data()
    return InvoiceData.model_validate(data["invoice"])


async def _save(state: FSMContext, inv: InvoiceData) -> None:
    await state.update_data(invoice=inv.model_dump(mode="json"))


def _parse_date(raw: str) -> date | None:
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


async def _send_to_iiko_stub(inv: InvoiceData) -> bool:
    logger.info(
        "STUB: накладная %s, позиций=%d (в iiko НЕ отправлено)",
        inv.document_number,
        len(inv.items),
    )
    return True


async def show_editor(message: Message, state: FSMContext, invoice: InvoiceData) -> None:
    await state.set_state(InvoiceEdit.overview)
    await state.update_data(invoice=invoice.model_dump(mode="json"))
    sent = await message.answer(
        render_overview(invoice),
        reply_markup=root_keyboard(invoice),
        parse_mode="HTML",
    )
    await state.update_data(msg_id=sent.message_id)


@router.callback_query(InvCB.filter(F.a == "root"))
async def cb_root(cb: CallbackQuery, state: FSMContext) -> None:
    inv = await _load(state)
    await cb.message.edit_text(render_overview(inv), reply_markup=root_keyboard(inv), parse_mode="HTML")  # type: ignore[union-attr]
    await state.set_state(InvoiceEdit.overview)
    await cb.answer()


@router.callback_query(InvCB.filter(F.a == "hdr"))
async def cb_header(cb: CallbackQuery, state: FSMContext) -> None:
    inv = await _load(state)
    await cb.message.edit_text(render_overview(inv), reply_markup=header_keyboard(), parse_mode="HTML")  # type: ignore[union-attr]
    await cb.answer()


@router.callback_query(InvCB.filter(F.a == "item"))
async def cb_item(cb: CallbackQuery, callback_data: InvCB, state: FSMContext) -> None:
    inv = await _load(state)
    i = callback_data.i
    if not 0 <= i < len(inv.items):
        await cb.answer("Позиция не найдена", show_alert=True)
        return
    await cb.message.edit_text(render_item(inv, i), reply_markup=item_keyboard(i), parse_mode="HTML")  # type: ignore[union-attr]
    await cb.answer()


@router.callback_query(InvCB.filter(F.a == "field"))
async def cb_field(cb: CallbackQuery, callback_data: InvCB, state: FSMContext) -> None:
    label = _FIELD_LABELS.get(callback_data.f, callback_data.f)
    await state.update_data(edit_i=callback_data.i, edit_f=callback_data.f)
    await state.set_state(InvoiceEdit.waiting_value)
    await cb.message.answer(f"Введите новое значение для «{label}»:")  # type: ignore[union-attr]
    await cb.answer()


@router.message(InvoiceEdit.waiting_value, F.text)
async def on_value(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    i = data.get("edit_i", -1)
    f = data.get("edit_f", "")
    raw = (message.text or "").strip()

    parsed_value: Any = None
    if f in _NUMERIC_FIELDS:
        parsed_value = _to_decimal(raw)
        if parsed_value is None:
            await message.answer("Не похоже на число, попробуйте ещё раз:")
            return
    elif f == "date":
        parsed_value = _parse_date(raw)
        if parsed_value is None:
            await message.answer("Неверная дата. Формат дд.мм.гггг или гггг-мм-дд:")
            return
    else:
        parsed_value = raw

    inv = await _load(state)

    if i == -1:
        if f == "sup":
            inv.supplier.name = parsed_value
        elif f == "num":
            inv.document_number = parsed_value
        elif f == "date":
            inv.document_date = parsed_value
        elif f == "addr":
            inv.delivery_address = parsed_value
    else:
        if not 0 <= i < len(inv.items):
            await message.answer("Позиция не найдена.")
            await state.set_state(InvoiceEdit.overview)
            return
        payload = inv.items[i].model_dump()
        payload[_ITEM_KEYS[f]] = parsed_value
        inv.items[i] = InvoiceItem.model_validate(payload)

    await _save(state, inv)
    await state.set_state(InvoiceEdit.overview)

    msg_id = data.get("msg_id")
    try:
        await message.bot.edit_message_text(  # type: ignore[union-attr]
            chat_id=message.chat.id,
            message_id=msg_id,
            text=render_overview(inv),
            reply_markup=root_keyboard(inv),
            parse_mode="HTML",
        )
    except Exception:
        sent = await message.answer(render_overview(inv), reply_markup=root_keyboard(inv), parse_mode="HTML")
        await state.update_data(msg_id=sent.message_id)
    await message.answer("✅ Обновлено.")


@router.callback_query(InvCB.filter(F.a == "send"))
async def cb_send(cb: CallbackQuery, state: FSMContext) -> None:
    inv = await _load(state)
    await _send_to_iiko_stub(inv)
    await cb.message.edit_text(  # type: ignore[union-attr]
        "✅ Накладная отправлена в iiko.\n(заглушка: реальная интеграция ещё не подключена)"
    )
    await cb.answer("Отправлено")
    await state.clear()
