#include "greedy_repair.h"
#include "nearest_route_insert.h"
#include "repair_docs.h"
#include "sisr_repair.h"
#include "bindings.h"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

namespace py = pybind11;

PYBIND11_MODULE(_repair, m)
{
    using setp_hgs_kernel::repair::SISRInsertion;
    using setp_hgs_kernel::repair::SISRRepairResult;

    py::class_<SISRInsertion>(m, "SISRInsertion")
        .def_readonly("client", &SISRInsertion::client)
        .def_readonly("route_index", &SISRInsertion::routeIndex)
        .def_readonly("position", &SISRInsertion::position)
        .def_readonly("delta_cost", &SISRInsertion::deltaCost);

    py::class_<SISRRepairResult>(m, "SISRRepairResult")
        .def_readonly("routes", &SISRRepairResult::routes)
        .def_readonly("selected_insertions",
                      &SISRRepairResult::selectedInsertions)
        .def_readonly("positions_evaluated",
                      &SISRRepairResult::positionsEvaluated)
        .def_readonly("positions_blinked",
                      &SISRRepairResult::positionsBlinked)
        .def_readonly("new_routes_created",
                      &SISRRepairResult::newRoutesCreated)
        .def_readonly("reconstructed", &SISRRepairResult::reconstructed);

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

    m.def("sisr_repair",
          &setp_hgs_kernel::repair::sisrRepair,
          py::arg("routes"),
          py::arg("unplanned"),
          py::arg("data"),
          py::arg("cost_evaluator"),
          py::arg("rng"),
          py::arg("blink_probability"),
          py::call_guard<py::gil_scoped_release>(),
          "Faithful incremental all-route SISR recreate.");
}
