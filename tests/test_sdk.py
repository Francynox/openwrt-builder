from __future__ import annotations

import hashlib
from unittest.mock import MagicMock, patch

import pytest
import requests

from openwrt_builder.sdk import SdkManager, _validate_component

# -- _validate_component ------------------------------------------------------


class TestValidateComponent:
    @pytest.mark.parametrize("val", ["x86", "64", "ramips", "mt7621", "ath79", "mediatek", "filogic"])
    def test_valid_components(self, val):
        _validate_component(val, "target")

    def test_path_traversal_rejected(self):
        with pytest.raises(ValueError, match="Invalid target"):
            _validate_component("../etc", "target")

    def test_slash_injection_rejected(self):
        with pytest.raises(ValueError, match="Invalid arch"):
            _validate_component("64/../../passwd", "arch")

    def test_empty_rejected(self):
        with pytest.raises(ValueError, match="Invalid target"):
            _validate_component("", "target")

    def test_space_rejected(self):
        with pytest.raises(ValueError, match="Invalid"):
            _validate_component("x86 64", "target")


# -- verify_checksum ---------------------------------------------------------


class TestVerifyChecksum:
    def test_valid_checksum(self, tmp_path):
        f = tmp_path / "test.bin"
        content = b"test content for checksum verification"
        f.write_bytes(content)
        expected = hashlib.sha256(content).hexdigest()
        SdkManager.verify_checksum(f, expected)
        assert f.exists()

    def test_mismatch_deletes_file(self, tmp_path):
        f = tmp_path / "test.bin"
        f.write_bytes(b"actual content")
        with pytest.raises(RuntimeError, match="SHA256 checksum mismatch"):
            SdkManager.verify_checksum(f, "0" * 64)
        assert not f.exists()


# -- fetch_checksums ---------------------------------------------------------


class TestFetchChecksums:
    def test_parse_sha256sums(self, tmp_workspace):
        manager = SdkManager(workspace_root=tmp_workspace)
        checksums_content = (
            "abc123def456  *openwrt-imagebuilder-25.12.5-x86-64.Linux-x86_64.tar.zst\n"
            "789xyz000111  *openwrt-imagebuilder-25.12.5-x86-64.Linux-x86_64.tar.xz\n"
        )

        mock_response = MagicMock()
        mock_response.text = checksums_content
        mock_response.raise_for_status = MagicMock()

        with patch("requests.Session.get", return_value=mock_response):
            result = manager.fetch_checksums("https://downloads.openwrt.org/releases/25.12.5/targets/x86/64")

        assert result["openwrt-imagebuilder-25.12.5-x86-64.Linux-x86_64.tar.zst"] == "abc123def456"
        assert result["openwrt-imagebuilder-25.12.5-x86-64.Linux-x86_64.tar.xz"] == "789xyz000111"

    def test_network_failure_returns_empty(self, tmp_workspace):
        manager = SdkManager(workspace_root=tmp_workspace)

        with patch("requests.Session.get", side_effect=requests.RequestException("network error")):
            result = manager.fetch_checksums("https://example.com")

        assert result == {}

    def test_handles_no_star_prefix(self, tmp_workspace):
        manager = SdkManager(workspace_root=tmp_workspace)
        checksums_content = "abc123  filename.tar.zst\n"

        mock_response = MagicMock()
        mock_response.text = checksums_content
        mock_response.raise_for_status = MagicMock()

        with patch("requests.Session.get", return_value=mock_response):
            result = manager.fetch_checksums("https://example.com")

        assert result["filename.tar.zst"] == "abc123"


# -- get_latest_version -------------------------------------------------------


class TestGetLatestVersion:
    def test_successful_fetch(self, tmp_workspace):
        manager = SdkManager(workspace_root=tmp_workspace)
        response_json = {"latest": ["25.12.5", "25.12.4"]}

        mock_response = MagicMock()
        mock_response.json.return_value = response_json
        mock_response.raise_for_status = MagicMock()

        with patch("requests.Session.get", return_value=mock_response):
            result = manager.get_latest_version()

        assert result == "25.12.5"

    @patch("time.sleep")
    def test_network_failure_raises_runtime(self, mock_sleep, tmp_workspace):
        manager = SdkManager(workspace_root=tmp_workspace)

        with (
            patch("requests.Session.get", side_effect=requests.RequestException("timeout")),
            pytest.raises(RuntimeError, match="Failed to fetch latest"),
        ):
            manager.get_latest_version()


# -- fetch_sdk ----------------------------------------------------------------


