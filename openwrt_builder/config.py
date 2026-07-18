from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

_VERSION_PATTERN = re.compile(r"^(latest|snapshot|\d+\.\d+\.\d+(-rc\d+)?)$")
_SAFE_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")


def load_yaml(config_path: str | Path) -> dict[str, Any]:
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
        if not isinstance(config, dict):
            raise ValueError("Config file must contain a YAML mapping")
        return config
    except (FileNotFoundError, yaml.YAMLError) as e:
        raise ValueError(f"Failed to load config {config_path}: {e}") from e


def validate_path_safety(path: str | Path, workspace_root: Path, description: str) -> None:
    path_str = str(path)
    if ".." in Path(path_str).parts:
        raise ValueError(f"{description} path contains directory traversal: {path_str}")
    # Also verify it doesn't escape workspace root if resolved
    resolved = (workspace_root / path_str).resolve()
    try:
        resolved.relative_to(workspace_root.resolve())
    except ValueError as e:
        raise ValueError(f"{description} path escapes workspace root: {path_str}") from e


def normalize_config_slashes(config: dict[str, Any]) -> None:
    def norm(val: Any) -> Any:
        if isinstance(val, str):
            return val.replace("\\", "/")
        if isinstance(val, list):
            return [norm(item) for item in val]
        if isinstance(val, dict):
            return {k: norm(v) for k, v in val.items()}
        return val

    for key in ["layers", "extra_packages", "permissions", "profiles"]:
        if key in config:
            config[key] = norm(config[key])


def _validate_permissions(perms: Any, context: str, workspace_root: Path) -> list[dict[str, Any]]:
    if not isinstance(perms, list):
        raise ValueError(f"{context} 'permissions' must be a list of rule mappings.")
    validated = []
    for idx, rule in enumerate(perms):
        if not isinstance(rule, dict):
            raise ValueError(f"{context} permission rule at index {idx} must be a mapping (key-value pairs).")
        try:
            path_val = rule["path"]
            mode_val = rule["mode"]
        except KeyError:
            raise ValueError(
                f"{context} permission rule at index {idx} is missing required 'path' or 'mode' keys."
            ) from None

        if not isinstance(path_val, str):
            raise ValueError(f"{context} permission rule at index {idx}: 'path' must be a string.")

        validate_path_safety(path_val, workspace_root, f"{context} permission rule at index {idx}")

        if not isinstance(mode_val, str):
            raise ValueError(
                f"{context} permission rule at index {idx}: 'mode' must be a string (e.g., '0755'). "
                f"Got {type(mode_val).__name__}. Please wrap the permission mode in quotes in your YAML."
            )
        try:
            int(mode_val, 8)
        except ValueError as e:
            raise ValueError(
                f"{context} permission rule at index {idx}: 'mode' '{mode_val}' is not a valid octal string."
            ) from e
        validated.append({"path": path_val, "mode": mode_val})
    return validated


class ProfileConfig:
    def __init__(self, name: str, data: dict[str, Any] | None, workspace_root: Path) -> None:
        self.name = name
        self.layers: list[str] = []
        self.permissions: list[dict[str, Any]] = []

        if data is not None:
            if not isinstance(data, dict):
                raise ValueError(f"Profile '{name}' must be a mapping")

            if "layers" in data:
                if not isinstance(data["layers"], list):
                    raise ValueError(f"Profile '{name}': 'layers' must be a list")
                for layer in data["layers"]:
                    if isinstance(layer, str):
                        validate_path_safety(layer, workspace_root, f"Profile '{name}' layer")
                        self.layers.append(layer)

            if "permissions" in data:
                self.permissions = _validate_permissions(data["permissions"], f"Profile '{name}'", workspace_root)


