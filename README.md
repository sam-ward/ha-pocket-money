[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/hacs/integration)  [![made-with-python](https://img.shields.io/badge/Made%20with-Python-1f425f.svg)](https://www.python.org/) [![Donate](https://img.shields.io/badge/Donate-PayPal-green.svg)](https://paypal.me/samward271)

# Pocket Money
The Pocket Money integration allows you to setup a simple account in Home Assistant that can have money credited to and debited from, while tracking the balance and transaction history.  Ideal for a simple pocket money tracker for children.

## Installation

### Manual
- Copy directory `custom_components/pocket-money` to your `<config dir>/custom_components` directory.
- Restart Home-Assistant.
- Follow configuration steps below.

## Configuration

Adding Pockey Money to your Home Assistant instance can be done via the integrations user interface.

- Browse to your Home Assistant instance.
- In the sidebar click on Configuration.
- From the configuration menu select: Integrations.
- In the bottom right, click on the Add Integration button.
- From the list, search and select “Pocket Money”.
- Follow the instruction on screen to complete the set up

After successful set up a standard set of sensors are enabled. 

## Available Sensors

Not every sensor holds meaningful values, it depends on the tracking and health devices you use, or the apps you have connected.

Enabled by default:

```text
sensor.pocket_money_<name> - The current balance of the account.
It also contains a 'Transactions" attribute that contains the last x number of transactions
(where x is the value configured when adding the integration, by default 50)
```

## Tips and Tricks

### Examples on how to add a transaction from the HA GUI

#### Add Transaction
```
action: pocket_money.<name>_add_transaction
data:
  amount: 17
  description: Weekly Pocket Money
```

## Debugging

Add the relevant lines below to the `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.pocket-money: debug
```

## Acknowledgements
[Icon by vexels.com](https://www.vexels.com/png-svg/preview/263263/money-business-piggy-bank-icon)

## Donation
[![Donate](https://img.shields.io/badge/Donate-PayPal-green.svg)](https://paypal.me/samward271)
