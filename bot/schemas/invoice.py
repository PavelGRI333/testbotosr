from __future__ import annotations

from decimal import Decimal
from datetime import date
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


class Supplier(BaseModel):
    name: str
    inn: Optional[str] = None


class InvoiceItem(BaseModel):
    name: str
    quantity: Decimal
    unit: Optional[str] = None
    price: Optional[Decimal] = None  # price per unit without VAT; may be None
    amount: Decimal  # total without VAT
    vat_rate: Optional[Decimal] = None
    vat_sum: Optional[Decimal] = None

    @model_validator(mode="after")
    def _fill_price(cls, values: "InvoiceItem") -> "InvoiceItem":
        """If price is missing, calculate it from amount/quantity (2‑decimal rounding)."""
        if values.price is None and values.quantity != 0:
            values.price = (values.amount / values.quantity).quantize(Decimal("0.01"))
        return values


class InvoiceData(BaseModel):
    supplier: Supplier
    buyer_inn: Optional[str] = None
    document_number: str
    document_date: date
    delivery_address: Optional[str] = Field(default=None, alias="delivery_address")
    items: List[InvoiceItem]

    model_config = {"populate_by_name": True}

