from pydantic import BaseModel, Field, model_validator, field_validator
from decimal import Decimal
from datetime import datetime, date


class Supplier(BaseModel):
    name: str
    inn: str | None = None

class InvoiceItem(BaseModel):
    name: str
    quantity: Decimal
    unit: str | None = None
    price: Decimal | None = None  # if None, will be calculated from amount/quantity
    amount: Decimal
    vat_rate: Decimal | None = None
    vat_sum: Decimal | None = None

    @model_validator(mode="after")
    def calculate_price(cls, values):
        if values.price is None and values.quantity != 0:
            # round to 2 decimal places
            values.price = (values.amount / values.quantity).quantize(Decimal('0.01'))
        return values

class InvoiceData(BaseModel):
    supplier: Supplier
    buyer_inn: str | None = None
    document_number: str
    document_date: date
    delivery_address: str | None = None
    items: list[InvoiceItem]

    @field_validator('document_date', mode='before')
    def parse_date(cls, v):
        if isinstance(v, date):
            return v
        if isinstance(v, str):
            # Try ISO first
            try:
                return datetime.fromisoformat(v).date()
            except ValueError:
                pass
            # Common Russian formats e.g., "07 мая 2026 г." or "07 мая 2026"
            v_clean = v.replace('г.', '').strip()
            parts = v_clean.split()
            if len(parts) >= 3:
                day = parts[0]
                month_str = parts[1].lower()
                year = parts[2]
                month_map = {
                    'января': '01', 'февраля': '02', 'марта': '03', 'апреля': '04',
                    'мая': '05', 'июня': '06', 'июля': '07', 'августа': '08',
                    'сентября': '09', 'октября': '10', 'ноября': '11', 'декабря': '12',
                    # short forms
                    'янв': '01', 'фев': '02', 'мар': '03', 'апр': '04',
                    'май': '05', 'июн': '06', 'июл': '07', 'авг': '08',
                    'сен': '09', 'окт': '10', 'ноя': '11', 'дек': '12'
                }
                month = month_map.get(month_str)
                if month:
                    try:
                        return date(int(year), int(month), int(day))
                    except ValueError:
                        pass
            raise ValueError(f"Unable to parse document_date: {v}")
        raise TypeError('document_date must be str or date')

    model_config = {"populate_by_name": True}

