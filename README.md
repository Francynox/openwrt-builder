# OpenWrt Builder

A containerized build system for OpenWrt based on the ImageBuilder SDK.

> **Note:** This is an open-source community tool and is not officially affiliated with or endorsed by the OpenWrt project.

Define your firmware configuration in YAML, and the builder handles SDK download, layer merging, package injection, and image compilation inside Docker.

## Features

- **YAML-driven configuration** — declarative firmware profiles with packages, layers, and permissions
- **Layer merging system** — overlay-style filesystem layers applied globally and per-profile
- **Parallel builds** — build multiple profiles concurrently with `--parallel`
- **SDK caching & validation** — downloads once, verifies integrity via SHA256
- **Extra packages** — inject local `.ipk`/`.apk` files or download URLs
- **Partition sizing & QEMU** — customize disk layouts and auto-generate VM images (x86)

## Prerequisites & Installation

- **Python 3.10+**
- **Docker & Docker Compose**

### Install from PyPI

```bash
pip install openwrt-builder
```

### Install from source

```bash
git clone https://github.com/francynox/openwrt-builder.git
cd openwrt-builder
pip install .
```

(or `pip install -e ".[dev]"` for development, `nix develop` for Nix dev shell)

## Quick Start

1. **Clone the repo:**
   ```bash
   git clone https://github.com/francynox/openwrt-builder.git
   cd openwrt-builder
   ```

2. **Build the example configuration:**
   ```bash
   python -m openwrt_builder build --config configs/example.yaml
   ```

3. **Find your firmware** in `output/example/demo/`.

For a fully customized setup, see [`configs/reference.yaml`](configs/reference.yaml).

## Usage

If installed via `pip`, run the CLI tool directly:
```bash
openwrt-builder [options] <command> [options]
```

Otherwise, run the module directly:
```bash
python -m openwrt_builder [options] <command> [options]
```

To see all options, use the `--help` flag:
```bash
openwrt-builder --help
# or
python -m openwrt_builder --help
```

## Configuration Reference

See [`configs/reference.yaml`](configs/reference.yaml) for a fully annotated example covering every available option.

## Disclaimer

OpenWrt is a registered trademark of the Software Freedom Conservancy (SFC). `openwrt-builder` is an independent third-party tool and is not officially affiliated with, maintained, or endorsed by the OpenWrt project.

