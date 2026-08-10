# Native extensions

This folder contains all C++ extension classes and functions. These extensions
are ordered in the way they will appear in the `setp_hgs_kernel` package: everything in
this top-level folder will be made available in the top-level `setp_hgs_kernel` package,
whereas for example everything in `cpp/search` will be present in 
`setp_hgs_kernel.search` after installation (and so on for the other folders).

> When building on our implementation, please refrain from defining symbols
> starting with the `PYVRP_` prefix, or in the `setp_hgs_kernel` namespace. PyVRP
> reserves these for internal use.

## Bindings

We use `pybind11` to generate Python bindings for the C++ codebase. These
bindings are generated from the `bindings.cpp` source files of each folder. 
Each `bindings.cpp` file is compiled into a single extension module named after
the installation folder, prefixed with an underscore.

The bindings depend on header files ending in `_docs.h`. Those header files
contain docstrings that are automatically extracted from the other header files
present in this directory. The documentation headers are generated automatically
by Meson during compilation.
