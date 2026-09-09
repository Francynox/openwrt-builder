{
  description = "OpenWrt Builder - Linux x86_64";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-parts.url = "github:hercules-ci/flake-parts";

    treefmt-nix = {
      url = "github:numtide/treefmt-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    git-hooks = {
      url = "github:cachix/git-hooks.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    inputs@{
      flake-parts,
      treefmt-nix,
      git-hooks,
      ...
    }:
    flake-parts.lib.mkFlake { inherit inputs; } {
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];

      imports = [
        treefmt-nix.flakeModule
        git-hooks.flakeModule
      ];

      perSystem =
        {
          config,
          pkgs,
          ...
        }:
        {
          treefmt = {
            projectRootFile = "flake.nix";
            programs.yamlfmt.enable = true;
            settings.formatter.yamlfmt.excludes = [
              "configs/**"
            ];
            programs.jsonfmt.enable = true;
            programs.just.enable = true;
            programs.nixfmt.enable = true;
            programs.deadnix.enable = true;
            programs.statix.enable = true;
            programs.ruff = {
              check = true;
              format = true;
            };
          };

          pre-commit = {
            check.enable = true;
            settings.hooks.treefmt.enable = true;
            settings.hooks.zizmor.enable = true;
            settings.hooks.actionlint.enable = true;
            settings.hooks.nix-flake-check = {
              enable = true;
              name = "nix-flake-check";
              entry = "bash -c 'if command -v nix >/dev/null; then nix flake check; else echo \"Skipping nix flake check in sandbox\"; fi'";
              language = "system";
              pass_filenames = false;
            };
          };

          devShells.default = pkgs.mkShell {
            shellHook = ''
              ${config.pre-commit.installationScript}
              echo "OpenWrt Build Environment Ready"
            '';

            nativeBuildInputs = with pkgs; [
              # Essential build tools
              git
              binutils
              patch
              perl
              wget
              unzip
              which
              diffutils

              # Python + UV
              python3
              uv

              # Linters and formatters
              config.treefmt.build.wrapper
              pkgs.zizmor
              pkgs.actionlint
              pkgs.ruff
            ];
          };
        };
    };
}
