from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from openwrt_builder.host import HostBuilder

# -- download_extra_packages --------------------------------------------------


class TestDownloadExtraPackages:
    def test_local_file_copy(self, tmp_workspace):
        builder = HostBuilder(workspace_root=tmp_workspace)
        extra_dir = tmp_workspace / "build" / "extra-packages" / "test"

        pkg_dir = tmp_workspace / "packages"
        pkg_dir.mkdir()
        pkg_file = pkg_dir / "my-pkg.ipk"
        pkg_file.write_bytes(b"fake package")

        builder.download_extra_packages(extra_dir, ["packages/my-pkg.ipk"])
        assert (extra_dir / "my-pkg.ipk").exists()

    def test_empty_packages_noop(self, tmp_workspace):
        builder = HostBuilder(workspace_root=tmp_workspace)
        extra_dir = tmp_workspace / "build" / "extra-packages" / "test"
        builder.download_extra_packages(extra_dir, None)
        assert extra_dir.exists()

    def test_https_url_downloads(self, tmp_workspace):
        builder = HostBuilder(workspace_root=tmp_workspace)
        extra_dir = tmp_workspace / "build" / "extra-packages" / "test"

        with patch.object(builder.sdk_manager, "download_file") as mock_dl:
            builder.download_extra_packages(extra_dir, ["https://example.com/my-pkg.apk"])

        mock_dl.assert_called_once()
        call_args = mock_dl.call_args
        assert "https://example.com/my-pkg.apk" in call_args[0]


# -- build & docker execution -------------------------------------------------


class TestHostBuilderBuild:
    def test_build_constructs_proper_command(self, mock_build_config):
        tmp_workspace = mock_build_config.config_path.parent.parent
        builder = HostBuilder(workspace_root=tmp_workspace)

        mock_build_config.get_combined_layers = MagicMock(return_value=["layer1"])

        with (
            patch.object(builder, "check", return_value=mock_build_config),
            patch.object(builder.sdk_manager, "fetch_sdk", return_value="tarball.tar.zst"),
            patch.object(builder, "download_extra_packages"),
            patch("subprocess.run") as mock_run,
        ):
            builder.build(
                config_file="config.yaml",
                profile_arg="demo",
            )

            # Assert prepare (which runs build) was called
            # and build commands were called
            assert mock_run.call_count >= 2

            # The second call is docker compose run
            run_call_args = mock_run.call_args_list[1]
            cmd = run_call_args[0][0]

            assert "docker" in cmd
            assert "compose" in cmd
            assert "run" in cmd
            assert "--rm" in cmd
            assert "builder" in cmd
            assert "python3" in cmd
            assert "-m" in cmd
            assert "openwrt_builder.internal" in cmd
            assert "--config" in cmd
            assert "--profile" in cmd
            assert "demo" in cmd
            assert "--tarball-name" in cmd
            assert "tarball.tar.zst" in cmd

    def test_prepare(self, tmp_workspace):
        builder = HostBuilder(workspace_root=tmp_workspace)

        with patch("subprocess.run") as mock_run:
            builder._prepare(dry_run=False)
            mock_run.assert_called_once()
            args, _ = mock_run.call_args
            cmd = args[0]
            assert cmd[:3] == ["docker", "compose", "-f"]
            assert "build" in cmd
            assert "builder" in cmd

    def test_build_failure_logs_last_lines(self, mock_build_config):
        tmp_workspace = mock_build_config.config_path.parent.parent
        builder = HostBuilder(workspace_root=tmp_workspace)

        fw_dir = tmp_workspace / "output" / "demo" / "demo"
        log_file = fw_dir / "build.log"
        log_lines = [f"line {i}" for i in range(25)]

        error = subprocess.CalledProcessError(returncode=2, cmd="docker compose run ...")

        def write_log_and_fail(*args, **kwargs):
            fw_dir.mkdir(parents=True, exist_ok=True)
            log_file.write_text("\n".join(log_lines))
            raise error

        with (
            patch.object(builder, "check", return_value=mock_build_config),
            patch.object(builder.sdk_manager, "fetch_sdk", return_value="tarball.tar.zst"),
            patch.object(builder, "download_extra_packages"),
            patch.object(builder, "_prepare"),
            patch("subprocess.run", side_effect=write_log_and_fail),
            patch("logging.Logger.error") as mock_log_err,
        ):
            with pytest.raises(subprocess.CalledProcessError):
                builder.build(
                    config_file="config.yaml",
                    profile_arg="demo",
                )

            mock_log_err.assert_any_call("Last 20 lines of build.log:")
            for i in range(5, 25):
                mock_log_err.assert_any_call(f"  line {i}")
