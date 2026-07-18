from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys

from openwrt_builder.host import HostBuilder

# Set up logging format globally
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("openwrt_builder")


def main() -> int:
    prog = os.path.basename(sys.argv[0])
    if prog == "__main__.py":
        prog = "python -m openwrt_builder"
    parser = argparse.ArgumentParser(prog=prog, description="OpenWrt Builder")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    parser.add_argument("--quiet", "-q", action="store_true", help="Suppress info messages")
    parser.add_argument(
        "--workspace", "-w", help="Path to the project workspace root directory (defaults to current working directory)"
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    build_cmd = subparsers.add_parser("build")
    build_cmd.add_argument("--config", required=True, help="Path to config YAML file")
    build_cmd.add_argument("--profile", help="Specific profile to build (default: all)")
    build_cmd.add_argument("--dry-run", action="store_true", help="Show execution plan without building")
    build_cmd.add_argument("--parallel", action="store_true", help="Build target profiles in parallel")

    build_cmd.add_argument(
        "--no-verify", action="store_true", help="Skip SHA256 checksum verification of SDK downloads"
    )

    check_cmd = subparsers.add_parser("check")
    check_cmd.add_argument("--config", required=True, help="Path to config YAML file")

    subparsers.add_parser("clean")

    args = parser.parse_args()

    # Configure the root logger level so it dynamically filters all sub-modules uniformly
    if args.quiet:
        logging.getLogger().setLevel(logging.WARNING)
    elif args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    builder = HostBuilder(workspace_root=args.workspace)

    try:
        if args.command == "clean":
            builder.clean()
        elif args.command == "check":
            builder.check(args.config)
        elif args.command == "build":
            builder.build(args.config, args.profile, args.dry_run, args.parallel, verify=not args.no_verify)

    except KeyboardInterrupt:
        logger.warning("\nBuild interrupted by user")
        return 130
    except subprocess.TimeoutExpired as e:
        logger.error(f"Host execution timed out during a subprocess task: {e}")
        return 1
    except subprocess.CalledProcessError as e:
        if e.cmd:
            logger.error(
                f"Subprocess failure: Command '{' '.join(e.cmd)}' returned non-zero exit status {e.returncode}"
            )
        return 1
    except Exception as e:
        logger.error(f"Fatal unexpected error: {e}", exc_info=args.verbose)
        return 1

    return 0
