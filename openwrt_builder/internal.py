#!/usr/bin/env python3

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from openwrt_builder.config import BuildConfig, load_yaml

logger = logging.getLogger("InternalBuilder")


class BuildError(Exception):
    pass


class ConfigError(Exception):
    pass


class InternalBuilder:
    def __init__(self, firmware_output_dir: str | Path, workspace_root: str | Path | None = None) -> None:
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else Path("/app")
        self.firmware_output_dir = Path(firmware_output_dir).resolve()
        self.sdk_cache_dir = self.workspace_root / "build" / "sdk-cache"

    def extract_sdk(self, profile_name: str, tarball_name: str) -> Path:
        archive_path = self.sdk_cache_dir / tarball_name
        if not archive_path.exists():
            raise BuildError(f"Expected cached SDK archive missing inside container: {archive_path}")

        sdk_dir = Path("/tmp") / profile_name / "sdk"
        shutil.rmtree(sdk_dir, ignore_errors=True)
        sdk_dir.mkdir(parents=True)

        logger.info(f"Extracting SDK context '{profile_name}'...")
        subprocess.run(["tar", "-xf", str(archive_path), "-C", str(sdk_dir), "--strip-components=1"], check=True)
        return sdk_dir

    @staticmethod
    def convert_vm(bin_dir: Path, vm_format: str) -> None:
        vm_dir = bin_dir / "qemu"
        vm_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Converting images to {vm_format}...")

        gz_files = list(bin_dir.glob("*.img.gz"))
        if not gz_files:
            logger.warning(f"No raw disk images found in {bin_dir} for VM conversion.")
            return

        for gz_file in gz_files:
            img_file = vm_dir / Path(gz_file.name).stem
            try:
                with open(img_file, "wb") as f_out:
                    subprocess.run(["gunzip", "-c", str(gz_file)], stdout=f_out, check=True)

                output = vm_dir / f"{img_file.stem}.{vm_format}"
                subprocess.run(
                    ["qemu-img", "convert", "-f", "raw", "-O", vm_format, str(img_file), str(output)], check=True
                )
                logger.info(f"Created {output}")
            except Exception as e:
                logger.warning(f"Failed to convert VM image {gz_file.name}: {e}")
            finally:
                if img_file.exists():
                    img_file.unlink()

    @staticmethod
    def enforce_permissions(inject_dir: Path, custom_permissions: list[dict] | None) -> None:
        logger.info("Normalizing container injection permissions (dirs=755, files=644)...")
        for p in inject_dir.rglob("*"):
            if not p.is_symlink():
                p.chmod(0o755 if p.is_dir() else 0o644)

        for rule in custom_permissions or []:
            perm_path = rule["path"]
            target = inject_dir / perm_path
            if target.exists():
                mode = int(rule["mode"], 8)
                logger.info(f"Setting permission {oct(mode)} on {perm_path}")
                target.chmod(mode)
            else:
                logger.warning(f"File for permission change not found: {target}")

    @staticmethod
    def normalize_line_endings(directory: Path) -> None:
        logger.info("Normalizing CRLF line endings to LF for container scripts...")
        for p in directory.rglob("*"):
            if p.is_file() and not p.is_symlink():
                try:
                    content = p.read_bytes()
                    if b"\x00" in content[:1024]:
                        continue
                    if b"\r\n" in content:
                        p.write_bytes(content.replace(b"\r\n", b"\n"))
                except Exception as e:
                    logger.warning(f"Could not normalize line endings for {p}: {e}")

    @staticmethod
    def apply_patches(config: BuildConfig, sdk_dir: Path) -> None:
        if not config.mod_partsize or not config.partition_size:
            return

        config_file = sdk_dir / ".config"
        if config_file.exists():
            logger.info("Applying partition size patches to SDK config base...")
            ksize = config.partition_size.get("kernel")
            rsize = config.partition_size.get("root")
            with open(config_file, "a") as f:
                if ksize:
                    f.write(f"\nCONFIG_TARGET_KERNEL_PARTSIZE={ksize}\n")
                if rsize:
                    f.write(f"CONFIG_TARGET_ROOTFS_PARTSIZE={rsize}\n")
        else:
            logger.warning(f"Default base configuration file missing at {config_file}; skipping sizes.")

    def _validate_symlinks(self, layer_path: Path) -> None:
        """Verify relative symlinks in a layer do not escape the workspace root."""
        for p in layer_path.rglob("*"):
            if not p.is_symlink():
                continue

            target = os.readlink(p)
            if os.path.isabs(target):
                continue

            resolved_target = (p.parent / target).resolve()
            try:
                resolved_target.relative_to(self.workspace_root.resolve())
            except ValueError as e:
                raise ConfigError(f"Symlink escapes workspace root: {p} -> {target}") from e

    def run(
        self,
        config_path: str | Path,
        profile_name: str,
        tarball_name: str,
        extra_packages_path: str | Path | None = None,
    ) -> None:
        try:
            config = BuildConfig.from_file(config_path, self.workspace_root)
        except ValueError as e:
            raise ConfigError(str(e)) from e

        if profile_name not in config.profiles:
            raise ConfigError(f"Profile '{profile_name}' not found in config")

        layers = config.get_combined_layers(profile_name)

        sdk_dir = self.extract_sdk(profile_name, tarball_name)

        if extra_packages_path:
            extra_pkgs_src = Path(extra_packages_path)
            if extra_pkgs_src.is_dir():
                sdk_pkgs_dir = sdk_dir / "packages"
                sdk_pkgs_dir.mkdir(parents=True, exist_ok=True)
                for f in extra_pkgs_src.iterdir():
                    if f.suffix in (".apk", ".ipk"):
                        logger.info(f"Injecting localized alternative package: {f.name}")
                        shutil.copy2(f, sdk_pkgs_dir)

        temp_inject_dir = Path(f"/tmp/inject-{profile_name}")
        shutil.rmtree(temp_inject_dir, ignore_errors=True)
        temp_inject_dir.mkdir(parents=True, exist_ok=True)

        try:
            for layer in layers or []:
                layer_path = self.workspace_root / layer
                if not layer_path.exists():
                    logger.warning(f"Layer path targeted but unavailable: {layer_path}")
                    continue

                self._validate_symlinks(layer_path)
                logger.info(f"Merging layer contents: {layer}")
                shutil.copytree(layer_path, temp_inject_dir, dirs_exist_ok=True, symlinks=True)

            self.normalize_line_endings(temp_inject_dir)

            global_perms = config.permissions
            profile_perms = config.profiles[profile_name].permissions
            self.enforce_permissions(temp_inject_dir, global_perms + profile_perms)

            self.apply_patches(config, sdk_dir)

            image_profile = config.image_profile
            packages_str = " ".join(config.packages)

            logger.info(f"Starting make image compilation for profile target: {image_profile}")
            cmd = [
                "make",
                "image",
                f"PROFILE={image_profile}",
                f"PACKAGES={packages_str}",
                f"FILES={temp_inject_dir}",
                f"BIN_DIR={self.firmware_output_dir}",
            ]
            if image_tag := config.image_tag:
                cmd.append(f"EXTRA_IMAGE_NAME={image_tag}")

            # Redirect make compilation output to a build.log file
            log_file = self.firmware_output_dir / "build.log"
            logger.info(f"Compiling OpenWrt image. Logging to: {log_file}")

            with open(log_file, "w") as f_log:
                subprocess.run(cmd, cwd=sdk_dir, stdout=f_log, stderr=f_log, check=True)
        finally:
            shutil.rmtree(temp_inject_dir, ignore_errors=True)

        if config.qemu:
            self.convert_vm(self.firmware_output_dir, "qcow2")


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenWrt Internal Builder")
    parser.add_argument("--config", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--tarball-name", required=True)
    parser.add_argument("--firmware-dir", required=True)
    parser.add_argument("--extra-packages")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--quiet", "-q", action="store_true")

    args = parser.parse_args()

    try:
        config = load_yaml(args.config)
        target = config.get("target", "unknown")
        prefix = f"[{target}/{args.profile}] "
    except Exception:
        prefix = f"[{args.profile}] "

    log_level = logging.INFO
    if args.quiet:
        log_level = logging.WARNING
    elif args.verbose:
        log_level = logging.DEBUG

    logging.basicConfig(level=log_level, format=f"%(asctime)s [%(levelname)s] {prefix}%(message)s")

    try:
        builder = InternalBuilder(args.firmware_dir)
        builder.run(args.config, args.profile, args.tarball_name, args.extra_packages)
    except KeyboardInterrupt:
        logger.warning("\nBuild interrupted by user")
        return 130
    except (ConfigError, BuildError, ValueError) as e:
        logger.error(str(e))
        return 1
    except subprocess.CalledProcessError as e:
        logger.error(f"Build command failed with exit code {e.returncode}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
