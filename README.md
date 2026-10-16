# NetBox Smart Inventory

A Python-based SNMP inventory collection and synchronization tool for NetBox.

The tool collects network-device inventory information and synchronizes the collected data with NetBox through its API.

## Features

- SNMP-based inventory collection using PySNMP.
- NetBox API integration.
- Configuration for multiple devices.
- Inventory collection for hardware, interfaces, and MAC address tables.
- Per-device success and failure reporting.
- Configurable SNMP timeout and retry values.
- External configuration files for credentials and device definitions.

## Requirements

- Python 3.10 or newer.
- Network access from the collector host to target devices over SNMP.
- Network access from the collector host to the NetBox API.
- A NetBox API token with permissions appropriate for the intended synchronization.
- SNMP v2c access to the target devices.

SNMP v2c is the only SNMP version currently implemented.

## Project Structure

```text
netbox-smart-inventory/
├── collector/
│   ├── inventory.py
│   └── netbox_sync.py
├── config/
│   ├── .env.example
│   └── devices.example.json
├── .gitignore
├── README.md
└── requirements.txt
```

## Installation

Clone or copy the repository to the collector host, then enter the project directory.

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install the dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Configuration

### 1. Environment file

Create the local environment file from the example:

```bash
cp config/.env.example config/.env
```

Edit it:

```bash
nano config/.env
```

Set the actual values for your environment.

Required settings include:

| Variable | Description |
|---|---|
| `NETBOX_URL` | Base URL of the NetBox instance |
| `NETBOX_TOKEN` | NetBox API token |
| `DEVICE_IP` | IP address used by the inventory module |
| `DEVICE_NAME` | Optional device name; defaults to `DEVICE_IP` |
| `SNMP_VERSION` | Currently supported value: `2c` |
| `SNMP_COMMUNITY` | SNMP v2c community string |
| `SNMP_TIMEOUT` | SNMP timeout in seconds |
| `SNMP_RETRIES` | Number of SNMP retries |

Keep `config/.env` private. Never commit credentials, API tokens, or SNMP community strings.

### 2. Device list

Create the local device configuration:

```bash
cp config/devices.example.json config/devices.json
```

Edit the file:

```bash
nano config/devices.json
```

Example:

```json
{
  "devices": [
    {
      "name": "example-switch",
      "ip": "192.0.2.10"
    }
  ]
}
```

Replace the example name and documentation IP address with the appropriate values for your environment.

The `devices` property must be a non-empty list. Every entry must contain a non-empty `name` and `ip`.

Keep `config/devices.json` out of version control if it contains internal device information.

## Running the Collector

From the project root, with the virtual environment activated and configuration files populated:

```bash
python collector/netbox_sync.py
```

The script reports per-device inventory counts and synchronization results, followed by a final success/failure summary.

The collector requires valid NetBox and SNMP configuration before execution. Run it only after confirming that the target devices and NetBox API are reachable.

## Security Notes

- Do not commit `config/.env`.
- Do not commit `config/devices.json` when it contains operational inventory.
- Use a NetBox API token with only the permissions required by the tool.
- Store secrets using an appropriate secret-management process for your environment.
- Protect access to the collector host and its configuration files.
- Review synchronization behavior and permissions before running against production.

## Current Limitations

- SNMP v2c only.
- Requires a manually maintained device list.
- Requires NetBox API connectivity.
- Device support and collected fields depend on the current implementation and the information exposed by each device.

## Development Status

This project is being prepared for version-controlled development. Validate the collector against a test NetBox instance and representative network devices before using it in production.
