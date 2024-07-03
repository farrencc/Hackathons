with import <nixpkgs> { };

let
  pythonPackages = python310Packages; # Change to Python 3.10
in pkgs.mkShell rec {
  name = "impurePythonEnv";
  venvDir = "./.venv";
  buildInputs = [

    pkgs.stdenv.cc.cc.lib

    git-crypt
    # stdenv.cc.cc # jupyter lab needs

    # pythonPackages.python
    pythonPackages.ipykernel
    pythonPackages.jupyterlab
    pythonPackages.pyzmq    # Adding pyzmq explicitly
    pythonPackages.venvShellHook
    pythonPackages.pip
    pythonPackages.numpy
    pythonPackages.pandas
    pythonPackages.requests
    pythonPackages.geopandas

    # sometimes you might need something additional like the following - you will get some useful error if it is looking for a binary in the environment.
    taglib
    openssl
    git
    libxml2
    libxslt
    libzip
    zlib

  ];
}
