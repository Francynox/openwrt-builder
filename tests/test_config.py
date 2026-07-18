"""Tests for openwrt_builder.config — YAML loading and config validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from openwrt_builder.config import BuildConfig, load_yaml


def validate_config(config: dict[str, Any]) -> None:
    BuildConfig(config, Path("dummy.yaml"), Path.cwd())


# -- load_yaml ----------------------------------------------------------------


class TestLoadYaml:
    def test_valid_yaml(self, tmp_path):
        f = tmp_path / "test.yaml"
        f.write_text("target: x86\narch: '64'\n")
        result = load_yaml(f)
        assert result == {"target": "x86", "arch": "64"}

    def test_file_not_found(self, tmp_path):
        with pytest.raises(ValueError, match="Failed to load config"):
            load_yaml(tmp_path / "nonexistent.yaml")

    def test_invalid_yaml_syntax(self, tmp_path):
        f = tmp_path / "bad.yaml"
        f.write_text("key: [unmatched")
        with pytest.raises(ValueError, match="Failed to load config"):
            load_yaml(f)

    def test_non_mapping_raises(self, tmp_path):
        f = tmp_path / "list.yaml"
        f.write_text("- item1\n- item2\n")
        with pytest.raises(ValueError, match="must contain a YAML mapping"):
            load_yaml(f)


# -- validate_config: required fields -----------------------------------------


class TestRequiredFields:
    def test_valid_minimal(self, sample_minimal_config):
        validate_config(sample_minimal_config)

    def test_valid_full(self, sample_full_config):
        validate_config(sample_full_config)

    def test_missing_target(self, sample_minimal_config):
        del sample_minimal_config["target"]
        with pytest.raises(ValueError, match="missing required fields.*target"):
            validate_config(sample_minimal_config)

    def test_missing_arch(self, sample_minimal_config):
        del sample_minimal_config["arch"]
        with pytest.raises(ValueError, match="missing required fields.*arch"):
            validate_config(sample_minimal_config)

    def test_missing_profiles(self, sample_minimal_config):
        del sample_minimal_config["profiles"]
        with pytest.raises(ValueError, match="missing required fields.*profiles"):
            validate_config(sample_minimal_config)

    def test_missing_image_profile(self, sample_minimal_config):
        del sample_minimal_config["image_profile"]
        with pytest.raises(ValueError, match="missing.*image_profile"):
            validate_config(sample_minimal_config)


# -- validate_config: profiles -------------------------------------------------


class TestProfiles:
    def test_profiles_not_dict(self, sample_minimal_config):
        sample_minimal_config["profiles"] = ["demo"]
        with pytest.raises(ValueError, match="non-empty mapping"):
            validate_config(sample_minimal_config)

    def test_profiles_empty(self, sample_minimal_config):
        sample_minimal_config["profiles"] = {}
        with pytest.raises(ValueError, match="non-empty mapping"):
            validate_config(sample_minimal_config)

    def test_profile_not_mapping(self, sample_minimal_config):
        sample_minimal_config["profiles"] = {"demo": "invalid"}
        with pytest.raises(ValueError, match="must be a mapping"):
            validate_config(sample_minimal_config)

    def test_profile_none_is_valid(self, sample_minimal_config):
        sample_minimal_config["profiles"] = {"demo": None}
        validate_config(sample_minimal_config)


# -- validate_config: packages and layers --------------------------------------


class TestPackagesAndLayers:
    def test_packages_not_list(self, sample_minimal_config):
        sample_minimal_config["packages"] = "curl"
        with pytest.raises(ValueError, match="'packages' must be a list"):
            validate_config(sample_minimal_config)

    def test_extra_packages_not_list(self, sample_minimal_config):
        sample_minimal_config["extra_packages"] = "https://example.com/pkg.ipk"
        with pytest.raises(ValueError, match="'extra_packages' must be a list"):
            validate_config(sample_minimal_config)

    def test_layers_not_list(self, sample_minimal_config):
        sample_minimal_config["layers"] = "layers/example"
        with pytest.raises(ValueError, match="must be a list"):
            validate_config(sample_minimal_config)

    def test_layers_backslash_normalization(self, sample_minimal_config):
        sample_minimal_config["layers"] = ["layers\\example"]
        validate_config(sample_minimal_config)
        assert sample_minimal_config["layers"] == ["layers/example"]

    def test_profile_layers_not_list(self, sample_minimal_config):
        sample_minimal_config["profiles"] = {"demo": {"layers": "layers/demo"}}
        with pytest.raises(ValueError, match="'layers' must be a list"):
            validate_config(sample_minimal_config)

    def test_profile_layers_backslash_normalization(self, sample_minimal_config):
        sample_minimal_config["profiles"] = {"demo": {"layers": ["layers\\demo"]}}
        validate_config(sample_minimal_config)
        assert sample_minimal_config["profiles"]["demo"]["layers"] == ["layers/demo"]


# -- validate_config: permissions ----------------------------------------------


class TestPermissions:
    def test_valid_permissions(self, sample_minimal_config):
        sample_minimal_config["permissions"] = [{"path": "etc/test", "mode": "0644"}]
        validate_config(sample_minimal_config)

    def test_permissions_not_list(self, sample_minimal_config):
        sample_minimal_config["permissions"] = {"path": "etc/test", "mode": "0644"}
        with pytest.raises(ValueError, match="must be a list"):
            validate_config(sample_minimal_config)

    def test_permission_missing_path(self, sample_minimal_config):
        sample_minimal_config["permissions"] = [{"mode": "0644"}]
        with pytest.raises(ValueError, match="missing required 'path' or 'mode'"):
            validate_config(sample_minimal_config)

    def test_permission_missing_mode(self, sample_minimal_config):
        sample_minimal_config["permissions"] = [{"path": "etc/test"}]
        with pytest.raises(ValueError, match="missing required 'path' or 'mode'"):
            validate_config(sample_minimal_config)

    def test_permission_mode_not_string(self, sample_minimal_config):
        sample_minimal_config["permissions"] = [{"path": "etc/test", "mode": 644}]
        with pytest.raises(ValueError, match="must be a string"):
            validate_config(sample_minimal_config)

    def test_permission_invalid_octal(self, sample_minimal_config):
        sample_minimal_config["permissions"] = [{"path": "etc/test", "mode": "999"}]
        with pytest.raises(ValueError, match="not a valid octal string"):
            validate_config(sample_minimal_config)

    def test_profile_permissions(self, sample_minimal_config):
        sample_minimal_config["profiles"] = {"demo": {"permissions": [{"path": "etc/demo", "mode": "0755"}]}}
        validate_config(sample_minimal_config)


# -- validate_config: partition size -------------------------------------------


class TestPartitionSize:
    def test_mod_partsize_valid(self, sample_minimal_config):
        sample_minimal_config["mod_partsize"] = True
        sample_minimal_config["partition_size"] = {"kernel": 64, "root": 512}
        validate_config(sample_minimal_config)

    def test_mod_partsize_missing_partition_size(self, sample_minimal_config):
        sample_minimal_config["mod_partsize"] = True
        with pytest.raises(ValueError, match="partition_size.*missing"):
            validate_config(sample_minimal_config)

    def test_mod_partsize_missing_kernel(self, sample_minimal_config):
        sample_minimal_config["mod_partsize"] = True
        sample_minimal_config["partition_size"] = {"root": 512}
        with pytest.raises(ValueError, match="partition_size.kernel"):
            validate_config(sample_minimal_config)

    def test_mod_partsize_missing_root(self, sample_minimal_config):
        sample_minimal_config["mod_partsize"] = True
        sample_minimal_config["partition_size"] = {"kernel": 64}
        with pytest.raises(ValueError, match="partition_size.root"):
            validate_config(sample_minimal_config)

    def test_mod_partsize_invalid_value(self, sample_minimal_config):
        sample_minimal_config["mod_partsize"] = True
        sample_minimal_config["partition_size"] = {"kernel": "big", "root": 512}
        with pytest.raises(ValueError, match="must be an integer"):
            validate_config(sample_minimal_config)


# -- validate_config: qemu ----------------------------------------------------


class TestQemu:
    def test_qemu_bool(self, sample_minimal_config):
        sample_minimal_config["qemu"] = True
        validate_config(sample_minimal_config)

    def test_qemu_not_bool(self, sample_minimal_config):
        sample_minimal_config["qemu"] = "yes"
        with pytest.raises(ValueError, match="must be a boolean"):
            validate_config(sample_minimal_config)


# -- validate_config: version format (Phase 5) --------------------------------


class TestVersionValidation:
    def test_valid_semver(self, sample_minimal_config):
        sample_minimal_config["version"] = "25.12.5"
        validate_config(sample_minimal_config)

    def test_valid_latest(self, sample_minimal_config):
        sample_minimal_config["version"] = "latest"
        validate_config(sample_minimal_config)

    def test_valid_snapshot(self, sample_minimal_config):
        sample_minimal_config["version"] = "snapshot"
        validate_config(sample_minimal_config)

    def test_valid_rc(self, sample_minimal_config):
        sample_minimal_config["version"] = "24.10.0-rc1"
        validate_config(sample_minimal_config)

    def test_invalid_version(self, sample_minimal_config):
        sample_minimal_config["version"] = "not-a-version"
        with pytest.raises(ValueError, match="Invalid 'version'"):
            validate_config(sample_minimal_config)


# -- validate_config: image_profile format (Phase 5) --------------------------


class TestImageProfileValidation:
    @pytest.mark.parametrize("name", ["generic", "linksys_e8450-ubi", "netgear_r7800", "x86.64"])
    def test_valid_names(self, sample_minimal_config, name):
        sample_minimal_config["image_profile"] = name
        validate_config(sample_minimal_config)

    @pytest.mark.parametrize("name", ["../etc", "pro file", ""])
    def test_invalid_names(self, sample_minimal_config, name):
        sample_minimal_config["image_profile"] = name
        with pytest.raises(ValueError, match="Invalid 'image_profile'|missing"):
            validate_config(sample_minimal_config)


# -- BuildConfig path safety & class tests -------------------------------------


class TestBuildConfigSafety:
    def test_layer_traversal_rejected(self, sample_minimal_config, tmp_path):
        sample_minimal_config["layers"] = ["../unsafe_layer"]

        with pytest.raises(ValueError, match="layer path contains directory traversal"):
            BuildConfig(sample_minimal_config, tmp_path / "dummy.yaml", tmp_path)

    def test_layer_escaping_workspace_rejected(self, sample_minimal_config, tmp_path):
        sample_minimal_config["layers"] = ["/etc"]

        with pytest.raises(ValueError, match="layer path escapes workspace root"):
            BuildConfig(sample_minimal_config, tmp_path / "dummy.yaml", tmp_path)

    def test_permission_traversal_rejected(self, sample_minimal_config, tmp_path):
        sample_minimal_config["permissions"] = [{"path": "../traversal.txt", "mode": "0755"}]

        with pytest.raises(ValueError, match="permission rule.*path contains directory traversal"):
            BuildConfig(sample_minimal_config, tmp_path / "dummy.yaml", tmp_path)

    def test_extra_packages_traversal_rejected(self, sample_minimal_config, tmp_path):
        sample_minimal_config["extra_packages"] = ["../unsafe_package.ipk"]

        with pytest.raises(ValueError, match="Extra package.*path contains directory traversal"):
            BuildConfig(sample_minimal_config, tmp_path / "dummy.yaml", tmp_path)

    def test_extra_packages_escaping_workspace_rejected(self, sample_minimal_config, tmp_path):
        sample_minimal_config["extra_packages"] = ["/etc/unsafe_package.ipk"]

        with pytest.raises(ValueError, match="Extra package.*path escapes workspace root"):
            BuildConfig(sample_minimal_config, tmp_path / "dummy.yaml", tmp_path)

    def test_extra_packages_http_url_rejected(self, sample_minimal_config, tmp_path):
        sample_minimal_config["extra_packages"] = ["http://example.com/unsafe_package.ipk"]

        with pytest.raises(ValueError, match="Insecure HTTP URL not allowed"):
            BuildConfig(sample_minimal_config, tmp_path / "dummy.yaml", tmp_path)

    def test_from_file_loads_correctly(self, sample_minimal_config, tmp_path):
        import yaml

        config_file = tmp_path / "config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(sample_minimal_config, f)

        bc = BuildConfig.from_file(config_file, tmp_path)
        assert bc.target == sample_minimal_config["target"]
        assert bc.arch == sample_minimal_config["arch"]
        assert bc.name == "config"
        assert bc.get_combined_layers("demo") == []
