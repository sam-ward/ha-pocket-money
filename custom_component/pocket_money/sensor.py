# <config>/custom_components/pocket_money/sensor.py
import logging
from typing import Any, Dict, List, Optional

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo # Import DeviceInfo
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    CONF_KID_NAME, # Used for naming
    ATTR_BALANCE, # Used for state
    ATTR_TRANSACTIONS,
    ATTR_LAST_UPDATE,
    SIGNAL_UPDATE_SENSOR,
)
from . import PocketMoneyDataManager # Import the data manager class type hint

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the pocket money sensor for the kid in this config entry."""
    entry_id = entry.entry_id
    data = hass.data[DOMAIN][entry_id]
    data_manager: PocketMoneyDataManager = data["manager"]
    currency_symbol = data["currency_symbol"]
    kid_name = data["kid_name"] # Get kid's name specific to this entry

    _LOGGER.debug(f"Setting up sensor for {kid_name} (Entry ID: {entry_id})")

    # Create the single sensor for this kid
    sensor = PocketMoneyBalanceSensor(entry_id, data_manager, kid_name, currency_symbol)
    async_add_entities([sensor], True) # True = update before adding


class PocketMoneyBalanceSensor(SensorEntity):
    """Representation of a Pocket Money Balance Sensor for one kid."""

    _attr_should_poll = False # Updates are pushed via dispatcher
    _attr_force_update = True # Force update of attributes even when the native_value hasnt changed

    def __init__(self, entry_id: str, data_manager: PocketMoneyDataManager, kid_name: str, currency_symbol: str):
        """Initialize the sensor."""
        self._entry_id = entry_id
        self._data_manager = data_manager
        self._kid_name = kid_name # Store for attributes and naming
        self._currency_symbol = currency_symbol

        self._attr_name = f"Pocket Money {self._kid_name}" # Simpler name, Balance implied by sensor type
        # Unique ID remains crucial, tied to the config entry and kid
        self._attr_unique_id = f"{DOMAIN}_{self._entry_id}_balance"
        self._attr_icon = "mdi:piggy-bank-outline" # Changed icon

        self._signal_update = SIGNAL_UPDATE_SENSOR.format(self._entry_id)
        self._unsub_dispatcher = None

        # Define device info to group entities under a device for this kid
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)}, # Unique identifier for the device
            name=f"Pocket Money ({self._kid_name})", # Device name in registry
            manufacturer="Pocket Money Custom Integration", # Optional
            model="Kid Account", # Optional
            entry_type="service", # Or None
            # You could add suggested_area=kid_name here if desired
        )


    @property
    def native_value(self) -> float:
        """Return the state of the sensor (current balance)."""
        return self._data_manager.get_balance()

    @property
    def native_unit_of_measurement(self) -> str:
        """Return the unit of measurement."""
        return self._currency_symbol

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return the state attributes."""
        _LOGGER.debug(f"[{self.unique_id}] extra_state_attributes called.")
        transactions = self._data_manager.get_transactions()
        _LOGGER.debug(f"[{self.unique_id}] Transactions received from manager: {transactions}")

        last_transaction_time_iso: Optional[str] = None
        # ... (code to get last_transaction_time_iso remains the same) ...
        if transactions:
             ts_str = transactions[0].get('timestamp')
             if ts_str:
                  try:
                     last_transaction_time_iso = ts_str
                  except Exception as e:
                     _LOGGER.warning(f"[{self.unique_id}] Error processing timestamp from transaction: {ts_str} - {e}")
                     last_transaction_time_iso = ts_str # Fallback


        attributes = {
            # ---> Return a shallow copy of the list <---
            ATTR_TRANSACTIONS: list(transactions),
            ATTR_LAST_UPDATE: last_transaction_time_iso,
        }
        _LOGGER.debug(f"[{self.unique_id}] Returning attributes: {attributes}")
        return attributes
    
    async def async_added_to_hass(self) -> None:
        """Register callbacks when entity is added."""
        _LOGGER.debug(f"Sensor {self.unique_id} ({self._kid_name}) added to hass, registering listener for {self._signal_update}")
        self._unsub_dispatcher = async_dispatcher_connect(
            self.hass, self._signal_update, self._handle_update
        )
        # Initial state was set by update_before_add=True in async_add_entities
        if self._unsub_dispatcher:
            _LOGGER.debug(f"[{self.unique_id}] Listener registration successful.")
        else:
            _LOGGER.error(f"[{self.unique_id}] Listener registration FAILED for signal: '{self._signal_update}'")

    async def async_will_remove_from_hass(self) -> None:
        """Clean up when entity is removed."""
        _LOGGER.debug(f"Sensor {self.unique_id} ({self._kid_name}) removing from hass, unsubscribing listener")
        if self._unsub_dispatcher:
            self._unsub_dispatcher()
            self._unsub_dispatcher = None

    @callback
    def _handle_update(self) -> None:
        """Handle data updates."""
        # Log when the update signal is received
        _LOGGER.debug(f"[{self.unique_id}] Received update signal via dispatcher (_handle_update). Scheduling state write.")
        self.async_write_ha_state()