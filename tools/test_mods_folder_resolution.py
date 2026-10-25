"""Check where Generate Mod writes, without a running Blender.

Run: python tools/test_mods_folder_resolution.py

The failure this protects against: a 3Dmigoto package install unpacks the
stock d3dx.ini (`include_recursive = Mods`), but the project's fixed layout
keeps the user's mods in `Stuffs`. The add-on must follow the host's resolved
root (published as ``modsDir``) instead of blindly creating `Mods`, otherwise
the exported mod lands in a folder the game never scans.

The real GlobalConfig class is read from production source; only Blender's
``bpy`` module and the properties object are replaced. That keeps this test
tied to the shipped resolution order instead of a copy of it.
"""
import ast
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest


# Production file, parsed rather than imported: importing it requires bpy.
ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "common" / "global_config.py"
TREE = ast.parse(SOURCE.read_text(encoding="utf-8"))

# Only the class definition is executed; the module-level imports are faked.
CLASSES = [node for node in TREE.body if isinstance(node, ast.ClassDef) and node.name == "GlobalConfig"]

# d3dx.ini bodies used by the scenarios below. The key line mirrors the stock
# GIMI package; the second variant mirrors a host-managed fixed layout.
STOCK_INI = "[Include]\ninclude = Core\\GIMI\\main.ini\ninclude_recursive = Mods\n"
STUFFS_INI = "[Include]\ninclude = Core\\GIMI\\main.ini\ninclude_recursive = Stuffs\n"


class ModsFolderResolutionTests(unittest.TestCase):
    def setUp(self):
        # Fresh class object per test: the resolution uses class attributes,
        # so one test must never leak its game folder into the next one.
        self.namespace = {
            "os": os,
            "json": json,
            # Methods that touch Blender properties are never called here.
            "bpy": SimpleNamespace(),
            "MIMIGlobalProperties": SimpleNamespace(),
        }
        module = ast.Module(body=CLASSES, type_ignores=[])
        exec(compile(module, str(SOURCE), "exec"), self.namespace)
        self.config = self.namespace["GlobalConfig"]
        self.temp = TemporaryDirectory()

    def tearDown(self):
        # The temporary folder owns every file created by this test only.
        self.temp.cleanup()

    def make_install(self, ini_text=STOCK_INI, folders=()):
        """Create a 3Dmigoto folder with an optional d3dx.ini and subfolders."""
        install = Path(self.temp.name) / "game"
        install.mkdir()
        if ini_text is not None:
            (install / "d3dx.ini").write_text(ini_text, encoding="utf-8")
        for folder in folders:
            (install / folder).mkdir(parents=True, exist_ok=True)
        self.config.current_game_migoto_folder = str(install)
        return install

    def resolved(self):
        """Normalized mods folder, so trailing separators do not matter."""
        return os.path.normpath(self.config.path_mods_folder())

    def test_host_resolved_root_wins_over_a_stock_ini(self):
        # The host says Stuffs (its fixed layout) while the ini still carries
        # the stock Mods entry a package install just unpacked.
        install = self.make_install(folders=("Mods", "Stuffs"))
        self.config.mods_location = str(install / "Stuffs")
        self.assertEqual(self.resolved(), str(install / "Stuffs"))

    def test_host_value_pointing_at_a_missing_folder_is_ignored(self):
        # A stale config (game folder moved) must not create a phantom mods
        # root far away from the game; the ini answer is used instead.
        install = self.make_install(folders=("Mods",))
        self.config.mods_location = str(Path(self.temp.name) / "gone" / "Stuffs")
        self.assertEqual(self.resolved(), str(install / "Mods"))

    def test_ini_stuffs_is_followed_without_host_config(self):
        # An old host build writes no `modsDir`; the ini still decides, and a
        # non-standard folder name must be honored.
        install = self.make_install(ini_text=STUFFS_INI, folders=("Stuffs",))
        self.assertEqual(self.resolved(), str(install / "Stuffs"))

    def test_existing_folder_wins_over_a_configured_but_missing_one(self):
        # Several include_recursive lines: only Stuffs exists on disk, so the
        # export must not recreate the missing Mods folder next to it.
        ini = "[Include]\ninclude_recursive = Mods\ninclude_recursive = Stuffs\n"
        install = self.make_install(ini_text=ini, folders=("Stuffs",))
        self.assertEqual(self.resolved(), str(install / "Stuffs"))

    def test_comma_separated_entries_pick_the_existing_mods_folder(self):
        # 3Dmigoto accepts several folders on one line; Core is not a mods
        # root, so the literal Mods entry still wins among existing folders.
        ini = "[Include]\ninclude_recursive = Core, Mods\n"
        install = self.make_install(ini_text=ini, folders=("Core", "Mods"))
        self.assertEqual(self.resolved(), str(install / "Mods"))

    def test_missing_ini_falls_back_to_mods(self):
        # Nothing to read: keep the conventional name so a first export still
        # lands somewhere predictable.
        install = self.make_install(ini_text=None)
        self.assertEqual(self.resolved(), str(install / "Mods"))

    def test_no_game_folder_configured_falls_back_to_mods(self):
        # The add-on may run before the host wrote any game config.
        self.config.current_game_migoto_folder = ""
        self.assertEqual(self.resolved(), os.path.normpath("Mods"))


if __name__ == "__main__":
    unittest.main()
