#!/usr/bin/env python3

import asyncio
import sys
from pathlib import Path
from typing import Any

from pysnmp.hlapi.v3arch.asyncio import (
    SnmpEngine,
    CommunityData,
    UdpTransportTarget,
    ContextData,
    ObjectType,
    ObjectIdentity,
    get_cmd,
    walk_cmd,
)


# ============================================================
# Paths / Configuration
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / "config" / ".env"


def load_env_file(path: Path) -> dict[str, str]:
    """
    Minimal .env loader.
    No external python-dotenv dependency required.
    """

    values = {}

    if not path.exists():
        raise FileNotFoundError(
            f"Configuration file not found: {path}"
        )

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            if not line:
                continue

            if line.startswith("#"):
                continue

            if "=" not in line:
                continue

            key, value = line.split("=", 1)

            key = key.strip()
            value = value.strip()

            if (
                len(value) >= 2
                and value[0] == value[-1]
                and value[0] in ("'", '"')
            ):
                value = value[1:-1]

            values[key] = value

    return values


CONFIG = load_env_file(ENV_FILE)


def cfg(
    name: str,
    default: str | None = None,
) -> str | None:
    return CONFIG.get(name, default)


DEVICE_IP = cfg("DEVICE_IP")
DEVICE_NAME = cfg("DEVICE_NAME", DEVICE_IP)

SNMP_VERSION = cfg("SNMP_VERSION", "2c")
SNMP_COMMUNITY = cfg("SNMP_COMMUNITY")

SNMP_TIMEOUT = float(
    cfg("SNMP_TIMEOUT", "2")
)

SNMP_RETRIES = int(
    cfg("SNMP_RETRIES", "1")
)


if not DEVICE_IP:
    raise RuntimeError(
        "DEVICE_IP is not configured in config/.env"
    )


if not SNMP_COMMUNITY:
    raise RuntimeError(
        "SNMP_COMMUNITY is not configured in config/.env"
    )


if SNMP_VERSION != "2c":
    raise RuntimeError(
        f"Currently only SNMP v2c is implemented. "
        f"Configured version: {SNMP_VERSION}"
    )


# ============================================================
# OIDs
# ============================================================

# -------------------------
# SYSTEM-MIB
# -------------------------

OID_SYS_DESCR = (
    "1.3.6.1.2.1.1.1.0"
)

OID_SYS_OBJECT_ID = (
    "1.3.6.1.2.1.1.2.0"
)

OID_SYS_UPTIME = (
    "1.3.6.1.2.1.1.3.0"
)

OID_SYS_NAME = (
    "1.3.6.1.2.1.1.5.0"
)

OID_SYS_LOCATION = (
    "1.3.6.1.2.1.1.6.0"
)


# -------------------------
# ENTITY-MIB
# -------------------------

OID_ENT_PHYSICAL_DESCR = (
    "1.3.6.1.2.1.47.1.1.1.1.2"
)

OID_ENT_PHYSICAL_VENDOR_TYPE = (
    "1.3.6.1.2.1.47.1.1.1.1.3"
)

OID_ENT_PHYSICAL_SERIAL = (
    "1.3.6.1.2.1.47.1.1.1.1.11"
)

OID_ENT_PHYSICAL_NAME = (
    "1.3.6.1.2.1.47.1.1.1.1.7"
)

OID_ENT_PHYSICAL_MODEL = (
    "1.3.6.1.2.1.47.1.1.1.1.13"
)

OID_ENT_PHYSICAL_CLASS = (
    "1.3.6.1.2.1.47.1.1.1.1.5"
)

OID_ENT_PHYSICAL_PARENT = (
    "1.3.6.1.2.1.47.1.1.1.1.4"
)


# -------------------------
# IF-MIB
# -------------------------

OID_IF_INDEX = (
    "1.3.6.1.2.1.2.2.1.1"
)

OID_IF_DESCR = (
    "1.3.6.1.2.1.2.2.1.2"
)

OID_IF_TYPE = (
    "1.3.6.1.2.1.2.2.1.3"
)

OID_IF_MTU = (
    "1.3.6.1.2.1.2.2.1.4"
)

OID_IF_SPEED = (
    "1.3.6.1.2.1.2.2.1.5"
)

OID_IF_PHYS_ADDRESS = (
    "1.3.6.1.2.1.2.2.1.6"
)

OID_IF_ADMIN_STATUS = (
    "1.3.6.1.2.1.2.2.1.7"
)

OID_IF_OPER_STATUS = (
    "1.3.6.1.2.1.2.2.1.8"
)

OID_IF_NAME = (
    "1.3.6.1.2.1.31.1.1.1.1"
)

OID_IF_HIGH_SPEED = (
    "1.3.6.1.2.1.31.1.1.1.15"
)

OID_IF_ALIAS = (
    "1.3.6.1.2.1.31.1.1.1.18"
)


# -------------------------
# Q-BRIDGE-MIB
# -------------------------

# dot1dBasePortIfIndex
# Bridge Port -> ifIndex
OID_BRIDGE_PORT_IFINDEX = (
    "1.3.6.1.2.1.17.1.4.1.2"
)

# dot1qTpFdbAddress
# VLAN + MAC index
OID_QBRIDGE_FDB_ADDRESS = (
    "1.3.6.1.2.1.17.7.1.2.2.1.1"
)

