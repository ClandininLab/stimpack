"""
Unit tests for how a screen resolves a stimulus name to a class.

Resolution used to be a scan of ``BaseProgram.__subclasses__()``. That registry is process-global,
keyed only by class name, and cannot be pruned -- a class stays in it for as long as anything holds
a reference, and a loaded stimulus instance does. So re-importing a stimulus module, which every
client does when it connects, left two classes of the same name and ``load_stim`` refused to choose
between them.

These cover the explicit registry that replaced it. No GL context is needed: the registry is
ordinary bookkeeping, so StimDisplay is built with ``__new__``.
"""
import os
import warnings

import pytest

pytest.importorskip("moderngl")
pytest.importorskip("PyQt6")

from stimpack.visual_stim.framework import StimDisplay

pytestmark = pytest.mark.unit


CUSTOM_MODULE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), 'examples', 'example_custom_module')


@pytest.fixture
def display():
    """A StimDisplay with only its stimulus registry initialized."""
    d = StimDisplay.__new__(StimDisplay)
    d.imported_stim_module_names = []
    d.imported_stim_module_paths = {}
    d.imported_stim_module_classes = {}
    d.stim_classes = {}
    d._rebuild_stim_registry()
    yield d
    for barcode in list(d.imported_stim_module_names):
        d.unload_stim_module([barcode])


def write_module(tmp_path, name, class_names):
    """A stimulus module directory defining the named BaseProgram subclasses."""
    directory = tmp_path / name
    directory.mkdir()
    body = 'from stimpack.visual_stim.base import BaseProgram\n'
    for class_name in class_names:
        body += f'\n\nclass {class_name}(BaseProgram):\n    origin = {name!r}\n'
    (directory / 'stimuli.py').write_text(body)
    return str(directory)


# --- the built-ins ------------------------------------------------------------------------------

def test_builtin_stimuli_are_registered(display):
    assert 'MovingPatch' in display.stim_classes
    assert 'Checkerboard' in display.stim_classes
    assert display.stim_classes['MovingPatch'].__module__.startswith('stimpack.')


def test_importing_adds_a_module_s_stimuli(display, tmp_path):
    path = write_module(tmp_path, 'mod_a', ['StimA'])
    assert 'StimA' not in display.stim_classes

    display.import_stim_module(path)

    assert display.stim_classes['StimA'].origin == 'mod_a'
    assert len(display.imported_stim_module_names) == 1


def test_only_the_module_s_own_classes_are_attributed_to_it(display, tmp_path):
    """The module imports BaseProgram, and other stimuli may already be loaded; neither should be
    recorded as having come from this module."""
    path = write_module(tmp_path, 'mod_a', ['StimA'])
    display.import_stim_module(path)

    barcode = display.imported_stim_module_names[0]
    assert set(display.imported_stim_module_classes[barcode]) == {'StimA'}


# --- re-importing is a reload -------------------------------------------------------------------

def test_reimporting_the_same_path_replaces_rather_than_duplicates(display, tmp_path):
    """The regression: every client imports its labpack's stimuli on connect, and the second one
    used to fail with '2 stimulus candidates found'."""
    path = write_module(tmp_path, 'mod_a', ['StimA'])
    display.import_stim_module(path)
    first = display.stim_classes['StimA']

    display.import_stim_module(path)

    assert len(display.imported_stim_module_names) == 1      # not two
    assert display.stim_classes['StimA'] is not first        # the fresh one


def test_reimporting_picks_up_an_edit(display, tmp_path):
    """Reload semantics are the point: the code on disk now is the code that runs. Skipping the
    second import would be quieter but would leave a stale stimulus running."""
    path = write_module(tmp_path, 'mod_a', ['StimA'])
    display.import_stim_module(path)
    assert display.stim_classes['StimA'].origin == 'mod_a'

    (tmp_path / 'mod_a' / 'stimuli.py').write_text(
        'from stimpack.visual_stim.base import BaseProgram\n\n\n'
        'class StimA(BaseProgram):\n    origin = "edited"\n')
    display.import_stim_module(path)

    assert display.stim_classes['StimA'].origin == 'edited'


def test_a_relative_and_absolute_path_are_the_same_module(display, tmp_path, monkeypatch):
    path = write_module(tmp_path, 'mod_a', ['StimA'])
    display.import_stim_module(path)
    display.import_stim_module(os.path.join(path, '.', ''))

    assert len(display.imported_stim_module_names) == 1


# --- shadowing ------------------------------------------------------------------------------------

def test_a_later_module_shadows_an_earlier_one(display, tmp_path):
    display.import_stim_module(write_module(tmp_path, 'mod_a', ['Shared']))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        display.import_stim_module(write_module(tmp_path, 'mod_b', ['Shared']))

    assert display.stim_classes['Shared'].origin == 'mod_b'
    assert any('shadows' in str(w.message) for w in caught)


def test_a_module_may_shadow_a_builtin_but_says_so(display, tmp_path):
    builtin = display.stim_classes['MovingPatch']
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        display.import_stim_module(write_module(tmp_path, 'mod_a', ['MovingPatch']))

    assert display.stim_classes['MovingPatch'] is not builtin
    assert display.stim_classes['MovingPatch'].origin == 'mod_a'
    assert any('MovingPatch' in str(w.message) and 'shadows' in str(w.message) for w in caught)


def test_unloading_restores_what_was_shadowed(display, tmp_path):
    builtin = display.stim_classes['MovingPatch']
    display.import_stim_module(write_module(tmp_path, 'mod_a', ['MovingPatch']))

    display.unload_stim_module([display.imported_stim_module_names[-1]])

    assert display.stim_classes['MovingPatch'] is builtin


def test_unloading_one_of_two_restores_the_earlier(display, tmp_path):
    display.import_stim_module(write_module(tmp_path, 'mod_a', ['Shared']))
    display.import_stim_module(write_module(tmp_path, 'mod_b', ['Shared']))
    assert display.stim_classes['Shared'].origin == 'mod_b'

    display.unload_stim_module([display.imported_stim_module_names[-1]])

    assert display.stim_classes['Shared'].origin == 'mod_a'


def test_unloading_everything_leaves_the_builtins(display, tmp_path):
    display.import_stim_module(write_module(tmp_path, 'mod_a', ['StimA']))
    display.unload_stim_module(barcodes=None)

    assert 'StimA' not in display.stim_classes
    assert 'MovingPatch' in display.stim_classes
    assert display.imported_stim_module_names == []


def test_import_order_decides_and_is_stable(display, tmp_path):
    """Rebuilding the registry must replay imports in order, or unloading an unrelated module
    could change which of two shadowing modules wins."""
    display.import_stim_module(write_module(tmp_path, 'mod_a', ['Shared']))
    display.import_stim_module(write_module(tmp_path, 'mod_b', ['Shared']))
    display.import_stim_module(write_module(tmp_path, 'mod_c', ['Unrelated']))

    display.unload_stim_module([display.imported_stim_module_names[-1]])   # drop mod_c

    assert display.stim_classes['Shared'].origin == 'mod_b'


# --- a module with nothing in it -------------------------------------------------------------------

def test_a_module_with_no_stimuli_is_harmless(display, tmp_path):
    directory = tmp_path / 'empty'
    directory.mkdir()
    (directory / 'stimuli.py').write_text('# nothing here\n')

    display.import_stim_module(str(directory))

    barcode = display.imported_stim_module_names[0]
    assert display.imported_stim_module_classes[barcode] == {}
    assert 'MovingPatch' in display.stim_classes      # built-ins untouched
