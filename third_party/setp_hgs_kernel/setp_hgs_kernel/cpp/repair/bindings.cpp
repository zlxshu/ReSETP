#include "greedy_repair.h"
#include "nearest_route_insert.h"
#include "repair_docs.h"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

namespace py = pybind11;

PYBIND11_MODULE(_repair, m)
{
    m.def("greedy_repair",
          &setp_hgs_kernel::repair::greedyRepair,
          py::arg("routes"),
          py::arg("unplanned"),
          py::arg("data"),
          py::arg("cost_evaluator"),
          py::call_guard<py::gil_scoped_release>(),
          DOC(setp_hgs_kernel, repair, greedyRepair));

    m.def("nearest_route_insert",
          &setp_hgs_kernel::repair::nearestRouteInsert,
          py::arg("routes"),
          py::arg("unplanned"),
          py::arg("data"),
          py::arg("cost_evaluator"),
          py::call_guard<py::gil_scoped_release>(),
          DOC(setp_hgs_kernel, repair, nearestRouteInsert));
}