# dot1qTpFdbPort
# VLAN + MAC -> Bridge Port
OID_QBRIDGE_FDB_PORT = (
    "1.3.6.1.2.1.17.7.1.2.2.1.2"
)

# dot1qTpFdbStatus
# VLAN + MAC -> FDB status
OID_QBRIDGE_FDB_STATUS = (
    "1.3.6.1.2.1.17.7.1.2.2.1.3"
)


# -------------------------
# CISCO-IF-EXTENSION-MIB
# -------------------------

# cieIfDot1dBaseMappingPort
#
# Cisco/NX-OS specific mapping:
#
#     ifIndex -> BridgePort
#
# The table index is the ifIndex and the value
# is the corresponding BridgePort.
#
OID_CISCO_DOT1D_MAPPING_PORT = (
    "1.3.6.1.4.1.9.9.276.1.5.1.1.1"
)


# ============================================================
# Normalization Constants
# ============================================================

ENTITY_CLASS_NAMES = {

    "1": "other",

    "2": "unknown",

    "3": "chassis",

    "4": "backplane",

    "5": "container",

    "6": "power_supply",

    "7": "fan",

    "8": "sensor",

    "9": "module",

    "10": "port",

    "11": "stack",

    "12": "cpu",
}


IF_ADMIN_STATUS_NAMES = {
    1: "up",
    2: "down",
    3: "testing",
}


IF_OPER_STATUS_NAMES = {
    1: "up",
    2: "down",
    3: "testing",
    4: "unknown",
    5: "dormant",
    6: "not_present",
    7: "lower_layer_down",
}


FDB_STATUS_NAMES = {
    1: "other",
    2: "invalid",
    3: "learned",
    4: "self",
    5: "mgmt",
}


# ============================================================
# Utility Functions
# ============================================================

def clean_string(value: Any) -> str:
    """
    Convert SNMP value to clean string.

    This function is only used for textual values.
    Raw SNMP values are preserved inside SNMPClient.walk().
    """

    if value is None:
        return ""

    value = str(value).strip()

    if (
        len(value) >= 2
        and value[0] == '"'
        and value[-1] == '"'
    ):
        value = value[1:-1]

    return value.strip()


def oid_index(
    oid: str,
    base_oid: str,
) -> str:
    """
    Extract table index from an OID.
    """

    prefix = base_oid + "."

    if oid.startswith(prefix):
        return oid[len(prefix):]

    return oid.split(".")[-1]


def mac_to_string(value: Any) -> str:
    """
    Convert SNMP OctetString MAC to:

        AA:BB:CC:DD:EE:FF
    """

    if value is None:
        return ""

    try:
        raw = bytes(value)

        if len(raw) == 6:
            return ":".join(
                f"{byte:02X}"
                for byte in raw
            )

    except Exception:
        pass

    text = clean_string(value)

    text = (
        text
        .replace(" ", "")
        .replace(":", "")
        .replace("-", "")
    )

    if (
        len(text) == 12
        and all(
            char in "0123456789abcdefABCDEF"
            for char in text
        )
    ):
        return ":".join(
            text[i:i + 2].upper()
            for i in range(0, 12, 2)
        )

    return clean_string(value)


def normalize_mac(
    value: Any,
) -> str:
    """
    Normalize any supported MAC representation to:

        AA:BB:CC:DD:EE:FF

    Returns an empty string when the value is not
    a valid six-octet MAC address.
    """

    mac = mac_to_string(value)

    if not mac:
        return ""

    parts = mac.split(":")

    if len(parts) != 6:
        return ""

    try:
        octets = [
            int(part, 16)
            for part in parts
        ]
    except ValueError:
        return ""

    if not all(
        0 <= octet <= 255
        for octet in octets
    ):
        return ""

    return ":".join(
        f"{octet:02X}"
        for octet in octets
    )


def mac_from_oid_index(
    index: str,
) -> str:
    """
    Extract MAC address from Q-BRIDGE FDB index.

    Q-BRIDGE index:

        VLAN.MAC1.MAC2.MAC3.MAC4.MAC5.MAC6

    Example:

        504.24.207.36.220.0.185

    becomes:

        18:CF:24:DC:00:B9
    """

    parts = index.split(".")

    if len(parts) != 7:
        return ""

    mac_parts = parts[1:]

    try:
        octets = [
            int(part)
            for part in mac_parts
        ]
    except ValueError:
        return ""

    if not all(
        0 <= octet <= 255
        for octet in octets
    ):
        return ""

    return ":".join(
        f"{octet:02X}"
        for octet in octets
    )


def vlan_from_oid_index(
    index: str,
) -> int:
    """
    Extract VLAN from Q-BRIDGE FDB index.
    """

    parts = index.split(".")

    if len(parts) != 7:
        return 0

    try:
        return int(parts[0])
    except ValueError:
        return 0


def to_int(
    value: Any,
    default: int = 0,
) -> int:
    """
    Safely convert SNMP numeric values to int.
    """

    if value is None:
        return default

    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def speed_to_mbps(
    speed_bps: int | float,
) -> float:
    """
    Convert bits/sec to Mbps.
    """

    if not speed_bps:
        return 0

    return round(
        float(speed_bps) / 1_000_000,
        2,
    )


def status_name(
    mapping: dict[int, str],
    value: Any,
) -> str:
    """
    Convert an SNMP status integer to a stable
    semantic string.
    """

    numeric = to_int(value, 0)

    return mapping.get(
        numeric,
        "unknown",
    )