class BuildConfig:
    @classmethod
    def from_file(cls, config_path: str | Path, workspace_root: str | Path) -> BuildConfig:
        config_path = Path(config_path).resolve()
        workspace_root = Path(workspace_root).resolve()
        config_data = load_yaml(config_path)
        return cls(config_data, config_path, workspace_root)

    def __init__(self, config: dict[str, Any], config_path: Path, workspace_root: Path) -> None:
        self.config_path = config_path
        normalize_config_slashes(config)
        self.name = config.get("name") or config_path.stem

        required_top = ["target", "arch", "profiles"]
        if missing := [f for f in required_top if config.get(f) is None or config.get(f) == ""]:
            raise ValueError(f"Config missing required fields: {', '.join(missing)}")

        self.target = config["target"]
        self.arch = config["arch"]

        profiles_data = config["profiles"]
        if not isinstance(profiles_data, dict) or not profiles_data:
            raise ValueError("'profiles' must be a non-empty mapping")

        self.profiles: dict[str, ProfileConfig] = {}
        for pname, pdata in profiles_data.items():
            self.profiles[pname] = ProfileConfig(pname, pdata, workspace_root)

        self.version = str(config.get("version", "latest"))
        if not _VERSION_PATTERN.match(self.version):
            raise ValueError(
                f"Invalid 'version': '{self.version}' — must be 'latest', 'snapshot', or semver (e.g., '23.05.2')"
            )

        self.image_profile = config.get("image_profile")
        if not self.image_profile:
            raise ValueError("Config missing global 'image_profile'")
        if not _SAFE_NAME.match(self.image_profile):
            raise ValueError(
                f"Invalid 'image_profile': '{self.image_profile}' — "
                "must be alphanumeric with hyphens/dots/underscores only"
            )

        self.image_tag = config.get("image_tag")

        if "packages" in config and not isinstance(config["packages"], list):
            raise ValueError(
                f"'packages' must be a list, got {type(config['packages']).__name__}. "
                "Use YAML list syntax (one '- package' per line)."
            )
        self.packages = config.get("packages") or []

        self.extra_packages: list[str] = []
        if "extra_packages" in config:
            if not isinstance(config["extra_packages"], list):
                raise ValueError(
                    f"'extra_packages' must be a list, got {type(config['extra_packages']).__name__}. "
                    "Use YAML list syntax (one '- package' per line)."
                )
            for item in config["extra_packages"]:
                if isinstance(item, str):
                    if item.startswith(("http://", "https://")):
                        if item.startswith("http://"):
                            raise ValueError(f"Insecure HTTP URL not allowed for extra package: {item}. Use HTTPS.")
                        self.extra_packages.append(item)
                    else:
                        validate_path_safety(item, workspace_root, f"Extra package '{item}'")
                        self.extra_packages.append(item)

        self.layers: list[str] = []
        if "layers" in config:
            if not isinstance(config["layers"], list):
                raise ValueError(
                    f"Global 'layers' must be a list, got {type(config['layers']).__name__}. "
                    "Use YAML list syntax (one '- layer' per line)."
                )
            for layer in config["layers"]:
                if isinstance(layer, str):
                    validate_path_safety(layer, workspace_root, "Global layer")
                    self.layers.append(layer)

        self.permissions: list[dict[str, Any]] = []
        if "permissions" in config:
            self.permissions = _validate_permissions(config["permissions"], "Global", workspace_root)

        self.qemu = bool(config.get("qemu", False))
        if "qemu" in config and not isinstance(config["qemu"], bool):
            raise ValueError("Global config option 'qemu' must be a boolean")

        self.mod_partsize = bool(config.get("mod_partsize", False))
        self.partition_size = config.get("partition_size")
        if self.mod_partsize:
            if not isinstance(self.partition_size, dict):
                raise ValueError("'mod_partsize' is true but 'partition_size' is missing or not a mapping")
            for key in ["kernel", "root"]:
                val = self.partition_size.get(key)
                if val is None:
                    raise ValueError(f"'partition_size.{key}' required when 'mod_partsize' is true")
                try:
                    int(val)
                except (ValueError, TypeError) as e:
                    raise ValueError(f"'partition_size.{key}' must be an integer, got '{val}'") from e

    def get_combined_layers(self, profile_name: str) -> list[str]:
        profile = self.profiles.get(profile_name)
        profile_layers = profile.layers if profile else []
        return self.layers + profile_layers
