import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "ex520_oneclick_tested",
    ROOT / "ex520_oneclick.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class FirmwareProfileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        MODULE._set_state_dir(Path(self.temporary.name))
        self.original_ssh_public_key = MODULE.ssh_public_key
        MODULE.ssh_public_key = lambda: b"ssh-rsa AAAA ex520-root\n"

    def tearDown(self):
        MODULE.ssh_public_key = self.original_ssh_public_key
        self.temporary.cleanup()

    def test_legacy_bundle_excludes_firmware_specific_web_helper(self):
        bundle = MODULE.build_bundle("192.0.2.10", profile="legacy-core")
        hook = bundle.assets["persistent-local-root.sh"]

        self.assertNotIn("ex520-web-root-init", bundle.assets)
        self.assertNotIn(b"ex520-web-root-init", bundle.assets["install.sh"])
        self.assertIn(b"enable_panel_root='0'", hook)
        self.assertNotIn(b"__ENABLE_PANEL_ROOT__", hook)
        self.assertNotIn(b"\r", hook)

    def test_supported_legacy_firmware_versions_use_safe_profile(self):
        self.assertEqual(
            MODULE.SUPPORTED_FIRMWARE_PROFILES["EX520v-v1.0_250522"],
            "legacy-core",
        )
        self.assertEqual(
            MODULE.SUPPORTED_FIRMWARE_PROFILES["EX520v-v1.0_250120"],
            "legacy-core",
        )

    def test_full_bundle_keeps_web_helper_and_enables_panel_patch(self):
        bundle = MODULE.build_bundle("192.0.2.10", profile="full")
        hook = bundle.assets["persistent-local-root.sh"]

        self.assertIn("ex520-web-root-init", bundle.assets)
        self.assertIn(b"ex520-web-root-init", bundle.assets["install.sh"])
        self.assertIn(b"enable_panel_root='1'", hook)

    def test_unknown_profile_is_rejected(self):
        with self.assertRaises(ValueError):
            MODULE.build_bundle("192.0.2.10", profile="unknown")


if __name__ == "__main__":
    unittest.main()
