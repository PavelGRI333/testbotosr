"""Service for communication with iiko RMS.

Responsibilities:
- Authentication (obtain token)
- Loading of supplier and product catalogs (delegated to ``IikoCatalog``)
- Building XML for incoming invoices
- Sending the invoice to iiko and parsing the XML response

All network calls are performed with ``httpx.AsyncClient`` and the class
does not rely on any global state – the client is created per instance.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Tuple

import httpx
import xml.sax.saxutils as saxutils
import xml.etree.ElementTree as ET
from xml.etree.ElementTree import Element, SubElement, tostring

from bot.core.config import Settings
from bot.schemas.invoice import InvoiceData, InvoiceItem


class IikoServerError(RuntimeError):
    """Domain‑specific error for iiko server operations."""


class IikoServerService:
    def __init__(self, settings: Settings, http_client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = http_client or httpx.AsyncClient(base_url=self._settings.iiko_server.effective_base_url, timeout=self._settings.iiko_server.timeout)
        self._token: str | None = None

    # ---------------------------------------------------------------------
    # Authentication
    # ---------------------------------------------------------------------
    async def login(self) -> str:
        if self._token:
            return self._token
        params = {
            "login": self._settings.iiko_server.login,
            "pass": self._settings.iiko_server.password_sha1,
        }
        resp = await self._client.get("/auth", params=params)
        resp.raise_for_status()
        data = resp.json()
        token = data.get("token")
        if not token:
            raise IikoServerError("Authentication failed – token missing")
        self._token = token
        return token

    async def logout(self) -> None:
        if not self._token:
            return
        await self._client.get("/logout", params={"key": self._token})
        self._token = None

    # ---------------------------------------------------------------------
    # Catalog loading – delegates to IikoCatalog
    # ---------------------------------------------------------------------
    async def load_catalog(self, catalog: "IikoCatalog") -> None:  # noqa: F821 – forward reference
        token = await self.login()
        # Suppliers
        sup_resp = await self._client.get("/suppliers", params={"key": token})
        sup_resp.raise_for_status()
        suppliers_xml = sup_resp.text
        # Products
        prod_resp = await self._client.get("/products", params={"key": token})
        prod_resp.raise_for_status()
        products_xml = prod_resp.text
        catalog.load(suppliers_xml, products_xml)

    # ---------------------------------------------------------------------
    # XML building helpers
    # ---------------------------------------------------------------------
    def _format_decimal(self, value: Decimal) -> str:
        # Remove trailing zeros, keep '.' as decimal separator
        normalized = value.normalize()
        # ``normalize`` may produce scientific notation; format explicitly
        return f"{normalized:f}".rstrip('0').rstrip('.') if '.' in f"{normalized:f}" else f"{normalized:f}"

    def _build_xml(
        self,
        invoice: InvoiceData,
        *,
        supplier_id: str,
        store_id: str,
        resolved: Dict[str, str],
        use_price_from_item: bool = True,
    ) -> str:
        """Build XML document for ``incomingInvoice``.

        ``resolved`` maps original product names to iiko GUIDs.
        ``use_price_from_item`` toggles whether ``price`` is taken from the
        ``InvoiceItem.price`` field or calculated as ``amount / quantity``.
        """
        doc = Element('document')
        SubElement(doc, 'documentNumber').text = saxutils.escape(invoice.document_number)
        dt = datetime.datetime.combine(invoice.document_date, datetime.time(hour=12, minute=0, second=0))
        SubElement(doc, 'dateIncoming').text = dt.strftime('%Y-%m-%dT%H:%M:%S')
        SubElement(doc, 'useDefaultDocumentTime').text = 'false'
        SubElement(doc, 'status').text = 'NEW'
        SubElement(doc, 'supplier').text = saxutils.escape(supplier_id)
        SubElement(doc, 'defaultStore').text = saxutils.escape(store_id)

        items_el = SubElement(doc, 'items')
        for idx, item in enumerate(invoice.items, start=1):
            product_guid = resolved.get(item.name)
            if not product_guid:
                continue  # caller should guarantee mapping exists
            item_el = SubElement(items_el, 'item')
            SubElement(item_el, 'num').text = str(idx)
            SubElement(item_el, 'productId').text = saxutils.escape(product_guid)
            SubElement(item_el, 'storeId').text = saxutils.escape(store_id)
            SubElement(item_el, 'amount').text = self._format_decimal(item.quantity)
            # price handling
            if use_price_from_item and item.price is not None:
                price_val = item.price
            else:
                # fallback to amount/quantity – avoid division by zero
                price_val = item.amount / item.quantity if item.quantity != 0 else Decimal('0')
            SubElement(item_el, 'price').text = self._format_decimal(price_val)
            SubElement(item_el, 'sum').text = self._format_decimal(item.amount)

        xml_bytes = tostring(doc, encoding='utf-8')
        return xml_bytes.decode('utf-8')

    # ---------------------------------------------------------------------
    # Invoice submission
    # ---------------------------------------------------------------------
    async def create_incoming_invoice(
        self,
        invoice: InvoiceData,
        *,
        supplier_id: str,
        store_id: str,
        resolved: Dict[str, str],
    ) -> Tuple[bool, str]:
        """Send ``invoice`` to iiko and return ``(ok, message)``.

        The response XML is expected to contain either ``<valid>true</valid>``
        or an ``<errorMessage>`` element.
        """
        token = await self.login()
        xml_body = self._build_xml(
            invoice,
            supplier_id=supplier_id,
            store_id=store_id,
            resolved=resolved,
        )
        headers = {"Content-Type": "application/xml"}
        url = f"/documents/import/incomingInvoice?key={token}"
        resp = await self._client.post(url, content=xml_body.encode('utf-8'), headers=headers)
        resp.raise_for_status()
        # Parse response XML
        try:
            root = ET.fromstring(resp.text)
            valid_el = root.find('.//valid')
            if valid_el is not None and valid_el.text == 'true':
                return True, 'Документ успешно импортирован.'
            err_el = root.find('.//errorMessage')
            message = err_el.text if err_el is not None else 'Неизвестная ошибка импорта.'
            return False, message
        except Exception as exc:  # pragma: no cover – defensive
            raise IikoServerError(f'Failed to parse iiko response: {exc}') from exc

# End of file
