{
  description = "OpenWrt Builder - Linux x86_64";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs {
        inherit system;
        config.allowUnfree = true;
      };

    in {
      devShells.${system}.default = pkgs.mkShell {
        # Packages required to compile OpenWrt
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
        ];

        shellHook = ''
          echo "OpenWrt Build Environment Ready"
        '';
      };
    };
}
