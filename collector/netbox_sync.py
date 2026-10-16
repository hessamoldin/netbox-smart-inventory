#!/usr/bin/env python3

import asyncio
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from inventory import (
    SNMPClient,
    InventoryCollector,
    normalize_inventory,
    DEVICE_IP,
    DEVICE_NAME,
    SNMP_COMMUNITY,
    SNMP_TIMEOUT,
    SNMP_RETRIES,
)


# =============================================================================
# Configuration
# =============================================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / "config" / ".env"
DEVICES_FILE = PROJECT_ROOT / "config" / "devices.json"


def load_env(path: Path) -> Dict[str, str]:
    env: Dict[str, str] = {}

    if not path.exists():
        raise FileNotFoundError(f"Environment file not found: {path}")

    for line in path.read_text().splitlines():
        line = line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        env[key.strip()] = value.strip()

    return env


ENV = load_env(ENV_FILE)

NETBOX_URL = ENV.get("NETBOX_URL", "").rstrip("/")
NETBOX_TOKEN = ENV.get("NETBOX_TOKEN", "")


def load_devices(
    path: Path,
) -> List[Dict[str, str]]:

    if not path.exists():
        raise FileNotFoundError(
            f"Devices file not found: {path}"
        )

    try:
        data = json.loads(
            path.read_text(encoding="utf-8")
        )
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Invalid JSON in {path}: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise RuntimeError(
            "devices.json root must be an object"
        )

    devices = data.get("devices")

    if not isinstance(devices, list):
        raise RuntimeError(
            "devices.json must contain a 'devices' list"
        )

    if not devices:
        raise RuntimeError(
            "devices.json contains no devices"
        )

    validated: List[Dict[str, str]] = []

    for index, item in enumerate(
        devices,
        start=1,
    ):

        if not isinstance(item, dict):
            raise RuntimeError(
                f"Device #{index} must be an object"
            )

        name = str(
            item.get("name", "")
        ).strip()

        ip = str(
            item.get("ip", "")
        ).strip()

        if not name:
            raise RuntimeError(
                f"Device #{index} has no name"
            )

        if not ip:
            raise RuntimeError(
                f"Device #{index} has no ip"
            )

        validated.append(
            {
                "name": name,
                "ip": ip,
            }
        )

    return validated


if not NETBOX_URL:
    raise RuntimeError("NETBOX_URL is not configured in config/.env")

if not NETBOX_TOKEN:
    raise RuntimeError("NETBOX_TOKEN is not configured in config/.env")


# =============================================================================
# NetBox API
# =============================================================================

