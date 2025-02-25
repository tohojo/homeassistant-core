"""Support for update entities of a Pi-hole system."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from hole import Hole

from homeassistant.components.update import UpdateEntity, UpdateEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from . import PiHoleEntity
from .const import DATA_KEY_API, DATA_KEY_COORDINATOR, DOMAIN


@dataclass
class PiHoleUpdateEntityDescription(UpdateEntityDescription):
    """Describes PiHole update entity."""

    current_version: Callable[[dict], str | None] = lambda api: None
    latest_version: Callable[[dict], str | None] = lambda api: None
    release_base_url: str | None = None
    title: str | None = None


UPDATE_ENTITY_TYPES: tuple[PiHoleUpdateEntityDescription, ...] = (
    PiHoleUpdateEntityDescription(
        key="core_update_available",
        name="Core Update Available",
        title="Pi-hole Core",
        entity_category=EntityCategory.DIAGNOSTIC,
        current_version=lambda versions: versions.get("core_current"),
        latest_version=lambda versions: versions.get("core_latest"),
        release_base_url="https://github.com/pi-hole/pi-hole/releases/tag",
    ),
    PiHoleUpdateEntityDescription(
        key="web_update_available",
        name="Web Update Available",
        title="Pi-hole Web interface",
        entity_category=EntityCategory.DIAGNOSTIC,
        current_version=lambda versions: versions.get("web_current"),
        latest_version=lambda versions: versions.get("web_latest"),
        release_base_url="https://github.com/pi-hole/AdminLTE/releases/tag",
    ),
    PiHoleUpdateEntityDescription(
        key="ftl_update_available",
        name="FTL Update Available",
        title="Pi-hole FTL DNS",
        entity_category=EntityCategory.DIAGNOSTIC,
        current_version=lambda versions: versions.get("FTL_current"),
        latest_version=lambda versions: versions.get("FTL_latest"),
        release_base_url="https://github.com/pi-hole/FTL/releases/tag",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Pi-hole update entities."""
    name = entry.data[CONF_NAME]
    hole_data = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        PiHoleUpdateEntity(
            hole_data[DATA_KEY_API],
            hole_data[DATA_KEY_COORDINATOR],
            name,
            entry.entry_id,
            description,
        )
        for description in UPDATE_ENTITY_TYPES
    )


class PiHoleUpdateEntity(PiHoleEntity, UpdateEntity):
    """Representation of a Pi-hole update entity."""

    entity_description: PiHoleUpdateEntityDescription

    def __init__(
        self,
        api: Hole,
        coordinator: DataUpdateCoordinator,
        name: str,
        server_unique_id: str,
        description: PiHoleUpdateEntityDescription,
    ) -> None:
        """Initialize a Pi-hole update entity."""
        super().__init__(api, coordinator, name, server_unique_id)
        self.entity_description = description

        self._attr_name = f"{name} {description.name}"
        self._attr_unique_id = f"{self._server_unique_id}/{description.name}"
        self._attr_title = description.title

    @property
    def current_version(self) -> str | None:
        """Version currently in use."""
        if isinstance(self.api.versions, dict):
            return self.entity_description.current_version(self.api.versions)
        return None

    @property
    def latest_version(self) -> str | None:
        """Latest version available for install."""
        if isinstance(self.api.versions, dict):
            return self.entity_description.latest_version(self.api.versions)
        return None

    @property
    def release_url(self) -> str | None:
        """URL to the full release notes of the latest version available."""
        if self.latest_version:
            return f"{self.entity_description.release_base_url}/{self.latest_version}"
        return None
