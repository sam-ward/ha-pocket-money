import logging
import voluptuous as vol
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import os  # For path manipulation
import csv # For CSV writing

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

# Import helpers and constants
from .helpers import sanitize_name
from .const import (
    DOMAIN,
    CONF_KID_NAME,
    CONF_CURRENCY_SYMBOL,
    CONF_INITIAL_BALANCE,
    CONF_MAX_TRANSACTIONS,
    CONF_LOG_TO_CSV,
    DEFAULT_LOG_TO_CSV,
    DEFAULT_MAX_TRANSACTIONS,
    STORAGE_VERSION,
    STORAGE_KEY_PREFIX,
    SERVICE_ADD_TRANSACTION,
    ATTR_AMOUNT,
    ATTR_DESCRIPTION,
    ATTR_TIMESTAMP,
    ATTR_BALANCE,
    ATTR_TRANSACTIONS,
    SIGNAL_UPDATE_SENSOR,
    CSV_FILENAME_FORMAT,
    CSV_HEADERS,
)

_LOGGER = logging.getLogger(__name__)

# Define platforms to be set up
PLATFORMS = ["sensor"]

# Define service schema - applies to the dynamic service for each kid
SERVICE_TRANSACTION_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_AMOUNT): vol.Coerce(float),
        vol.Optional(ATTR_DESCRIPTION, default=""): cv.string,
        vol.Optional(ATTR_TIMESTAMP): cv.string, # Optional timestamp string (ISO format)
    }
)