class NetBoxAPI:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")

        if token.startswith("Bearer "):
            authorization = token
        else:
            authorization = f"Token {token}"

        self.session = requests.Session()

        self.session.headers.update(
            {
                "Authorization": authorization,
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

    def _url(self, endpoint: str) -> str:
        if endpoint.startswith("http://") or endpoint.startswith("https://"):
            return endpoint

        return f"{self.base_url}{endpoint}"

    def request(
        self,
        method: str,
        endpoint: str,
        payload: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        url = self._url(endpoint)

        response = self.session.request(
            method=method,
            url=url,
            json=payload,
            params=params,
            timeout=60,
        )

        if not response.ok:
            print()
            print("=" * 100)
            print("NETBOX API ERROR")
            print("=" * 100)
            print(f"Method : {method}")
            print(f"URL    : {url}")
            print(f"HTTP   : {response.status_code}")

            try:
                print(
                    json.dumps(
                        response.json(),
                        indent=2,
                        ensure_ascii=False,
                    )
                )
            except Exception:
                print(response.text)

            print("=" * 100)

            response.raise_for_status()

        if response.status_code == 204:
            return None

        if not response.text:
            return None

        return response.json()

    def get(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        return self.request(
            "GET",
            endpoint,
            params=params,
        )

    def post(
        self,
        endpoint: str,
        payload: Dict[str, Any],
    ) -> Any:
        return self.request(
            "POST",
            endpoint,
            payload=payload,
        )

    def patch(
        self,
        endpoint: str,
        payload: Dict[str, Any],
    ) -> Any:
        return self.request(
            "PATCH",
            endpoint,
            payload=payload,
        )

    def delete(self, endpoint: str) -> Any:
        return self.request(
            "DELETE",
            endpoint,
        )

    def get_all(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []

        data = self.get(
            endpoint,
            params=params,
        )

        while True:
            if not isinstance(data, dict):
                break

            page_results = data.get("results", [])

            if isinstance(page_results, list):
                results.extend(page_results)

            next_url = data.get("next")

            if not next_url:
                break

            data = self.get(next_url)

        return results


# =============================================================================
# Helpers
# =============================================================================

def clean_string(value: Any) -> str:
    if value is None:
        return ""

    return str(value).strip()


def build_change_message(
    object_type: str,
    object_name: str,
    changes: Dict[str, Tuple[Any, Any]],
) -> str:
    """
    Build a human-readable NetBox changelog message.

    changes format:

        {
            "serial": ("OLD", "NEW"),
            "status": ("offline", "active"),
        }
    """

    parts: List[str] = []

    for field, values in changes.items():

        old_value, new_value = values

        old_text = clean_string(
            old_value
        )

        new_text = clean_string(
            new_value
        )

        if not old_text:
            old_text = "<empty>"

        if not new_text:
            new_text = "<empty>"

        parts.append(
            f"{field}: "
            f"{old_text} -> {new_text}"
        )

    if not parts:
        return (
            f"Weekly inventory sync | "
            f"{object_type} {object_name}"
        )

    return (
        f"Weekly inventory sync | "
        f"{object_type} {object_name} | "
        f"changes: "
        f"{'; '.join(parts)}"
    )


def slugify(value: str) -> str:
    value = clean_string(value).lower()

    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")

    return value[:100] or "asset-role"


def normalize_mac(value: Any) -> Optional[str]:
    if value is None:
        return None

    value = str(value).strip()

    if not value:
        return None

    value = (
        value
        .replace(":", "")
        .replace("-", "")
        .replace(".", "")
    )

    if len(value) != 12:
        return None

    if not re.fullmatch(r"[0-9a-fA-F]{12}", value):
        return None

    return ":".join(
        value[i:i + 2].upper()
        for i in range(0, 12, 2)
    )


def get_object_id(obj: Any) -> Optional[int]:
    if isinstance(obj, int):
        return obj

    if isinstance(obj, dict):
        value = obj.get("id")

        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

    return None


def nested_id(value: Optional[int]) -> Optional[Dict[str, int]]:
    """
    Build the nested representation expected by NetBox Inventory
    serializers.

    Example:
        5 -> {"id": 5}
    """
    if value is None:
        return None

    return {"id": int(value)}


def print_section(title: str) -> None:
    print()
    print("=" * 100)
    print(title)
    print("=" * 100)


# =============================================================================
# Defaults
# =============================================================================

DEFAULT_SITE_NAME = "Shatel Mobile"
DEFAULT_MANUFACTURER_NAME = "Cisco"
DEFAULT_DEVICE_ROLE_NAME = "Network Switch"


# =============================================================================
# Site
# =============================================================================

def ensure_site(
    api: NetBoxAPI,
    name: str,
) -> Dict[str, Any]:

    results = api.get_all(
        "/api/dcim/sites/",
        params={"name": name},
    )

    if results:
        print(
            f"[EXISTS] Site : "
            f"{name} | id={results[0]['id']}"
        )

        return results[0]

    payload = {
        "name": name,
        "slug": slugify(name),
        "status": "active",
    }

    result = api.post(
        "/api/dcim/sites/",
        payload,
    )

    print(
        f"[CREATED] Site : "
        f"{name} | id={result['id']}"
    )

    return result


# =============================================================================
# Manufacturer
# =============================================================================

def ensure_manufacturer(
    api: NetBoxAPI,
    name: str,
) -> Dict[str, Any]:

    results = api.get_all(
        "/api/dcim/manufacturers/",
        params={"name": name},
    )

    if results:
        print(
            f"[EXISTS] Manufacturer : "
            f"{name} | id={results[0]['id']}"
        )

        return results[0]

    payload = {
        "name": name,
        "slug": slugify(name),
    }

    result = api.post(
        "/api/dcim/manufacturers/",
        payload,
    )

    print(
        f"[CREATED] Manufacturer : "
        f"{name} | id={result['id']}"
    )

    return result


# =============================================================================
# Device Role
# =============================================================================

def ensure_device_role(
    api: NetBoxAPI,
    name: str,
) -> Dict[str, Any]:

    results = api.get_all(
        "/api/dcim/device-roles/",
        params={"name": name},
    )

    if results:
        print(
            f"[EXISTS] Device Role : "
            f"{name} | id={results[0]['id']}"
        )

        return results[0]

    payload = {
        "name": name,
        "slug": slugify(name),
        "color": "607d8b",
    }

    result = api.post(
        "/api/dcim/device-roles/",
        payload,
    )

    print(
        f"[CREATED] Device Role : "
        f"{name} | id={result['id']}"
    )

    return result


# =============================================================================
# Device Type
# =============================================================================

def ensure_device_type(
    api: NetBoxAPI,
    model: str,
    manufacturer_id: int,
) -> Dict[str, Any]:

    model = clean_string(model)

    if not model:
        raise ValueError(
            "Cannot create device type without model"
        )

    results = api.get_all(
        "/api/dcim/device-types/",
        params={"model": model},
    )

    for item in results:
        item_manufacturer = get_object_id(
            item.get("manufacturer")
        )

        if item_manufacturer == manufacturer_id:
            print(
                f"[EXISTS] Device Type : "
                f"{model} | id={item['id']}"
            )

            return item

    payload = {
        "manufacturer": manufacturer_id,
        "model": model,
        "slug": slugify(model),
    }

    result = api.post(
        "/api/dcim/device-types/",
        payload,
    )

    print(
        f"[CREATED] Device Type : "
        f"{model} | id={result['id']}"
    )

    return result


# =============================================================================
# Asset Roles
# =============================================================================

ASSET_ROLES = {
    "chassis": "Chassis",
    "module": "Module",
    "power_supply": "Power Supply",
    "fan": "Fan",
    "transceiver": "Transceiver",
}


def ensure_asset_role(
    api: NetBoxAPI,
    name: str,
) -> Dict[str, Any]:

    results = api.get_all(
        "/api/plugins/inventory/asset-roles/",
        params={"name": name},
    )

    if results:
        print(
            f"[EXISTS] Asset Role : "
            f"{name} | id={results[0]['id']}"
        )

        return results[0]

    payload = {
        "name": name,
        "slug": slugify(name),
        "description": (
            "Automatically managed by SNMP inventory: "
            f"{name}"
        ),
    }

    result = api.post(
        "/api/plugins/inventory/asset-roles/",
        payload,
    )

    print(
        f"[CREATED] Asset Role : "
        f"{name} | id={result['id']}"
    )

    return result


def ensure_asset_roles(
    api: NetBoxAPI,
) -> Dict[str, Dict[str, Any]]:

    roles: Dict[str, Dict[str, Any]] = {}

    for key, name in ASSET_ROLES.items():
        roles[key] = ensure_asset_role(
            api,
            name,
        )

    return roles


# =============================================================================
# Module Types
# =============================================================================

def ensure_module_type(
    api: NetBoxAPI,
    model: str,
    manufacturer: Dict[str, Any],
) -> Dict[str, Any]:

    model = clean_string(model)

    if not model:
        raise ValueError(
            "Cannot create module type without model"
        )

    manufacturer_id = manufacturer["id"]

    results = api.get_all(
        "/api/dcim/module-types/",
        params={"model": model},
    )

    for item in results:
        item_manufacturer = get_object_id(
            item.get("manufacturer")
        )

        if item_manufacturer == manufacturer_id:
            print(
                f"[EXISTS] Module Type : "
                f"{model} | id={item['id']}"
            )

            return item

    manufacturer_name = clean_string(
        manufacturer.get("name")
    )

    payload = {
        "manufacturer": {
            "name": manufacturer_name,
        },
        "model": model,
        "part_number": "",
        "description": (
            "Automatically discovered by "
            "NETBOX INVENTORY via ENTITY-MIB."
        ),
    }

    result = api.post(
        "/api/dcim/module-types/",
        payload,
    )

    print(
        f"[CREATED] Module Type : "
        f"{model} | id={result['id']}"
    )

    return result


# =============================================================================
# Device Sync
# =============================================================================

def sync_device(
    api: NetBoxAPI,
    device: Dict[str, Any],
    device_type: Dict[str, Any],
    role: Dict[str, Any],
    site: Dict[str, Any],
) -> Dict[str, Any]:

    name = clean_string(
        device.get("name")
    )

    if not name:
        raise ValueError(
            "Device name is empty"
        )

    desired = {
        "name": name,
        "device_type": device_type["id"],
        "role": role["id"],
        "site": site["id"],
        "serial": clean_string(
            device.get("serial")
        ),
        "status": "active",
    }

    results = api.get_all(
        "/api/dcim/devices/",
        params={"name": name},
    )

    if not results:
        result = api.post(
            "/api/dcim/devices/",
            desired,
        )

        print(
            f"[CREATED] Device : "
            f"{name} | id={result['id']}"
        )

        return result

    current = results[0]

    changed: Dict[str, Any] = {}

    change_details: Dict[
        str,
        Tuple[Any, Any],
    ] = {}

    current_device_type = get_object_id(
        current.get("device_type")
    )

    current_role = get_object_id(
        current.get("role")
    )

    current_site = get_object_id(
        current.get("site")
    )

    if current.get("name") != desired["name"]:
        changed["name"] = desired["name"]

        change_details["name"] = (
            current.get("name"),
            desired["name"],
        )

    if current_device_type != desired["device_type"]:
        changed["device_type"] = desired["device_type"]

        change_details["device_type"] = (
            current_device_type,
            desired["device_type"],
        )

    if current_role != desired["role"]:
        changed["role"] = desired["role"]

        change_details["role"] = (
            current_role,
            desired["role"],
        )

    if current_site != desired["site"]:
        changed["site"] = desired["site"]

        change_details["site"] = (
            current_site,
            desired["site"],
        )

    current_serial = clean_string(
        current.get("serial")
    )

    if current_serial != desired["serial"]:
        changed["serial"] = desired["serial"]

        change_details["serial"] = (
            current_serial,
            desired["serial"],
        )

    current_status = current.get("status")

    if isinstance(current_status, dict):
        current_status = current_status.get("value")

    if current_status != "active":
        changed["status"] = "active"

        change_details["status"] = (
            current_status,
            "active",
        )

    if changed:

        changelog_message = build_change_message(
            "Device",
            name,
            change_details,
        )

        changed["changelog_message"] = (
            changelog_message
        )

        result = api.patch(
            f"/api/dcim/devices/{current['id']}/",
            changed,
        )

        print(
            f"[UPDATED] Device : "
            f"{name} | "
            f"fields="
            f"{', '.join(change_details.keys())}"
        )

        print(
            f"[CHANGE] "
            f"{changelog_message}"
        )

        return result

    print(
        f"[UNCHANGED] Device : "
        f"{name} | id={current['id']}"
    )

    return current


# =============================================================================
# Interface Sync
# =============================================================================

def interface_enabled(value: Any) -> bool:
    if isinstance(value, bool):
        return value

    return str(value).lower() in {
        "1",
        "true",
        "up",
        "enabled",
    }


def normalize_interface_type(
    _: Dict[str, Any],
) -> str:
    return "other"


def sync_interfaces(
    api: NetBoxAPI,
    device: Dict[str, Any],
    interfaces: List[Dict[str, Any]],
) -> None:

    device_id = device["id"]
    device_name = device["name"]

    existing = api.get_all(
        "/api/dcim/interfaces/",
        params={"device_id": device_id},
    )

    existing_by_name = {
        clean_string(item.get("name")): item
        for item in existing
    }

    created = 0
    updated = 0
    unchanged = 0

    for interface in interfaces:
        name = clean_string(
            interface.get("name")
        )

        if not name:
            continue

        desired = {
            "device": device_id,
            "name": name,
            "type": normalize_interface_type(
                interface
            ),
            "enabled": interface_enabled(
                interface.get("admin_status")
            ),
        }

        description = clean_string(
            interface.get("description")
            or interface.get("alias")
        )

        if description:
            desired["description"] = description

        mtu = interface.get("mtu")

        if mtu:
            try:
                desired["mtu"] = int(mtu)
            except (TypeError, ValueError):
                pass

        speed = interface.get("speed")

        if speed:
            try:
                desired["speed"] = int(speed)
            except (TypeError, ValueError):
                pass

        current = existing_by_name.get(name)

        if current is None:
            api.post(
                "/api/dcim/interfaces/",
                desired,
            )

            created += 1
            continue

        changed: Dict[str, Any] = {}

        current_type = current.get("type")

        if isinstance(current_type, dict):
            current_type = current_type.get("value")

        if current_type != desired["type"]:
            changed["type"] = desired["type"]

        if current.get("enabled") != desired["enabled"]:
            changed["enabled"] = desired["enabled"]

        if "description" in desired:
            if (
                clean_string(
                    current.get("description")
                )
                != desired["description"]
            ):
                changed["description"] = desired[
                    "description"
                ]

        if "mtu" in desired:
            try:
                current_mtu = int(
                    current.get("mtu")
                )
            except (TypeError, ValueError):
                current_mtu = None

            if current_mtu != desired["mtu"]:
                changed["mtu"] = desired["mtu"]

        if "speed" in desired:
            try:
                current_speed = int(
                    current.get("speed")
                )
            except (TypeError, ValueError):
                current_speed = None

            if current_speed != desired["speed"]:
                changed["speed"] = desired["speed"]

        if changed:
            api.patch(
                f"/api/dcim/interfaces/{current['id']}/",
                changed,
            )

            updated += 1

        else:
            unchanged += 1

    print(
        f"[INTERFACES] {device_name} | "
        f"created={created} "
        f"updated={updated} "
        f"unchanged={unchanged}"
    )


# =============================================================================
# Management IP
# =============================================================================

def sync_management_ip(
    api: NetBoxAPI,
    device: Dict[str, Any],
) -> None:

    management_ip = clean_string(
        device.get("management_ip")
    )

    if not management_ip:
        print(
            f"[SKIPPED] Management IP "
            f"{device['name']} | no management IP"
        )
        return

    if "/" not in management_ip:
        management_ip = f"{management_ip}/32"

    address_only = management_ip.split(
        "/",
        1,
    )[0]

    results = api.get_all(
        "/api/ipam/ip-addresses/",
        params={"address": management_ip},
    )

    if results:
        ip_obj = results[0]

        print(
            f"[EXISTS] Management IP : "
            f"{management_ip} | id={ip_obj['id']}"
        )

    else:
        payload = {
            "address": management_ip,
            "status": "active",
        }

        ip_obj = api.post(
            "/api/ipam/ip-addresses/",
            payload,
        )

        print(
            f"[CREATED] Management IP : "
            f"{management_ip} | id={ip_obj['id']}"
        )

    desired_primary = ip_obj["id"]

    current_primary_id = get_object_id(
        device.get("primary_ip4")
    )

    if current_primary_id != desired_primary:
        api.patch(
            f"/api/dcim/devices/{device['id']}/",
            {
                "primary_ip4": desired_primary,
            },
        )

        print(
            f"[UPDATED] Primary IPv4 : "
            f"{device['name']} -> {address_only}"
        )

    else:
        print(
            f"[UNCHANGED] Primary IPv4 : "
            f"{device['name']} -> {address_only}"
        )


# =============================================================================
# Asset Classification
# =============================================================================

def classify_asset(
    item: Dict[str, Any],
) -> Optional[str]:

    entity_class = clean_string(
        item.get("class")
    ).lower()

    name = clean_string(
        item.get("name")
    )

    model = clean_string(
        item.get("model")
    )

    serial = clean_string(
        item.get("serial")
    )

    name_lower = name.lower()

    # -------------------------------------------------------------------------
    # Chassis
    # -------------------------------------------------------------------------

    if entity_class == "chassis":
        return "chassis"

    # -------------------------------------------------------------------------
    # Power Supply
    # -------------------------------------------------------------------------

    if entity_class == "power_supply":
        if model or serial:
            return "power_supply"

        return None

    # -------------------------------------------------------------------------
    # Fan
    #
    # Keep only physical fan modules.
    # Ignore internal Fan-1 / Fan-2 records.
    # -------------------------------------------------------------------------

    if entity_class == "fan":

        # Only the physical fan-module ENTITY records are Assets.
        # Internal child records such as:
        #   "Fan Module-1 Fan-1"
        #   "Fan Module-1 Fan-2"
        # must not become separate Assets.
        if re.fullmatch(
            r"Fan Module-\d+",
            name,
            re.IGNORECASE,
        ):
            return "fan"

        return None

    # -------------------------------------------------------------------------
    # Module / Transceiver
    # -------------------------------------------------------------------------

    if entity_class == "module":

        if "forwarding engine" in name_lower:
            return None

        if "transceiver(" in name_lower:
            if model or serial:
                return "transceiver"

            return None

        if model or serial:
            return "module"

        return None

    # -------------------------------------------------------------------------
    # Explicitly excluded:
    #
    # stack
    # sensor
    # port
    # cpu
    # backplane
    # container
    # other
    # unknown
    # -------------------------------------------------------------------------

    return None


def asset_type_model(
    item: Dict[str, Any],
    asset_kind: str,
) -> str:

    model = clean_string(
        item.get("model")
    )

    if model:
        return model

    description = clean_string(
        item.get("description")
    )

    if description:
        return description[:100]

    name = clean_string(
        item.get("name")
    )

    if name:
        return name[:100]

    return (
        f"SNMP ENTITY "
        f"{clean_string(item.get('index'))}"
    )


def asset_display_name(
    device_name: str,
    item: Dict[str, Any],
    asset_kind: str,
) -> str:

    index = clean_string(
        item.get("index")
    )

    name = clean_string(
        item.get("name")
    )

    if not name:
        name = f"Entity {index}"

    if asset_kind == "chassis":
        display = "Chassis"

    elif asset_kind == "transceiver":
        match = re.search(
            r"slot:(\d+)-port:(\d+)",
            name,
            re.IGNORECASE,
        )

        if match:
            slot = match.group(1)
            port = match.group(2)

            display = (
                f"Transceiver(Eth{slot}/{port})"
            )
        else:
            display = name

    else:
        display = name

    result = (
        f"{device_name} | {display}"
    )

    return result[:128]


def asset_description(
    device_name: str,
    item: Dict[str, Any],
    asset_kind: str,
) -> str:

    index = clean_string(
        item.get("index")
    )

    description = clean_string(
        item.get("description")
    )

    model = clean_string(
        item.get("model")
    )

    serial = clean_string(
        item.get("serial")
    )

    parent = clean_string(
        item.get("parent")
    )

    lines = [
        "Automatically discovered by NETBOX INVENTORY.",
        f"SNMP Device: {device_name}",
        f"SNMP Entity Index: {index}",
        f"Hardware Class: {asset_kind}",
    ]

    if description:
        lines.append(
            f"SNMP Description: {description}"
        )

    if model:
        lines.append(
            f"Model: {model}"
        )

    if serial:
        lines.append(
            f"Serial: {serial}"
        )

    if parent:
        lines.append(
            f"SNMP Parent Entity: {parent}"
        )

    # NetBox Inventory Asset.description has a maximum length of 200
    # characters. Keep the complete structure when possible, but never
    # submit a payload that violates the serializer limit.
    return "\n".join(lines)[:200]


# =============================================================================
# Asset Identity
# =============================================================================

def get_existing_assets(
    api: NetBoxAPI,
) -> List[Dict[str, Any]]:

    return api.get_all(
        "/api/plugins/inventory/assets/",
    )


def asset_identity_from_name(
    name: str,
) -> Optional[str]:

    match = re.match(
        r"^SNMP-(.+?)-ENTITY-(\d+)\s*\|",
        name,
    )

    if not match:
        return None

    device_name = match.group(1)
    entity_index = match.group(2)

    return (
        f"{device_name}:{entity_index}"
    )


def asset_identity_from_description(
    description: str,
) -> Optional[str]:
    """
    Extract the complete managed SNMP Asset identity from
    Asset.description.

    Expected format:

        SNMP Device: N9K-EDGE-1
        SNMP Entity Index: 123
    """

    device_match = re.search(
        r"SNMP Device:\s*(.+)",
        description,
        re.IGNORECASE,
    )

    entity_match = re.search(
        r"SNMP Entity Index:\s*(\d+)",
        description,
        re.IGNORECASE,
    )

    if not device_match or not entity_match:
        return None

    device_name = clean_string(
        device_match.group(1)
    )

    entity_index = clean_string(
        entity_match.group(1)
    )

    if not device_name or not entity_index:
        return None

    return (
        f"{device_name}:{entity_index}"
    )


def make_asset_identity(
    device_name: str,
    item: Dict[str, Any],
) -> str:

    return (
        f"{device_name}:"
        f"{clean_string(item.get('index'))}"
    )


def find_existing_asset(
    existing_assets: List[Dict[str, Any]],
    device_name: str,
    item: Dict[str, Any],
) -> Optional[Dict[str, Any]]:

    identity = make_asset_identity(
        device_name,
        item,
    )

    entity_index = clean_string(
        item.get("index")
    )

    for asset in existing_assets:

        description = clean_string(
            asset.get("description")
        )

        name = clean_string(
            asset.get("name")
        )

        # ------------------------------------------------------------------
        # 1. Preferred identity:
        #    New Assets contain both Device + ENTITY index in Description.
        #
        #    SNMP Device: N9K-EDGE-2
        #    SNMP Entity Index: 48873
        # ------------------------------------------------------------------

        description_identity = (
            asset_identity_from_description(
                description
            )
        )

        if description_identity == identity:
            return asset

        # ------------------------------------------------------------------
        # 2. Migration path for existing Assets.
        #
        #    Older Assets already have the authoritative device name
        #    in their Name, for example:
        #
        #        N9K-EDGE-2 | Transceiver(Eth1/20)
        #
        #    but their Description only contains:
        #
        #        SNMP Entity Index: 48873
        #
        #    Match Device from Name + ENTITY index from Description.
        # ------------------------------------------------------------------

        entity_match = re.search(
            r"SNMP Entity Index:\s*(\d+)",
            description,
            re.IGNORECASE,
        )

        if entity_match:
            legacy_entity_index = clean_string(
                entity_match.group(1)
            )

            name_prefix = (
                f"{device_name} |"
            )

            if (
                name.startswith(name_prefix)
                and legacy_entity_index == entity_index
            ):
                return asset

        # ------------------------------------------------------------------
        # 3. Backward compatibility with the old explicit identity format:
        #
        #        SNMP-<device>-ENTITY-<index>
        # ------------------------------------------------------------------

        if asset_identity_from_name(name) == identity:
            return asset

    return None


# =============================================================================
# Asset Hardware Type
# =============================================================================

def ensure_inventory_item_type(
    api: NetBoxAPI,
    model: str,
    manufacturer: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Ensure a NetBox InventoryItemType exists.

    The netbox-inventory plugin serializer uses a nested ManufacturerSerializer,
    therefore manufacturer must be sent as a nested object, not as a bare ID.
    """
    model = clean_string(model)

    if not model:
        raise ValueError(
            "Cannot create inventory item type without model"
        )

    manufacturer_id = manufacturer["id"]
    manufacturer_name = clean_string(manufacturer.get("name"))

    results = api.get_all(
        "/api/plugins/inventory/inventory-item-types/",
        params={"model": model},
    )

    for item in results:
        item_manufacturer = get_object_id(
            item.get("manufacturer")
        )

        if item_manufacturer == manufacturer_id:
            print(
                f"[EXISTS] Inventory Item Type : "
                f"{model} | id={item['id']}"
            )

            return item

    payload = {
        "manufacturer": {
            "name": manufacturer_name,
        },
        "model": model,
        "slug": slugify(model),
        "part_number": "",
        "description": (
            "Automatically discovered by "
            "NETBOX INVENTORY via ENTITY-MIB."
        ),
    }

    result = api.post(
        "/api/plugins/inventory/inventory-item-types/",
        payload,
    )

    print(
        f"[CREATED] Inventory Item Type : "
        f"{model} | id={result['id']}"
    )

    return result


def ensure_hardware_type_for_asset(
    api: NetBoxAPI,
    item: Dict[str, Any],
    asset_kind: str,
    manufacturer: Dict[str, Any],
    device_type: Dict[str, Any],
) -> Tuple[str, int]:

    model = asset_type_model(
        item,
        asset_kind,
    )

    # Chassis -> existing DeviceType.
    if asset_kind == "chassis":
        return (
            "device_type",
            device_type["id"],
        )

    # Actual pluggable/physical modules -> ModuleType.
    #
    # We intentionally do NOT create dcim.Module records here because
    # dcim.Module requires a valid module_bay relationship, which ENTITY-MIB
    # alone does not safely provide.
    if asset_kind == "module":
        module_type = ensure_module_type(
            api=api,
            model=model,
            manufacturer=manufacturer,
        )

        return (
            "module_type",
            module_type["id"],
        )

    # Fans, power supplies and transceivers are represented as plugin
    # InventoryItemType Assets. This avoids incorrectly treating them as
    # dcim.Module objects and avoids the required module_bay relationship.
    inventory_item_type = ensure_inventory_item_type(
        api=api,
        model=model,
        manufacturer=manufacturer,
    )

    return (
        "inventoryitem_type",
        inventory_item_type["id"],
    )


# =============================================================================
# Asset Sync
# =============================================================================

def sync_assets(
    api: NetBoxAPI,
    device: Dict[str, Any],
    inventory: Dict[str, Any],
    manufacturer: Dict[str, Any],
    device_type: Dict[str, Any],
    asset_roles: Dict[str, Dict[str, Any]],
) -> None:

    print_section(
        f"ASSET INVENTORY SYNC | {device['name']}"
    )

    existing_assets = get_existing_assets(api)

    print(
        f"Existing plugin Assets : "
        f"{len(existing_assets)}"
    )

    created = 0
    updated = 0
    unchanged = 0
    retired = 0
    already_retired = 0
    skipped = 0

    # Build the current set of managed SNMP identities first.
    # Only classified hardware with a valid ENTITY-MIB index participates.
    current_identities = set()

    for item in inventory.get("hardware", []):
        asset_kind = classify_asset(item)
        entity_index = clean_string(item.get("index"))

        if not asset_kind or not entity_index:
            continue

        current_identities.add(
            make_asset_identity(
                device["name"],
                item,
            )
        )

    # -------------------------------------------------------------------------
    # Current SNMP assets: create/update/restore.
    # -------------------------------------------------------------------------

    for item in inventory.get(
        "hardware",
    ):

        asset_kind = classify_asset(item)

        if not asset_kind:
            skipped += 1
            continue

        entity_index = clean_string(
            item.get("index")
        )

        if not entity_index:
            skipped += 1
            continue

        asset_name = asset_display_name(
            device["name"],
            item,
            asset_kind,
        )

        description = asset_description(
            device["name"],
            item,
            asset_kind,
        )

        serial = clean_string(
            item.get("serial")
        ) or None

        role = asset_roles.get(
            asset_kind
        )

        if not role:
            raise RuntimeError(
                f"Asset Role not found for "
                f"{asset_kind}"
            )

        role_id = get_object_id(role)

        if role_id is None:
            raise RuntimeError(
                f"Invalid Asset Role ID for "
                f"{asset_kind}"
            )

        hardware_type_field, hardware_type_id = (
            ensure_hardware_type_for_asset(
                api=api,
                item=item,
                asset_kind=asset_kind,
                manufacturer=manufacturer,
                device_type=device_type,
            )
        )

        desired: Dict[str, Any] = {
            "name": asset_name,
            "description": description,
            "serial": serial,
            "status": "used",
            "role": nested_id(role_id),
            hardware_type_field: nested_id(
                hardware_type_id
            ),
        }

        if asset_kind == "chassis":
            desired["device"] = nested_id(
                device["id"]
            )

        existing = find_existing_asset(
            existing_assets=existing_assets,
            device_name=device["name"],
            item=item,
        )

        if existing is None:

            result = api.post(
                "/api/plugins/inventory/assets/",
                desired,
            )

            created += 1

            print(
                f"[ASSET CREATED] "
                f"ENTITY={entity_index} | "
                f"CLASS={asset_kind} | "
                f"NAME={asset_name} | "
                f"MODEL={asset_type_model(item, asset_kind)} | "
                f"SERIAL={serial or '-'} | "
                f"ID={result['id']}"
            )

            existing_assets.append(result)
            continue

        changed: Dict[str, Any] = {}

        change_details: Dict[
            str,
            Tuple[Any, Any],
        ] = {}

        # Name
        existing_name = clean_string(
            existing.get("name")
        )

        if existing_name != asset_name:
            changed["name"] = asset_name
            change_details["name"] = (
                existing_name,
                asset_name,
            )

        # Description
        existing_description = clean_string(
            existing.get("description")
        )

        if existing_description != description:
            changed["description"] = description
            change_details["description"] = (
                existing_description,
                description,
            )

        # Serial
        existing_serial = clean_string(
            existing.get("serial")
        ) or None

        if existing_serial != serial:
            changed["serial"] = serial
            change_details["serial"] = (
                existing_serial,
                serial,
            )

        # Status
        existing_status = existing.get("status")

        if isinstance(existing_status, dict):
            existing_status = existing_status.get("value")

        if existing_status != "used":
            changed["status"] = "used"
            change_details["status"] = (
                existing_status,
                "used",
            )

        # Asset Role
        existing_role_id = get_object_id(
            existing.get("role")
        )

        if existing_role_id != role_id:
            changed["role"] = nested_id(role_id)
            change_details["role"] = (
                existing_role_id,
                role_id,
            )

        # Hardware Type
        existing_type_id = get_object_id(
            existing.get(hardware_type_field)
        )

        if existing_type_id != hardware_type_id:
            changed[hardware_type_field] = nested_id(
                hardware_type_id
            )
            change_details[hardware_type_field] = (
                existing_type_id,
                hardware_type_id,
            )

        # Device
        if asset_kind == "chassis":
            existing_device_id = get_object_id(
                existing.get("device")
            )

            if existing_device_id != device["id"]:
                changed["device"] = nested_id(
                    device["id"]
                )
                change_details["device"] = (
                    existing_device_id,
                    device["id"],
                )

        # Apply changes + NetBox Changelog
        if changed:
            changelog_message = build_change_message(
                "Asset",
                asset_name,
                change_details,
            )

            changed["changelog_message"] = (
                changelog_message
            )

            result = api.patch(
                f"/api/plugins/inventory/assets/{existing['id']}/",
                changed,
            )

            updated += 1

            print(
                f"[ASSET UPDATED] "
                f"ENTITY={entity_index} | "
                f"CLASS={asset_kind} | "
                f"ID={existing['id']} | "
                f"FIELDS={', '.join(change_details.keys())}"
            )

            print(
                f"[CHANGE] "
                f"{changelog_message}"
            )

            existing.update(result)

        else:
            unchanged += 1

            print(
                f"[ASSET UNCHANGED] "
                f"ENTITY={entity_index} | "
                f"CLASS={asset_kind} | "
f"ID={existing['id']}"
            )

    # -------------------------------------------------------------------------
    # Asset drift retirement.
    #
    # Retire only Assets that belong to THIS device and whose
    # SNMP ENTITY identity is no longer present.
    #
    # Asset identity:
    #
    #     <device-name>:<entity-index>
    #
    # This prevents an ENTITY index from one device being confused
    # with the same ENTITY index on another device.
    # -------------------------------------------------------------------------

    device_name = device["name"]

    for asset in existing_assets:

        description = clean_string(
            asset.get("description")
        )

        identity = asset_identity_from_description(
            description
        )

        # Legacy Assets:
        # Try the old name-based identity if the new Description
        # identity is not available.
        if not identity:

            name = clean_string(
                asset.get("name")
            )

            identity = asset_identity_from_name(
                name
            )

        if not identity:
            continue

        # IMPORTANT:
        # Never touch Assets belonging to another device.
        if not identity.startswith(
            f"{device_name}:"
        ):
            continue

        if identity in current_identities:
            continue

        status = asset.get("status")

        if isinstance(status, dict):
            status = status.get("value")

        if status == "retired":
            already_retired += 1
            continue

        api.patch(
            f"/api/plugins/inventory/assets/{asset['id']}/",
            {
                "status": "retired"
            },
        )

        retired += 1

        entity_index = identity.split(
            ":",
            1,
        )[1]

        print(
            f"[ASSET RETIRED] "
            f"ENTITY={entity_index} | "
            f"ID={asset['id']} | "
            f"NAME={clean_string(asset.get('name'))}"
        )

    print()
    print(
        f"[ASSETS SUMMARY] "
        f"created={created} "
        f"updated={updated} "
        f"unchanged={unchanged} "
        f"retired={retired} "
        f"already_retired={already_retired} "
        f"skipped={skipped}"
    )


# =============================================================================
# Legacy DCIM Inventory Items
# =============================================================================

def sync_hardware_legacy_inventory_items(
    api: NetBoxAPI,
    device: Dict[str, Any],
    hardware: List[Dict[str, Any]],
) -> None:

    """
    Keep the existing DCIM InventoryItem synchronization for compatibility.

    Existing InventoryItems are NOT deleted or migrated automatically.

    This function intentionally remains separate from Plugin Assets.
    """

    existing = api.get_all(
        "/api/dcim/inventory-items/",
        params={
            "device_id": device["id"],
        },
    )

    identity_map: Dict[
        Tuple[str, str, str],
        Dict[str, Any],
    ] = {}

    for item in existing:
        key = (
            clean_string(
                item.get("name")
            ),
            clean_string(
                item.get("part_id")
            ),
            clean_string(
                item.get("serial")
            ),
        )

        identity_map[key] = item

    created = 0
    unchanged = 0

    for item in hardware:

        name = clean_string(
            item.get("name")
        )

        model = clean_string(
            item.get("model")
        )

        serial = clean_string(
            item.get("serial")
        )

        if not name and not model and not serial:
            continue

        key = (
            name,
            model,
            serial,
        )

        if key in identity_map:
            unchanged += 1
            continue

        payload = {
            "device": device["id"],
            "name": (
                name[:64]
                if name
                else "SNMP Entity"
            ),
            "part_id": (
                model[:50]
                if model
                else ""
            ),
            "serial": (
                serial[:50]
                if serial
                else ""
            ),
        }

        try:
            result = api.post(
                "/api/dcim/inventory-items/",
                payload,
            )

            created += 1

            print(
                f"[LEGACY INVENTORY CREATED] "
                f"{result.get('name')} | "
                f"serial={result.get('serial') or '-'}"
            )

        except requests.HTTPError:
            print(
                f"[LEGACY INVENTORY SKIPPED] "
                f"{name} | "
                f"likely already exists"
            )

    print(
        f"[LEGACY INVENTORY SUMMARY] "
        f"created={created} "
        f"unchanged={unchanged}"
    )


# =============================================================================
# MAC Address Sync
# =============================================================================

def sync_mac_table(
    api: NetBoxAPI,
    device: Dict[str, Any],
    mac_table: List[Dict[str, Any]],
) -> None:

    if not mac_table:
        print(
            f"[MAC] {device['name']} | "
            f"no dynamic MAC entries"
        )
        return

    # -------------------------------------------------------------------------
    # Existing MAC Addresses
    # -------------------------------------------------------------------------
    #
    # MAC records created by the current inventory sync are currently stored
    # in NetBox without an assigned interface/device. Therefore the NetBox
    # `device_id` filter returns zero records in this environment.
    #
    # Read all existing MAC records and normalize their addresses instead.
    # This prevents the weekly sync from creating the same MAC repeatedly.
    #
    existing = api.get_all(
        "/api/dcim/mac-addresses/",
    )

    existing_macs = set()

    for item in existing:
        mac = normalize_mac(
            item.get("mac_address")
        )

        if mac:
            existing_macs.add(mac)

    created = 0
    unchanged = 0

    for entry in mac_table:

        mac = normalize_mac(
            entry.get("mac")
            or entry.get("mac_address")
        )

        if not mac:
            continue

        if mac in existing_macs:
            unchanged += 1

            print(
                f"[MAC UNCHANGED] "
                f"{mac}"
            )

            continue

        payload = {
            "mac_address": mac,
        }

        try:
            result = api.post(
                "/api/dcim/mac-addresses/",
                payload,
            )

            created += 1
            existing_macs.add(mac)

            print(
                f"[MAC CREATED] "
                f"{mac} | id={result.get('id')}"
            )

        except requests.HTTPError:
            print(
                f"[MAC SKIPPED] "
                f"{mac} | "
                f"API rejected or already exists"
            )

    print(
        f"[MAC SUMMARY] "
        f"created={created} "
        f"unchanged={unchanged}"
    )


# =============================================================================
# SNMP Inventory Collection
# =============================================================================

async def collect_inventory(
    device_name: str,
    device_ip: str,
) -> Dict[str, Any]:

    print_section(
        "COLLECTING SNMP INVENTORY"
    )

    print(
        f"Device IP : {device_ip}"
    )

    print(
        f"Device     : {device_name}"
    )

    snmp = SNMPClient(
        host=device_ip,
        community=SNMP_COMMUNITY,
        timeout=SNMP_TIMEOUT,
        retries=SNMP_RETRIES,
    )

    try:
        await snmp.connect()

        collector = InventoryCollector(
            snmp,
            device_name,
        )

        raw = await collector.collect()

        inventory = normalize_inventory(
            raw
        )

        return inventory

    finally:
        snmp.engine.close_dispatcher()


# =============================================================================
# Main NetBox Synchronization
# =============================================================================

def sync_inventory(
    api: NetBoxAPI,
    inventory: Dict[str, Any],
) -> None:

    device_data = inventory["device"]

    device_name = clean_string(
        device_data.get("name")
    )

    if not device_name:
        raise RuntimeError(
            "Inventory does not contain an authoritative device name"
        )

    vendor = clean_string(
        device_data.get("vendor")
    ) or DEFAULT_MANUFACTURER_NAME

    model = clean_string(
        device_data.get("model")
    )

    if not model:
        raise RuntimeError(
            f"Cannot determine device model "
            f"for {device_name}"
        )

    print_section(
        f"NETBOX SYNC | {device_name}"
    )

    # -------------------------------------------------------------------------
    # Base Objects
    # -------------------------------------------------------------------------

    site = ensure_site(
        api,
        DEFAULT_SITE_NAME,
    )

    manufacturer = ensure_manufacturer(
        api,
        vendor,
    )

    device_role = ensure_device_role(
        api,
        DEFAULT_DEVICE_ROLE_NAME,
    )

    device_type = ensure_device_type(
        api,
        model,
        manufacturer["id"],
    )

    # -------------------------------------------------------------------------
    # Device
    # -------------------------------------------------------------------------

    device = sync_device(
        api=api,
        device=device_data,
        device_type=device_type,
        role=device_role,
        site=site,
    )

    # -------------------------------------------------------------------------
    # Asset Roles
    # -------------------------------------------------------------------------

    asset_roles = ensure_asset_roles(
        api,
    )

    # -------------------------------------------------------------------------
    # Interfaces
    # -------------------------------------------------------------------------

    sync_interfaces(
        api=api,
        device=device,
        interfaces=inventory.get(
            "interfaces",
            [],
        ),
    )

    # -------------------------------------------------------------------------
    # Management IP
    # -------------------------------------------------------------------------

    sync_management_ip(
        api=api,
        device=device,
    )

    # -------------------------------------------------------------------------
    # Plugin Asset Inventory
    # -------------------------------------------------------------------------

    sync_assets(
        api=api,
        device=device,
        inventory=inventory,
        manufacturer=manufacturer,
        device_type=device_type,
        asset_roles=asset_roles,
    )

    # -------------------------------------------------------------------------
    # Existing legacy DCIM InventoryItems
    # -------------------------------------------------------------------------

    sync_hardware_legacy_inventory_items(
        api=api,
        device=device,
        hardware=inventory.get(
            "hardware",
            [],
        ),
    )

    # -------------------------------------------------------------------------
    # MAC Table
    # -------------------------------------------------------------------------

    sync_mac_table(
        api=api,
        device=device,
        mac_table=inventory.get(
            "mac_table",
            [],
        ),
    )

    print_section(
        f"SYNC COMPLETE | {device_name}"
    )


# =============================================================================
# Main
# =============================================================================

def main() -> None:

    print()
    print("=" * 100)
    print("NETBOX AUTOMATED MULTI-DEVICE INVENTORY")
    print("=" * 100)

    print(
        f"NetBox : {NETBOX_URL}"
    )

    print(
        f"Devices: {DEVICES_FILE}"
    )

    print("=" * 100)

    # -------------------------------------------------------------------------
    # Load Devices
    # -------------------------------------------------------------------------

    devices = load_devices(
        DEVICES_FILE
    )

    print()
    print(
        f"Configured devices: {len(devices)}"
    )

    for index, device_config in enumerate(
        devices,
        start=1,
    ):
        print(
            f"  {index}. "
            f"{device_config['name']} "
            f"({device_config['ip']})"
        )

    # -------------------------------------------------------------------------
    # Shared NetBox API
    # -------------------------------------------------------------------------

    api = NetBoxAPI(
        base_url=NETBOX_URL,
        token=NETBOX_TOKEN,
    )

    # -------------------------------------------------------------------------
    # NetBox Health Check
    # -------------------------------------------------------------------------

    status = api.get(
        "/api/status/"
    )

    print(
        f"NetBox status : "
        f"{status.get('netbox-version', 'unknown')}"
    )

    # -------------------------------------------------------------------------
    # Multi-Device Processing
    # -------------------------------------------------------------------------

    success = 0
    failed = 0
    failed_devices: List[Dict[str, str]] = []

    total = len(devices)

    for index, device_config in enumerate(
        devices,
        start=1,
    ):

        device_name = device_config["name"]
        device_ip = device_config["ip"]

        print()
        print("=" * 100)
        print(
            f"DEVICE {index}/{total} | "
            f"{device_name} | "
            f"{device_ip}"
        )
        print("=" * 100)

        try:

            inventory = asyncio.run(
                collect_inventory(
                    device_name=device_name,
                    device_ip=device_ip,
                )
            )

            # -----------------------------------------------------------------
            # Inventory Summary
            # -----------------------------------------------------------------

            print()
            print(
                f"Hardware  : "
                f"{len(inventory.get('hardware', []))}"
            )

            print(
                f"Interfaces: "
                f"{len(inventory.get('interfaces', []))}"
            )

            print(
                f"MAC Table : "
                f"{len(inventory.get('mac_table', []))}"
            )

            # -----------------------------------------------------------------
            # NetBox Sync
            # -----------------------------------------------------------------

            sync_inventory(
                api=api,
                inventory=inventory,
            )

            success += 1

            print()
            print(
                f"[DEVICE SUCCESS] "
                f"{device_name} "
                f"({device_ip})"
            )

        except Exception as exc:

            failed += 1

            failed_devices.append(
                {
                    "name": device_name,
                    "ip": device_ip,
                }
            )

            print()
            print(
                f"[DEVICE FAILED] "
                f"{device_name} "
                f"({device_ip})"
            )

            print(
                f"ERROR: {exc}"
            )

            continue

    # -------------------------------------------------------------------------
    # Final Summary
    # -------------------------------------------------------------------------

    print()
    print("=" * 100)
    print("FINAL SUMMARY")
    print("=" * 100)

    print(
        f"Total   : {total}"
    )

    print(
        f"Success : {success}"
    )

    print(
        f"Failed  : {failed}"
    )

    if failed_devices:

        print()
        print("Failed devices:")

        for item in failed_devices:

            print(
                f"  - {item['name']} "
                f"({item['ip']})"
            )

    print("=" * 100)


if __name__ == "__main__":
    main()
