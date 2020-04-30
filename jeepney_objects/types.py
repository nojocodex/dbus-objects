# SPDX-License-Identifier: MIT

import typing


Byte = typing.TypeVar('Byte', int, int)
UInt16 = typing.TypeVar('UInt16', int, int)
UInt32 = typing.TypeVar('UInt32', int, int)
UInt64 = typing.TypeVar('UInt64', int, int)
Int16 = typing.TypeVar('Int16', int, int)
Int32 = typing.TypeVar('Int32', int, int)
Int64 = typing.TypeVar('Int64', int, int)
Signature = typing.TypeVar('Signature', str, bytes)


class DBusMethod(typing.Protocol):
    is_dbus_method: typing.Literal[True]
    dbus_interface: str
    dbus_method_name: str
    dbus_signature: typing.Tuple[str, str]  # in, out
    dbus_parameters: typing.Dict[str, str]  # name -> signature
    __call__: typing.Callable[..., typing.Any]
