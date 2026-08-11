"""Small network profile and strict account-address validation."""

from dataclasses import dataclass


BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


@dataclass(frozen=True)
class NetworkProfile:
    chain_family: str
    chain_id: str
    account_hrp: str = "g"
    account_payload_length: int = 20
    native_denom: str = "ugnot"
    native_symbol: str = "GNOT"
    native_decimals: int = 6


def gno_profile(chain_id: str) -> NetworkProfile:
    return NetworkProfile(chain_family="gno", chain_id=chain_id)


def _polymod(values: list[int]) -> int:
    generators = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    checksum = 1
    for value in values:
        top = checksum >> 25
        checksum = ((checksum & 0x1FFFFFF) << 5) ^ value
        for index, generator in enumerate(generators):
            if (top >> index) & 1:
                checksum ^= generator
    return checksum


def _expand_hrp(hrp: str) -> list[int]:
    return [ord(char) >> 5 for char in hrp] + [0] + [ord(char) & 31 for char in hrp]


def _convert_bits(values: list[int], from_bits: int, to_bits: int, pad: bool) -> bytes | None:
    accumulator = bits = 0
    output = bytearray()
    for value in values:
        if value < 0 or value >> from_bits:
            return None
        accumulator = (accumulator << from_bits) | value
        bits += from_bits
        while bits >= to_bits:
            bits -= to_bits
            output.append((accumulator >> bits) & ((1 << to_bits) - 1))
    if pad and bits:
        output.append((accumulator << (to_bits - bits)) & ((1 << to_bits) - 1))
    elif bits >= from_bits or ((accumulator << (to_bits - bits)) & ((1 << to_bits) - 1)):
        return None
    return bytes(output)


def validate_account_address(address: str, profile: NetworkProfile) -> bool:
    if not isinstance(address, str) or not 8 <= len(address) <= 90 or address != address.lower():
        return False
    if any(ord(char) < 33 or ord(char) > 126 for char in address):
        return False
    separator = address.rfind("1")
    if separator < 1 or separator + 7 > len(address) or address[:separator] != profile.account_hrp:
        return False
    try:
        values = [BECH32_CHARSET.index(char) for char in address[separator + 1:]]
    except ValueError:
        return False
    if _polymod(_expand_hrp(profile.account_hrp) + values) != 1:
        return False
    payload = _convert_bits(values[:-6], 5, 8, False)
    return payload is not None and len(payload) == profile.account_payload_length
