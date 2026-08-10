#include "diversity.h"
#include "diversity_docs.h"

#include <pybind11/pybind11.h>

namespace py = pybind11;

PYBIND11_MODULE(_diversity, m)
{
    m.def("broken_pairs_distance",
          &setp_hgs_kernel::diversity::brokenPairsDistance,
          py::arg("first"),
          py::arg("second"),
          DOC(setp_hgs_kernel, diversity, brokenPairsDistance));
}
