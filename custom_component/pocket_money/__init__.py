# <config>/custom_components/pocket_money/__init__.py
import logging
import voluptuous as vol
from datetime import datetime, timezone # Use timezone-aware datetime
from typing import Dict, Any, List, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .helpers import sanitize_name

from .const import (
    DOMAIN,
    CONF_KID_NAME,
    CONF_CURRENCY_SYMBOL,
    CONF_INITIAL_BALANCE,
    CONF_MAX_TRANSACTIONS,
    STORAGE_VERSION,
    STORAGE_KEY_PREFIX,
    SERVICE_ADD_TRANSACTION,
    ATTR_AMOUNT,
    ATTR_DESCRIPTION,
    ATTR_TIMESTAMP, # Added
    ATTR_BALANCE,
    ATTR_TRANSACTIONS,
    SIGNAL_UPDATE_SENSOR,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]

# Define service schema - NO kid_name here, service is specific to the instance
SERVICE_TRANSACTION_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_AMOUNT): vol.Coerce(float),
        vol.Optional(ATTR_DESCRIPTION, default=""): cv.string,
        vol.Optional(ATTR_TIMESTAMP): cv.string, # Optional timestamp string (ISO format)
    }
)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Pocket Money Tracker from a config entry for a single kid."""
    hass.data.setdefault(DOMAIN, {})

    kid_name = entry.data[CONF_KID_NAME]
    currency_symbol = entry.data[CONF_CURRENCY_SYMBOL]
    initial_balance = entry.data[CONF_INITIAL_BALANCE]
    max_transactions = entry.data[CONF_MAX_TRANSACTIONS]
    entry_id = entry.entry_id # Unique ID for this config entry instance

    _LOGGER.info(f"Setting up pocket money for {kid_name} (Entry ID: {entry_id})")

    # Create data manager instance specific to this kid/entry
    data_manager = PocketMoneyDataManager(hass, entry_id, kid_name, max_transactions)
    await data_manager.async_load(initial_balance) # Load persistent data or initialize

    # Store manager instance and config data associated with this entry_id
    hass.data[DOMAIN][entry_id] = {
        "manager": data_manager,
        "currency_symbol": currency_symbol,
        "kid_name": kid_name, # Store kid_name for reference if needed
    }

    # Register service specific to this kid instance
    async def handle_add_transaction(call: ServiceCall) -> ServiceResponse:
        """Handle the add_transaction service call for this specific kid."""
        # Get data manager associated with the service call's context (entry_id)
        # Note: Service calls don't inherently have entry_id context easily.
        # We'll register the service *without* tying it directly here,
        # but the handler needs to know which instance it *should* apply to.
        # A better pattern might be a device action, but a domain service is requested.
        # Let's stick to domain service, but it means the service call applies
        # to the kid associated with THIS config entry.

        amount = call.data.get(ATTR_AMOUNT)
        description = call.data.get(ATTR_DESCRIPTION)
        timestamp_str = call.data.get(ATTR_TIMESTAMP)
        transaction_timestamp: Optional[datetime] = None

        _LOGGER.debug(f"Service call add_transaction for {kid_name} (Entry ID: {entry_id}): Amount={amount}, Desc='{description}', Timestamp='{timestamp_str}'")

        if timestamp_str:
            try:
                # Try parsing user-provided timestamp (expect ISO format)
                transaction_timestamp = dt_util.parse_datetime(timestamp_str)
                if transaction_timestamp is None: # Should not happen if parse succeeds but check anyway
                     raise ValueError("Parsed timestamp is None")
                # Ensure it's timezone-aware (UTC preferrably)
                if transaction_timestamp.tzinfo is None:
                     _LOGGER.warning(f"Provided timestamp '{timestamp_str}' lacks timezone info, assuming local timezone and converting to UTC.")
                     transaction_timestamp = dt_util.as_utc(transaction_timestamp) # Convert local to UTC
                else:
                    transaction_timestamp = transaction_timestamp.astimezone(timezone.utc) # Ensure UTC

            except ValueError as e:
                 _LOGGER.error(f"Invalid timestamp format provided '{timestamp_str}': {e}. Transaction NOT added.")
                 raise ServiceValidationError(
                    f"Invalid timestamp format: '{timestamp_str}'. Please use ISO format (e.g., YYYY-MM-DDTHH:MM:SSZ or YYYY-MM-DD HH:MM:SS).",
                    translation_domain=DOMAIN,
                    translation_key="invalid_timestamp",
                    translation_placeholders={"timestamp": timestamp_str},
                 ) from e
            except Exception as e:
                 _LOGGER.error(f"Error processing provided timestamp '{timestamp_str}': {e}. Transaction NOT added.")
                 raise HomeAssistantError(f"Error processing timestamp '{timestamp_str}'.") from e
        else:
            # Default to current time in UTC if no timestamp provided
            transaction_timestamp = dt_util.utcnow()

        try:
            new_balance = await data_manager.async_add_transaction(
                amount=float(amount),
                description=description,
                timestamp_override=transaction_timestamp # Pass parsed or current time
            )
            _LOGGER.info(f"Transaction added for {kid_name} ({entry_id}): {amount}. New balance: {new_balance}")
            # Return the new balance in the service response
            return {"new_balance": new_balance}

        except Exception as e:
            _LOGGER.error(f"Error processing transaction for {kid_name} ({entry_id}): {e}")
            # Raise a HomeAssistantError to indicate failure in the service call
            raise HomeAssistantError(f"Failed to add transaction for {kid_name}: {e}") from e


    # Register the service. It will appear as "Pocket Money ({Kid Name}): Add Transaction"
    # The service name (`add_transaction`) is the same, but it's tied to the config entry.
    # When called from UI/automation targeting the *device* associated with this config entry,
    # it should work correctly. Calling it generically might be ambiguous if multiple kids exist.
    # Let's register it non-specifically for now, relying on HA's service targetting.
    hass.services.async_register(
        DOMAIN,
        f"{sanitize_name(kid_name)}_{SERVICE_ADD_TRANSACTION}", # Make service name unique per kid
        handle_add_transaction,
        schema=SERVICE_TRANSACTION_SCHEMA,
        supports_response=SupportsResponse.ONLY, # Indicate service returns a response
    )

    # Forward setup to sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Listen for config entry updates (if options flow is added)
    entry.async_on_unload(entry.add_update_listener(update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    entry_id = entry.entry_id
    data = hass.data[DOMAIN].get(entry_id)

    if not data:
        _LOGGER.warning(f"Attempting to unload pocket money entry {entry_id} which was not loaded.")
        return True # Already unloaded or never loaded

    kid_name = data.get("kid_name", "Unknown Kid")
    _LOGGER.info(f"Unloading Pocket Money integration for {kid_name} ({entry_id})")

    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Remove service specific to this kid
        service_name = f"{sanitize_name(kid_name)}_{SERVICE_ADD_TRANSACTION}"
        hass.services.async_remove(DOMAIN, service_name)
        _LOGGER.debug(f"Removed service: {DOMAIN}.{service_name}")

        # Remove data manager and other stored info
        hass.data[DOMAIN].pop(entry_id)
        _LOGGER.info(f"Pocket Money for {kid_name} ({entry_id}) unloaded successfully.")

    return unload_ok

async def update_listener(hass: HomeAssistant, entry: ConfigEntry):
    """Handle options update."""
    _LOGGER.info(f"Pocket Money configuration updated for {entry.title}, reloading entry {entry.entry_id}")
    await hass.config_entries.async_reload(entry.entry_id)


class PocketMoneyDataManager:
    """Manages pocket money data and persistence for a single kid."""

    def __init__(self, hass: HomeAssistant, entry_id: str, kid_name: str, max_transactions: int):
        """Initialize the data manager."""
        self.hass = hass
        self._entry_id = entry_id # Use entry_id for storage key uniqueness
        self._kid_name = kid_name
        self._store = Store[Dict[str, Any]](hass, STORAGE_VERSION, f"{STORAGE_KEY_PREFIX}{self._entry_id}")
        self._max_transactions = max_transactions
        self._data: Dict[str, Any] = {ATTR_BALANCE: 0.0, ATTR_TRANSACTIONS: []}

    async def async_load(self, initial_balance: float) -> None:
        """Load data from store or initialize."""
        loaded_data = await self._store.async_load()

        if loaded_data is None:
            _LOGGER.info(f"Initializing pocket money data store for {self._kid_name} ({self._entry_id}) with balance: {initial_balance}")
            self._data = {
                ATTR_BALANCE: float(initial_balance),
                ATTR_TRANSACTIONS: [] # Start with empty history
            }
            await self.async_save() # Save initial state
        else:
            _LOGGER.debug(f"Loaded pocket money data for {self._kid_name} ({self._entry_id}) from store")
            # Basic validation/migration could happen here if STORAGE_VERSION changes
            self._data = loaded_data
            # Ensure keys exist with defaults if loading older/corrupt data
            self._data.setdefault(ATTR_BALANCE, 0.0)
            self._data.setdefault(ATTR_TRANSACTIONS, [])

    async def async_save(self) -> None:
        """Save data to store."""
        _LOGGER.debug(f"Saving pocket money data for {self._kid_name} ({self._entry_id})")
        await self._store.async_save(self._data)

    
    async def async_add_transaction(self, amount: float, description: str, timestamp_override: datetime) -> float:
        """Add a transaction, update balance, save, and notify. Returns new balance."""

        timestamp_iso = timestamp_override.isoformat()
        current_balance = self._data.get(ATTR_BALANCE, 0.0) # Use .get for safety
        new_balance = round(current_balance + amount, 2)

        transaction = {
            "timestamp": timestamp_iso,
            "amount": amount,
            "description": description or ("Credit" if amount >= 0 else "Debit"),
            "balance_after": new_balance
        }
        _LOGGER.debug(f"[{self._kid_name}] Created transaction record: {transaction}")

        # Update balance
        self._data[ATTR_BALANCE] = new_balance

        # Add transaction and trim history
        # Ensure the key exists and is a list
        if ATTR_TRANSACTIONS not in self._data or not isinstance(self._data[ATTR_TRANSACTIONS], list):
            _LOGGER.warning(f"[{self._kid_name}] Initializing transactions list as it was missing or not a list.")
            self._data[ATTR_TRANSACTIONS] = []

        transactions_list = self._data[ATTR_TRANSACTIONS]
        _LOGGER.debug(f"[{self._kid_name}] Transactions list BEFORE insert: {transactions_list}")

        transactions_list.insert(0, transaction) # Add to beginning (modifies list in place)
        _LOGGER.debug(f"[{self._kid_name}] Transactions list AFTER insert: {transactions_list}")


        if len(transactions_list) > self._max_transactions:
            _LOGGER.debug(f"[{self._kid_name}] Trimming transactions list from {len(transactions_list)} to {self._max_transactions}")
            # Reassign the key in self._data to the new sliced list
            self._data[ATTR_TRANSACTIONS] = transactions_list[:self._max_transactions]
            _LOGGER.debug(f"[{self._kid_name}] Transactions list AFTER trim: {self._data[ATTR_TRANSACTIONS]}")


        # Log the entire data structure right before saving
        _LOGGER.debug(f"[{self._kid_name}] Data structure BEFORE save: {self._data}")

        # Save the updated state
        await self.async_save()

        # Notify the specific sensor to update its state using entry_id
        signal = SIGNAL_UPDATE_SENSOR.format(self._entry_id)
        _LOGGER.debug(f"[{self._kid_name}] Dispatching update signal: {signal}")
        async_dispatcher_send(self.hass, signal)

        return new_balance

    def get_balance(self) -> float:
        """Get the current balance."""
        return self._data.get(ATTR_BALANCE, 0.0)

    def get_transactions(self) -> List[Dict[str, Any]]:
        """Get the transaction history."""
        transactions_list = self._data.get(ATTR_TRANSACTIONS, [])
        # Add logging here too
        _LOGGER.debug(f"[{self._kid_name}] get_transactions called. Returning: {transactions_list}")
        return transactions_list