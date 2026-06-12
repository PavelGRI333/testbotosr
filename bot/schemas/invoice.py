from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, field_validator, model_validator


def _to_decimal(v: object) -> Decimal | None:
    if v is None or isinstance(v, Decimal):
        return v
    if isinstance(v, int | float):
        return Decimal(str(v))
    if isinstance(v, str):
        s = v.strip()
        if s.lower() in {"", "-", "—", "–", "null", "none", "n/a", "нет"}:
            return None
        s = s.replace("\u00a0", "").replace(" ", "")
        s = s.replace("руб.", "").replace("руб", "").replace("₽", "").replace("р.", "")
        s = s.replace(",", ".")
        try:
            return Decimal(s)
        except InvalidOperation:
            return None
    return None


class Supplier(BaseModel):
    name: str
    inn: str | None = None


class InvoiceItem(BaseModel):
    name: str
    quantity: Decimal | None = None
    unit: str | None = None
    price: Decimal | None = None
    amount: Decimal | None = None
    vat_rate: Decimal | None = None
    vat_sum: Decimal | None = None

    @field_validator("quantity", "price", "amount", "vat_rate", "vat_sum", mode="before")
    @classmethod
    def _clean_decimal(cls, v: object) -> Decimal | None:
        return _to_decimal(v)

    @model_validator(mode="after")
    def _fill_missing(self) -> InvoiceItem:
        if self.amount is None and self.quantity is not None and self.price is not None:
            self.amount = self.quantity * self.price
        if self.price is None and self.amount is not None and self.quantity:
            self.price = self.amount / self.quantity
        return self

    @property
    def needs_review(self) -> bool:
        return self.amount is None or self.quantity is None or self.price is None


class InvoiceData(BaseModel):
    supplier: Supplier
    buyer_inn: str | None = None
    document_number: str | None = None
    document_date: date | None = None
    delivery_address: str | None = None
    items: list[InvoiceItem]

    @field_validator("document_date", mode="before")
    @classmethod
    def parse_date(cls, v: object) -> date | None:
        if v is None:
            return None
        if isinstance(v, date):
            return v
        if isinstance(v, str):
            s = v.strip()
            if s.lower() in {"", "null", "none", "n/a"}:
                return None
            try:
                return datetime.fromisoformat(s).date()
            except ValueError:
                pass
            s_clean = s.replace("г.", "").strip()
            parts = s_clean.split()
            if len(parts) >= 3:
                day = parts[0]
                month_str = parts[1].lower()
                year = parts[2]
                month_map = {
                    "января": "01", "февраля": "02", "марта": "03", "апреля": "04",
                    "мая": "05", "июня": "06", "июля": "07", "августа": "08",
                    "сентября": "09", "октября": "10", "ноября": "11", "декабря": "12",
                    "янв": "01", "фев": "02", "мар": "03", "апр": "04",
                    "май": "05", "июн": "06", "июл": "07", "авг": "08",
                    "сен": "09", "окт": "10", "ноя": "11", "дек": "12",
                }
                month = month_map.get(month_str)
                if month:
                    try:
                        return date(int(year), int(month), int(day))
                    except ValueError:
                        pass
            try:
                return datetime.strptime(s, "%d.%m.%Y").date()
            except ValueError:
                pass
            return None
        return None

    @property
    def needs_review(self) -> bool:
        return any(i.needs_review for i in self.items)

    model_config = {"populate_by_name": True}
