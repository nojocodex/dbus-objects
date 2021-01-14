# SPDX-License-Identifier: MIT

import xml.etree.ElementTree as ET

import pytest
import xmldiff.main

from dbus_objects.object import DBusObject, DBusObjectException, dbus_method, DBusSignal


def test_dbus_object(obj):
    assert obj.is_dbus_object
    assert obj.dbus_name == 'ExampleObject'
    assert 'ExampleMethod' in [
        descriptor.name
        for _method, descriptor in obj.get_dbus_methods()
    ]


def test_call(obj_methods):
    for method, descriptor in obj_methods:
        if descriptor.name == 'ExampleMethod':
            assert method() == 'test'
            return
    assert False  # pragma: no cover


def test_signature(obj_methods):
    for _method, descriptor in obj_methods:
        if descriptor.name == 'ExampleMethod':
            assert descriptor.signature == ('', 's')
            return
    assert False  # pragma: no cover


def test_signature_multiple_return(obj_methods):
    for _method, descriptor in obj_methods:
        if descriptor.name == 'Multiple':
            assert descriptor.signature == ('s', 'ii')
            return
    assert False  # pragma: no cover


def test_no_interface():
    class TestObject(DBusObject):
        @dbus_method()
        def method() -> None:
            pass  # pragma: no cover

    with pytest.raises(DBusObjectException):
        list(TestObject().get_dbus_methods())


def test_property(obj_properties):
    for getter, setter, descriptor in obj_properties:
        if descriptor.name == 'Prop':
            assert descriptor.signature == 's'
            setter('something else')
            assert getter() == 'something else'
            return
    assert False  # pragma: no cover


def test_decorated_signal(obj_signals, obj):
    DBusSignal.queue.clear()
    for emitter, descriptor in obj_signals:
        if descriptor.name == 'DecoratedSignal':
            assert descriptor.signature == 'si'
            assert list(descriptor._signature.names) == ['val1', 'val2']
            assert len(DBusSignal.queue) == 0
            emitter('a', 1)
            assert len(DBusSignal.queue) == 1
            assert DBusSignal.queue[0] == (descriptor.name, descriptor.signature, ('a', 1), obj, descriptor.interface)
            return
    assert False  # pragma: no cover


def test_empty_signal(obj_signals, obj):
    DBusSignal.queue.clear()
    for emitter, descriptor in obj_signals:
        if descriptor.name == 'EmptySignal':
            assert descriptor.signature == ''
            assert descriptor._signature.names == None
            assert len(DBusSignal.queue) == 0
            emitter()
            assert len(DBusSignal.queue) == 1
            assert DBusSignal.queue[0] == (descriptor.name, descriptor.signature, (), obj, descriptor.interface)
            return
    assert False  # pragma: no cover


def test_unnamed_signal(obj_signals, obj):
    DBusSignal.queue.clear()
    for emitter, descriptor in obj_signals:
        if descriptor.name == 'UnnamedSignal':
            assert descriptor.signature == 'si'
            assert descriptor._signature.names == None
            assert len(DBusSignal.queue) == 0
            emitter('a', 1)
            assert len(DBusSignal.queue) == 1
            assert DBusSignal.queue[0] == (descriptor.name, descriptor.signature, ('a', 1), obj, descriptor.interface)
            return
    assert False  # pragma: no cover


def test_named_signal(obj_signals, obj):
    DBusSignal.queue.clear()
    for emitter, descriptor in obj_signals:
        if descriptor.name == 'NamedSignal':
            assert descriptor.signature == 'si'
            assert list(descriptor._signature.names) == ['val1', 'val2']
            assert len(DBusSignal.queue) == 0
            emitter('a', 1)
            assert len(DBusSignal.queue) == 1
            assert DBusSignal.queue[0] == (descriptor.name, descriptor.signature, ('a', 1), obj, descriptor.interface)
            return
    assert False  # pragma: no cover


def test_method_xml(obj_methods):
    for _method, descriptor in obj_methods:
        if descriptor.name == 'ExampleMethod':
            assert not xmldiff.main.diff_texts(
                ET.tostring(descriptor.xml).decode(),
                (
                    '<method name="ExampleMethod"><arg direction="out" '
                    f'type="{descriptor.signature[1]}" /></method>'
                )
            )
            return
    assert False  # pragma: no cover


def test_property_xml(obj_properties):
    for _getter, _setter, descriptor in obj_properties:
        if descriptor.name == 'Prop':
            assert not xmldiff.main.diff_texts(
                ET.tostring(descriptor.xml).decode(),
                (
                    f'<property name="Prop" type="{descriptor.signature}" '
                    'access="readwrite" />'
                )
            )
            return
    assert False  # pragma: no cover


def test_signal_xml(obj_signals):
    expected = { 'DecoratedSignal':
                    f'<signal name="DecoratedSignal">'
                    f'<arg type="s" name="val1" />'
                    f'<arg type="i" name="val2" />'
                    f'</signal>',
                 'EmptySignal':
                    f'<signal name="EmptySignal" />',
                 'UnnamedSignal':
                    f'<signal name="UnnamedSignal">'
                    f'<arg type="s" />'
                    f'<arg type="i" />'
                    f'</signal>',
                 'NamedSignal':
                    f'<signal name="NamedSignal">'
                    f'<arg type="s" name="val1" />'
                    f'<arg type="i" name="val2" />'
                    f'</signal>',
               }
    must_see = list(expected.keys())

    for _emitter, descriptor in obj_signals:
        if descriptor.name in expected:
            assert not xmldiff.main.diff_texts(
                ET.tostring(descriptor.xml).decode(), expected[descriptor.name]
            )
            must_see.remove(descriptor.name)
    assert len(must_see) == 0

