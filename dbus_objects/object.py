# SPDX-License-Identifier: MIT

from __future__ import annotations

import itertools
import types
import xml.etree.ElementTree as ET

from typing import Any, Callable, Generator, List, Optional, Sequence, Tuple

import dbus_objects.signature


class _DBusDescriptorBase():
    '''
    Base descriptor class that implements DBus interface objects

    Having a descriptor class allows us to save data on the method owner and
    allows us to easily implement things like properties.
    '''
    def __init__(
        self,
        interface: Optional[str] = None,
        name: Optional[str] = None,
    ) -> None:
        self._interface_orig = interface
        self._interface = self._interface_orig
        self._name = dbus_objects.signature.dbus_case(name) if name else None
        self._list_name: Optional[str] = None

    @property
    def interface(self) -> str:
        if not self._interface:
            raise ValueError("Interface hasn't been set yet")
        return self._interface

    @property
    def name(self) -> str:
        if not self._name:
            raise ValueError("Name hasn't been set yet")
        return self._name

    def register_interface(self, obj: Any) -> None:
        if not self._interface_orig:
            if obj.default_interface_root:
                self._interface = '.'.join([obj.default_interface_root, obj._dbus_name])
            else:
                raise DBusObjectException(f'Missing interface in DBus method: {self.name}')

    def __set_name__(self, obj_type: Any, name: str) -> None:
        if not issubclass(obj_type, DBusObject):
            raise DBusObjectException(
                f'The {self.__class__.__name__} decorator can only be used inside DBusObject'
            )
        self._owner = obj_type
        self._descriptor_name = name

        # get the method list for our type and initialize it if necessary
        assert self._list_name
        self._method_list = getattr(self._owner, self._list_name) or []
        setattr(self._owner, self._list_name, self._method_list)

        # add ourselves to the owner method list
        self._method_list.append((self._descriptor_name, self))

    def __get__(self, obj: Any, obj_type: Any = None) -> Any:
        raise NotImplementedError('This should be implemented in a subclass')


class _DBusMethodBase(_DBusDescriptorBase):
    '''
    Base descriptor class that implements DBus interface objects based on a method
    '''
    def __init__(
        self,
        func: Callable[..., Any],
        interface: Optional[str] = None,
        name: Optional[str] = None,
        return_names: Optional[Sequence[str]] = None,
        multiple_returns: bool = False,
    ) -> None:
        super().__init__(interface, name if name else func.__name__)
        self._func = func
        self._return_names = return_names or []
        self._multiple_returns = multiple_returns

        self._input_signature = dbus_objects.signature.DBusSignature.from_parameters(
            self._func,
        )
        self._output_signature = dbus_objects.signature.DBusSignature.from_return(
            self._func,
            self._return_names,
            self._multiple_returns,
        )

    def __get__(self, obj: Any, obj_type: Any = None) -> Any:
        if obj is None:
            return self._func
        # construct interface from obj
        self.register_interface(obj)
        return types.MethodType(self._func, obj)


class _DBusMethod(_DBusMethodBase):
    '''
    Descriptor class that implements a DBus method
    '''
    def __init__(
        self,
        func: Callable[..., Any],
        interface: Optional[str] = None,
        name: Optional[str] = None,
        return_names: Optional[Sequence[str]] = None,
        multiple_returns: bool = False,
    ) -> None:
        super().__init__(func, interface, name, return_names, multiple_returns)
        self._list_name = '_dbus_methods'

    @property
    def signature(self) -> Tuple[str, str]:
        return str(self._input_signature), str(self._output_signature)

    @property
    def xml(self) -> ET.Element:
        if not self._input_signature or not self._output_signature:
            raise ValueError("Signature hasn't been set yet")

        xml = ET.Element('method', {'name': self.name})

        for direction, signature, names in (
            ('in', list(self._input_signature), self._input_signature.names or []),
            ('out', list(self._output_signature), self._output_signature.names or []),
        ):
            for name, sig in itertools.zip_longest(names, signature):
                data = {
                    'direction': direction,
                    'type': sig,
                }
                if name:
                    data['name'] = name
                ET.SubElement(xml, 'arg', data)

        # TODO: export documentation
        return xml


class _DBusProperty(_DBusMethodBase):
    '''
    Descriptor class that implements a DBus property

    Works like a simpler :meth:`property`
    '''
    def __init__(
        self,
        func: Callable[..., Any],
        interface: Optional[str] = None,
        name: Optional[str] = None,
        return_names: Optional[Sequence[str]] = None,
        multiple_returns: bool = False,
    ) -> None:
        super().__init__(func, interface, name, return_names, multiple_returns)
        self._list_name = '_dbus_properties'
        self._setter: Optional[Callable[[Any, Any], Any]] = None
        # TODO: Verify signature
        # TODO: Allow emiting a signal when the value changes

    @property
    def signature(self) -> str:
        return str(self._output_signature)

    @property
    def xml(self) -> ET.Element:
        if not self._input_signature or not self._output_signature:
            raise ValueError("Signature hasn't been set yet")

        xml = ET.Element('property', {
            'name': self.name,
            'type': self.signature,
            'access': 'read' if not self._setter else 'readwrite',
        })

        # TODO: Support write-only properties
        # TODO: Export documentation
        return xml

    def __get__(self, obj: Any, obj_type: Any = None) -> Any:
        if obj is None:
            return self._func(obj)
        return self._func(obj)

    def __set__(self, obj: Any, value: Any) -> None:
        if self._setter is None:
            raise AttributeError(f'{self._descriptor_name} has no setter')
        self._setter(obj, value)

    def setter(self, value: Callable[[Any, Any], Any]) -> _DBusProperty:
        '''
        Decorator that registers the method as the property setter

        Works just like the built-in :meth:`property`
        '''
        self._setter = value
        return self


