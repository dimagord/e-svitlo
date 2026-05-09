"""Async API client for sm.e-svitlo.com.ua."""
from __future__ import annotations

import asyncio
import re
from html.parser import HTMLParser
from typing import Any

import aiohttp

from .const import (
    URL_ACCOUNTS,
    URL_CONSUMPTION_YEAR,
    URL_DETAILS,
    URL_LOGIN,
    URL_METER_PAGE,
    URL_SUBMIT,
    USER_AGENT,
)


class AuthError(Exception):
    """Raised when login fails."""


class ESvitloAccount:
    def __init__(self, internal_id: str, personal_no: str, name: str, address: str) -> None:
        self.internal_id = internal_id
        self.personal_no = personal_no
        self.name = name
        self.address = address

    def __repr__(self) -> str:
        return f"ESvitloAccount({self.personal_no}, a={self.internal_id})"


class _AccountTableParser(HTMLParser):
    """Parse the /account_household table to extract accounts."""

    def __init__(self) -> None:
        super().__init__()
        self._in_row = False
        self._cells: list[str] = []
        self._current_cell = ""
        self._internal_id: str | None = None
        self.accounts: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "tr":
            self._in_row = True
            self._cells = []
            self._internal_id = None
        elif tag == "td" and self._in_row:
            self._current_cell = ""
        elif tag == "a" and self._in_row:
            href = attrs_dict.get("href", "") or ""
            m = re.search(r"[?&]a=(\d+)", href)
            if m:
                self._internal_id = m.group(1)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._in_row:
            self._cells.append(self._current_cell.strip())
            self._current_cell = ""
        elif tag == "tr" and self._in_row:
            self._in_row = False
            # Expect at least 3 cells: personal_no, name, address
            if self._internal_id and len(self._cells) >= 3:
                self.accounts.append(
                    {
                        "internal_id": self._internal_id,
                        "personal_no": self._cells[0],
                        "name": self._cells[1],
                        "address": self._cells[2],
                    }
                )

    def handle_data(self, data: str) -> None:
        if self._in_row:
            self._current_cell += data