def natural_sort_key(
    value: str,
) -> tuple[int, Any]:
    """
    Stable sorting for numeric SNMP indexes.
    """

    if str(value).isdigit():
        return (0, int(value))

    return (1, str(value))


def detect_vendor(
    sys_object_id: str,
) -> str:
    """
    Detect vendor from sysObjectID.

    Cisco enterprise OID:

        1.3.6.1.4.1.9
    """

    if (
        sys_object_id == "1.3.6.1.4.1.9"
        or sys_object_id.startswith(
            "1.3.6.1.4.1.9."
        )
    ):
        return "Cisco"

    return ""


def detect_platform(
    sys_descr: str,
) -> str:
    """
    Detect a high-level platform family from
    sysDescr without trying to infer a precise
    hardware model.
    """

    text = sys_descr.lower()

    if "nx-os" in text or "nxos" in text:
        return "Cisco NX-OS"

    if "ios xe" in text:
        return "Cisco IOS-XE"

    if "ios software" in text:
        return "Cisco IOS"

    if "ios-xe" in text:
        return "Cisco IOS-XE"

    return ""


def uptime_to_seconds(
    value: Any,
) -> int:
    """
    Convert SNMP sysUpTime from TimeTicks to seconds.

    sysUpTime is expressed in hundredths of a second.
    """

    text = clean_string(value)

    if not text:
        return 0

    try:
        return int(value) // 100
    except (TypeError, ValueError):
        pass

    digits = ""

    for char in text:
        if char.isdigit():
            digits += char
        else:
            break

    if not digits:
        return 0

    try:
        return int(digits) // 100
    except ValueError:
        return 0


# ============================================================
# SNMP Client
# ============================================================

class SNMPClient:

    def __init__(
        self,
        host: str,
        community: str,
        timeout: float = 2,
        retries: int = 1,
    ):

        self.host = host
        self.community = community
        self.timeout = timeout
        self.retries = retries

        self.engine = SnmpEngine()

        self.auth = CommunityData(
            community,
            mpModel=1,
        )

        self.context = ContextData()

        self.transport = None

    async def connect(self):

        self.transport = (
            await UdpTransportTarget.create(
                (self.host, 161),
                timeout=self.timeout,
                retries=self.retries,
            )
        )

    async def get(
        self,
        oid: str,
    ) -> str:

        (
            error_indication,
            error_status,
            error_index,
            var_binds,
        ) = await get_cmd(
            self.engine,
            self.auth,
            self.transport,
            self.context,
            ObjectType(
                ObjectIdentity(oid)
            ),
        )

        if error_indication:
            raise RuntimeError(
                f"SNMP error for {self.host}: "
                f"{error_indication}"
            )

        if error_status:
            raise RuntimeError(
                f"SNMP error for {self.host}: "
                f"{error_status.prettyPrint()}"
            )

        if not var_binds:
            return ""

        return clean_string(
            var_binds[0][1]
        )

    async def walk(
        self,
        base_oid: str,
    ) -> dict[str, Any]:

        result: dict[str, Any] = {}

        async for (
            error_indication,
            error_status,
            error_index,
            var_binds,
        ) in walk_cmd(
            self.engine,
            self.auth,
            self.transport,
            self.context,
            ObjectType(
                ObjectIdentity(base_oid)
            ),
            lexicographicMode=False,
        ):

            if error_indication:
                raise RuntimeError(
                    f"SNMP walk error for {self.host}: "
                    f"{error_indication}"
                )

            if error_status:
                raise RuntimeError(
                    f"SNMP walk error for {self.host}: "
                    f"{error_status.prettyPrint()}"
                )

            for oid, value in var_binds:

                oid_text = str(oid)

                index = oid_index(
                    oid_text,
                    base_oid,
                )

                # Preserve raw SNMP value.
                result[index] = value

        return result


# ============================================================
# Inventory Collector
# ============================================================