class DBusSignal(_DBusDescriptorBase):
    ''' Descriptor class to support signal message generation by DBus objects.

        This class may be used to define the signals that may be sent by a
        :class:`DBusObject`-derived class. To do so, either use the decorator
        :func:`dbus_signal()` defined below on a method in the class, or just
        assign an instance of this class to an attribute in the target class.
        Calling the decorated method or attribute will result in a signal being
        added to the global queue, to be handled by the I/O integration at some
        later time.

        This class handles generating the signal's body, which is just a tuple
        of values, and holds the signal's signature, which describes the types
        and (optionally) names of the body tuple's elements.

        The body generation and signature may be initialized by constructing an
        instance of this class and providing one of the following:

         - a function that generates the signal body, in which case the signal's
           signature is taken from the function's arguments. Note that this
           requires the function's arguments to have type annotations.
         - zero or more *types* as positional arguments, in which case these
           types form the signal's signature. In this case, the elements of the
           signature will be unnamed. When emitting a signal, the signal member
           must be called with positional arguments whose values match the
           signature and that will be returned directly as the signal body; or
         - one or more keyword arguments whose values are *types*, which is
           handled identically to the positional case above, except that the
           signal signature attributes will be named by the keyword arguments'
           names.

        Attributes:
         queue (List):          (Class attribute) global queue of signals that
                                are waiting to be emitted.
         signature (str):       The signal's signature as a string.
         xml (str):             The signal's introspection XML string.
    '''

    # The global signal queue.
    #
    queue: List[Tuple[dbus_objects.object.DBusObject, str, str, Tuple[Any, ...]]] = []


    # --------------------------------------------------------------------------
    #
    # Constructor.
    #

    def __init__(self, *args, func: Callable[..., Any] = None, interface: Optional[str] = None, name: Optional[str] = None, **kwargs):
        ''' Constructor.

            Args:
             func (Callable):   The function that will generate the signal's
                                body tuple.
             interface (str):   The interface of which this signal is part.
             name (str):        The object name of which this signal is part.
             *args:             Positional arguments specifying the types of
                                the signal's body tuple's elements.
             **kwargs:          Keyword arguments specifying the types of the
                                signal's body tuple's elements.
        '''

        super().__init__(interface, name)

        # Ensure at most one of our sources of wrapped function & signature was
        #  provided. Note that if none of these sources were provided, the
        #  signal body will just be empty.
        #
        if [bool(func), bool(args), bool(kwargs)].count(True) > 1:
            raise ValueError('Must specify at most one of function, positional arguments and keyword arguments for a DBus signal')

        # Get `dbus_objects` to magically populate the signal list.
        #
        self._list_name = '_dbus_signals'

        # If a function was provided (e.g. by the :func:`dbus_signal()` decorator
        #  below), wrap it. Otherwise, use a default implementation that just
        #  returns its (positional) arguments minus the first one (`self`).
        #
        self._func = func or (lambda *args: args[1:])

        # Set up our signature.
        #
        if func:
            self._signature = dbus_objects.signature.DBusSignature.from_parameters(func)
        elif args:
            self._signature = dbus_objects.signature.DBusSignature(args, None)
        elif kwargs:
            self._signature = dbus_objects.signature.DBusSignature(kwargs.values(), kwargs.keys())
        else:
            self._signature = dbus_objects.signature.DBusSignature([], None)


    # --------------------------------------------------------------------------
    #
    # Properties.
    #

    @property
    def signature(self) -> str:
        ''' The DBus signature for this signal as a string.
        '''
        return str(self._signature)


    @property
    def xml(self) -> ET.Element:
        ''' The DBus introspection XML for this signal.
        '''

        if not self._signature:
            raise ValueError("Signature hasn't been set yet")

        xml = ET.Element('signal', {'name': self.name})

        names = self._signature.names or []

        for name, sigtype in itertools.zip_longest(names, self.signature):
            data = { 'type': sigtype }

            if name:
                data['name'] = name

            ET.SubElement(xml, 'arg', data)

        return xml


    # --------------------------------------------------------------------------
    #
    # Descriptor protocol.
    #

    def __set_name__(self, obj_type: Any, name: str) -> None:
        super().__set_name__(obj_type, name)

        # Default the signal name to the name of the attribute to which the
        #  descriptor is assigned.
        #
        if self._name is None:
            self._name = dbus_objects.signature.dbus_case(name)


    def __get__(self, obj: Any, obj_type: Any = None) -> Any:
        if not obj:
            return self._func

        self.register_interface(obj)

        return lambda *args: self.queue.append( (self.name, self.signature, self._func(obj, *args), obj, self.interface) )


