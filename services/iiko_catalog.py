"""Iiko catalog caching and matching utilities.

Provides:
- Loading of suppliers and products from XML strings.
- Normalisation of names for matching.
- Fuzzy search of product names (rapidfuzz).
- Alias handling persisted to JSON.
- TTL based staleness check.

All I/O (file reads/writes) is isolated; the class works purely on the
provided XML content, making it easy to unit‑test.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from rapidfuzz import process, fuzz
import xml.etree.ElementTree as ET


def _norm(name: str) -> str:
    """Normalise a supplier or product name.

    - lower‑case
    - replace doubled quotes ``""`` with a single ``"``
    - strip common prefix ``(Выводим)`` (case‑insensitive)
    - strip surrounding quotes and whitespace
    - collapse multiple spaces to a single space
    """
    if not name:
        return ""
    s = name.lower()
    s = s.replace('""', '"')
    # remove prefix like "(выводим)"
    prefix = '(выводим)'
    if s.startswith(prefix):
        s = s[len(prefix) :]
    s = s.strip(' "')
    # collapse spaces
    s = " ".join(s.split())
    return s


class IikoCatalog:
    """Cache of iiko dictionaries and fuzzy‑matching helpers.

    The class holds two main indexes:
    * ``_suppliers_by_inn`` – map of numeric INN → GUID
    * ``_suppliers_by_name`` – map of normalised name → GUID
    * ``_products_by_name`` – map of normalised name → GUID
    * ``_product_names`` – list of all normalised product names (for rapidfuzz)
    * ``_aliases`` – explicit alias map loaded from a JSON file.
    """

    def __init__(self, aliases_path: Path, ttl_sec: int = 300) -> None:
        self._aliases_path = aliases_path
        self._ttl_sec = ttl_sec
        self._loaded_at: float | None = None
        self._suppliers_by_inn: Dict[str, str] = {}
        self._suppliers_by_name: Dict[str, str] = {}
        self._products_by_name: Dict[str, str] = {}
        self._product_names: List[str] = []
        self._aliases: Dict[str, str] = {}

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------
    def is_stale(self) -> bool:
        """Return ``True`` if the cached data is older than ``ttl_sec``.
        """
        if self._loaded_at is None:
            return True
        return (time.time() - self._loaded_at) > self._ttl_sec

    def load(self, suppliers_xml: str, products_xml: str) -> None:
        """Parse supplied XML strings and fill internal indexes.

        The method also merges any persisted aliases.
        """
        # Suppliers ----------------------------------------------------------
        root = ET.fromstring(suppliers_xml)
        for employee in root.findall('.//employee'):
            # filter flags
            supplier_flag = employee.findtext('supplier')
            deleted_flag = employee.findtext('deleted')
            if supplier_flag != 'true' or deleted_flag == 'true':
                continue
            guid = employee.findtext('id')
            inn_raw = employee.findtext('taxpayerIdNumber') or ''
            inn = ''.join(filter(str.isdigit, inn_raw))
            name_raw = employee.findtext('name') or ''
            name = _norm(name_raw)
            if inn:
                self._suppliers_by_inn[inn] = guid
            if name:
                self._suppliers_by_name[name] = guid

        # Products ----------------------------------------------------------
        root = ET.fromstring(products_xml)
        for prod in root.findall('.//productDto'):
            ptype = prod.findtext('productType')
            if ptype not in {'GOODS', 'OUTER'}:
                continue
            guid = prod.findtext('id')
            name_raw = prod.findtext('name') or ''
            name = _norm(name_raw)
            if name:
                self._products_by_name[name] = guid
                self._product_names.append(name)

        # Aliases -----------------------------------------------------------
        self._load_aliases()
        # Apply aliases (they have priority over the auto‑generated index)
        for alias_name, alias_guid in self._aliases.items():
            self._products_by_name[alias_name] = alias_guid
            if alias_name not in self._product_names:
                self._product_names.append(alias_name)

        self._loaded_at = time.time()

    # ---------------------------------------------------------------------
    # Supplier matching
    # ---------------------------------------------------------------------
    def match_supplier(self, inn: str | None, name: str | None) -> str | None:
        """Return supplier GUID.

        Preference order: exact INN → normalised name.
        """
        if inn:
            inn_digits = ''.join(filter(str.isdigit, inn))
            guid = self._suppliers_by_inn.get(inn_digits)
            if guid:
                return guid
        if name:
            norm_name = _norm(name)
            return self._suppliers_by_name.get(norm_name)
        return None

    # ---------------------------------------------------------------------
    # Product matching
    # ---------------------------------------------------------------------
    def match_product(self, name: str, limit: int = 3) -> List[Tuple[str, int, str]]:
        """Fuzzy match a product name.

        Returns a list of tuples ``(original_name, score, guid)`` sorted by
        descending score.  An exact match yields ``score == 100``.
        """
        norm_name = _norm(name)
        # Exact lookup first
        if guid := self._products_by_name.get(norm_name):
            return [(name, 100, guid)]
        # Fuzzy search using token_set_ratio
        results = process.extract(
            norm_name,
            self._product_names,
            scorer=fuzz.token_set_ratio,
            limit=limit,
        )
        # ``results`` is a list of (matched_name, score, index). Convert to guid.
        matched: List[Tuple[str, int, str]] = []
        for matched_name, score, _ in results:
            guid = self._products_by_name.get(matched_name)
            if guid:
                matched.append((matched_name, int(score), guid))
        return matched

    # ---------------------------------------------------------------------
    # Alias handling
    # ---------------------------------------------------------------------
    def add_alias(self, name: str, guid: str) -> None:
        """Persist a new alias and update internal indexes.
        """
        norm_name = _norm(name)
        self._aliases[norm_name] = guid
        self._products_by_name[norm_name] = guid
        if norm_name not in self._product_names:
            self._product_names.append(norm_name)
        self._save_aliases()

    # ---------------------------------------------------------------------
    # Private helpers
    # ---------------------------------------------------------------------
    def _load_aliases(self) -> None:
        if self._aliases_path.is_file():
            try:
                data = json.loads(self._aliases_path.read_text(encoding='utf-8'))
                if isinstance(data, dict):
                    # ensure keys are normalised
                    self._aliases = { _norm(k): v for k, v in data.items() }
            except Exception as exc:  # pragma: no cover – defensive
                # If the file is corrupted, start with an empty dict.
                self._aliases = {}
        else:
            self._aliases = {}

    def _save_aliases(self) -> None:
        # Ensure directory exists
        self._aliases_path.parent.mkdir(parents=True, exist_ok=True)
        # Write as compact JSON (keys already normalised)
        data = {k: v for k, v in self._aliases.items()}
        self._aliases_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

# End of file
