"""Ask tankerkoenig.de for petrol price information."""
from __future__ import annotations

from datetime import timedelta
import logging
from math import ceil

import pytankerkoenig
from requests.exceptions import RequestException
import voluptuous as vol

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import (
    CONF_API_KEY,
    CONF_LATITUDE,
    CONF_LOCATION,
    CONF_LONGITUDE,
    CONF_NAME,
    CONF_RADIUS,
    CONF_SCAN_INTERVAL,
    CONF_SHOW_ON_MAP,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_FUEL_TYPES,
    CONF_STATIONS,
    DEFAULT_RADIUS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    FUEL_TYPES,
)

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema(
    vol.All(
        cv.deprecated(DOMAIN),
        {
            DOMAIN: vol.Schema(
                {
                    vol.Required(CONF_API_KEY): cv.string,
                    vol.Optional(
                        CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
                    ): cv.time_period,
                    vol.Optional(CONF_FUEL_TYPES, default=FUEL_TYPES): vol.All(
                        cv.ensure_list, [vol.In(FUEL_TYPES)]
                    ),
                    vol.Inclusive(
                        CONF_LATITUDE,
                        "coordinates",
                        "Latitude and longitude must exist together",
                    ): cv.latitude,
                    vol.Inclusive(
                        CONF_LONGITUDE,
                        "coordinates",
                        "Latitude and longitude must exist together",
                    ): cv.longitude,
                    vol.Optional(CONF_RADIUS, default=DEFAULT_RADIUS): vol.All(
                        cv.positive_int, vol.Range(min=1)
                    ),
                    vol.Optional(CONF_STATIONS, default=[]): vol.All(
                        cv.ensure_list, [cv.string]
                    ),
                    vol.Optional(CONF_SHOW_ON_MAP, default=True): cv.boolean,
                }
            )
        },
    ),
    extra=vol.ALLOW_EXTRA,
)

PLATFORMS = [Platform.SENSOR]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set the tankerkoenig component up."""
    if DOMAIN not in config:
        return True

    conf = config[DOMAIN]
    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_IMPORT},
            data={
                CONF_NAME: "Home",
                CONF_API_KEY: conf[CONF_API_KEY],
                CONF_FUEL_TYPES: conf[CONF_FUEL_TYPES],
                CONF_LOCATION: {
                    "latitude": conf.get(CONF_LATITUDE, hass.config.latitude),
                    "longitude": conf.get(CONF_LONGITUDE, hass.config.longitude),
                },
                CONF_RADIUS: conf[CONF_RADIUS],
                CONF_STATIONS: conf[CONF_STATIONS],
                CONF_SHOW_ON_MAP: conf[CONF_SHOW_ON_MAP],
            },
        )
    )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set a tankerkoenig configuration entry up."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][
        entry.unique_id
    ] = coordinator = TankerkoenigDataUpdateCoordinator(
        hass,
        entry,
        _LOGGER,
        name=entry.unique_id or DOMAIN,
        update_interval=DEFAULT_SCAN_INTERVAL,
    )

    try:
        setup_ok = await hass.async_add_executor_job(coordinator.setup)
    except RequestException as err:
        raise ConfigEntryNotReady from err
    if not setup_ok:
        _LOGGER.error("Could not setup integration")
        return False

    await coordinator.async_config_entry_first_refresh()

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    hass.config_entries.async_setup_platforms(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Tankerkoenig config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.unique_id)

    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


class TankerkoenigDataUpdateCoordinator(DataUpdateCoordinator):
    """Get the latest data from the API."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        logger: logging.Logger,
        name: str,
        update_interval: int,
    ) -> None:
        """Initialize the data object."""

        super().__init__(
            hass=hass,
            logger=logger,
            name=name,
            update_interval=timedelta(minutes=update_interval),
        )

        self._api_key = entry.data[CONF_API_KEY]
        self._selected_stations = entry.data[CONF_STATIONS]
        self._hass = hass
        self.stations: dict[str, dict] = {}
        self.fuel_types = entry.data[CONF_FUEL_TYPES]
        self.show_on_map = entry.options[CONF_SHOW_ON_MAP]

    def setup(self):
        """Set up the tankerkoenig API."""
        for station_id in self._selected_stations:
            try:
                station_data = pytankerkoenig.getStationData(self._api_key, station_id)
            except pytankerkoenig.customException as err:
                station_data = {
                    "ok": False,
                    "message": err,
                    "exception": True,
                }

            if not station_data["ok"]:
                _LOGGER.error(
                    "Error when adding station %s:\n %s",
                    station_id,
                    station_data["message"],
                )
                return False
            self.add_station(station_data["station"])
        if len(self.stations) > 10:
            _LOGGER.warning(
                "Found more than 10 stations to check. "
                "This might invalidate your api-key on the long run. "
                "Try using a smaller radius"
            )
        return True

    async def _async_update_data(self):
        """Get the latest data from tankerkoenig.de."""
        _LOGGER.debug("Fetching new data from tankerkoenig.de")
        station_ids = list(self.stations)

        prices = {}

        # The API seems to only return at most 10 results, so split the list in chunks of 10
        # and merge it together.
        for index in range(ceil(len(station_ids) / 10)):
            data = await self._hass.async_add_executor_job(
                pytankerkoenig.getPriceList,
                self._api_key,
                station_ids[index * 10 : (index + 1) * 10],
            )

            _LOGGER.debug("Received data: %s", data)
            if not data["ok"]:
                _LOGGER.error(
                    "Error fetching data from tankerkoenig.de: %s", data["message"]
                )
                raise UpdateFailed(data["message"])
            if "prices" not in data:
                _LOGGER.error("Did not receive price information from tankerkoenig.de")
                raise UpdateFailed("No prices in data")
            prices.update(data["prices"])
        return prices

    def add_station(self, station: dict):
        """Add fuel station to the entity list."""
        station_id = station["id"]
        if station_id in self.stations:
            _LOGGER.warning(
                "Sensor for station with id %s was already created", station_id
            )
            return

        self.stations[station_id] = station
        _LOGGER.debug("add_station called for station: %s", station)
