from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def sample_minimal_config():
    """Smallest valid config — only required fields."""
    return {
        "target": "x86",
        "arch": "64",
        "image_profile": "generic",
        "profiles": {"demo": None},
    }


@pytest.fixture
def sample_full_config():
    """Full-featured config exercising every optional field."""
    return {
        "name": "example",
        "target": "x86",
        "arch": "64",
        "image_profile": "generic",
        "version": "25.12.5",
        "packages": ["curl", "nano"],
        "extra_packages": ["https://example.com/my-pkg.apk"],
        "layers": ["layers/example"],
        "mod_partsize": True,
        "partition_size": {"kernel": 64, "root": 512},
        "qemu": True,
        "permissions": [{"path": "etc/test", "mode": "0644"}],
        "profiles": {
            "demo": {
                "layers": ["layers/demo"],
                "permissions": [{"path": "etc/demo", "mode": "0755"}],
            },
            "demo2": None,
        },
    }


@pytest.fixture
def tmp_workspace(tmp_path):
    """Temporary workspace with expected directory structure."""
    (tmp_path / "build" / "sdk-cache").mkdir(parents=True)
    (tmp_path / "output").mkdir()
    (tmp_path / "configs").mkdir()
    (tmp_path / "layers" / "example" / "etc").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def mock_build_config(tmp_workspace):
    from openwrt_builder.config import BuildConfig, ProfileConfig

    config = MagicMock(spec=BuildConfig)
    config.target = "x86"
    config.arch = "64"
    config.name = "demo"
    config.version = "25.12.5"
    config.config_path = tmp_workspace / "config.yaml"
    config.image_profile = "generic"
    config.image_tag = None
    config.packages = []
    config.extra_packages = []
    config.permissions = []
    config.qemu = False
    config.mod_partsize = False
    config.partition_size = None
    config.get_combined_layers = MagicMock(return_value=[])

    demo_profile = MagicMock(spec=ProfileConfig)
    demo_profile.name = "demo"
    demo_profile.layers = []
    demo_profile.permissions = []

    config.profiles = {"demo": demo_profile}
    return config
