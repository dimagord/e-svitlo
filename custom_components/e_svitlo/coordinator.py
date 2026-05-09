"""DataUpdateCoordinator for e-svitlo accounts."""
from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ESvitloClient

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(hours=1)


class ESvitloCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch data for one household account once per hour."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: ESvitloClient,
        account_id: str,
        account_name: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"e_svitlo_{account_id}",
            update_interval=SCAN_INTERVAL,
        )
        self.client = client
        self.account_id = account_id
        self.account_name = account_name

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.client.get_account_details(self.account_id)
        except Exception as err:
            raise UpdateFailed(f"Error fetching e-svitlo data for {self.account_id}: {err}") from err
