# <config>/custom_components/pocket_money/config_flow.py
import voluptuous as vol
import logging
#import re # For sanitizing name for unique ID

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .helpers import sanitize_name

from .const import (
    DOMAIN,
    CONF_KID_NAME,
    CONF_CURRENCY_SYMBOL,
    DEFAULT_CURRENCY_SYMBOL,
    CONF_INITIAL_BALANCE,
    DEFAULT_INITIAL_BALANCE,
    CONF_MAX_TRANSACTIONS,
    DEFAULT_MAX_TRANSACTIONS,
    CONF_LOG_TO_CSV,
    DEFAULT_LOG_TO_CSV,
)

_LOGGER = logging.getLogger(__name__)

class PocketMoneyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Pocket Money Tracker (per kid)."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            kid_name = user_input[CONF_KID_NAME].strip()
            if not kid_name:
                errors["base"] = "kid_name_empty"
            else:
                # Generate a unique ID based on the kid's name
                # Ensure uniqueness across HA instance for this domain
                sanitized_name = sanitize_name(kid_name)
                unique_id = f"{DOMAIN}_{sanitized_name}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured(
                    updates={CONF_KID_NAME: kid_name} # Allow updating name if ID exists? Maybe not.
                )

                _LOGGER.info(f"Setting up Pocket Money for kid: {kid_name} (ID: {unique_id})")

                # Optional: Add initial balance step if needed, or just start at 0.
                # For now, just create the entry. Initial balance is handled by data manager.
                return self.async_create_entry(
                    title=f"Pocket Money ({kid_name})", # Entry title in UI
                    data={
                        CONF_KID_NAME: kid_name,
                        CONF_CURRENCY_SYMBOL: user_input[CONF_CURRENCY_SYMBOL],
                        CONF_INITIAL_BALANCE: user_input[CONF_INITIAL_BALANCE],
                        CONF_MAX_TRANSACTIONS: user_input[CONF_MAX_TRANSACTIONS],
                        CONF_LOG_TO_CSV: user_input[CONF_LOG_TO_CSV],
                    }
                )

        # Schema for the user form (one kid at a time)
        data_schema = vol.Schema(
            {
                vol.Required(CONF_KID_NAME): selector.TextSelector(),
                vol.Optional(CONF_CURRENCY_SYMBOL, default=DEFAULT_CURRENCY_SYMBOL): selector.TextSelector(),
                vol.Optional(CONF_INITIAL_BALANCE, default=DEFAULT_INITIAL_BALANCE): selector.NumberSelector(
                     selector.NumberSelectorConfig(step=0.01, mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Optional(CONF_MAX_TRANSACTIONS, default=DEFAULT_MAX_TRANSACTIONS): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=500, step=1, mode=selector.NumberSelectorMode.BOX)
                ),
                # Add the CSV logging toggle
                vol.Optional(CONF_LOG_TO_CSV, default=DEFAULT_LOG_TO_CSV): selector.BooleanSelector(),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "kid_name_label": "Kid's Name"
            }
        )

    # Optional: Implement Options Flow to change currency, max transactions later
    # @staticmethod
    # @callback
    # def async_get_options_flow(config_entry):
    #    return PocketMoneyOptionsFlowHandler(config_entry)

# class PocketMoneyOptionsFlowHandler(config_entries.OptionsFlow):
#     # ... implementation ...
#     async def async_step_init(self, user_input=None):
#         # Similar schema building as config flow, but use self.config_entry.options
#         # Return self.async_create_entry(title="", data=updated_options)