class TestFetchSdk:
    def _mock_head_success(self):
        """Create a mock that succeeds for HEAD requests."""
        mock = MagicMock()
        mock.raise_for_status = MagicMock()
        return mock

    def test_url_construction_release(self, tmp_workspace):
        manager = SdkManager(workspace_root=tmp_workspace)

        with (
            patch.object(manager, "download_file") as mock_dl,
            patch.object(manager, "fetch_checksums", return_value={}),
            patch("requests.Session.head", return_value=self._mock_head_success()),
        ):
            result = manager.fetch_sdk("25.12.5", "x86", "64", verify=False)

        assert result == "openwrt-imagebuilder-25.12.5-x86-64.Linux-x86_64.tar.zst"
        mock_dl.assert_called_once()
        assert "releases/25.12.5" in mock_dl.call_args[0][0]

    def test_url_construction_snapshot(self, tmp_workspace):
        manager = SdkManager(workspace_root=tmp_workspace)

        with (
            patch.object(manager, "download_file") as mock_dl,
            patch.object(manager, "fetch_checksums", return_value={}),
            patch("requests.Session.head", return_value=self._mock_head_success()),
        ):
            manager.fetch_sdk("snapshot", "x86", "64", verify=False)

        assert "snapshots/targets" in mock_dl.call_args[0][0]

    def test_invalid_target_rejected(self, tmp_workspace):
        manager = SdkManager(workspace_root=tmp_workspace)
        with pytest.raises(ValueError, match="Invalid target"):
            manager.fetch_sdk("25.12.5", "../etc", "64")

    def test_invalid_arch_rejected(self, tmp_workspace):
        manager = SdkManager(workspace_root=tmp_workspace)
        with pytest.raises(ValueError, match="Invalid arch"):
            manager.fetch_sdk("25.12.5", "x86", "64/../../etc")

    def test_cached_sdk_skips_download(self, tmp_workspace):
        manager = SdkManager(workspace_root=tmp_workspace)

        cached_file = tmp_workspace / "build" / "sdk-cache" / "openwrt-imagebuilder-25.12.5-x86-64.Linux-x86_64.tar.zst"
        cached_file.write_bytes(b"cached")
        expected_hash = hashlib.sha256(b"cached").hexdigest()

        with (
            patch.object(manager, "download_file") as mock_dl,
            patch.object(manager, "fetch_checksums", return_value={cached_file.name: expected_hash}),
            patch("requests.Session.head", return_value=self._mock_head_success()),
        ):
            result = manager.fetch_sdk("25.12.5", "x86", "64")

        mock_dl.assert_not_called()
        assert result == "openwrt-imagebuilder-25.12.5-x86-64.Linux-x86_64.tar.zst"

    def test_cached_sdk_verification_failure_redownloads(self, tmp_workspace):
        manager = SdkManager(workspace_root=tmp_workspace)

        cached_file = tmp_workspace / "build" / "sdk-cache" / "openwrt-imagebuilder-25.12.5-x86-64.Linux-x86_64.tar.zst"
        cached_file.write_bytes(b"corrupted cached content")

        def mock_download(url, filepath, **kwargs):
            filepath.write_bytes(b"fresh content")

        expected_hash = hashlib.sha256(b"fresh content").hexdigest()
        with (
            patch.object(manager, "download_file", side_effect=mock_download) as mock_dl,
            patch.object(manager, "fetch_checksums", return_value={cached_file.name: expected_hash}),
            patch("requests.Session.head", return_value=self._mock_head_success()),
        ):
            result = manager.fetch_sdk("25.12.5", "x86", "64")

        mock_dl.assert_called_once()
        assert result == "openwrt-imagebuilder-25.12.5-x86-64.Linux-x86_64.tar.zst"
        assert cached_file.read_bytes() == b"fresh content"

    def test_snapshot_always_redownloads(self, tmp_workspace):
        manager = SdkManager(workspace_root=tmp_workspace)

        cached_file = (
            tmp_workspace / "build" / "sdk-cache" / "openwrt-imagebuilder-snapshot-x86-64.Linux-x86_64.tar.zst"
        )
        cached_file.write_bytes(b"old snapshot")

        with (
            patch.object(manager, "download_file") as mock_dl,
            patch.object(manager, "fetch_checksums", return_value={}),
            patch("requests.Session.head", return_value=self._mock_head_success()),
        ):
            manager.fetch_sdk("snapshot", "x86", "64", verify=False)

        mock_dl.assert_called_once()

    def test_verification_fails_if_checksum_missing(self, tmp_workspace):
        manager = SdkManager(workspace_root=tmp_workspace)

        with (
            patch.object(manager, "download_file"),
            patch.object(manager, "fetch_checksums", return_value={}),
            patch("requests.Session.head", return_value=self._mock_head_success()),
            pytest.raises(RuntimeError, match="Verification enabled but no checksum available"),
        ):
            manager.fetch_sdk("25.12.5", "x86", "64", verify=True)

    def test_checksum_verified_on_download(self, tmp_workspace):
        manager = SdkManager(workspace_root=tmp_workspace)

        checksums = {"openwrt-imagebuilder-25.12.5-x86-64.Linux-x86_64.tar.zst": "abc123"}

        with (
            patch.object(manager, "download_file"),
            patch.object(manager, "fetch_checksums", return_value=checksums),
            patch.object(manager, "verify_checksum") as mock_verify,
            patch("requests.Session.head", return_value=self._mock_head_success()),
        ):
            manager.fetch_sdk("25.12.5", "x86", "64", verify=True)

        mock_verify.assert_called_once()

    def test_no_verify_skips_checksum(self, tmp_workspace):
        manager = SdkManager(workspace_root=tmp_workspace)

        with (
            patch.object(manager, "download_file"),
            patch.object(manager, "fetch_checksums") as mock_cs,
            patch("requests.Session.head", return_value=self._mock_head_success()),
        ):
            manager.fetch_sdk("25.12.5", "x86", "64", verify=False)

        mock_cs.assert_not_called()


# -- download_file ------------------------------------------------------------


class TestDownloadFile:
    def test_successful_download(self, tmp_workspace):
        manager = SdkManager(workspace_root=tmp_workspace)
        filepath = tmp_workspace / "test-download.bin"
        content = b"file content here"

        mock_response = MagicMock()
        mock_response.headers = {"content-length": str(len(content))}
        mock_response.iter_content.return_value = [content]
        mock_response.raise_for_status = MagicMock()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("requests.Session.get", return_value=mock_response):
            manager.download_file("https://example.com/file", filepath)

        assert filepath.read_bytes() == content

    def test_failure_cleans_up(self, tmp_workspace):
        manager = SdkManager(workspace_root=tmp_workspace)
        filepath = tmp_workspace / "failed-download.bin"

        with (
            patch("requests.Session.get", side_effect=requests.RequestException("connection refused")),
            pytest.raises(requests.RequestException),
        ):
            manager.download_file("https://example.com/file", filepath)

        assert not filepath.exists()
