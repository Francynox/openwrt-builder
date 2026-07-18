from __future__ import annotations

import concurrent.futures
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from openwrt_builder.config import BuildConfig, validate_path_safety
from openwrt_builder.sdk import SdkManager

logger = logging.getLogger("HostBuilder")


class HostBuilder:
    def __init__(self, workspace_root: str | Path | None = None) -> None:
        self.builder_dir = Path(__file__).resolve().parent
        self.root = Path(workspace_root).resolve() if workspace_root else Path.cwd()

        self.build_dir = self.root / "build"
        self.output_dir = self.root / "output"

        self.sdk_manager = SdkManager(workspace_root=self.root)

    # -- Network helpers -------------------------------------------------------

    def download_extra_packages(self, extra_pkgs_dir: Path, extra_packages: list[str] | None) -> None:
        validate_path_safety(extra_pkgs_dir, self.root, "Extra packages directory")
        shutil.rmtree(extra_pkgs_dir, ignore_errors=True)
        extra_pkgs_dir.mkdir(parents=True, exist_ok=True)

        if not extra_packages:
            return

        for item in extra_packages:
            if item.startswith("https://"):
                name = item.split("/")[-1]
                logger.info(f"Downloading extra package: {item}")
                self.sdk_manager.download_file(item, extra_pkgs_dir / name)
            else:
                resolved = self.root / Path(item)
                files = list(resolved.parent.glob(resolved.name))
                if not files:
                    logger.warning(f"No files matched extra package path: {item}")
                for f in files:
                    logger.info(f"Copying extra package: {f}")
                    shutil.copy2(f, extra_pkgs_dir)

    # -- Build commands --------------------------------------------------------

    def clean(self) -> None:
        validate_path_safety(self.build_dir, self.root, "Build directory")
        validate_path_safety(self.output_dir, self.root, "Output directory")
        shutil.rmtree(self.build_dir, ignore_errors=True)
        shutil.rmtree(self.output_dir, ignore_errors=True)
        logger.info("Clean complete.")

    def check(self, config_file: str) -> BuildConfig:
        config = BuildConfig.from_file(config_file, self.root)
        logger.info("Config valid.")
        return config

    def _run_compose(self, *args: str, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        cmd = ["docker", "compose", "-f", str(self.builder_dir / "docker-compose.yml")] + list(args)
        logger.info(f"Running: {' '.join(cmd)}")
        env = {**os.environ, "WORKSPACE_ROOT": self.root.as_posix()}
        return subprocess.run(cmd, env=env, check=True, **kwargs)

    def _prepare(self, dry_run: bool = False) -> None:
        if not dry_run:
            logger.info("Reviewing Docker image state...")
            self._run_compose("build", "builder")

    def _build_profile(
        self,
        config: BuildConfig,
        pname: str,
        tarball_name: str,
        extra_pkgs_dir: Path,
        dry_run: bool = False,
    ) -> None:
        logger.info(f"\n=== Processing Profile: {pname} ===")

        fw_dir = self.output_dir / config.name / pname

        if not dry_run:
            shutil.rmtree(fw_dir, ignore_errors=True)
            fw_dir.mkdir(parents=True, exist_ok=True)

        config_rel = os.path.relpath(config.config_path, self.root)
        config_posix = Path(config_rel).as_posix()
        fw_posix = fw_dir.relative_to(self.root).as_posix()
        extra_posix = extra_pkgs_dir.relative_to(self.root).as_posix()

        run_cmd = ["run", "--rm"]

        if os.name == "posix":
            run_cmd.extend(["--user", f"{os.getuid()}:{os.getgid()}"])

        run_cmd.extend(
            [
                "builder",
                "python3",
                "-m",
                "openwrt_builder.internal",
                "--config",
                f"/app/{config_posix}",
                "--profile",
                pname,
                "--tarball-name",
                tarball_name,
                "--firmware-dir",
                f"/app/{fw_posix}",
                "--extra-packages",
                f"/app/{extra_posix}",
            ]
        )

        if logger.isEnabledFor(logging.DEBUG):
            run_cmd.append("--verbose")
        elif logger.getEffectiveLevel() >= logging.WARNING:
            run_cmd.append("--quiet")

        if not dry_run:
            try:
                self._run_compose(*run_cmd, timeout=7200)
            except subprocess.TimeoutExpired:
                logger.error(f"Docker build timed out after 7200s for profile '{pname}'")
                raise
            except subprocess.CalledProcessError as e:
                logger.error(f"Docker execution failed for profile '{pname}': exit code {e.returncode}")
                log_file = fw_dir / "build.log"
                if log_file.exists():
                    try:
                        content = log_file.read_text().splitlines()
                        logger.error("Last 20 lines of build.log:")
                        for line in content[-20:]:
                            logger.error(f"  {line}")
                    except Exception as log_err:
                        logger.warning(f"Could not read build log: {log_err}")
                raise

    def build(
        self,
        config_file: str,
        profile_arg: str | None,
        dry_run: bool = False,
        parallel: bool = False,
        verify: bool = True,
    ) -> None:
        config = self.check(config_file)
        config_name = config.name

        profiles = config.profiles
        targets = [profile_arg] if profile_arg else list(profiles.keys())
        logger.info(f"Target profiles: {targets}")

        self._prepare(dry_run)

        # Download SDK once on host before kicking off compilation jobs
        tarball_name = ""
        if not dry_run:
            tarball_name = self.sdk_manager.fetch_sdk(
                config.version,
                config.target,
                config.arch,
                verify=verify,
            )

        extra_pkgs_dir = self.build_dir / "extra-packages" / config_name
        if not dry_run:
            self.download_extra_packages(extra_pkgs_dir, config.extra_packages)

        valid_targets = [pname for pname in targets if pname in profiles]
        for pname in targets:
            if pname not in profiles:
                logger.error(f"Profile '{pname}' not found or invalid.")

        if valid_targets:
            if parallel:
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    futures = {
                        executor.submit(
                            self._build_profile, config, pname, tarball_name, extra_pkgs_dir, dry_run
                        ): pname
                        for pname in valid_targets
                    }
                    failed = False
                    for future in concurrent.futures.as_completed(futures):
                        pname = futures[future]
                        try:
                            future.result()
                        except Exception as e:
                            logger.error(f"Profile '{pname}' build failed: {e}")
                            failed = True
                    if failed:
                        raise RuntimeError("One or more profile builds failed.")
            else:
                for pname in valid_targets:
                    self._build_profile(config, pname, tarball_name, extra_pkgs_dir, dry_run)
