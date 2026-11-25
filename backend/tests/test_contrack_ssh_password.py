import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import SecretStr
import yaml

from app.modules.contrack_environments.config import EnvironmentError, EnvironmentSettings, load_settings
from app.modules.contrack_environments.version_switch import SSHHostRunner


class SSHPasswordTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.known_hosts = self.root / "known_hosts"
        self.known_hosts.write_text("10.166.136.7 ssh-ed25519 dummy-test-key\n")
        self.password = "test :#$()'\\ secret"
        self.settings = EnvironmentSettings(root=self.root, enabled=True, operation_mode="switch_version", switch_version={
            "auth_method": "password", "ssh_host": "10.166.136.7", "ssh_user": "vsvndev",
            "ssh_password": self.password, "private_key": str(self.root / "does-not-exist"),
            "known_hosts": str(self.known_hosts),
            "runner_path": "/home/vsvndev/contrack tool/host_runner.py",
            "host_config": "/home/vsvndev/Contrack-Recreate/config/host-switch.json",
        })
        self.runner = SSHHostRunner(self.settings)
        self.which = patch("app.modules.contrack_environments.version_switch.shutil.which", side_effect=lambda name: "/usr/bin/" + name)
        self.which.start()
        self.addCleanup(self.which.stop)

    def test_password_mode_does_not_require_a_private_key(self):
        self.assertFalse(Path(self.settings.switch_version.private_key).exists())
        self.assertIsNone(self.runner.configuration_error())

    def test_password_uses_pipe_not_arguments_environment_or_shell_and_invokes_fixed_host_helper(self):
        captured = {}
        def run(command, **kwargs):
            captured.update(command=command, kwargs=kwargs, fd=kwargs["pass_fds"][0])
            self.assertEqual(command[:3], ["sshpass", "-d", str(captured["fd"])])
            self.assertEqual(os.read(captured["fd"], 4096), (self.password + "\n").encode())
            return SimpleNamespace(returncode=0, stdout='{"ok":true}', stderr="")
        with patch.dict(os.environ, {"CONTRACK_ENV_SSH_PASSWORD": self.password, "SSHPASS": self.password}), \
             patch("subprocess.run", side_effect=run):
            self.assertTrue(self.runner.call("check")["ok"])
        command, kwargs = captured["command"], captured["kwargs"]
        self.assertNotIn(self.password, repr(command))
        self.assertNotIn(self.password, repr(kwargs))
        self.assertNotIn("CONTRACK_ENV_SSH_PASSWORD", kwargs["env"])
        self.assertNotIn("SSHPASS", kwargs["env"])
        self.assertFalse(kwargs.get("shell", False))
        self.assertIn("StrictHostKeyChecking=yes", command)
        self.assertIn("BatchMode=no", command)
        self.assertIn("PreferredAuthentications=password", command)
        self.assertIn("PubkeyAuthentication=no", command)
        self.assertNotIn("-i", command)
        self.assertEqual(shlex.split(command[-1]), ["python3", self.settings.switch_version.runner_path,
                         "--config", self.settings.switch_version.host_config, "check"])
        with self.assertRaises(OSError):
            os.read(captured["fd"], 1)

    def test_run_id_is_forwarded_as_an_argument_not_a_shell_fragment(self):
        def run(command, **kwargs):
            os.read(kwargs["pass_fds"][0], 4096)
            self.assertEqual(shlex.split(command[-1])[-2:], ["run", "20261125T100000-aaaaaaaaaaaa"])
            return SimpleNamespace(returncode=0, stdout='{"ok":true}', stderr="")
        with patch("subprocess.run", side_effect=run):
            self.runner.call("run", "20261125T100000-aaaaaaaaaaaa")
        with patch("subprocess.run") as process:
            with self.assertRaises(EnvironmentError):
                self.runner.call("run", "id; rm anything")
            process.assert_not_called()

    def test_key_mode_keeps_existing_forced_command_protocol(self):
        key = self.root / "id_ed25519"
        key.write_text("dummy-key")
        self.settings.switch_version.auth_method = "key"
        self.settings.switch_version.private_key = str(key)
        with patch("subprocess.run", return_value=SimpleNamespace(returncode=0, stdout='{"ok":true}', stderr="")) as process:
            self.runner.call("check")
        command = process.call_args.args[0]
        self.assertEqual(command[0], "ssh")
        self.assertEqual(command[-1], "check")
        self.assertIn("BatchMode=yes", command)
        self.assertIn(str(key), command)
        self.assertNotIn("pass_fds", process.call_args.kwargs)

    def test_password_file_is_supported_and_literal_password_takes_precedence(self):
        secret = self.root / "ssh_password"
        secret.write_bytes(b"  file-pass#$  \r\n")
        self.settings.switch_version.ssh_password_file = str(secret)
        self.assertEqual(self.runner._password(), self.password)
        self.settings.switch_version.ssh_password = SecretStr("")
        self.assertEqual(self.runner._password(), "  file-pass#$  ")
        self.assertIsNone(self.runner.configuration_error())

    def test_missing_or_invalid_secrets_return_sanitized_configuration_errors(self):
        self.settings.switch_version.ssh_password = SecretStr("")
        self.settings.switch_version.ssh_password_file = str(self.root / "missing-password")
        self.assertIn("ssh_password", self.runner.configuration_error())
        for value in ("first\nsecond", "first\rsecond", "first\0second", "x" * 2049):
            with self.subTest(length=len(value)):
                self.settings.switch_version.ssh_password = SecretStr(value)
                error = self.runner.configuration_error()
                self.assertIn("one nonempty line", error)
                self.assertNotIn(value, error)

    def test_password_mode_requires_known_hosts_paths_and_sshpass(self):
        with patch("app.modules.contrack_environments.version_switch.shutil.which", side_effect=lambda name: None if name == "sshpass" else "/usr/bin/ssh"):
            self.assertIn("sshpass", self.runner.configuration_error())
        self.settings.switch_version.runner_path = "relative/runner.py"
        self.assertIn("absolute", self.runner.configuration_error())
        self.settings.switch_version.runner_path = "/tmp/runner\n.py"
        self.assertIn("absolute", self.runner.configuration_error())
        self.known_hosts.unlink()
        self.assertIn("known_hosts", self.runner.configuration_error())

    def test_wrong_password_and_transport_failures_never_echo_secret_or_stderr(self):
        with patch("subprocess.run", return_value=SimpleNamespace(returncode=5, stdout="", stderr=self.password)):
            with self.assertRaises(EnvironmentError) as caught:
                self.runner.call("check")
        self.assertEqual(caught.exception.code, "SSH_AUTHENTICATION_FAILED")
        self.assertNotIn(self.password, str(caught.exception))
        captured = {}
        def timeout(command, **kwargs):
            captured["fd"] = kwargs["pass_fds"][0]
            raise subprocess.TimeoutExpired(command, kwargs["timeout"], stderr=self.password)
        with patch("subprocess.run", side_effect=timeout):
            with self.assertRaises(EnvironmentError) as caught:
                self.runner.call("check")
        self.assertEqual(caught.exception.code, "HOST_CONNECTION_FAILED")
        self.assertNotIn(self.password, str(caught.exception))
        with self.assertRaises(OSError):
            os.read(captured["fd"], 1)

    def test_host_application_errors_are_preserved_without_forwarding_stderr(self):
        with patch("subprocess.run", return_value=SimpleNamespace(returncode=1, stdout='{"ok":false,"code":"HOST_CONFIGURATION_INVALID"}', stderr=self.password)):
            with self.assertRaises(EnvironmentError) as caught:
                self.runner.call("check")
        self.assertEqual(caught.exception.code, "HOST_CONFIGURATION_INVALID")
        self.assertNotIn(self.password, str(caught.exception))

    def test_yaml_password_is_masked_excluded_from_dumps_and_environment_override_works(self):
        values = {"root": str(self.root), "enabled": True, "operation_mode": "switch_version",
                  "switch_version": {"auth_method": "password", "ssh_password": self.password}}
        config = self.root / "environment.yaml"
        config.write_text(yaml.safe_dump(values), encoding="utf-8")
        with patch.dict(os.environ, {"CONTRACK_ENV_CONFIG": str(config), "CONTRACK_ENV_SSH_PASSWORD": "", "CONTRACK_ENV_ROOT": ""}):
            settings = load_settings()
            self.assertEqual(settings.switch_version.ssh_password.get_secret_value(), self.password)
            self.assertNotIn(self.password, repr(settings))
            self.assertNotIn("ssh_password", settings.model_dump()["switch_version"])
            self.assertNotIn(self.password, settings.model_dump_json())
            with patch.dict(os.environ, {"CONTRACK_ENV_SSH_PASSWORD": "environment-secret"}):
                settings = load_settings()
                self.assertEqual(settings.switch_version.ssh_password.get_secret_value(), "environment-secret")

    def test_malformed_yaml_configuration_does_not_echo_password(self):
        values = {"root": str(self.root), "switch_version": {"ssh_password": self.password, "auth_method": "invalid"}}
        config = self.root / "bad.yaml"
        config.write_text(yaml.safe_dump(values), encoding="utf-8")
        with patch.dict(os.environ, {"CONTRACK_ENV_CONFIG": str(config)}), self.assertRaises(EnvironmentError) as caught:
            load_settings()
        self.assertNotIn(self.password, str(caught.exception))
