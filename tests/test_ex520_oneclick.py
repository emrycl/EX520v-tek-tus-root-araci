import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.request import urlopen
from unittest.mock import patch

import ex520_oneclick as app


class DeviceNetworkIdTests(unittest.TestCase):
    def device_id_for(self, arp_output: str) -> str:
        completed = SimpleNamespace(stdout=arp_output, returncode=0)
        with (
            patch.object(
                app.shutil,
                "which",
                side_effect=lambda name: name if name == "arp" else None,
            ),
            patch.object(app.socket, "create_connection", side_effect=OSError),
            patch.object(app.subprocess, "run", return_value=completed),
        ):
            return app.device_network_id()

    def test_windows_hyphenated_mac_address(self):
        output = "  192.168.1.1          8c-86-dd-8e-36-ad     dynamic\r\n"
        expected = hashlib.sha256(b"8c86dd8e36ad").hexdigest()[:16]
        self.assertEqual(self.device_id_for(output), expected)

    def test_unix_colon_separated_mac_address(self):
        output = "? (192.168.1.1) at 8c:86:dd:8e:36:ad [ether] on eno1\n"
        expected = hashlib.sha256(b"8c86dd8e36ad").hexdigest()[:16]
        self.assertEqual(self.device_id_for(output), expected)


class SshPublicKeyTests(unittest.TestCase):
    def test_windows_crlf_public_key_is_normalized(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            private_key = state / "ssh-id-rsa"
            public_key = state / "ssh-id-rsa.pub"
            private_key.write_bytes(b"private")
            public_key.write_bytes(b"ssh-rsa QUJDRA== ex520-root\r\n")

            old_state = app.STATE_DIR
            try:
                app._set_state_dir(state)
                self.assertEqual(
                    app.ssh_public_key(),
                    b"ssh-rsa QUJDRA== ex520-root\n",
                )
            finally:
                app._set_state_dir(old_state)


class InstallerTests(unittest.TestCase):
    def test_installer_does_not_parse_platform_specific_df_output(self):
        with tempfile.TemporaryDirectory() as directory:
            old_state = app.STATE_DIR
            try:
                app._set_state_dir(Path(directory))
                public_key = b"ssh-rsa QUJDRA== ex520-root\n"
                with patch.object(app, "ssh_public_key", return_value=public_key):
                    bundle = app.build_bundle(
                        "192.168.1.250",
                        lifemote_backup=b'{"known":true}',
                    )
            finally:
                app._set_state_dir(old_state)

        installer = bundle.assets["install.sh"].decode()
        self.assertNotIn("df -k", installer)
        self.assertNotIn("already-present=1", installer)
        self.assertIn('wget -O /dev/null "$base/install-complete"', installer)

    def test_stale_panel_session_is_refreshed_once(self):
        with (
            patch.object(app, "activate_lifemote", side_effect=(False, True)) as activate,
            patch.object(app, "clear_panel_session") as clear,
            patch.object(app, "try_default_panel_login", return_value=True) as login,
            patch.object(app, "wait_for_panel_login") as wait,
        ):
            self.assertTrue(
                app.activate_lifemote_with_fresh_login("http://192.168.1.250/install.sh")
            )

        self.assertEqual(activate.call_count, 2)
        clear.assert_called_once_with()
        login.assert_called_once_with()
        wait.assert_not_called()


class SshClientTests(unittest.TestCase):
    def test_null_known_hosts_path_is_platform_specific(self):
        with tempfile.TemporaryDirectory() as directory:
            old_state = app.STATE_DIR
            try:
                app._set_state_dir(Path(directory))
                app.SSH_PRIVATE_KEY_FILE.write_bytes(b"private")
                completed = SimpleNamespace(
                    stdout=b"Uid:\t0\t0\t0\t0\n",
                    returncode=0,
                )
                with patch.object(app.subprocess, "run", return_value=completed) as run:
                    self.assertTrue(app.ssh_ready(timeout=1))
            finally:
                app._set_state_dir(old_state)

        command = run.call_args.args[0]
        self.assertIn(f"UserKnownHostsFile={app.os.devnull}", command)


class MacOsTests(unittest.TestCase):
    def test_application_firewall_rule_is_added_and_removable(self):
        completed = SimpleNamespace(stdout="", returncode=0)
        with (
            patch.object(app.sys, "platform", "darwin"),
            patch.object(app.shutil, "which", return_value="/usr/bin/sudo"),
            patch.object(app.Path, "is_file", return_value=True),
            patch.object(app.subprocess, "run", return_value=completed) as run,
        ):
            rule = app.open_temporary_firewall("192.168.1.250")

        self.assertIsNotNone(rule)
        self.assertEqual(run.call_count, 2)
        self.assertIn("--add", rule[0])
        self.assertIn("--remove", rule[1])

    def test_application_firewall_add_is_rolled_back_if_unblock_fails(self):
        ok = SimpleNamespace(stdout="", returncode=0)
        failed = SimpleNamespace(stdout="", returncode=1)
        with (
            patch.object(app.sys, "platform", "darwin"),
            patch.object(app.shutil, "which", return_value="/usr/bin/sudo"),
            patch.object(app.Path, "is_file", return_value=True),
            patch.object(
                app.subprocess,
                "run",
                side_effect=(ok, failed, ok),
            ) as run,
        ):
            rule = app.open_temporary_firewall("192.168.1.250")

        self.assertIsNone(rule)
        self.assertEqual(run.call_count, 3)
        self.assertIn("--remove", run.call_args_list[-1].args[0])

    def test_user_applications_chrome_is_supported(self):
        expected = app.Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

        def is_file(path):
            return path == expected

        with (
            patch.object(app.sys, "platform", "darwin"),
            patch.object(app.os, "name", "posix"),
            patch.object(app.shutil, "which", return_value=None),
            patch.object(app.Path, "is_file", is_file),
        ):
            self.assertEqual(app.chrome_binary(), str(expected))


class PayloadServerTests(unittest.TestCase):
    def test_only_install_complete_finishes_the_transfer(self):
        bundle = app.Bundle(
            assets={"install.sh": b"installer", "install-complete": b"OK\n"},
            shell_password="password",
            api_token="token",
            nonce="nonce",
        )
        with patch.object(app, "PORT", 0):
            server, complete, snapshot = app.serve_bundle("127.0.0.1", bundle)

        try:
            base = f"http://127.0.0.1:{server.server_port}/nonce"
            with urlopen(f"{base}/install.sh", timeout=2) as response:
                self.assertEqual(response.read(), b"installer")
            self.assertFalse(complete.is_set())

            with urlopen(f"{base}/install-complete", timeout=2) as response:
                self.assertEqual(response.read(), b"OK\n")
            self.assertTrue(complete.wait(1))
            self.assertEqual(snapshot(), (["install-complete", "install.sh"], []))
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