def dbus_method(
    interface: Optional[str] = None,
    name: Optional[str] = None,
    return_names: Optional[Sequence[str]] = None,
    multiple_returns: bool = False,
) -> Callable[[Callable[..., Any]], _DBusMethod]:
    '''
    This decorator exports a function as a DBus method

    The function must have type annotations, they will be used to resolve the
    method signature.

    The function name will be used as the DBus method name unless otherwise
    specified in the arguments.

    :param interface: DBus interface name
    :param name: DBus method name
    :param return_names: Names of the return arguments
    :param multiple_returns: Returns multiple parameters
    '''
    def decorator(func: Callable[..., Any]) -> _DBusMethod:
        return _DBusMethod(func, interface, name, return_names, multiple_returns)
    return decorator


def dbus_property(
    interface: Optional[str] = None,
    name: Optional[str] = None,
    return_names: Optional[Sequence[str]] = None,
    multiple_returns: bool = False,
) -> Callable[[Callable[..., Any]], _DBusProperty]:
    '''
    This decorator exports a method as a DBus property

    Works just like :meth:`dbus_method` and :meth:`property`

    :param interface: DBus interface name
    :param name: DBus method name
    :param return_names: Names of the return arguments
    :param multiple_returns: Returns multiple parameters
    '''
    def decorator(func: Callable[..., Any]) -> _DBusProperty:
        return _DBusProperty(func, interface, name, return_names, multiple_returns)
    return decorator


def dbus_signal(interface: Optional[str] = None, name: Optional[str] = None) -> Callable[[Callable[..., Any]], DBusSignal]:
    '''
    Decorator for callables that generate a DBus signal message.

    Works just like :meth:`dbus_method`, except that calling the decorated
    method will queue a signal to be sent and return `None`.

    :param interface: DBus interface name
    :param name: DBus signal name. Defaults to the decorated function's name.
    '''
    def decorator(func: Callable[..., Any]) -> DBusSignal:
        return DBusSignal(func = func, interface = interface, name = name or func.__name__)

    return decorator


_DBusMethodTupleInternal = Tuple[str, _DBusMethod]  # method name, method descriptor
_DBusMethodTuple = Tuple[Callable[..., Any], _DBusMethod]  # method, method descriptor

_DBusPropertyTupleInternal = Tuple[str, _DBusProperty]  # property name, property descriptor
_DBusPropertyTuple = Tuple[
    Callable[[], Any],
    Callable[[Any], Any],
    _DBusProperty
]  # getter, setter, descriptor

_DBusSignalTupleInternal = Tuple[str, DBusSignal] # signal name, signal descriptor
_DBusSignalTuple = Tuple[Callable[..., Any], DBusSignal] # signal queuing function, descriptor

class DBusObject():
    '''
    This class represents a DBus object. It should be subclassed and to export
    DBus methods, you must define typed functions with the
    :meth:`dbus_objects.object.dbus_object` decorator.
    '''
    # type -> method name list
    _dbus_methods: Optional[List[_DBusMethodTupleInternal]] = None
    _dbus_properties: Optional[List[_DBusPropertyTupleInternal]] = None
    _dbus_signals: Optional[List[_DBusSignalTupleInternal]] = None


    def __init__(self, name: Optional[str] = None, default_interface_root: Optional[str] = None):
        '''
        The class name will be used as the DBus object name unless otherwise
        specified in the arguments.

        :param name: DBus object name
        '''
        self.is_dbus_object = True
        self._dbus_name = dbus_objects.signature.dbus_case(
            name if name else type(self).__name__
        )
        self.default_interface_root = default_interface_root

    @property
    def dbus_name(self) -> str:
        return self._dbus_name

    def get_dbus_methods(self) -> Generator[_DBusMethodTuple, _DBusMethodTuple, None]:
        '''
        Generator that provides the DBus methods
        '''
        if not self._dbus_methods:
            return
        for method_name, descriptor in self._dbus_methods:
            yield getattr(self, method_name), descriptor

    def get_dbus_properties(self) -> Generator[_DBusPropertyTuple, _DBusPropertyTuple, None]:
        '''
        Generator that provides the DBus properties
        '''
        if not self._dbus_properties:
            return
        for property_name, descriptor in self._dbus_properties:
            descriptor.register_interface(self)  # explicitely register the interface
            yield (
                lambda: getattr(self, property_name),
                lambda value: setattr(self, property_name, value),
                descriptor,
            )

    def get_dbus_signals(self) -> Generator[_DBusSignalTuple, _DBusSignalTuple, None]:
        if not self._dbus_signals:
            return
        for signal_name, descriptor in self._dbus_signals:
            yield getattr(self, signal_name), descriptor



class DBusObjectException(Exception):
    pass