# --- Setup Functions ---

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Pocket Money Tracker from a config entry for a single kid."""
    hass.data.setdefault(DOMAIN, {})

    # Retrieve configuration data from the entry
    kid_name = entry.data[CONF_KID_NAME]
    currency_symbol = entry.data[CONF_CURRENCY_SYMBOL]
    initial_balance = entry.data[CONF_INITIAL_BALANCE]
    max_transactions = entry.data[CONF_MAX_TRANSACTIONS]
    # Use .get for the new option for backward compatibility if needed, default to False
    log_to_csv = entry.data.get(CONF_LOG_TO_CSV, DEFAULT_LOG_TO_CSV)
    entry_id = entry.entry_id

    _LOGGER.info(
        f"Setting up pocket money for {kid_name} "
        f"(Entry ID: {entry_id}, Log to CSV: {log_to_csv})"
    )

    # Create data manager instance specific to this kid/entry
    data_manager = PocketMoneyDataManager(
        hass,
        entry_id,
        kid_name,
        max_transactions,
        log_to_csv # Pass the CSV logging flag
    )
    # Load persistent data or initialize
    await data_manager.async_load(initial_balance)

    # Store manager instance and config data associated with this entry_id
    hass.data[DOMAIN][entry_id] = {
        "manager": data_manager,
        "currency_symbol": currency_symbol,
        "kid_name": kid_name,
    }

    # Define an async wrapper function for the service handler
    # This wrapper will have access to manager_instance and kid_name from the outer scope
    async def service_handler_wrapper(call: ServiceCall) -> ServiceResponse:
        """Async wrapper to call the actual handler with captured context."""
        # Correctly await the async handler function
        return await _handle_add_transaction(call, data_manager, kid_name)

    # Register the dynamic service for this specific kid instance
    service_name = f"{sanitize_name(kid_name)}_{SERVICE_ADD_TRANSACTION}"
    hass.services.async_register(
        DOMAIN,
        service_name,
        # Use lambda to ensure the correct data_manager instance is passed
        service_handler_wrapper, # Register the async wrapper
        schema=SERVICE_TRANSACTION_SCHEMA,
        supports_response=SupportsResponse.ONLY, # Service returns the new balance
    )
    _LOGGER.debug(f"Registered service: {DOMAIN}.{service_name}")

    # Forward setup to the sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Listen for config entry updates (if options flow is implemented)
    entry.async_on_unload(entry.add_update_listener(update_listener))

    return True


async def _handle_add_transaction(
    call: ServiceCall, data_manager: "PocketMoneyDataManager", kid_name: str
) -> ServiceResponse:
    """Handle the add_transaction service call for a specific kid."""
    amount = call.data.get(ATTR_AMOUNT)
    description = call.data.get(ATTR_DESCRIPTION)
    timestamp_str = call.data.get(ATTR_TIMESTAMP)
    transaction_timestamp: Optional[datetime] = None

    _LOGGER.debug(
        f"Service call add_transaction for {kid_name}: "
        f"Amount={amount}, Desc='{description}', Timestamp='{timestamp_str}'"
    )

    # Parse and validate timestamp if provided
    if timestamp_str:
        try:
            transaction_timestamp = dt_util.parse_datetime(timestamp_str)
            if transaction_timestamp is None:
                raise ValueError("Parsed timestamp is None")
            # Ensure timestamp is timezone-aware (UTC)
            if transaction_timestamp.tzinfo is None:
                 _LOGGER.warning(
                     f"Provided timestamp '{timestamp_str}' lacks timezone info, "
                     "assuming local timezone and converting to UTC."
                 )
                 transaction_timestamp = dt_util.as_utc(transaction_timestamp)
            else:
                # Convert to UTC if it's not already
                transaction_timestamp = transaction_timestamp.astimezone(timezone.utc)

        except ValueError as e:
             _LOGGER.error(f"Invalid timestamp format provided '{timestamp_str}': {e}. Transaction NOT added.")
             # Raise specific error for HA UI
             raise ServiceValidationError(
                f"Invalid timestamp format: '{timestamp_str}'. Please use ISO format (e.g., YYYY-MM-DDTHH:MM:SSZ).",
                translation_domain=DOMAIN,
                translation_key="invalid_timestamp", # Needs matching key in translations/en.json error section
                translation_placeholders={"timestamp": timestamp_str},
             ) from e
        except Exception as e:
             _LOGGER.error(f"Error processing provided timestamp '{timestamp_str}': {e}. Transaction NOT added.")
             raise HomeAssistantError(f"Error processing timestamp '{timestamp_str}'.") from e
    else:
        # Default to current time in UTC if no timestamp provided
        transaction_timestamp = dt_util.utcnow()

    # Call the data manager to add the transaction
    try:
        new_balance = await data_manager.async_add_transaction(
            amount=float(amount),
            description=description,
            timestamp_override=transaction_timestamp # Pass validated/generated timestamp
        )
        _LOGGER.info(f"Transaction added for {kid_name}: {amount}. New balance: {new_balance}")
        # Return the new balance as the service response
        return {"new_balance": new_balance}

    except Exception as e:
        _LOGGER.error(f"Error processing transaction for {kid_name}: {e}")
        # Raise error to indicate failure in the service call log
        raise HomeAssistantError(f"Failed to add transaction for {kid_name}: {e}") from e


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    entry_id = entry.entry_id
    data = hass.data[DOMAIN].get(entry_id)

    if not data:
        _LOGGER.warning(f"Attempting to unload pocket money entry {entry_id} which was not loaded.")
        return True # Already unloaded or never loaded

    kid_name = data.get("kid_name", "Unknown Kid")
    _LOGGER.info(f"Unloading Pocket Money integration for {kid_name} ({entry_id})")

    # Unload platforms (sensor)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Remove service specific to this kid
        service_name_to_remove = f"{sanitize_name(kid_name)}_{SERVICE_ADD_TRANSACTION}"
        hass.services.async_remove(DOMAIN, service_name_to_remove)
        _LOGGER.debug(f"Removed service: {DOMAIN}.{service_name_to_remove}")

        # Remove data stored in hass.data
        hass.data[DOMAIN].pop(entry_id)
        _LOGGER.info(f"Pocket Money for {kid_name} ({entry_id}) unloaded successfully.")

    return unload_ok


async def update_listener(hass: HomeAssistant, entry: ConfigEntry):
    """Handle options update (if options flow is implemented)."""
    _LOGGER.info(f"Pocket Money configuration updated for {entry.title}, reloading entry {entry.entry_id}")
    # Reload the integration instance to apply changes
    await hass.config_entries.async_reload(entry.entry_id)


# --- Data Manager Class ---

class PocketMoneyDataManager:
    """Manages pocket money data and persistence for a single kid."""

    def __init__(self, hass: HomeAssistant, entry_id: str, kid_name: str, max_transactions: int, log_to_csv: bool):
        """Initialize the data manager."""
        self.hass = hass
        self._entry_id = entry_id
        self._kid_name = kid_name
        self._store = Store[Dict[str, Any]](hass, STORAGE_VERSION, f"{STORAGE_KEY_PREFIX}{self._entry_id}")
        self._max_transactions = max_transactions
        self._data: Dict[str, Any] = {ATTR_BALANCE: 0.0, ATTR_TRANSACTIONS: []}

        # === Ensure max_transactions is a positive integer ===
        try:
            # Convert the input to int and ensure it's at least 1
            self._max_transactions = max(1, int(max_transactions))
            _LOGGER.debug(f"[{self._kid_name}] Max transactions set to: {self._max_transactions}")
        except (ValueError, TypeError):
            # Fallback to default if conversion fails or input is invalid type
            _LOGGER.warning(
                f"[{self._kid_name}] Invalid max_transactions value received "
                f"({max_transactions}). Defaulting to {DEFAULT_MAX_TRANSACTIONS}."
            )
            self._max_transactions = DEFAULT_MAX_TRANSACTIONS # Use default from const.py

        # CSV Logging Setup
        self._log_to_csv = log_to_csv
        self._csv_filepath: Optional[str] = None
        if self._log_to_csv:
            try:
                # Generate filename using sanitized name within HA config dir
                filename = CSV_FILENAME_FORMAT.format(sanitize_name(self._kid_name))
                # hass.config.path() gives the full path to the config directory
                self._csv_filepath = hass.config.path(filename)
                _LOGGER.info(f"CSV logging enabled for {self._kid_name}. File: {self._csv_filepath}")
            except Exception as e:
                _LOGGER.error(f"Error setting up CSV file path for {self._kid_name}: {e}. CSV logging disabled.")
                self._log_to_csv = False # Disable if path setup fails

    async def async_load(self, initial_balance: float) -> None:
        """Load data from store or initialize with initial balance as first transaction."""
        loaded_data = await self._store.async_load()

        if loaded_data is None:
            _LOGGER.info(f"Initializing pocket money data store for {self._kid_name} ({self._entry_id})")

            # Ensure initial_balance is a float
            initial_balance_float = float(initial_balance)

            # Create the initial transaction record
            now_utc = dt_util.utcnow()
            timestamp_iso = now_utc.isoformat()
            initial_transaction = {
                "timestamp": timestamp_iso,
                "amount": initial_balance_float, # Amount is the initial balance itself
                "description": "Initial Balance", # Description for clarity
                "balance_after": initial_balance_float # Balance after this setup transaction
            }
            _LOGGER.debug(f"[{self._kid_name}] Created initial transaction record: {initial_transaction}")


            # Initialize the data with the balance and the first transaction
            self._data = {
                ATTR_BALANCE: initial_balance_float,
                # Only add the transaction if the balance is non-zero OR you always want an entry
                # Let's always add it for consistency, even if balance is 0
                ATTR_TRANSACTIONS: [initial_transaction]
            }

            # Save this initial state
            await self.async_save()
            _LOGGER.debug(f"[{self._kid_name}] Initial state saved.")

            # --- Log this initial transaction to CSV if enabled ---
            if self._log_to_csv and self._csv_filepath:
                 _LOGGER.debug(f"[{self._kid_name}] Logging initial balance transaction to CSV: {self._csv_filepath}")
                 try:
                    # Run the blocking file I/O operation in HA's executor thread pool
                    await self.hass.async_add_executor_job(
                        self._write_transaction_to_csv, initial_transaction
                    )
                    _LOGGER.debug(f"[{self._kid_name}] Initial balance CSV write task submitted successfully.")
                 except Exception as e:
                    _LOGGER.error(f"[{self._kid_name}] Failed to submit initial balance CSV write task: {e}")
            elif self._log_to_csv:
                _LOGGER.warning(f"[{self._kid_name}] CSV logging enabled but file path is not set during init. Skipping CSV write.")

        else:
            # Loading existing data - no changes needed here
            _LOGGER.debug(f"Loaded pocket money data for {self._kid_name} ({self._entry_id}) from store")
            self._data = loaded_data
            self._data.setdefault(ATTR_BALANCE, 0.0)
            self._data.setdefault(ATTR_TRANSACTIONS, [])

    async def async_save(self) -> None:
        """Save data to store (for balance and HA transaction attribute)."""
        _LOGGER.debug(f"Saving pocket money primary data for {self._kid_name} ({self._entry_id})")
        await self._store.async_save(self._data)

    async def async_add_transaction(self, amount: float, description: str, timestamp_override: datetime) -> float:
        """Add transaction to memory, save state, log to CSV (if enabled), and notify sensor."""

        # Prepare transaction data
        timestamp_iso = timestamp_override.isoformat()
        current_balance = self._data.get(ATTR_BALANCE, 0.0)
        new_balance = round(current_balance + amount, 2)

        # The dictionary structure matches CSV_HEADERS for easy writing
        transaction = {
            "timestamp": timestamp_iso,
            "amount": amount,
            "description": description or ("Credit" if amount >= 0 else "Debit"),
            "balance_after": new_balance
        }
        _LOGGER.debug(f"[{self._kid_name}] Created transaction record: {transaction}")

        # Update balance in memory
        self._data[ATTR_BALANCE] = new_balance

        # Add transaction to list in memory and trim if needed
        if ATTR_TRANSACTIONS not in self._data or not isinstance(self._data[ATTR_TRANSACTIONS], list):
             _LOGGER.warning(f"[{self._kid_name}] Initializing transactions list as it was missing or not a list.")
             self._data[ATTR_TRANSACTIONS] = []
        transactions_list = self._data[ATTR_TRANSACTIONS]
        transactions_list.insert(0, transaction) # Add to beginning (most recent first)

        #trim the list as required to max_transactions
        if len(transactions_list) > self._max_transactions:
             self._data[ATTR_TRANSACTIONS] = transactions_list[:self._max_transactions] # Keep the newest ones
        else:
            self._data[ATTR_TRANSACTIONS] = transactions_list


        # Save the updated HA state (balance and transaction list attribute)
        _LOGGER.debug(f"[{self._kid_name}] Data structure BEFORE save: {self._data}")
        await self.async_save()
        _LOGGER.debug(f"[{self._kid_name}] Primary data saved successfully.")


        # Append to CSV File asynchronously in executor if enabled
        if self._log_to_csv and self._csv_filepath:
            _LOGGER.debug(f"[{self._kid_name}] Attempting to log transaction to CSV: {self._csv_filepath}")
            try:
                # Run the blocking file I/O operation in HA's executor thread pool
                await self.hass.async_add_executor_job(
                    self._write_transaction_to_csv, transaction
                )
                _LOGGER.debug(f"[{self._kid_name}] CSV write task submitted successfully.")
            except Exception as e:
                 # Log error if submitting the job itself fails
                 _LOGGER.error(f"[{self._kid_name}] Failed to submit CSV write task: {e}")
        elif self._log_to_csv:
             # Log if enabled but path is missing (shouldn't happen if init check worked)
            _LOGGER.warning(f"[{self._kid_name}] CSV logging enabled but file path is not set. Skipping CSV write.")


        # Notify the sensor entity to update its state in HA UI
        signal = SIGNAL_UPDATE_SENSOR.format(self._entry_id)
        _LOGGER.debug(f"[{self._kid_name}] Dispatching update signal: '{signal}'")
        async_dispatcher_send(self.hass, signal)

        # Return the new balance for the service response
        return new_balance

    def _write_transaction_to_csv(self, transaction: Dict[str, Any]) -> None:
        """Write a single transaction to the CSV file.
        This method is synchronous and designed to be run in an executor thread.
        """
        # Double-check file path existence before proceeding
        if not self._csv_filepath:
            _LOGGER.error(f"[{self._kid_name}] _write_transaction_to_csv called without a valid file path.")
            return

        try:
            # Check if file exists *before* opening to decide on writing header
            file_exists = os.path.exists(self._csv_filepath)
            _LOGGER.debug(f"[{self._kid_name}] Checking CSV file existence '{self._csv_filepath}': {file_exists}")

            # Open file in append mode ('a'). newline='' prevents extra blank rows.
            # Use utf-8 encoding for broader compatibility.
            with open(self._csv_filepath, mode='a', newline='', encoding='utf-8') as csvfile:
                # Use DictWriter for convenience with the transaction dictionary.
                # fieldnames must match the keys in the transaction dict AND the desired CSV column order.
                writer = csv.DictWriter(csvfile, fieldnames=CSV_HEADERS)

                # Write the header row only if the file didn't exist before opening
                if not file_exists:
                    _LOGGER.info(f"[{self._kid_name}] Writing CSV header to new file: {self._csv_filepath}")
                    writer.writeheader()

                # Write the actual transaction data row
                writer.writerow(transaction)
                _LOGGER.debug(f"[{self._kid_name}] Successfully wrote transaction to CSV.")

        except IOError as e:
            _LOGGER.error(f"[{self._kid_name}] IO Error writing transaction to CSV file '{self._csv_filepath}': {e}")
        except Exception as e:
            _LOGGER.error(f"[{self._kid_name}] Unexpected Error writing transaction to CSV file '{self._csv_filepath}': {e}")
            # Log errors but don't crash the executor thread or HA


    def get_balance(self) -> float:
        """Get the current balance."""
        return self._data.get(ATTR_BALANCE, 0.0)

    def get_transactions(self) -> List[Dict[str, Any]]:
        """Get the transaction history stored in HA state."""
        return self._data.get(ATTR_TRANSACTIONS, [])