class ESvitloClient:
    """Async HTTP client for e-svitlo personal cabinet."""

    def __init__(self, base_url: str, email: str, password: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._email = email
        self._password = password
        self._session: aiohttp.ClientSession | None = None
        self._lock = asyncio.Lock()

    def _make_session(self) -> aiohttp.ClientSession:
        return aiohttp.ClientSession(
            headers={"User-Agent": USER_AGENT},
            cookie_jar=aiohttp.CookieJar(),
        )

    def _url(self, path: str) -> str:
        return self._base_url + path

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = self._make_session()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def login(self) -> None:
        """Authenticate and store session cookie. Raises AuthError on failure."""
        session = await self._ensure_session()
        data = aiohttp.FormData()
        data.add_field("email", self._email)
        data.add_field("password", self._password)

        async with session.post(
            self._url(URL_LOGIN),
            data=data,
            allow_redirects=True,
        ) as resp:
            final_url = str(resp.url)
            # Successful login redirects to /user_register; failure stays at /
            if final_url.rstrip("/") == self._base_url or "login" in final_url:
                raise AuthError("Login failed — check credentials")

    async def _get_html(self, path: str, params: dict[str, str] | None = None) -> str:
        session = await self._ensure_session()
        async with self._lock:
            async with session.get(self._url(path), params=params, allow_redirects=True) as resp:
                text = await resp.text(encoding="utf-8")
                # Session expired → redirected to login page
                if resp.url.path == "/" and "login" not in resp.url.path:
                    return ""
                return text

    async def _ensure_logged_in(self, path: str, params: dict[str, str] | None = None) -> str:
        """GET page, re-login once if session has expired."""
        html = await self._get_html(path, params)
        if not html:
            await self.login()
            html = await self._get_html(path, params)
        return html

    async def get_accounts(self) -> list[ESvitloAccount]:
        """Return list of household accounts linked to this user."""
        html = await self._ensure_logged_in(URL_ACCOUNTS)
        parser = _AccountTableParser()
        parser.feed(html)
        return [
            ESvitloAccount(
                internal_id=a["internal_id"],
                personal_no=a["personal_no"],
                name=a["name"],
                address=a["address"],
            )
            for a in parser.accounts
        ]

    async def get_meter_info(self, account_id: str) -> dict[str, Any]:
        """Return zone count and last readings for an account.

        Returns dict with keys: zone_count (int), last_z1, last_z2, last_z3 (int).
        """
        html = await self._ensure_logged_in(
            URL_METER_PAGE, {"a": account_id, "highlight": "insert_calc_value", "osr": "1"}
        )
        zone_count = 1
        m = re.search(r"const current_zone\s*=\s*`(\d+)`", html)
        if m:
            zone_count = int(m.group(1))

        def _extract(var: str) -> int:
            match = re.search(rf"const {re.escape(var)}\s*=\s*\+`(\d+)`", html)
            return int(match.group(1)) if match else 0

        return {
            "zone_count": zone_count,
            "last_z1": _extract("previous_data_z1"),
            "last_z2": _extract("previous_data_z2"),
            "last_z3": _extract("previous_data_z3"),
            "submission_allowed": "Внести покази дозволено" in html,
        }

    async def get_account_details(self, account_id: str) -> dict[str, Any]:
        """Fetch balance, last payment, and last meter readings for an account."""
        html = await self._ensure_logged_in(
            URL_DETAILS,
            {"a": account_id, "highlight": "account_household", "osr": "1"},
        )

        def _borg(label: str) -> str | None:
            m = re.search(
                rf'class="borg-text"[^>]*>\s*{re.escape(label)}\s*</div>\s*<div[^>]*class="borg-response"[^>]*>([^<]+)',
                html,
            )
            return m.group(1).strip() if m else None

        def _parse_amount(raw: str | None) -> float | None:
            if not raw:
                return None
            m = re.search(r"([\d.,]+)", raw)
            return float(m.group(1).replace(",", ".")) if m else None

        balance_raw = _borg("Заборгованість")
        last_payment_raw = _borg("Остання оплата")
        last_payment_date = _borg("Дата останньої оплати")

        # Last readings: date in class="second-column", values in <b> tags
        last_reading_date: str | None = None
        m_date = re.search(r'class="second-column">(\d{2}\.\d{2}\.\d{4})</div>', html)
        if m_date:
            last_reading_date = m_date.group(1)

        readings: list[int] = []
        m_section = re.search(
            r'Останні розрахункові покази лічильника</div>(.*?)(?:class="wrap-personal|<h2|<hr)',
            html,
            re.DOTALL,
        )
        if m_section:
            readings = [int(v) for v in re.findall(r"<b>(\d+)</b>", m_section.group(1))]

        # Monthly consumption from JSON endpoint
        monthly: dict[str, Any] = {}
        session = await self._ensure_session()
        try:
            async with session.get(
                self._url(URL_CONSUMPTION_YEAR), params={"a": account_id}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    monthly = data.get("res", {})
        except Exception:
            pass

        # Latest month is the one with the highest period key
        latest_consumption: int | None = None
        if monthly:
            latest_key = max(monthly.keys())
            latest_consumption = monthly[latest_key].get("cons")

        return {
            "balance": _parse_amount(balance_raw),
            "last_payment": _parse_amount(last_payment_raw),
            "last_payment_date": last_payment_date,
            "last_reading_date": last_reading_date,
            "last_z1": readings[0] if readings else None,
            "last_z2": readings[1] if len(readings) > 1 else None,
            "monthly_consumption": latest_consumption,
        }

    async def submit_reading(
        self,
        account_id: str,
        z1: int,
        z2: int = 0,
        z3: int = 0,
    ) -> str:
        """Submit meter reading. Returns raw response text.

        Re-authenticates once if session has expired.
        """
        return await self._do_submit(account_id, z1, z2, z3, retry=True)

    async def _do_submit(
        self,
        account_id: str,
        z1: int,
        z2: int,
        z3: int,
        retry: bool,
    ) -> str:
        session = await self._ensure_session()
        payload = {
            "z1": str(z1),
            "z2": str(z2),
            "z3": str(z3),
            "val_zag": str(z1 + z2 + z3),
            "a": account_id,
            "zgen": "",
        }
        async with self._lock:
            async with session.post(
                self._url(URL_SUBMIT),
                data=payload,
                allow_redirects=True,
            ) as resp:
                text = await resp.text(encoding="utf-8")
                # Session expired → redirected to login page
                if resp.url.path == "/" and retry:
                    await self.login()
                    return await self._do_submit(account_id, z1, z2, z3, retry=False)
                return text
