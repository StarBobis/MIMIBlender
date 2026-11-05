"""Blender-free acceptance tests for generated INI/resource artifact framing.

Every owned fixture stays under tmp and is retained. No original Mod or source
workspace is opened, rewritten or removed by the test harness.
"""
# Audit acceptance:
# - Real fixture files, not mocked existence checks, establish resource closure.
# - Case-insensitive duplicate sections are rejected within one INI.
# - Conditional blocks must terminate before a section boundary or EOF.
# - Resource filename paths must stay inside the explicit generated root.
# - Native external symbolic APIs are not invented as local source files.
# - File SHA256 values are actual retained bytes, not operator status strings.
# - Tests remain independent of bpy and any running game process.
# - Fixture directories are exclusive new children and are never deleted.
import importlib.util
import importlib
from pathlib import Path
import sys
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
NAME = "mimi_automation_audit_test"
spec = importlib.util.spec_from_file_location(NAME, ROOT / "automation" / "__init__.py",
                                             submodule_search_locations=[str(ROOT / "automation")])
package = importlib.util.module_from_spec(spec)
sys.modules[NAME] = package
spec.loader.exec_module(package)
audits = importlib.import_module(NAME + ".audits")
Error = importlib.import_module(NAME + ".contract").AutomationError


class AuditTests(unittest.TestCase):
    """Exercise the real parser and file hashing against isolated output fixtures."""
    def setUp(self):
        # Do not use TemporaryDirectory: retain all developer evidence under tmp.
        self.root = ROOT / "tmp" / "automation-audit-fixtures" / uuid.uuid4().hex
        self.root.mkdir(parents=True, exist_ok=False)

    def ini(self, text):
        # A new fixture INI never overwrites an existing generated Mod.
        path = self.root / "fixture.ini"
        with path.open("x", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def test_valid_resource_closure_and_hash_evidence(self):
        # Source bytes are known so SHA256 and byte counts can be checked.
        (self.root / "buffers").mkdir()
        (self.root / "buffers" / "mesh.buf").write_bytes(b"real-buffer-bytes")
        self.ini("namespace = owned\n[ResourceVB]\nfilename = buffers\\mesh.buf\n[TextureOverrideBody]\nif $active\nhandling = skip\nendif\n")
        result = audits.audit_directory(str(self.root))
        self.assertEqual(result["scope"], "offline_ini_framing_and_resource_file_closure")  # The result labels its limited acceptance layer.
        self.assertFalse(result["in_game_verified"])  # No file-only audit can certify game behavior.
        self.assertEqual(result["inis"][0]["resource_files"], [str(Path("buffers") / "mesh.buf")])  # Declared references have real local targets.
        self.assertTrue(all(len(item["sha256"]) == 64 for item in result["files"]))  # Reproducible per-file hashes are published.

    def test_missing_resource_is_not_success(self):
        # A generated section is not usable merely because its filename is text.
        self.ini("[ResourceMissing]\nfilename = missing.buf\n")
        with self.assertRaises(Error) as caught:
            audits.audit_directory(str(self.root))
        self.assertEqual(caught.exception.code, "INVALID_ARTIFACTS")  # Missing resources remain an explicit failed artifact result.
        self.assertEqual(caught.exception.details["inis"][0]["errors"][0]["code"], "MISSING_RESOURCE_FILE")

    def test_duplicate_sections_and_unterminated_blocks_fail(self):
        # Duplicates are case-insensitive, matching the consumer namespace rule.
        self.ini("[Body]\nif $active\n[body]\nhash = 12345678\n")
        with self.assertRaises(Error) as caught:
            audits.audit_directory(str(self.root))
        codes = {item["code"] for item in caught.exception.details["inis"][0]["errors"]}
        self.assertIn("DUPLICATE_OR_EMPTY_SECTION", codes)
        self.assertIn("UNTERMINATED_CONDITIONAL", codes)

    def test_filename_escape_is_rejected(self):
        # A relative filename cannot acquire access to another user directory.
        self.ini("[ResourceEscape]\nfilename = ../outside.buf\n")
        with self.assertRaises(Error) as caught:
            audits.audit_directory(str(self.root))
        self.assertEqual(caught.exception.details["inis"][0]["errors"][0]["code"], "OUTPUT_PATH_ESCAPE")

    def test_empty_output_and_external_symbolic_api(self):
        # No INI is an error; an external API symbol is explicitly reported.
        with self.assertRaises(Error):
            audits.audit_directory(str(self.root))
        self.ini("[TextureOverrideAPI]\nps-t0 = Resource\\GIMI\\Diffuse\n")
        result = audits.audit_directory(str(self.root))
        self.assertEqual(result["inis"][0]["external_symbols"], [r"Resource\GIMI\Diffuse"])


# Standard Python exits normally; the user's visible Blender is unaffected.
if __name__ == "__main__":
    unittest.main()
