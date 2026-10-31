# NetBox Smart Inventory

A Python-based SNMP inventory collection and synchronization tool for
NetBox.

The project collects hardware, interface, IP address, and MAC address
information from network devices using SNMP v2c, then synchronizes
supported inventory data with NetBox through its REST API.

## Features

-   SNMP-based inventory collection using PySNMP.
-   NetBox REST API integration.
-   Multi-device configuration through a JSON device list.
-   Physical hardware inventory using ENTITY-MIB.
-   Interface inventory and interface metadata collection.
-   IPv4 interface address collection using IP-MIB.
-   MAC address table collection.
-   Per-device synchronization and success/failure reporting.
-   Configurable SNMP timeout and retry values.
-   External configuration files for credentials and device definitions.
-   Conservative IP assignment handling to avoid moving existing IP
    addresses.
-   Automatic Asset retirement disabled to prevent incorrect retirement
    when SNMP inventory is incomplete.

## Requirements

-   Python 3.10 or newer.
-   Network connectivity from the collector host to target devices over
    SNMP.
-   Network connectivity from the collector host to the NetBox API.
-   A NetBox API token with permissions appropriate for the intended
    synchronization.
-   SNMP v2c access to supported target devices.

SNMP v2c is the only SNMP version currently implemented.

## Project Structure

``` text
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

Clone or copy the repository to the collector host and enter the project
directory.

Create and activate a virtual environment:

``` bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

``` bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Configuration

### 1. Environment variables

Create the local environment file:

``` bash
cp config/.env.example config/.env
```

Edit the file:

``` bash
nano config/.env
```

Configure the following variables:

  Variable           Required   Description
  ------------------ ---------- ------------------------------------------
  `NETBOX_URL`       Yes        Base URL of the NetBox instance
  `NETBOX_TOKEN`     Yes        NetBox API token
  `SNMP_COMMUNITY`   Yes        SNMP v2c community string
  `SNMP_VERSION`     No         SNMP version; defaults to `2c`
  `SNMP_TIMEOUT`     No         SNMP timeout in seconds; defaults to `2`
  `SNMP_RETRIES`     No         Number of SNMP retries; defaults to `1`

The `DEVICE_IP` and `DEVICE_NAME` environment variables are not used for
device selection. Device definitions are maintained in
`config/devices.json`.

Keep `config/.env` private. Never commit credentials, API tokens, or
SNMP community strings.

### 2. Device list

Create the local device configuration:

``` bash
cp config/devices.example.json config/devices.json
```

Edit the file:

``` bash
nano config/devices.json
```

Example:

``` json
{
  "devices": [
    {
      "name": "example-switch",
      "ip": "192.0.2.10"
    },
    {
      "name": "example-router",
      "ip": "192.0.2.20"
    }
  ]
}
```

Replace the example names and documentation IP addresses with the
appropriate values for your environment.

The `devices` property must contain a non-empty list. Every device entry
must include a non-empty `name` and `ip`.

Keep `config/devices.json` out of version control if it contains
internal device information.

## Running the Collector

From the project root, with the virtual environment activated and
configuration files populated:

``` bash
python collector/netbox_sync.py
```

The collector processes the configured devices and reports per-device
inventory and synchronization results, followed by a final
success/failure summary.

Run the collector only after validating the configuration, target-device
connectivity, and NetBox API permissions.

## NetBox Synchronization Scope

The collector is not read-only. It uses NetBox API POST and PATCH
operations to create or update supported inventory records.

Depending on the collected data and existing NetBox records,
synchronization may create or update:

-   Sites, manufacturers, device roles, and device types.
-   Devices and interfaces.
-   VLANs and IP address records.
-   Device primary IPv4 assignments.
-   Asset roles, hardware/module types, and plugin Assets.
-   Legacy DCIM Inventory Items and Inventory Item Types.
-   MAC address records.

### IP address handling

The collector uses conservative assignment rules:

-   Existing IP assignments are not moved between interfaces or devices.
-   An existing IP can be assigned only when it is unassigned or already
    assigned to the intended interface.
-   Conflicting or incomplete assignments are skipped and reported.
-   Management IP records are not automatically created.
-   The primary IPv4 address is updated only when the matching IP is
    already assigned to an interface belonging to the same device.

### Asset handling

-   Assets identified by the current SNMP collection can be created or
    updated.
-   Previously retired Assets can be restored to `used` when they
    reappear in the collection.
-   Automatic retirement of Assets missing from an SNMP collection is
    disabled in this release.

This prevents incomplete SNMP ENTITY-MIB responses from causing existing
Assets to be incorrectly retired.

### Deletion behavior

The current synchronization implementation does not invoke NetBox API
DELETE operations.

POST and PATCH operations can still modify NetBox data. Review the
synchronization scope and API permissions before running against
production.

## Security Notes

-   Never commit `config/.env`.
-   Never commit `config/devices.json` when it contains operational
    device information.
-   Use a NetBox API token with only the permissions required by the
    collector.
-   Store credentials using an appropriate secret-management process.
-   Protect access to the collector host and its configuration files.
-   Validate synchronization behavior against a test NetBox instance
    before production use.
-   Review API permissions and expected changes before every production
    deployment.

## Current Limitations

-   SNMP v2c only.
-   Requires a manually maintained device list.
-   Requires NetBox API connectivity.
-   Device support and collected fields depend on the information
    exposed by each device.
-   Automatic Asset retirement is disabled.
-   Management IP creation and automatic management-interface creation
    are not part of the current synchronization workflow.

## Development Status

This project is maintained as a version-controlled network inventory
synchronization tool.

Validate the collector against a test NetBox instance and representative
network devices before using it in production.
