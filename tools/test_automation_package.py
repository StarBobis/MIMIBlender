"""Read-only package validation regressions with retained ZIP fixtures."""
# Package fixture ownership:
# - Write only exclusive archives under repository tmp.
# - Never run release.ps1, publish a version or install an add-on.
# - Positive fixtures contain the actual automation source bytes from this tree.
# - Negative fixtures intentionally omit or duplicate one runtime member.
# - ZIP inspection never extracts paths into the workspace or user directories.
# - Syntax validation compiles source without importing Blender or executing it.
# - All fixture archives remain available for manual inspection after tests.
# - Required runtime files include dedicated MCP, collaboration UI and materials.
# - A valid archive does not certify in-game behavior or native Blender execution.
import unittest
import re
from pathlib import Path
import uuid
import warnings
import zipfile

from check_automation_package import check_package, REQUIRED


ROOT = Path(__file__).resolve().parents[1]
PREFIX = "mimiblender-test"


class PackageTests(unittest.TestCase):
    """Missing automation code must fail local acceptance before any upload."""

    def setUp(self):
        self.base = ROOT / "tmp" / "automation-package-tests" / uuid.uuid4().hex  # An exclusive namespace avoids overwriting old fixtures.
        self.base.mkdir(parents=True, exist_ok=False)

    def archive(self, missing=None, extra=None):
        path = self.base / (uuid.uuid4().hex + ".zip")  # Lowercase generated names remain stable on Windows/Git.
        with zipfile.ZipFile(path, "w") as archive:
            for name in ("__init__.py",) + REQUIRED:
                if name != missing:
                    archive.writestr(PREFIX + "/" + name, (ROOT / name).read_bytes())  # Copy actual authored source, never a substitute stub.
            if extra:
                archive.writestr(extra, b"# fixture\n")  # Malformed lexical ZIP paths are inert entries, never extracted files.
        return path

    def test_actual_runtime_surface_is_present_and_compilable(self):
        report = check_package(self.archive(), PREFIX)  # Exercise the production checker against actual source members.
        self.assertTrue(report["ok"])
        self.assertEqual(len(report["automation_files"]), len(REQUIRED))
        self.assertFalse(report["in_game_verified"])  # Packaging cannot promote file generation to game validation.

    def test_native_release_guard_matches_runtime_manifest(self):
        # Read the authored native script without executing any publishing step.
        # Both pack-check implementations must require the same runtime modules.
        # Future transport/adapters cannot quietly drift out of the native guard.
        # The actual release command remains opt-in and is not invoked here.
        script = (ROOT / "release.ps1").read_text(encoding="utf-8")
        block = re.search(r"\$automationModules\s*=\s*@\((.*?)\)", script, re.S)
        self.assertIsNotNone(block)
        native = set(re.findall(r"'([^']+)'", block.group(1)))
        self.assertEqual(native, {Path(name).stem for name in REQUIRED})
        self.assertIn("git archive --format=zip", script)

    def test_missing_material_runtime_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "materials.py"):
            check_package(self.archive(missing="automation/materials.py"), PREFIX)

    def test_duplicate_runtime_entry_is_rejected(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)  # Duplicate ZIP warnings are expected for this intentional negative fixture.
            path = self.archive(extra=PREFIX + "/automation/registry.py")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            check_package(path, PREFIX)  # Reject ambiguity before compiling a potentially shadowed runtime entry.

    def test_path_escape_and_unsafe_prefix_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "escapes"):
            check_package(self.archive(extra=PREFIX + "/../outside.py"), PREFIX)
        with self.assertRaisesRegex(ValueError, "safe wrapper"):
            check_package(self.archive(), "../unsafe")  # An untrusted wrapper cannot redirect local extraction because none occurs.


# Ordinary Python is sufficient; native Blender is not started by these tests.
# A separate committed git archive check proves real release-path inclusion.
if __name__ == "__main__":
    unittest.main()
