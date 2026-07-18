"""Tests for openwrt_builder.internal — InternalBuilder operation safety and logs."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from openwrt_builder.internal import ConfigError, InternalBuilder


class TestInternalBuilderSymlinkSafety:
    def test_safe_relative_symlink(self, tmp_path, mock_build_config):
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        layer = workspace / "layer"
        layer.mkdir()

        target_file = layer / "target.txt"
        target_file.write_text("hello")

        link_file = layer / "link.txt"
        link_file.symlink_to("target.txt")

        builder = InternalBuilder(firmware_output_dir=workspace / "output", workspace_root=workspace)
        builder.firmware_output_dir.mkdir(parents=True, exist_ok=True)

        mock_build_config.get_combined_layers.return_value = ["layer"]

        with (
            patch("openwrt_builder.internal.BuildConfig.from_file", return_value=mock_build_config),
            patch.object(builder, "extract_sdk", return_value=workspace / "sdk"),
            patch("shutil.copytree"),
            patch("subprocess.run"),
        ):
            builder.run("config.yaml", "demo", "tarball.tar.zst")

    def test_unsafe_relative_symlink_escapes_workspace(self, tmp_path, mock_build_config):
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        layer = workspace / "layer"
        layer.mkdir()

        link_file = layer / "unsafe_link.txt"
        link_file.symlink_to("../../../etc/passwd")

        builder = InternalBuilder(firmware_output_dir=workspace / "output", workspace_root=workspace)
        builder.firmware_output_dir.mkdir(parents=True, exist_ok=True)

        mock_build_config.get_combined_layers.return_value = ["layer"]

        with (
            patch("openwrt_builder.internal.BuildConfig.from_file", return_value=mock_build_config),
            patch.object(builder, "extract_sdk", return_value=workspace / "sdk"),
            patch("subprocess.run"),
            pytest.raises(ConfigError, match="Symlink escapes workspace root"),
        ):
            builder.run("config.yaml", "demo", "tarball.tar.zst")

    def test_absolute_symlink_allowed(self, tmp_path, mock_build_config):
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        layer = workspace / "layer"
        layer.mkdir()

        link_file = layer / "absolute_link.txt"
        link_file.symlink_to("/etc/resolv.conf")

        builder = InternalBuilder(firmware_output_dir=workspace / "output", workspace_root=workspace)
        builder.firmware_output_dir.mkdir(parents=True, exist_ok=True)

        mock_build_config.get_combined_layers.return_value = ["layer"]

        with (
            patch("openwrt_builder.internal.BuildConfig.from_file", return_value=mock_build_config),
            patch.object(builder, "extract_sdk", return_value=workspace / "sdk"),
            patch("shutil.copytree"),
            patch("subprocess.run"),
        ):
            builder.run("config.yaml", "demo", "tarball.tar.zst")


class TestInternalBuilderMain:
    def test_returns_1_on_build_failure(self, tmp_path):
        from openwrt_builder.internal import main

        fw_dir = tmp_path / "firmware"
        fw_dir.mkdir()

        test_args = [
            "internal.py",
            "--config",
            "config.yaml",
            "--profile",
            "demo",
            "--tarball-name",
            "tarball.tar.zst",
            "--firmware-dir",
            str(fw_dir),
        ]

        error = subprocess.CalledProcessError(returncode=2, cmd="make image")

        with (
            patch("sys.argv", test_args),
            patch("openwrt_builder.internal.BuildConfig.from_file"),
            patch("openwrt_builder.internal.InternalBuilder.run", side_effect=error),
            patch("logging.Logger.error") as mock_log_err,
        ):
            exit_code = main()
            assert exit_code == 1

            mock_log_err.assert_any_call("Build command failed with exit code 2")
