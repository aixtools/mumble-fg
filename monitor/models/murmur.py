from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class MumbleUser:
    """
    Data needed to create or manage a Murmur user.
    """
    name: str
    comment: str
    password_clear: str
    password_salt_hex: str
    password_hash_hex: str


@dataclass(frozen=True)
class MumbleChannel:
    """
    Mumble channel layout specification for bootstrap operations.
    """
    name: str
    children: List["MumbleChannel"]