class InventoryCollector:

    def __init__(
        self,
        snmp: SNMPClient,
        device_name: str,
    ):
        self.snmp = snmp
        self.device_name = device_name

    async def collect_system(
        self,
    ) -> dict[str, Any]:

        values = {}

        values["sysDescr"] = await self.snmp.get(
            OID_SYS_DESCR
        )

        values["sysObjectID"] = await self.snmp.get(
            OID_SYS_OBJECT_ID
        )

        values["sysUpTime"] = await self.snmp.get(
            OID_SYS_UPTIME
        )

        values["sysName"] = await self.snmp.get(
            OID_SYS_NAME
        )

        values["sysLocation"] = await self.snmp.get(
            OID_SYS_LOCATION
        )

        return values

    async def collect_entity(
        self,
    ) -> dict[str, dict[str, str]]:

        names = await self.snmp.walk(
            OID_ENT_PHYSICAL_NAME
        )

        descriptions = await self.snmp.walk(
            OID_ENT_PHYSICAL_DESCR
        )

        serials = await self.snmp.walk(
            OID_ENT_PHYSICAL_SERIAL
        )

        models = await self.snmp.walk(
            OID_ENT_PHYSICAL_MODEL
        )

        classes = await self.snmp.walk(
            OID_ENT_PHYSICAL_CLASS
        )

        parents = await self.snmp.walk(
            OID_ENT_PHYSICAL_PARENT
        )

        indexes = set()

        indexes.update(names.keys())
        indexes.update(descriptions.keys())
        indexes.update(serials.keys())
        indexes.update(models.keys())
        indexes.update(classes.keys())
        indexes.update(parents.keys())

        entities = {}

        for index in sorted(
            indexes,
            key=natural_sort_key,
        ):

            entities[index] = {
                "index": index,

                "name": clean_string(
                    names.get(index, "")
                ),

                "description": clean_string(
                    descriptions.get(index, "")
                ),

                "serial": clean_string(
                    serials.get(index, "")
                ),

                "model": clean_string(
                    models.get(index, "")
                ),

                "class": clean_string(
                    classes.get(index, "")
                ),

                "parent": clean_string(
                    parents.get(index, "")
                ),
            }

        return entities

    async def collect_interfaces(
        self,
    ) -> dict[str, dict[str, Any]]:

        if_index = await self.snmp.walk(
            OID_IF_INDEX
        )

        if_descr = await self.snmp.walk(
            OID_IF_DESCR
        )

        if_type = await self.snmp.walk(
            OID_IF_TYPE
        )

        if_mtu = await self.snmp.walk(
            OID_IF_MTU
        )

        if_speed = await self.snmp.walk(
            OID_IF_SPEED
        )

        if_phys = await self.snmp.walk(
            OID_IF_PHYS_ADDRESS
        )

        if_admin = await self.snmp.walk(
            OID_IF_ADMIN_STATUS
        )

        if_oper = await self.snmp.walk(
            OID_IF_OPER_STATUS
        )

        if_name = await self.snmp.walk(
            OID_IF_NAME
        )

        if_high_speed = await self.snmp.walk(
            OID_IF_HIGH_SPEED
        )

        if_alias = await self.snmp.walk(
            OID_IF_ALIAS
        )

        indexes = set()

        indexes.update(if_index.keys())
        indexes.update(if_descr.keys())
        indexes.update(if_name.keys())

        interfaces = {}

        for index in sorted(
            indexes,
            key=natural_sort_key,
        ):

            speed_bps = to_int(
                if_speed.get(index),
                0,
            )

            high_speed_mbps = to_int(
                if_high_speed.get(index),
                0,
            )

            mtu = to_int(
                if_mtu.get(index),
                0,
            )

            if_type_value = to_int(
                if_type.get(index),
                0,
            )

            admin_status = to_int(
                if_admin.get(index),
                0,
            )

            oper_status = to_int(
                if_oper.get(index),
                0,
            )

            interfaces[index] = {

                "ifIndex": (
                    int(index)
                    if index.isdigit()
                    else index
                ),

                "name": clean_string(
                    if_name.get(index, "")
                ),

                "description": clean_string(
                    if_descr.get(index, "")
                ),

                "alias": clean_string(
                    if_alias.get(index, "")
                ),

                "type": if_type_value,

                "mtu": mtu,

                "speed_bps": speed_bps,

                "speed_mbps": speed_to_mbps(
                    speed_bps
                ),

                "high_speed_mbps": (
                    high_speed_mbps
                ),

                "mac": mac_to_string(
                    if_phys.get(index)
                ),

                "admin_status": admin_status,

                "oper_status": oper_status,

                "enabled": (
                    admin_status == 1
                ),

                "up": (
                    oper_status == 1
                ),
            }

        return interfaces

    async def collect_mac_table(
        self,
        interfaces: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Collect dynamic MAC addresses using Q-BRIDGE-MIB.

        Primary data:

            VLAN
            MAC
            BridgePort
            FDB status

        BridgePort is resolved through:

            BridgePort -> ifIndex -> ifName

        Mapping sources:

            1. Standard BRIDGE-MIB
               dot1dBasePortIfIndex

            2. Cisco CISCO-IF-EXTENSION-MIB
               cieIfDot1dBaseMappingPort

        Standard BRIDGE-MIB mapping has priority.
        Cisco mapping is used as a fallback for
        BridgePorts that are not exposed through
        dot1dBasePortIfIndex.

        Only FDB status 3 (learned) is retained.
        """

        # ----------------------------------------------------
        # Standard Bridge Port -> ifIndex
        # ----------------------------------------------------

        bridge_port_ifindex = (
            await self.snmp.walk(
                OID_BRIDGE_PORT_IFINDEX
            )
        )

        # ----------------------------------------------------
        # Cisco/NX-OS ifIndex -> Bridge Port
        # ----------------------------------------------------

        cisco_ifindex_to_bridge_port = (
            await self.snmp.walk(
                OID_CISCO_DOT1D_MAPPING_PORT
            )
        )

        # ----------------------------------------------------
        # Q-BRIDGE FDB
        # ----------------------------------------------------

        fdb_port = await self.snmp.walk(
            OID_QBRIDGE_FDB_PORT
        )

        fdb_status = await self.snmp.walk(
            OID_QBRIDGE_FDB_STATUS
        )

        # ----------------------------------------------------
        # Build BridgePort -> ifIndex
        # ----------------------------------------------------

        bridge_to_ifindex: dict[int, int] = {}

        # Standard BRIDGE-MIB mapping.
        for index, value in bridge_port_ifindex.items():

            try:
                bridge_port = int(index)
                ifindex = int(value)

                bridge_to_ifindex[
                    bridge_port
                ] = ifindex

            except (TypeError, ValueError):
                continue

        # Cisco/NX-OS mapping.
        #
        # Table index:
        #
        #     ifIndex
        #
        # Table value:
        #
        #     BridgePort
        #
        # Convert it to:
        #
        #     BridgePort -> ifIndex

        for index, value in (
            cisco_ifindex_to_bridge_port.items()
        ):

            try:
                ifindex = int(index)
                bridge_port = int(value)

            except (TypeError, ValueError):
                continue

            # Never overwrite a valid standard
            # BRIDGE-MIB mapping.
            bridge_to_ifindex.setdefault(
                bridge_port,
                ifindex,
            )

        # ----------------------------------------------------
        # Build ifIndex -> interface name
        # ----------------------------------------------------

        ifindex_to_name: dict[int, str] = {}

        for interface in interfaces.values():

            ifindex = interface.get(
                "ifIndex"
            )

            ifname = interface.get(
                "name"
            )

            if isinstance(ifindex, int) and ifname:
                ifindex_to_name[
                    ifindex
                ] = ifname

        # ----------------------------------------------------
        # Build MAC table
        # ----------------------------------------------------

        mac_table: list[dict[str, Any]] = []

        for index, port_value in fdb_port.items():

            vlan = vlan_from_oid_index(
                index
            )

            mac = mac_from_oid_index(
                index
            )

            if not vlan or not mac:
                continue

            bridge_port = to_int(
                port_value,
                0,
            )

            status = to_int(
                fdb_status.get(index),
                0,
            )

            # Asset inventory keeps only learned
            # dynamic MACs.
            #
            # This intentionally excludes:
            #
            # 1 = other
            # 2 = invalid
            # 4 = self
            # 5 = mgmt
            #
            if status != 3:
                continue

            # A learned MAC must have a valid
            # BridgePort.
            if bridge_port <= 0:
                continue

            ifindex = bridge_to_ifindex.get(
                bridge_port
            )

            ifname = (
                ifindex_to_name.get(
                    ifindex
                )
                if ifindex is not None
                else None
            )

            mac_table.append(
                {
                    "vlan": vlan,

                    "mac": normalize_mac(
                        mac
                    ),

                    "bridge_port": bridge_port,

                    "ifIndex": ifindex,

                    "ifName": ifname,

                    "status": "dynamic",
                }
            )

        # ----------------------------------------------------
        # Remove invalid MACs
        # ----------------------------------------------------

        mac_table = [
            item
            for item in mac_table
            if item.get("mac")
        ]

        # ----------------------------------------------------
        # Stable sorting
        # ----------------------------------------------------

        mac_table.sort(
            key=lambda item: (
                item["vlan"],
                item["mac"],
                item.get("ifName") or "",
            )
        )

        return mac_table

    async def collect(
        self,
    ) -> dict[str, Any]:

        print()
        print("=" * 70)
        print("NETBOX INVENTORY COLLECTOR")
        print("=" * 70)

        print(
            f"Device IP : {self.snmp.host}"
        )

        print(
            f"Device     : {self.device_name}"
        )

        print("=" * 70)

        # ----------------------------------------------------
        # SYSTEM
        # ----------------------------------------------------

        print()
        print(
            "[1/4] Collecting SYSTEM-MIB..."
        )

        system = await self.collect_system()

        print("      OK")

        # ----------------------------------------------------
        # ENTITY
        # ----------------------------------------------------

        print()
        print(
            "[2/4] Collecting ENTITY-MIB..."
        )

        entity = await self.collect_entity()

        print(
            f"      OK - {len(entity)} "
            f"physical entities"
        )

        # ----------------------------------------------------
        # INTERFACES
        # ----------------------------------------------------

        print()
        print(
            "[3/4] Collecting IF-MIB..."
        )

        interfaces = (
            await self.collect_interfaces()
        )

        print(
            f"      OK - {len(interfaces)} "
            f"interfaces"
        )

        # ----------------------------------------------------
        # MAC TABLE
        # ----------------------------------------------------

        print()
        print(
            "[4/4] Collecting Q-BRIDGE-MIB..."
        )

        mac_table = await self.collect_mac_table(
            interfaces
        )

        print(
            f"      OK - {len(mac_table)} "
            f"dynamic MAC entries"
        )

        return {
            "device": {
                "ip": self.snmp.host,
                "configured_name": self.device_name,
            },

            "system": system,

            "entity": entity,

            "interfaces": interfaces,

            "mac_table": mac_table,
        }


# ============================================================
# Normalization
# ============================================================

def find_chassis(
    entity: dict[str, dict[str, str]],
) -> dict[str, str] | None:

    # Prefer an explicit ENTITY-MIB chassis.
    for item in entity.values():

        if item.get("class") == "3":
            return item

    # Fallback to the first entity carrying a serial.
    for item in entity.values():

        if item.get("serial"):
            return item

    return None


def normalize_entity(
    item: dict[str, str],
) -> dict[str, Any]:
    """
    Convert one raw ENTITY-MIB record to the
    canonical hardware representation.
    """

    class_id = clean_string(
        item.get("class", "")
    )

    class_name = ENTITY_CLASS_NAMES.get(
        class_id,
        "unknown",
    )

    return {
        "index": (
            int(item["index"])
            if str(item.get("index", "")).isdigit()
            else item.get("index", "")
        ),

        "class": class_name,

        "name": clean_string(
            item.get("name", "")
        ),

        "description": clean_string(
            item.get("description", "")
        ),

        "model": clean_string(
            item.get("model", "")
        ),

        "serial": clean_string(
            item.get("serial", "")
        ),

        "parent": (
            int(item["parent"])
            if str(item.get("parent", "")).isdigit()
            else item.get("parent", "")
        ),
    }


def normalize_interfaces(
    interfaces: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Convert IF-MIB dictionary into a stable list.

    Interface identity is ifName.
    """

    normalized = []

    for item in interfaces.values():

        name = clean_string(
            item.get("name", "")
        )

        description = clean_string(
            item.get("description", "")
        )

        alias = clean_string(
            item.get("alias", "")
        )

        ifindex = item.get(
            "ifIndex"
        )

        if isinstance(ifindex, str):
            ifindex = (
                int(ifindex)
                if ifindex.isdigit()
                else ifindex
            )

        speed_mbps = item.get(
            "high_speed_mbps"
        ) or item.get(
            "speed_mbps"
        ) or 0

        normalized.append(
            {
                "if_index": ifindex,

                "name": name,

                "description": description,

                "alias": alias,

                "type": to_int(
                    item.get("type"),
                    0,
                ),

                "mtu": to_int(
                    item.get("mtu"),
                    0,
                ),

                "speed_mbps": float(
                    speed_mbps or 0
                ),

                "mac": normalize_mac(
                    item.get("mac")
                ),

                "admin_status": status_name(
                    IF_ADMIN_STATUS_NAMES,
                    item.get("admin_status"),
                ),

                "oper_status": status_name(
                    IF_OPER_STATUS_NAMES,
                    item.get("oper_status"),
                ),

                "enabled": bool(
                    item.get("enabled")
                ),

                "up": bool(
                    item.get("up")
                ),
            }
        )

    normalized.sort(
        key=lambda item: (
            item.get("name") or "",
            str(item.get("if_index") or ""),
        )
    )

    return normalized


def normalize_mac_table(
    mac_table: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Normalize MAC table records.

    Only learned/dynamic MAC records are accepted.
    """

    normalized = []

    for item in mac_table:

        if item.get("status") != "dynamic":
            continue

        vlan = to_int(
            item.get("vlan"),
            0,
        )

        bridge_port = to_int(
            item.get("bridge_port"),
            0,
        )

        if vlan <= 0:
            continue

        if bridge_port <= 0:
            continue

        mac = normalize_mac(
            item.get("mac")
        )

        if not mac:
            continue

        ifindex = item.get(
            "ifIndex"
        )

        if isinstance(ifindex, str):
            ifindex = (
                int(ifindex)
                if ifindex.isdigit()
                else ifindex
            )

        ifname = clean_string(
            item.get("ifName", "")
        )

        normalized.append(
            {
                "vlan": vlan,

                "mac": mac,

                "interface": ifname,

                "if_index": ifindex,

                "bridge_port": bridge_port,

                "status": "dynamic",
            }
        )

    normalized.sort(
        key=lambda item: (
            item["vlan"],
            item["mac"],
            item.get("interface") or "",
        )
    )

    return normalized


def normalize_inventory(
    raw: dict[str, Any],
) -> dict[str, Any]:
    """
    Convert raw collector output into the canonical
    inventory schema used by future NetBox synchronization.

    This function must not perform SNMP operations.
    It only transforms already-collected data.
    """

    system = raw.get(
        "system",
        {},
    )

    entity = raw.get(
        "entity",
        {},
    )

    interfaces = raw.get(
        "interfaces",
        {},
    )

    mac_table = raw.get(
        "mac_table",
        [],
    )

    # --------------------------------------------------------
    # System
    # --------------------------------------------------------

    sys_name = clean_string(
        system.get("sysName", "")
    )

    configured_name = clean_string(
        raw.get(
            "device",
            {}
        ).get(
            "configured_name",
            ""
        )
    )

    device_name = (
        configured_name
        or sys_name
        or clean_string(
            raw.get(
                "device",
                {}
            ).get(
                "ip",
                ""
            )
        )
    )

    sys_descr = clean_string(
        system.get(
            "sysDescr",
            ""
        )
    )

    sys_object_id = clean_string(
        system.get(
            "sysObjectID",
            ""
        )
    )

    sys_location = clean_string(
        system.get(
            "sysLocation",
            ""
        )
    )

    vendor = detect_vendor(
        sys_object_id
    )

    platform = detect_platform(
        sys_descr
    )

    # --------------------------------------------------------
    # Chassis
    # --------------------------------------------------------

    chassis = find_chassis(
        entity
    )

    chassis_model = ""

    chassis_serial = ""

    chassis_name = ""

    chassis_description = ""

    if chassis:

        chassis_model = clean_string(
            chassis.get(
                "model",
                ""
            )
        )

        chassis_serial = clean_string(
            chassis.get(
                "serial",
                ""
            )
        )

        chassis_name = clean_string(
            chassis.get(
                "name",
                ""
            )
        )

        chassis_description = clean_string(
            chassis.get(
                "description",
                ""
            )
        )

    # --------------------------------------------------------
    # Hardware
    # --------------------------------------------------------

    hardware = []

    for item in entity.values():

        normalized_item = normalize_entity(
            item
        )

        # Keep meaningful physical entities.
        if not any(
            [
                normalized_item["name"],
                normalized_item["description"],
                normalized_item["model"],
                normalized_item["serial"],
            ]
        ):
            continue

        hardware.append(
            normalized_item
        )

    hardware.sort(
        key=lambda item: (
            str(item.get("class") or ""),
            str(item.get("name") or ""),
            str(item.get("index") or ""),
        )
    )

    # --------------------------------------------------------
    # Interfaces
    # --------------------------------------------------------

    normalized_interfaces = (
        normalize_interfaces(
            interfaces
        )
    )

    # --------------------------------------------------------
    # MAC table
    # --------------------------------------------------------

    normalized_mac_table = (
        normalize_mac_table(
            mac_table
        )
    )

    # --------------------------------------------------------
    # Canonical device object
    # --------------------------------------------------------

    normalized_device = {

        "name": device_name,

        "hostname": sys_name,

        "management_ip": clean_string(
            raw.get(
                "device",
                {}
            ).get(
                "ip",
                ""
            )
        ),

        "vendor": vendor,

        "platform": platform,

        "model": chassis_model,

        "serial": chassis_serial,

        "location": sys_location,

        "sys_object_id": sys_object_id,

        "sys_descr": sys_descr,

        "uptime_seconds": uptime_to_seconds(
            system.get(
                "sysUpTime",
                ""
            )
        ),

        "chassis_name": chassis_name,

        "chassis_description": chassis_description,
    }

    return {
        "schema_version": "1.0",

        "device": normalized_device,

        "interfaces": normalized_interfaces,

        "hardware": hardware,

        "mac_table": normalized_mac_table,
    }


# ============================================================
# Display Helpers
# ============================================================

def print_normalized_inventory(
    data: dict[str, Any],
):
    """
    Display the canonical normalized inventory.
    """

    device = data["device"]

    interfaces = data["interfaces"]

    hardware = data["hardware"]

    mac_table = data["mac_table"]

    print()
    print()
    print("#" * 70)
    print("NORMALIZED INVENTORY")
    print("#" * 70)

    # ========================================================
    # DEVICE
    # ========================================================

    print()
    print("DEVICE")
    print("-" * 70)

    print(
        f"Schema Version    : "
        f"{data.get('schema_version', '')}"
    )

    print(
        f"Name              : "
        f"{device.get('name', '')}"
    )

    print(
        f"Hostname          : "
        f"{device.get('hostname', '')}"
    )

    print(
        f"Management IP     : "
        f"{device.get('management_ip', '')}"
    )

    print(
        f"Vendor            : "
        f"{device.get('vendor', '')}"
    )

    print(
        f"Platform          : "
        f"{device.get('platform', '')}"
    )

    print(
        f"Model             : "
        f"{device.get('model', '')}"
    )

    print(
        f"Serial            : "
        f"{device.get('serial', '')}"
    )

    print(
        f"Location          : "
        f"{device.get('location', '')}"
    )

    print(
        f"SysObjectID       : "
        f"{device.get('sys_object_id', '')}"
    )

    print(
        f"Uptime Seconds    : "
        f"{device.get('uptime_seconds', 0)}"
    )

    # ========================================================
    # HARDWARE
    # ========================================================

    print()
    print("HARDWARE")
    print("-" * 70)

    print(
        f"Total normalized hardware: "
        f"{len(hardware)}"
    )

    # ========================================================
    # INTERFACES
    # ========================================================

    print()
    print("INTERFACES")
    print("-" * 70)

    print(
        f"Total normalized interfaces: "
        f"{len(interfaces)}"
    )

    header = (
        f"{'Name':<28} "
        f"{'ifIndex':>12} "
        f"{'Admin':<12} "
        f"{'Oper':<20} "
        f"{'Speed':>12} "
        f"{'MAC':<18}"
    )

    print(header)
    print("-" * 110)

    for item in interfaces:

        speed = item.get(
            "speed_mbps",
            0,
        )

        print(
            f"{str(item.get('name') or '-'):28.28} "
            f"{str(item.get('if_index') or '-'):>12} "
            f"{str(item.get('admin_status') or '-'):12.12} "
            f"{str(item.get('oper_status') or '-'):20.20} "
            f"{str(speed):>12} "
            f"{str(item.get('mac') or '-'):18}"
        )

    # ========================================================
    # MAC TABLE
    # ========================================================

    print()
    print("MAC TABLE")
    print("-" * 70)

    print(
        f"Total normalized dynamic MAC entries: "
        f"{len(mac_table)}"
    )

    for item in mac_table:

        print(
            f"VLAN={item['vlan']} "
            f"MAC={item['mac']} "
            f"Interface={item.get('interface') or '-'} "
            f"ifIndex={item.get('if_index') or '-'} "
            f"BridgePort={item['bridge_port']}"
        )

    print()
    print("#" * 70)


# ============================================================
# Raw Inventory Display
# ============================================================

def print_inventory(
    data: dict[str, Any],
):

    system = data["system"]

    entity = data["entity"]

    interfaces = data["interfaces"]

    mac_table = data["mac_table"]

    chassis = find_chassis(entity)

    print()
    print()
    print("#" * 70)
    print("DEVICE INVENTORY")
    print("#" * 70)

    # ========================================================
    # DEVICE
    # ========================================================

    print()
    print("DEVICE")
    print("-" * 70)

    print(
        f"IP Address       : "
        f"{data['device']['ip']}"
    )

    print(
        f"Configured Name  : "
        f"{data['device']['configured_name']}"
    )

    print(
        f"SysName          : "
        f"{system.get('sysName', '')}"
    )

    print(
        f"Location         : "
        f"{system.get('sysLocation', '')}"
    )

    print(
        f"SysObjectID      : "
        f"{system.get('sysObjectID', '')}"
    )

    print(
        f"SysUpTime        : "
        f"{system.get('sysUpTime', '')}"
    )

    # ========================================================
    # SYSTEM DESCRIPTION
    # ========================================================

    print()
    print("SYSTEM DESCRIPTION")
    print("-" * 70)

    print(
        system.get("sysDescr", "")
    )

    # ========================================================
    # CHASSIS
    # ========================================================

    print()
    print("CHASSIS")
    print("-" * 70)

    if chassis:

        print(
            f"Index            : "
            f"{chassis.get('index', '')}"
        )

        print(
            f"Name             : "
            f"{chassis.get('name', '')}"
        )

        print(
            f"Description      : "
            f"{chassis.get('description', '')}"
        )

        print(
            f"Model            : "
            f"{chassis.get('model', '')}"
        )

        print(
            f"Serial Number    : "
            f"{chassis.get('serial', '')}"
        )

    else:

        print(
            "Chassis information not found."
        )

    # ========================================================
    # PHYSICAL ENTITIES
    # ========================================================

    print()
    print("PHYSICAL ENTITIES")
    print("-" * 70)

    for item in entity.values():

        name = item.get(
            "name",
            "",
        )

        description = item.get(
            "description",
            "",
        )

        serial = item.get(
            "serial",
            "",
        )

        model = item.get(
            "model",
            "",
        )

        class_id = item.get(
            "class",
            "",
        )

        class_name = ENTITY_CLASS_NAMES.get(
            class_id,
            class_id,
        )

        if not any(
            [
                name,
                description,
                serial,
                model,
            ]
        ):
            continue

        print(
            f"[{item['index']}] "
            f"{class_name:12} "
            f"{name:30} "
            f"Model={model or '-':25} "
            f"Serial={serial or '-'}"
        )

    # ========================================================
    # INTERFACES
    # ========================================================

    print()
    print("INTERFACES")
    print("-" * 70)

    header = (
        f"{'Index':>12} "
        f"{'Name':<24} "
        f"{'Admin':<8} "
        f"{'Oper':<8} "
        f"{'Speed':>10} "
        f"{'MAC':<18} "
        f"Description"
    )

    print(header)

    print("-" * 125)

    for item in interfaces.values():

        name = (
            item.get("name")
            or item.get("description")
            or "-"
        )

        admin = (
            "up"
            if item.get("enabled")
            else "down"
        )

        oper = (
            "up"
            if item.get("up")
            else "down"
        )

        speed = (
            item.get("high_speed_mbps")
            or item.get("speed_mbps")
        )

        if speed:

            if speed >= 1000:

                speed_text = (
                    f"{speed / 1000:g} G"
                )

            else:

                speed_text = (
                    f"{speed:g} M"
                )

        else:

            speed_text = "-"

        mac = (
            item.get("mac")
            or "-"
        )

        description = (
            item.get("alias")
            or item.get("description")
            or "-"
        )

        print(
            f"{str(item.get('ifIndex', '-')):>12} "
            f"{name[:24]:<24} "
            f"{admin:<8} "
            f"{oper:<8} "
            f"{speed_text:>10} "
            f"{mac:<18} "
            f"{description}"
        )

    # ========================================================
    # MAC TABLE
    # ========================================================

    print()
    print("MAC ADDRESS TABLE")
    print("-" * 70)

    print(
        f"{'VLAN':>6} "
        f"{'MAC':<18} "
        f"{'BridgePort':>11} "
        f"{'ifIndex':>12} "
        f"{'Interface':<24} "
        f"{'Status'}"
    )

    print("-" * 100)

    for item in mac_table:

        print(
            f"{item['vlan']:>6} "
            f"{item['mac']:<18} "
            f"{item['bridge_port']:>11} "
            f"{str(item.get('ifIndex') or '-'):>12} "
            f"{str(item.get('ifName') or '-'):<24} "
            f"{item['status']}"
        )

    print()
    print(
        f"Total Dynamic MAC Entries: "
        f"{len(mac_table)}"
    )

    print()
    print("#" * 70)

    print(
        "DRY-RUN ONLY - "
        "NO NETBOX CHANGES WERE MADE"
    )

    print("#" * 70)
    print()


# ============================================================
# Main
# ============================================================

async def main():

    snmp = SNMPClient(
        host=DEVICE_IP,
        community=SNMP_COMMUNITY,
        timeout=SNMP_TIMEOUT,
        retries=SNMP_RETRIES,
    )

    await snmp.connect()

    collector = InventoryCollector(
        snmp,
        DEVICE_NAME,
    )

    try:

        raw_inventory = (
            await collector.collect()
        )

        # ----------------------------------------------------
        # Raw output
        # ----------------------------------------------------

        print_inventory(
            raw_inventory
        )

        # ----------------------------------------------------
        # Normalized output
        # ----------------------------------------------------

        normalized_inventory = (
            normalize_inventory(
                raw_inventory
            )
        )

        print_normalized_inventory(
            normalized_inventory
        )

    finally:

        snmp.engine.close_dispatcher()


if __name__ == "__main__":

    try:

        asyncio.run(main())

    except KeyboardInterrupt:

        print(
            "\nInterrupted."
        )

    except Exception as exc:

        print()
        print("=" * 70)
        print("ERROR")
        print("=" * 70)
        print(exc)
        print()

        sys.exit(1)
