with import <nixpkgs> {};

pkgs.mkShell {
  buildInputs = with pkgs; [
    xorg.libX11
    libGL
    gcc
    cmake
    gfortran
    gsl
    doxygen
  ];

  packages = [
  (pkgs.python3.withPackages(python-pkgs: [
    python-pkgs.numpy
    python-pkgs.matplotlib
    python-pkgs.scipy
    python-pkgs.pandas
    python-pkgs.geopandas
    python-pkgs.ipy
    python-pkgs.jupyterlab
    python-pkgs.notebook
    python-pkgs.geopy
  ]))
  ];

}
