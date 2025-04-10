# <config>/custom_components/pocket_money/const.py
DOMAIN = "pocket_money"

# Configuration Keys
CONF_KID_NAME = "kid_name" # Changed from CONF_KIDS
CONF_CURRENCY_SYMBOL = "currency_symbol"
CONF_INITIAL_BALANCE = "initial_balance"
CONF_MAX_TRANSACTIONS = "max_transactions"

# Defaults
DEFAULT_CURRENCY_SYMBOL = "$"
DEFAULT_MAX_TRANSACTIONS = 50
DEFAULT_INITIAL_BALANCE = 0.0 # Can be used in config flow if desired

# Data Storage
STORAGE_VERSION = 1
STORAGE_KEY_PREFIX = f"{DOMAIN}_kid_" # Prefix for storage key per kid

# Attributes
ATTR_BALANCE = "balance"
ATTR_TRANSACTIONS = "transactions"
ATTR_LAST_UPDATE = "last_update_time"

# Services
SERVICE_ADD_TRANSACTION = "add_transaction"
ATTR_AMOUNT = "amount"
ATTR_DESCRIPTION = "description"
ATTR_TIMESTAMP = "timestamp" # New attribute for service call

# Signals (for updating sensors)
# Make signal specific to the config entry ID
SIGNAL_UPDATE_SENSOR = f"{DOMAIN}_update_{{}}" # Placeholder for entry_id