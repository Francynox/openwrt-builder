from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from tqdm import tqdm
from urllib3.util import Retry

logger = logging.getLogger("SdkManager")

_SAFE_COMPONENT = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")


def _validate_component(value: str, name: str) -> None:
    """Validate that a URL path component is safe (no path traversal, no injection)."""
    if not _SAFE_COMPONENT.match(value):
        raise ValueError(f"Invalid {name}: '{value}' — must be alphanumeric with hyphens/dots/underscores only")


class SdkManager:
    def __init__(self, workspace_root: str | Path | None = None) -> None:
        self.root = Path(workspace_root).resolve() if workspace_root else Path.cwd()
        self.build_dir = self.root / "build"

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0"})

        retries = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504],
            raise_on_status=False,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retries))

    def download_file(self, url: str, filepath: Path, *, timeout: int = 120) -> None:
        try:
            with self.session.get(url, stream=True, timeout=timeout) as r:
                r.raise_for_status()
                total_size = int(r.headers.get("content-length", 0))
                with (
                    open(filepath, "wb") as f,
                    tqdm(
                        desc=f"  {filepath.name}",
                        total=total_size,
                        unit="B",
                        unit_scale=True,
                        unit_divisor=1024,
                        miniters=1,
                        leave=False,
                    ) as bar,
                ):
                    for chunk in r.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)
                            bar.update(len(chunk))
        except BaseException:
            filepath.unlink(missing_ok=True)
            raise

    def fetch_checksums(self, base_url: str) -> dict[str, str]:
        """Fetch and parse sha256sums from an OpenWrt release directory."""
        checksums_url = f"{base_url}/sha256sums"
        try:
            r = self.session.get(checksums_url, timeout=15)
            r.raise_for_status()
            content = r.text
        except Exception as e:
            logger.warning(f"Could not fetch checksums from {checksums_url}: {e}")
            return {}

        result = {}
        for line in content.strip().splitlines():
            parts = line.split()
            if len(parts) == 2:
                hash_val, filename = parts
                result[filename.lstrip("*")] = hash_val
        return result

    @staticmethod
    def verify_checksum(filepath: Path, expected_hash: str) -> None:
        """Verify SHA256 checksum of a downloaded file. Deletes file on mismatch."""
        sha256 = hashlib.sha256()
        with open(filepath, "rb") as f:
            while chunk := f.read(65536):
                sha256.update(chunk)
        actual = sha256.hexdigest()

        if actual.lower() != expected_hash.lower():
            filepath.unlink(missing_ok=True)
            raise RuntimeError(
                f"SHA256 checksum mismatch for {filepath.name}\n  Expected: {expected_hash}\n  Got:      {actual}"
            )
        logger.info(f"SHA256 verified: {filepath.name}")

    def get_latest_version(self) -> str:
        """Resolves latest OpenWrt stable version from upstream."""
        logger.info("Resolving latest OpenWrt stable version from upstream...")
        release_url = "https://sysupgrade.openwrt.org/json/v1/latest.json"
        try:
            r = self.session.get(release_url, timeout=15)
            r.raise_for_status()
            return str(r.json()["latest"][0])
        except Exception as e:
            raise RuntimeError(f"Failed to fetch latest OpenWrt version from upstream: {e}") from e

    def _resolve_url_and_prefix(self, version: str, target: str, arch: str) -> tuple[str, str, str]:
        _validate_component(target, "target")
        _validate_component(arch, "arch")
        resolved_version = self.get_latest_version() if version == "latest" else version
        base_url = (
            f"https://downloads.openwrt.org/snapshots/targets/{target}/{arch}"
            if resolved_version == "snapshot"
            else f"https://downloads.openwrt.org/releases/{resolved_version}/targets/{target}/{arch}"
        )
        filename_prefix = f"openwrt-imagebuilder-{resolved_version}-{target}-{arch}.Linux-x86_64"
        return resolved_version, base_url, filename_prefix

    def _find_cached_sdk(
        self, sdk_cache_dir: Path, filename_prefix: str, checksums: dict[str, str], verify: bool
    ) -> str | None:
        for ext in ["tar.zst", "tar.xz"]:
            filepath = sdk_cache_dir / f"{filename_prefix}.{ext}"
            if filepath.exists():
                if verify:
                    expected = checksums.get(filepath.name)
                    if expected:
                        try:
                            self.verify_checksum(filepath, expected)
                            return ext
                        except Exception as e:
                            logger.warning(f"Cached file checksum mismatch/error: {e}. Re-downloading...")
                            filepath.unlink(missing_ok=True)
                    else:
                        logger.warning(f"No checksum found for cached {filepath.name}. Re-downloading...")
                        filepath.unlink(missing_ok=True)
                else:
                    return ext
        return None

    def _resolve_active_extension(
        self, base_url: str, filename_prefix: str, checksums: dict[str, str], verify: bool
    ) -> str:
        if verify:
            for ext in ["tar.zst", "tar.xz"]:
                if f"{filename_prefix}.{ext}" in checksums:
                    return ext

        for ext in ["tar.zst", "tar.xz"]:
            check_url = f"{base_url}/{filename_prefix}.{ext}"
            try:
                r = self.session.head(check_url, timeout=10)
                r.raise_for_status()
                return ext
            except Exception:
                continue

        raise RuntimeError(f"Could not locate active ImageBuilder archive at {base_url}")

    def fetch_sdk(self, version: str, target: str, arch: str, *, verify: bool = True) -> str:
        """Resolves extension and downloads the ImageBuilder archive exactly once on the host."""
        resolved_version, base_url, filename_prefix = self._resolve_url_and_prefix(version, target, arch)

        sdk_cache_dir = self.build_dir / "sdk-cache"
        sdk_cache_dir.mkdir(parents=True, exist_ok=True)

        checksums = self.fetch_checksums(base_url) if verify else {}

        chosen_ext = None
        if resolved_version != "snapshot":
            chosen_ext = self._find_cached_sdk(sdk_cache_dir, filename_prefix, checksums, verify)

        if not chosen_ext:
            chosen_ext = self._resolve_active_extension(base_url, filename_prefix, checksums, verify)

        tarball_name = f"{filename_prefix}.{chosen_ext}"
        filepath = sdk_cache_dir / tarball_name

        if resolved_version == "snapshot" and filepath.exists():
            logger.info("Refreshing stale snapshot ImageBuilder archive...")
            filepath.unlink()

        if not filepath.exists():
            url = f"{base_url}/{tarball_name}"
            logger.info(f"Downloading ImageBuilder target artifact: {tarball_name}")
            self.download_file(url, filepath, timeout=300)

            if verify:
                expected = checksums.get(tarball_name)
                if expected:
                    self.verify_checksum(filepath, expected)
                else:
                    raise RuntimeError(f"Verification enabled but no checksum available for {tarball_name}")

        return tarball_name
