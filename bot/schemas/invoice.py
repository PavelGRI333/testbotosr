from pydantic import BaseModel, Field


class InvoiceItem(BaseModel):
    name: str
    quantity: float
    amount: float


class InvoiceData(BaseModel):
    supplier: str | None = None
    delivery_address: str | None = Field(default=None, alias="delivery_address")
    document_number: str | None = None
    document_date: str | None = None
    items: list[InvoiceItem] = Field(default_factory=list)

    model_config = {"populate_by_name": True}
