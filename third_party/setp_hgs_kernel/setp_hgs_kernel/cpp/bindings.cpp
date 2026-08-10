#include "bindings.h"
#include "CostEvaluator.h"
#include "DurationSegment.h"
#include "DynamicBitset.h"
#include "LoadSegment.h"
#include "Matrix.h"
#include "ProblemData.h"
#include "RandomNumberGenerator.h"
#include "Route.h"
#include "Solution.h"
#include "SubPopulation.h"
#include "Trip.h"
#include "setp_hgs_kernel_docs.h"

#include <pybind11/functional.h>
#include <pybind11/numpy.h>
#include <pybind11/operators.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <algorithm>
#include <memory>
#include <optional>
#include <sstream>
#include <string>
#include <tuple>
#include <variant>

namespace py = pybind11;

using setp_hgs_kernel::CostEvaluator;
using setp_hgs_kernel::DurationSegment;
using setp_hgs_kernel::DynamicBitset;
using setp_hgs_kernel::LoadSegment;
using setp_hgs_kernel::Matrix;
using setp_hgs_kernel::PopulationParams;
using setp_hgs_kernel::ProblemData;
using setp_hgs_kernel::RandomNumberGenerator;
using setp_hgs_kernel::Route;
using setp_hgs_kernel::Solution;
using setp_hgs_kernel::SubPopulation;
using setp_hgs_kernel::Trip;

PYBIND11_MODULE(_setp_hgs_kernel, m)
{
    py::class_<DynamicBitset>(m, "DynamicBitset", DOC(setp_hgs_kernel, DynamicBitset))
        .def(py::init<size_t>(), py::arg("num_bits"))
        .def(py::self == py::self, py::arg("other"))  // this is __eq__
        .def("all", &DynamicBitset::all)
        .def("any", &DynamicBitset::any)
        .def("none", &DynamicBitset::none)
        .def("count", &DynamicBitset::count)
        .def("__len__", &DynamicBitset::size)
        .def("reset", &DynamicBitset::reset)
        .def(
            "__getitem__",
            [](DynamicBitset const &bitset, size_t idx) { return bitset[idx]; },
            py::arg("idx"))
        .def(
            "__setitem__",
            [](DynamicBitset &bitset, size_t idx, bool value)
            { bitset[idx] = value; },
            py::arg("idx"),
            py::arg("value"))
        .def("__or__", &DynamicBitset::operator|, py::arg("other"))
        .def("__and__", &DynamicBitset::operator&, py::arg("other"))
        .def("__xor__", &DynamicBitset::operator^, py::arg("other"))
        .def("__invert__", &DynamicBitset::operator~);

    py::class_<ProblemData::Client>(
        m, "Client", DOC(setp_hgs_kernel, ProblemData, Client))
        .def(py::init<setp_hgs_kernel::Coordinate,
                      setp_hgs_kernel::Coordinate,
                      std::vector<setp_hgs_kernel::Load>,
                      std::vector<setp_hgs_kernel::Load>,
                      setp_hgs_kernel::Duration,
                      setp_hgs_kernel::Duration,
                      setp_hgs_kernel::Duration,
                      setp_hgs_kernel::Duration,
                      setp_hgs_kernel::Cost,
                      bool,
                      std::optional<size_t>,
                      char const *>(),
             py::arg("x"),
             py::arg("y"),
             py::arg("delivery") = py::list(),
             py::arg("pickup") = py::list(),
             py::arg("service_duration") = 0,
             py::arg("tw_early") = 0,
             py::arg("tw_late") = std::numeric_limits<setp_hgs_kernel::Duration>::max(),
             py::arg("release_time") = 0,
             py::arg("prize") = 0,
             py::arg("required") = true,
             py::arg("group") = py::none(),
             py::kw_only(),
             py::arg("name") = "")
        .def_readonly("x", &ProblemData::Client::x)
        .def_readonly("y", &ProblemData::Client::y)
        .def_readonly("delivery",
                      &ProblemData::Client::delivery,
                      py::return_value_policy::reference_internal)
        .def_readonly("pickup",
                      &ProblemData::Client::pickup,
                      py::return_value_policy::reference_internal)
        .def_readonly("service_duration", &ProblemData::Client::serviceDuration)
        .def_readonly("tw_early", &ProblemData::Client::twEarly)
        .def_readonly("tw_late", &ProblemData::Client::twLate)
        .def_readonly("release_time", &ProblemData::Client::releaseTime)
        .def_readonly("prize", &ProblemData::Client::prize)
        .def_readonly("required", &ProblemData::Client::required)
        .def_readonly("group", &ProblemData::Client::group)
        .def_readonly("name",
                      &ProblemData::Client::name,
                      py::return_value_policy::reference_internal)
        .def(py::self == py::self)  // this is __eq__
        .def(py::pickle(
            [](ProblemData::Client const &client) {  // __getstate__
                return py::make_tuple(client.x,
                                      client.y,
                                      client.delivery,
                                      client.pickup,
                                      client.serviceDuration,
                                      client.twEarly,
                                      client.twLate,
                                      client.releaseTime,
                                      client.prize,
                                      client.required,
                                      client.group,
                                      client.name);
            },
            [](py::tuple t) {  // __setstate__
                ProblemData::Client client(
                    t[0].cast<setp_hgs_kernel::Coordinate>(),         // x
                    t[1].cast<setp_hgs_kernel::Coordinate>(),         // y
                    t[2].cast<std::vector<setp_hgs_kernel::Load>>(),  // delivery
                    t[3].cast<std::vector<setp_hgs_kernel::Load>>(),  // pickup
                    t[4].cast<setp_hgs_kernel::Duration>(),           // service duration
                    t[5].cast<setp_hgs_kernel::Duration>(),           // tw early
                    t[6].cast<setp_hgs_kernel::Duration>(),           // tw late
                    t[7].cast<setp_hgs_kernel::Duration>(),           // release time
                    t[8].cast<setp_hgs_kernel::Cost>(),               // prize
                    t[9].cast<bool>(),                      // required
                    t[10].cast<std::optional<size_t>>(),    // group
                    t[11].cast<std::string>());             // name

                return client;
            }))
        .def(
            "__str__",
            [](ProblemData::Client const &client) { return client.name; },
            py::return_value_policy::reference_internal);

    py::class_<ProblemData::Depot>(m, "Depot", DOC(setp_hgs_kernel, ProblemData, Depot))
        .def(py::init<setp_hgs_kernel::Coordinate,
                      setp_hgs_kernel::Coordinate,
                      setp_hgs_kernel::Duration,
                      setp_hgs_kernel::Duration,
                      char const *>(),
             py::arg("x"),
             py::arg("y"),
             py::arg("tw_early") = 0,
             py::arg("tw_late") = std::numeric_limits<setp_hgs_kernel::Duration>::max(),
             py::kw_only(),
             py::arg("name") = "")
        .def_readonly("x", &ProblemData::Depot::x)
        .def_readonly("y", &ProblemData::Depot::y)
        .def_readonly("tw_early", &ProblemData::Depot::twEarly)
        .def_readonly("tw_late", &ProblemData::Depot::twLate)
        .def_readonly("name",
                      &ProblemData::Depot::name,
                      py::return_value_policy::reference_internal)
        .def(py::self == py::self)  // this is __eq__
        .def(py::pickle(
            [](ProblemData::Depot const &depot) {  // __getstate__
                return py::make_tuple(
                    depot.x, depot.y, depot.twEarly, depot.twLate, depot.name);
            },
            [](py::tuple t) {  // __setstate__
                ProblemData::Depot depot(
                    t[0].cast<setp_hgs_kernel::Coordinate>(),  // x
                    t[1].cast<setp_hgs_kernel::Coordinate>(),  // y
                    t[2].cast<setp_hgs_kernel::Duration>(),    // tw early
                    t[3].cast<setp_hgs_kernel::Duration>(),    // tw late
                    t[4].cast<std::string>());       // name

                return depot;
            }))
        .def(
            "__str__",
            [](ProblemData::Depot const &depot) { return depot.name; },
            py::return_value_policy::reference_internal);

    py::class_<ProblemData::ClientGroup>(
        m, "ClientGroup", DOC(setp_hgs_kernel, ProblemData, ClientGroup))
        .def(py::init<std::vector<size_t>, bool, char const *>(),
             py::arg("clients") = py::list(),
             py::arg("required") = true,
             py::kw_only(),
             py::arg("name") = "")
        .def("add_client",
             &ProblemData::ClientGroup::addClient,
             py::arg("client"))
        .def("clear", &ProblemData::ClientGroup::clear)
        .def_property_readonly("clients",
                               &ProblemData::ClientGroup::clients,
                               py::return_value_policy::reference_internal)
        .def_readonly("required", &ProblemData::ClientGroup::required)
        .def_readonly("mutually_exclusive",
                      &ProblemData::ClientGroup::mutuallyExclusive)
        .def_readonly("name",
                      &ProblemData::ClientGroup::name,
                      py::return_value_policy::reference_internal)
        .def(py::self == py::self)  // this is __eq__
        .def(py::pickle(
            [](ProblemData::ClientGroup const &group) {  // __getstate__
                return py::make_tuple(
                    group.clients(), group.required, group.name);
            },
            [](py::tuple t) {  // __setstate__
                ProblemData::ClientGroup group(
                    t[0].cast<std::vector<size_t>>(),  // clients
                    t[1].cast<bool>(),                 // required
                    t[2].cast<std::string>());         // name

                return group;
            }))
        .def("__len__", &ProblemData::ClientGroup::size)
        .def(
            "__iter__",
            [](ProblemData::ClientGroup const &group)
            { return py::make_iterator(group.begin(), group.end()); },
            py::return_value_policy::reference_internal)
        .def(
            "__str__",
            [](ProblemData::ClientGroup const &group) { return group.name; },
            py::return_value_policy::reference_internal);

    py::class_<ProblemData::VehicleType>(
        m, "VehicleType", DOC(setp_hgs_kernel, ProblemData, VehicleType))
        .def(py::init<size_t,
                      std::vector<setp_hgs_kernel::Load>,
                      size_t,
                      size_t,
                      setp_hgs_kernel::Cost,
                      setp_hgs_kernel::Duration,
                      setp_hgs_kernel::Duration,
                      setp_hgs_kernel::Duration,
                      setp_hgs_kernel::Distance,
                      setp_hgs_kernel::Cost,
                      setp_hgs_kernel::Cost,
                      size_t,
                      std::optional<setp_hgs_kernel::Duration>,
                      std::vector<setp_hgs_kernel::Load>,
                      std::vector<size_t>,
                      size_t,
                      setp_hgs_kernel::Duration,
                      setp_hgs_kernel::Cost,
                      char const *>(),
             py::arg("num_available") = 1,
             py::arg("capacity") = py::list(),
             py::arg("start_depot") = 0,
             py::arg("end_depot") = 0,
             py::arg("fixed_cost") = 0,
             py::arg("tw_early") = 0,
             py::arg("tw_late") = std::numeric_limits<setp_hgs_kernel::Duration>::max(),
             py::arg("shift_duration")
             = std::numeric_limits<setp_hgs_kernel::Duration>::max(),
             py::arg("max_distance")
             = std::numeric_limits<setp_hgs_kernel::Distance>::max(),
             py::arg("unit_distance_cost") = 1,
             py::arg("unit_duration_cost") = 0,
             py::arg("profile") = 0,
             py::arg("start_late") = py::none(),
             py::arg("initial_load") = py::list(),
             py::arg("reload_depots") = py::list(),
             py::arg("max_reloads") = std::numeric_limits<size_t>::max(),
             py::arg("max_overtime") = 0,
             py::arg("unit_overtime_cost") = 0,
             py::kw_only(),
             py::arg("name") = "")
        .def_readonly("num_available", &ProblemData::VehicleType::numAvailable)
        .def_readonly("capacity",
                      &ProblemData::VehicleType::capacity,
                      py::return_value_policy::reference_internal)
        .def_readonly("start_depot", &ProblemData::VehicleType::startDepot)
        .def_readonly("end_depot", &ProblemData::VehicleType::endDepot)
        .def_readonly("fixed_cost", &ProblemData::VehicleType::fixedCost)
        .def_readonly("tw_early", &ProblemData::VehicleType::twEarly)
        .def_readonly("tw_late", &ProblemData::VehicleType::twLate)
        .def_readonly("shift_duration",
                      &ProblemData::VehicleType::shiftDuration)
        .def_readonly("max_distance", &ProblemData::VehicleType::maxDistance)
        .def_readonly("unit_distance_cost",
                      &ProblemData::VehicleType::unitDistanceCost)
        .def_readonly("unit_duration_cost",
                      &ProblemData::VehicleType::unitDurationCost)
        .def_readonly("profile", &ProblemData::VehicleType::profile)
        .def_readonly("start_late", &ProblemData::VehicleType::startLate)
        .def_readonly("initial_load",
                      &ProblemData::VehicleType::initialLoad,
                      py::return_value_policy::reference_internal)
        .def_readonly("reload_depots",
                      &ProblemData::VehicleType::reloadDepots,
                      py::return_value_policy::reference_internal)
        .def_readonly("max_reloads", &ProblemData::VehicleType::maxReloads)
        .def_readonly("max_overtime", &ProblemData::VehicleType::maxOvertime)
        .def_readonly("unit_overtime_cost",
                      &ProblemData::VehicleType::unitOvertimeCost)
        .def_readonly("max_duration", &ProblemData::VehicleType::maxDuration)
        .def_property_readonly("max_trips", &ProblemData::VehicleType::maxTrips)
        .def_readonly("name",
                      &ProblemData::VehicleType::name,
                      py::return_value_policy::reference_internal)
        .def("replace",
             &ProblemData::VehicleType::replace,
             py::arg("num_available") = py::none(),
             py::arg("capacity") = py::none(),
             py::arg("start_depot") = py::none(),
             py::arg("end_depot") = py::none(),
             py::arg("fixed_cost") = py::none(),
             py::arg("tw_early") = py::none(),
             py::arg("tw_late") = py::none(),
             py::arg("shift_duration") = py::none(),
             py::arg("max_distance") = py::none(),
             py::arg("unit_distance_cost") = py::none(),
             py::arg("unit_duration_cost") = py::none(),
             py::arg("profile") = py::none(),
             py::arg("start_late") = py::none(),
             py::arg("initial_load") = py::none(),
             py::arg("reload_depots") = py::none(),
             py::arg("max_reloads") = py::none(),
             py::arg("max_overtime") = py::none(),
             py::arg("unit_overtime_cost") = py::none(),
             py::kw_only(),
             py::arg("name") = py::none(),
             DOC(setp_hgs_kernel, ProblemData, VehicleType, replace))
        .def(py::self == py::self)  // this is __eq__
        .def(py::pickle(
            [](ProblemData::VehicleType const &vehicleType) {  // __getstate__
                return py::make_tuple(vehicleType.numAvailable,
                                      vehicleType.capacity,
                                      vehicleType.startDepot,
                                      vehicleType.endDepot,
                                      vehicleType.fixedCost,
                                      vehicleType.twEarly,
                                      vehicleType.twLate,
                                      vehicleType.shiftDuration,
                                      vehicleType.maxDistance,
                                      vehicleType.unitDistanceCost,
                                      vehicleType.unitDurationCost,
                                      vehicleType.profile,
                                      vehicleType.startLate,
                                      vehicleType.initialLoad,
                                      vehicleType.reloadDepots,
                                      vehicleType.maxReloads,
                                      vehicleType.maxOvertime,
                                      vehicleType.unitOvertimeCost,
                                      vehicleType.name);
            },
            [](py::tuple t) {  // __setstate__
                ProblemData::VehicleType vehicleType(
                    t[0].cast<size_t>(),                    // num available
                    t[1].cast<std::vector<setp_hgs_kernel::Load>>(),  // capacity
                    t[2].cast<size_t>(),                    // start depot
                    t[3].cast<size_t>(),                    // end depot
                    t[4].cast<setp_hgs_kernel::Cost>(),               // fixed cost
                    t[5].cast<setp_hgs_kernel::Duration>(),           // tw early
                    t[6].cast<setp_hgs_kernel::Duration>(),           // tw late
                    t[7].cast<setp_hgs_kernel::Duration>(),           // shift duration
                    t[8].cast<setp_hgs_kernel::Distance>(),           // max distance
                    t[9].cast<setp_hgs_kernel::Cost>(),       // unit distance cost
                    t[10].cast<setp_hgs_kernel::Cost>(),      // unit duration cost
                    t[11].cast<size_t>(),           // profile
                    t[12].cast<setp_hgs_kernel::Duration>(),  // start late
                    t[13].cast<std::vector<setp_hgs_kernel::Load>>(),  // initial load
                    t[14].cast<std::vector<size_t>>(),       // reload depots
                    t[15].cast<size_t>(),                    // max reloads
                    t[16].cast<setp_hgs_kernel::Duration>(),           // max overtime
                    t[17].cast<setp_hgs_kernel::Cost>(),   // unit overtime cost
                    t[18].cast<std::string>());  // name

                return vehicleType;
            }))
        .def(
            "__str__",
            [](ProblemData::VehicleType const &vehType)
            { return vehType.name; },
            py::return_value_policy::reference_internal);

    py::class_<ProblemData>(m, "ProblemData", DOC(setp_hgs_kernel, ProblemData))
        .def(py::init<std::vector<ProblemData::Client>,
                      std::vector<ProblemData::Depot>,
                      std::vector<ProblemData::VehicleType>,
                      std::vector<Matrix<setp_hgs_kernel::Distance>>,
                      std::vector<Matrix<setp_hgs_kernel::Duration>>,
                      std::vector<ProblemData::ClientGroup>>(),
             py::arg("clients"),
             py::arg("depots"),
             py::arg("vehicle_types"),
             py::arg("distance_matrices"),
             py::arg("duration_matrices"),
             py::arg("groups") = py::list())
        .def("replace",
             &ProblemData::replace,
             py::arg("clients") = py::none(),
             py::arg("depots") = py::none(),
             py::arg("vehicle_types") = py::none(),
             py::arg("distance_matrices") = py::none(),
             py::arg("duration_matrices") = py::none(),
             py::arg("groups") = py::none(),
             DOC(setp_hgs_kernel, ProblemData, replace))
        .def_property_readonly("num_clients",
                               &ProblemData::numClients,
                               DOC(setp_hgs_kernel, ProblemData, numClients))
        .def_property_readonly("num_depots",
                               &ProblemData::numDepots,
                               DOC(setp_hgs_kernel, ProblemData, numDepots))
        .def_property_readonly("num_groups",
                               &ProblemData::numGroups,
                               DOC(setp_hgs_kernel, ProblemData, numGroups))
        .def_property_readonly("num_locations",
                               &ProblemData::numLocations,
                               DOC(setp_hgs_kernel, ProblemData, numLocations))
        .def_property_readonly("num_vehicle_types",
                               &ProblemData::numVehicleTypes,
                               DOC(setp_hgs_kernel, ProblemData, numVehicleTypes))
        .def_property_readonly("num_vehicles",
                               &ProblemData::numVehicles,
                               DOC(setp_hgs_kernel, ProblemData, numVehicles))
        .def_property_readonly("num_profiles",
                               &ProblemData::numProfiles,
                               DOC(setp_hgs_kernel, ProblemData, numProfiles))
        .def_property_readonly("num_load_dimensions",
                               &ProblemData::numLoadDimensions,
                               DOC(setp_hgs_kernel, ProblemData, numLoadDimensions))
        .def(
            "location",
            [](ProblemData const &data,
               size_t idx) -> std::variant<ProblemData::Client const *,
                                           ProblemData::Depot const *>
            {
                if (idx >= data.numLocations())
                    throw py::index_error();

                auto const proxy = data.location(idx);
                if (idx < data.numDepots())
                    return proxy.depot;
                else
                    return proxy.client;
            },
            py::arg("idx"),
            py::return_value_policy::reference_internal,
            DOC(setp_hgs_kernel, ProblemData, location))
        .def("clients",
             &ProblemData::clients,
             py::return_value_policy::reference_internal,
             DOC(setp_hgs_kernel, ProblemData, clients))
        .def("depots",
             &ProblemData::depots,
             py::return_value_policy::reference_internal,
             DOC(setp_hgs_kernel, ProblemData, depots))
        .def("groups",
             &ProblemData::groups,
             py::return_value_policy::reference_internal,
             DOC(setp_hgs_kernel, ProblemData, groups))
        .def("vehicle_types",
             &ProblemData::vehicleTypes,
             py::return_value_policy::reference_internal,
             DOC(setp_hgs_kernel, ProblemData, vehicleTypes))
        .def("distance_matrices",
             &ProblemData::distanceMatrices,
             py::return_value_policy::reference_internal,
             DOC(setp_hgs_kernel, ProblemData, distanceMatrices))
        .def("duration_matrices",
             &ProblemData::durationMatrices,
             py::return_value_policy::reference_internal,
             DOC(setp_hgs_kernel, ProblemData, durationMatrices))
        .def("centroid",
             &ProblemData::centroid,
             py::return_value_policy::reference_internal,
             DOC(setp_hgs_kernel, ProblemData, centroid))
        .def("group",
             &ProblemData::group,
             py::arg("group"),
             py::return_value_policy::reference_internal,
             DOC(setp_hgs_kernel, ProblemData, group))
        .def("vehicle_type",
             &ProblemData::vehicleType,
             py::arg("vehicle_type"),
             py::return_value_policy::reference_internal,
             DOC(setp_hgs_kernel, ProblemData, vehicleType))
        .def("distance_matrix",
             &ProblemData::distanceMatrix,
             py::arg("profile"),
             py::return_value_policy::reference_internal,
             DOC(setp_hgs_kernel, ProblemData, distanceMatrix))
        .def("duration_matrix",
             &ProblemData::durationMatrix,
             py::arg("profile"),
             py::return_value_policy::reference_internal,
             DOC(setp_hgs_kernel, ProblemData, durationMatrix))
        .def("has_time_windows",
             &ProblemData::hasTimeWindows,
             DOC(setp_hgs_kernel, ProblemData, hasTimeWindows))
        .def(py::self == py::self)  // this is __eq__
        .def(py::pickle(
            [](ProblemData const &data) {  // __getstate__
                return py::make_tuple(data.clients(),
                                      data.depots(),
                                      data.vehicleTypes(),
                                      data.distanceMatrices(),
                                      data.durationMatrices(),
                                      data.groups());
            },
            [](py::tuple t) {  // __setstate__
                using Clients = std::vector<ProblemData::Client>;
                using Depots = std::vector<ProblemData::Depot>;
                using VehicleTypes = std::vector<ProblemData::VehicleType>;
                using DistMats = std::vector<setp_hgs_kernel::Matrix<setp_hgs_kernel::Distance>>;
                using DurMats = std::vector<setp_hgs_kernel::Matrix<setp_hgs_kernel::Duration>>;
                using Groups = std::vector<ProblemData::ClientGroup>;

                ProblemData data(t[0].cast<Clients>(),
                                 t[1].cast<Depots>(),
                                 t[2].cast<VehicleTypes>(),
                                 t[3].cast<DistMats>(),
                                 t[4].cast<DurMats>(),
                                 t[5].cast<Groups>());

                return data;
            }));

    py::class_<Trip>(m, "Trip", DOC(setp_hgs_kernel, Trip))
        .def(py::init<ProblemData const &,
                      std::vector<size_t>,
                      size_t,
                      std::optional<size_t>,
                      std::optional<size_t>>(),
             py::arg("data"),
             py::arg("visits"),
             py::arg("vehicle_type"),
             py::arg("start_depot") = py::none(),
             py::arg("end_depot") = py::none())
        .def("visits",
             &Trip::visits,
             py::return_value_policy::reference_internal,
             DOC(setp_hgs_kernel, Trip, visits))
        .def("distance", &Trip::distance, DOC(setp_hgs_kernel, Trip, distance))
        .def("delivery",
             &Trip::delivery,
             py::return_value_policy::reference_internal,
             DOC(setp_hgs_kernel, Trip, delivery))
        .def("pickup",
             &Trip::pickup,
             py::return_value_policy::reference_internal,
             DOC(setp_hgs_kernel, Trip, pickup))
        .def("load",
             &Trip::load,
             py::return_value_policy::reference_internal,
             DOC(setp_hgs_kernel, Trip, load))
        .def("excess_load",
             &Trip::excessLoad,
             py::return_value_policy::reference_internal,
             DOC(setp_hgs_kernel, Trip, excessLoad))
        .def("travel_duration",
             &Trip::travelDuration,
             DOC(setp_hgs_kernel, Trip, travelDuration))
        .def("service_duration",
             &Trip::serviceDuration,
             DOC(setp_hgs_kernel, Trip, serviceDuration))
        .def("release_time", &Trip::releaseTime, DOC(setp_hgs_kernel, Trip, releaseTime))
        .def("prizes", &Trip::prizes, DOC(setp_hgs_kernel, Trip, prizes))
        .def("centroid", &Trip::centroid, DOC(setp_hgs_kernel, Trip, centroid))
        .def("vehicle_type", &Trip::vehicleType, DOC(setp_hgs_kernel, Trip, vehicleType))
        .def("start_depot", &Trip::startDepot, DOC(setp_hgs_kernel, Trip, startDepot))
        .def("end_depot", &Trip::endDepot, DOC(setp_hgs_kernel, Trip, endDepot))
        .def("has_excess_load",
             &Trip::hasExcessLoad,
             DOC(setp_hgs_kernel, Trip, hasExcessLoad))
        .def(py::self == py::self)  // this is __eq__
        .def("__len__", &Trip::size, DOC(setp_hgs_kernel, Trip, size))
        .def(
            "__iter__",
            [](Trip const &trip)
            { return py::make_iterator(trip.begin(), trip.end()); },
            py::return_value_policy::reference_internal)
        .def(
            "__getitem__",
            [](Trip const &trip, int idx)
            {
                // int so we also support negative offsets from the end.
                idx = idx < 0 ? trip.size() + idx : idx;
                if (idx < 0 || static_cast<size_t>(idx) >= trip.size())
                    throw py::index_error();
                return trip[idx];
            },
            py::arg("idx"))
        .def(py::pickle(
            [](Trip const &trip) {  // __getstate__
                // Returns a tuple that completely encodes the trip's state.
                return py::make_tuple(trip.visits(),
                                      trip.distance(),
                                      trip.delivery(),
                                      trip.pickup(),
                                      trip.load(),
                                      trip.excessLoad(),
                                      trip.travelDuration(),
                                      trip.serviceDuration(),
                                      trip.releaseTime(),
                                      trip.prizes(),
                                      trip.centroid(),
                                      trip.vehicleType(),
                                      trip.startDepot(),
                                      trip.endDepot());
            },
            [](py::tuple t) {  // __setstate__
                using Coord = setp_hgs_kernel::Coordinate;
                using Centroid = std::pair<Coord, Coord>;
                using Loads = std::vector<setp_hgs_kernel::Load>;

                Trip trip(t[0].cast<Trip::Visits>(),     // visits
                          t[1].cast<setp_hgs_kernel::Distance>(),  // distance
                          t[2].cast<Loads>(),            // delivery
                          t[3].cast<Loads>(),            // pickup
                          t[4].cast<Loads>(),            // load
                          t[5].cast<Loads>(),            // excess load
                          t[6].cast<setp_hgs_kernel::Duration>(),  // travel
                          t[7].cast<setp_hgs_kernel::Duration>(),  // service
                          t[8].cast<setp_hgs_kernel::Duration>(),  // release
                          t[9].cast<setp_hgs_kernel::Cost>(),      // prizes
                          t[10].cast<Centroid>(),        // centroid
                          t[11].cast<size_t>(),          // vehicle type
                          t[12].cast<size_t>(),          // start depot
                          t[13].cast<size_t>());         // end depot

                return trip;
            }))
        .def("__str__",
             [](Trip const &trip)
             {
                 std::stringstream stream;
                 stream << trip;
                 return stream.str();
             });

    py::class_<Route::ScheduledVisit>(
        m, "ScheduledVisit", DOC(setp_hgs_kernel, Route, ScheduledVisit))
        .def_readonly("location", &Route::ScheduledVisit::location)
        .def_readonly("trip", &Route::ScheduledVisit::trip)
        .def_readonly("start_service", &Route::ScheduledVisit::startService)
        .def_readonly("end_service", &Route::ScheduledVisit::endService)
        .def_readonly("wait_duration", &Route::ScheduledVisit::waitDuration)
        .def_readonly("time_warp", &Route::ScheduledVisit::timeWarp)
        .def_property_readonly("service_duration",
                               &Route::ScheduledVisit::serviceDuration)
        .def(py::pickle(
            [](Route::ScheduledVisit const &visit) {  // __getstate__
                return py::make_tuple(visit.location,
                                      visit.trip,
                                      visit.startService,
                                      visit.endService,
                                      visit.waitDuration,
                                      visit.timeWarp);
            },
            [](py::tuple t) {  // __setstate__
                Route::ScheduledVisit visit(
                    t[0].cast<size_t>(),            // location
                    t[1].cast<size_t>(),            // trip
                    t[2].cast<setp_hgs_kernel::Duration>(),   // start service
                    t[3].cast<setp_hgs_kernel::Duration>(),   // end service
                    t[4].cast<setp_hgs_kernel::Duration>(),   // wait duration
                    t[5].cast<setp_hgs_kernel::Duration>());  // time warp

                return visit;
            }));

    py::class_<Route>(m, "Route", DOC(setp_hgs_kernel, Route))
        .def(py::init<ProblemData const &, std::vector<size_t>, size_t>(),
             py::arg("data"),
             py::arg("visits"),
             py::arg("vehicle_type"))
        .def(py::init<ProblemData const &, std::vector<Trip>, size_t>(),
             py::arg("data"),
             py::arg("visits"),  // name is compatible with other constructor
             py::arg("vehicle_type"))
        .def("num_trips", &Route::numTrips, DOC(setp_hgs_kernel, Route, numTrips))
        .def("trips",
             &Route::trips,
             py::return_value_policy::reference_internal,
             DOC(setp_hgs_kernel, Route, trips))
        .def("trip",
             &Route::trip,
             py::arg("idx"),
             py::return_value_policy::reference_internal,
             DOC(setp_hgs_kernel, Route, trip))
        .def("visits",
             &Route::visits,
             py::return_value_policy::reference_internal,
             DOC(setp_hgs_kernel, Route, visits))
        .def("distance", &Route::distance, DOC(setp_hgs_kernel, Route, distance))
        .def("distance_cost",
             &Route::distanceCost,
             DOC(setp_hgs_kernel, Route, distanceCost))
        .def("excess_distance",
             &Route::excessDistance,
             DOC(setp_hgs_kernel, Route, excessDistance))
        .def("delivery",
             &Route::delivery,
             py::return_value_policy::reference_internal,
             DOC(setp_hgs_kernel, Route, delivery))
        .def("pickup",
             &Route::pickup,
             py::return_value_policy::reference_internal,
             DOC(setp_hgs_kernel, Route, pickup))
        .def("excess_load",
             &Route::excessLoad,
             py::return_value_policy::reference_internal,
             DOC(setp_hgs_kernel, Route, excessLoad))
        .def("duration", &Route::duration, DOC(setp_hgs_kernel, Route, duration))
        .def("overtime", &Route::overtime, DOC(setp_hgs_kernel, Route, overtime))
        .def("duration_cost",
             &Route::durationCost,
             DOC(setp_hgs_kernel, Route, durationCost))
        .def("time_warp", &Route::timeWarp, DOC(setp_hgs_kernel, Route, timeWarp))
        .def("start_time", &Route::startTime, DOC(setp_hgs_kernel, Route, startTime))
        .def("end_time", &Route::endTime, DOC(setp_hgs_kernel, Route, endTime))
        .def("slack", &Route::slack, DOC(setp_hgs_kernel, Route, slack))
        .def("travel_duration",
             &Route::travelDuration,
             DOC(setp_hgs_kernel, Route, travelDuration))
        .def("service_duration",
             &Route::serviceDuration,
             DOC(setp_hgs_kernel, Route, serviceDuration))
        .def("wait_duration",
             &Route::waitDuration,
             DOC(setp_hgs_kernel, Route, waitDuration))
        .def(
            "release_time", &Route::releaseTime, DOC(setp_hgs_kernel, Route, releaseTime))
        .def("prizes", &Route::prizes, DOC(setp_hgs_kernel, Route, prizes))
        .def("centroid", &Route::centroid, DOC(setp_hgs_kernel, Route, centroid))
        .def(
            "vehicle_type", &Route::vehicleType, DOC(setp_hgs_kernel, Route, vehicleType))
        .def("start_depot", &Route::startDepot, DOC(setp_hgs_kernel, Route, startDepot))
        .def("end_depot", &Route::endDepot, DOC(setp_hgs_kernel, Route, endDepot))
        .def("is_feasible", &Route::isFeasible, DOC(setp_hgs_kernel, Route, isFeasible))
        .def("has_excess_load",
             &Route::hasExcessLoad,
             DOC(setp_hgs_kernel, Route, hasExcessLoad))
        .def("has_excess_distance",
             &Route::hasExcessDistance,
             DOC(setp_hgs_kernel, Route, hasExcessDistance))
        .def("has_time_warp",
             &Route::hasTimeWarp,
             DOC(setp_hgs_kernel, Route, hasTimeWarp))
        .def("schedule", &Route::schedule, DOC(setp_hgs_kernel, Route, schedule))
        .def("__len__", &Route::size, DOC(setp_hgs_kernel, Route, size))
        .def(
            "__iter__",
            [](Route const &route)
            { return py::make_iterator(route.begin(), route.end()); },
            py::return_value_policy::reference_internal)
        .def(
            "__getitem__",
            [](Route const &route, int idx)
            {
                // conditional so we support negative offsets from the end.
                return route[idx < 0 ? route.size() + idx : idx];
            },
            py::arg("idx"))
        .def(py::self == py::self)  // this is __eq__
        .def(py::pickle(
            [](Route const &route) {  // __getstate__
                // Returns a tuple that completely encodes the route's state.
                return py::make_tuple(route.trips(),
                                      route.distance(),
                                      route.distanceCost(),
                                      route.excessDistance(),
                                      route.delivery(),
                                      route.pickup(),
                                      route.excessLoad(),
                                      route.duration(),
                                      route.overtime(),
                                      route.durationCost(),
                                      route.timeWarp(),
                                      route.travelDuration(),
                                      route.serviceDuration(),
                                      route.startTime(),
                                      route.slack(),
                                      route.prizes(),
                                      route.centroid(),
                                      route.vehicleType(),
                                      route.startDepot(),
                                      route.endDepot(),
                                      route.schedule());
            },
            [](py::tuple t) {  // __setstate__
                using Coord = setp_hgs_kernel::Coordinate;
                using Centroid = std::pair<Coord, Coord>;
                using Trips = std::vector<Trip>;
                using Schedule = std::vector<Route::ScheduledVisit>;

                Route route(
                    t[0].cast<Trips>(),                     // trips
                    t[1].cast<setp_hgs_kernel::Distance>(),           // distance
                    t[2].cast<setp_hgs_kernel::Cost>(),               // distance cost
                    t[3].cast<setp_hgs_kernel::Distance>(),           // excess distance
                    t[4].cast<std::vector<setp_hgs_kernel::Load>>(),  // delivery
                    t[5].cast<std::vector<setp_hgs_kernel::Load>>(),  // pickup
                    t[6].cast<std::vector<setp_hgs_kernel::Load>>(),  // excess load
                    t[7].cast<setp_hgs_kernel::Duration>(),           // duration
                    t[8].cast<setp_hgs_kernel::Duration>(),           // overtime
                    t[9].cast<setp_hgs_kernel::Cost>(),               // duration cost
                    t[10].cast<setp_hgs_kernel::Duration>(),          // time warp
                    t[11].cast<setp_hgs_kernel::Duration>(),          // travel
                    t[12].cast<setp_hgs_kernel::Duration>(),          // service
                    t[13].cast<setp_hgs_kernel::Duration>(),          // start time
                    t[14].cast<setp_hgs_kernel::Duration>(),          // slack
                    t[15].cast<setp_hgs_kernel::Cost>(),              // prizes
                    t[16].cast<Centroid>(),                 // centroid
                    t[17].cast<size_t>(),                   // vehicle type
                    t[18].cast<size_t>(),                   // start depot
                    t[19].cast<size_t>(),                   // end depot
                    t[20].cast<Schedule>());                // visit schedule

                return route;
            }))
        .def("__str__",
             [](Route const &route)
             {
                 std::stringstream stream;
                 stream << route;
                 return stream.str();
             });

    m.def(
        "best_route_rotation",
        [](ProblemData const &data,
           std::vector<size_t> const &visits,
           size_t vehicleType) -> py::object
        {
            if (visits.empty())
                throw std::invalid_argument(
                    "Cannot rotate an empty route sequence.");

            using Cost = setp_hgs_kernel::Cost;
            using Distance = setp_hgs_kernel::Distance;
            using Duration = setp_hgs_kernel::Duration;
            std::optional<std::pair<Cost, size_t>> best;
            {
                py::gil_scoped_release release;
                auto const &specification = data.vehicleType(vehicleType);
                auto const &distances
                    = data.distanceMatrix(specification.profile);
                auto const &durations
                    = data.durationMatrix(specification.profile);
                auto const size = visits.size();

                std::vector<DurationSegment> durationAt;
                durationAt.reserve(size);
                Cost prizes = 0;
                for (auto const client : visits)
                {
                    ProblemData::Client const &clientData
                        = data.location(client);
                    durationAt.emplace_back(clientData);
                    prizes += clientData.prize;
                }

                std::vector<DurationSegment> durationPrefix(size);
                std::vector<DurationSegment> durationSuffix(size);
                durationPrefix[0] = durationAt[0];
                for (size_t idx = 1; idx != size; ++idx)
                    durationPrefix[idx] = DurationSegment::merge(
                        durations(visits[idx - 1], visits[idx]),
                        durationPrefix[idx - 1],
                        durationAt[idx]);
                durationSuffix[size - 1] = durationAt[size - 1];
                for (size_t idx = size - 1; idx != 0; --idx)
                    durationSuffix[idx - 1] = DurationSegment::merge(
                        durations(visits[idx - 1], visits[idx]),
                        durationAt[idx - 1],
                        durationSuffix[idx]);

                Distance internalDistance = 0;
                for (size_t idx = 1; idx != size; ++idx)
                    internalDistance
                        += distances(visits[idx - 1], visits[idx]);

                auto const dimensions = data.numLoadDimensions();
                std::vector<std::vector<LoadSegment>> loadPrefix(
                    dimensions, std::vector<LoadSegment>(size));
                std::vector<std::vector<LoadSegment>> loadSuffix(
                    dimensions, std::vector<LoadSegment>(size));
                for (size_t dim = 0; dim != dimensions; ++dim)
                {
                    ProblemData::Client const &first
                        = data.location(visits[0]);
                    loadPrefix[dim][0] = LoadSegment(first, dim);
                    for (size_t idx = 1; idx != size; ++idx)
                    {
                        ProblemData::Client const &client
                            = data.location(visits[idx]);
                        loadPrefix[dim][idx] = LoadSegment::merge(
                            loadPrefix[dim][idx - 1],
                            LoadSegment(client, dim));
                    }

                    ProblemData::Client const &last
                        = data.location(visits[size - 1]);
                    loadSuffix[dim][size - 1] = LoadSegment(last, dim);
                    for (size_t idx = size - 1; idx != 0; --idx)
                    {
                        ProblemData::Client const &client
                            = data.location(visits[idx - 1]);
                        loadSuffix[dim][idx - 1] = LoadSegment::merge(
                            LoadSegment(client, dim),
                            loadSuffix[dim][idx]);
                    }
                }

                ProblemData::Depot const &startDepot
                    = data.location(specification.startDepot);
                DurationSegment const start = DurationSegment::merge(
                    0,
                    DurationSegment(specification,
                                    specification.startLate),
                    DurationSegment(startDepot));
                ProblemData::Depot const &endDepot
                    = data.location(specification.endDepot);
                DurationSegment const end = DurationSegment::merge(
                    0,
                    DurationSegment(endDepot),
                    DurationSegment(specification, specification.twLate));

                for (size_t offset = 0; offset != visits.size(); ++offset)
                {
                    auto const first = visits[offset];
                    auto const last
                        = visits[offset == 0 ? size - 1 : offset - 1];
                    auto clientDuration = durationPrefix[size - 1];
                    auto rotatedInternalDistance = internalDistance;
                    if (offset != 0)
                    {
                        clientDuration = DurationSegment::merge(
                            durations(visits[size - 1], visits[0]),
                            durationSuffix[offset],
                            durationPrefix[offset - 1]);
                        rotatedInternalDistance
                            = internalDistance
                              - distances(visits[offset - 1], visits[offset])
                              + distances(visits[size - 1], visits[0]);
                    }

                    auto routeDuration = DurationSegment::merge(
                        durations(specification.startDepot, first),
                        start,
                        clientDuration);
                    routeDuration = DurationSegment::merge(
                        durations(last, specification.endDepot),
                        routeDuration,
                        end);
                    auto const distance
                        = distances(specification.startDepot, first)
                          + rotatedInternalDistance
                          + distances(last, specification.endDepot);
                    if (distance > specification.maxDistance
                        || routeDuration.timeWarp(
                               specification.maxDuration)
                               > 0)
                        continue;

                    bool loadFeasible = true;
                    for (size_t dim = 0; dim != dimensions; ++dim)
                    {
                        auto clientLoad = loadPrefix[dim][size - 1];
                        if (offset != 0)
                            clientLoad = LoadSegment::merge(
                                loadSuffix[dim][offset],
                                loadPrefix[dim][offset - 1]);
                        auto const load = LoadSegment::merge(
                            LoadSegment(specification, dim), clientLoad);
                        if (load.excessLoad(specification.capacity[dim]) > 0)
                        {
                            loadFeasible = false;
                            break;
                        }
                    }
                    if (!loadFeasible)
                        continue;

                    auto const duration = routeDuration.duration();
                    auto const overtime = std::max<Duration>(
                        duration - specification.shiftDuration, 0);
                    auto const cost
                        = specification.fixedCost
                          + specification.unitDistanceCost
                                * static_cast<Cost>(distance)
                          + specification.unitDurationCost
                                * static_cast<Cost>(duration)
                          + specification.unitOvertimeCost
                                * static_cast<Cost>(overtime)
                          - prizes;
                    auto const candidate = std::pair{cost, offset};
                    if (!best || candidate < *best)
                        best = candidate;
                }
            }

            if (!best)
                return py::none();
            auto rotated = visits;
            std::rotate(rotated.begin(),
                        rotated.begin() + best->second,
                        rotated.end());
            return py::make_tuple(best->first, best->second, rotated);
        },
        py::arg("data"),
        py::arg("visits"),
        py::arg("vehicle_type"));

    py::class_<Solution, std::shared_ptr<Solution>>(
        m, "Solution", DOC(setp_hgs_kernel, Solution))
        // Since Route implements __len__ and __getitem__, it is convertible to
        // std::vector<size_t> and thus a list of Routes is a valid argument for
        // both constructors. We want to avoid using the second constructor
        // since that would lose the vehicle type associations. As pybind11
        // will use the first matching constructor we put this one first.
        .def(py::init<ProblemData const &, std::vector<Route> const &>(),
             py::arg("data"),
             py::arg("routes"))
        .def(py::init<ProblemData const &,
                      std::vector<std::vector<size_t>> const &>(),
             py::arg("data"),
             py::arg("routes"))
        .def_property_readonly_static(
            "make_random",            // this is a bit of a workaround for
            [](py::object)            // classmethods, because pybind does
            {                         // not yet support those natively.
                py::options options;  // See issue 1693 in the pybind repo.
                options.disable_function_signatures();

                return py::cpp_function(
                    [](ProblemData const &data, RandomNumberGenerator &rng)
                    { return Solution(data, rng); },
                    py::arg("data"),
                    py::arg("rng"),
                    DOC(setp_hgs_kernel, Solution, Solution));
            })
        .def(
            "num_routes", &Solution::numRoutes, DOC(setp_hgs_kernel, Solution, numRoutes))
        .def("num_trips", &Solution::numTrips, DOC(setp_hgs_kernel, Solution, numTrips))
        .def("num_clients",
             &Solution::numClients,
             DOC(setp_hgs_kernel, Solution, numClients))
        .def("num_missing_clients",
             &Solution::numMissingClients,
             DOC(setp_hgs_kernel, Solution, numMissingClients))
        .def("routes",
             &Solution::routes,
             py::return_value_policy::reference_internal,
             DOC(setp_hgs_kernel, Solution, routes))
        .def("neighbours",
             &Solution::neighbours,
             py::return_value_policy::reference_internal,
             DOC(setp_hgs_kernel, Solution, neighbours))
        .def("is_feasible",
             &Solution::isFeasible,
             DOC(setp_hgs_kernel, Solution, isFeasible))
        .def("is_group_feasible",
             &Solution::isGroupFeasible,
             DOC(setp_hgs_kernel, Solution, isGroupFeasible))
        .def("is_complete",
             &Solution::isComplete,
             DOC(setp_hgs_kernel, Solution, isComplete))
        .def("has_excess_load",
             &Solution::hasExcessLoad,
             DOC(setp_hgs_kernel, Solution, hasExcessLoad))
        .def("has_excess_distance",
             &Solution::hasExcessDistance,
             DOC(setp_hgs_kernel, Solution, hasExcessDistance))
        .def("has_time_warp",
             &Solution::hasTimeWarp,
             DOC(setp_hgs_kernel, Solution, hasTimeWarp))
        .def("distance", &Solution::distance, DOC(setp_hgs_kernel, Solution, distance))
        .def("distance_cost",
             &Solution::distanceCost,
             DOC(setp_hgs_kernel, Solution, distanceCost))
        .def("duration", &Solution::duration, DOC(setp_hgs_kernel, Solution, duration))
        .def("overtime", &Solution::overtime, DOC(setp_hgs_kernel, Solution, overtime))
        .def("duration_cost",
             &Solution::durationCost,
             DOC(setp_hgs_kernel, Solution, durationCost))
        .def("excess_load",
             &Solution::excessLoad,
             DOC(setp_hgs_kernel, Solution, excessLoad))
        .def("excess_distance",
             &Solution::excessDistance,
             DOC(setp_hgs_kernel, Solution, excessDistance))
        .def("fixed_vehicle_cost",
             &Solution::fixedVehicleCost,
             DOC(setp_hgs_kernel, Solution, fixedVehicleCost))
        .def("time_warp", &Solution::timeWarp, DOC(setp_hgs_kernel, Solution, timeWarp))
        .def("prizes", &Solution::prizes, DOC(setp_hgs_kernel, Solution, prizes))
        .def("uncollected_prizes",
             &Solution::uncollectedPrizes,
             DOC(setp_hgs_kernel, Solution, uncollectedPrizes))
        .def("__copy__", [](Solution const &sol) { return Solution(sol); })
        .def(
            "__deepcopy__",
            [](Solution const &sol, py::dict) { return Solution(sol); },
            py::arg("memo"))
        .def("__hash__",
             [](Solution const &sol) { return std::hash<Solution>()(sol); })
        .def(py::self == py::self)  // this is __eq__
        .def(py::pickle(
            [](Solution const &sol) {  // __getstate__
                // Returns a tuple that completely encodes the solution's state.
                return py::make_tuple(sol.numClients(),
                                      sol.numMissingClients(),
                                      sol.distance(),
                                      sol.distanceCost(),
                                      sol.duration(),
                                      sol.overtime(),
                                      sol.durationCost(),
                                      sol.excessDistance(),
                                      sol.excessLoad(),
                                      sol.fixedVehicleCost(),
                                      sol.prizes(),
                                      sol.uncollectedPrizes(),
                                      sol.timeWarp(),
                                      sol.isGroupFeasible(),
                                      sol.routes(),
                                      sol.neighbours());
            },
            [](py::tuple t) {  // __setstate__
                using Routes = std::vector<Route>;
                using Neighbours
                    = std::vector<std::optional<std::pair<size_t, size_t>>>;

                Solution sol(
                    t[0].cast<size_t>(),                    // num clients
                    t[1].cast<size_t>(),                    // num missing
                    t[2].cast<setp_hgs_kernel::Distance>(),           // distance
                    t[3].cast<setp_hgs_kernel::Cost>(),               // distance cost
                    t[4].cast<setp_hgs_kernel::Duration>(),           // duration
                    t[5].cast<setp_hgs_kernel::Duration>(),           // overtime
                    t[6].cast<setp_hgs_kernel::Cost>(),               // duration cost
                    t[7].cast<setp_hgs_kernel::Distance>(),           // excess distance
                    t[8].cast<std::vector<setp_hgs_kernel::Load>>(),  // excess load
                    t[9].cast<setp_hgs_kernel::Cost>(),               // fixed veh cost
                    t[10].cast<setp_hgs_kernel::Cost>(),              // prizes
                    t[11].cast<setp_hgs_kernel::Cost>(),              // uncollected
                    t[12].cast<setp_hgs_kernel::Duration>(),          // time warp
                    t[13].cast<bool>(),                     // is group feasible
                    t[14].cast<Routes>(),                   // routes
                    t[15].cast<Neighbours>());              // neighbours

                return sol;
            }))
        .def("__str__",
             [](Solution const &sol)
             {
                 std::stringstream stream;
                 stream << sol;
                 return stream.str();
             });

    py::class_<CostEvaluator>(m, "CostEvaluator", DOC(setp_hgs_kernel, CostEvaluator))
        .def(py::init<std::vector<double>, double, double>(),
             py::arg("load_penalties"),
             py::arg("tw_penalty"),
             py::arg("dist_penalty"))
        .def("load_penalty",
             &CostEvaluator::loadPenalty,
             py::arg("load"),
             py::arg("capacity"),
             py::arg("dimension"),
             DOC(setp_hgs_kernel, CostEvaluator, loadPenalty))
        .def("tw_penalty",
             &CostEvaluator::twPenalty,
             py::arg("time_warp"),
             DOC(setp_hgs_kernel, CostEvaluator, twPenalty))
        .def("dist_penalty",
             &CostEvaluator::distPenalty,
             py::arg("distance"),
             py::arg("max_distance"),
             DOC(setp_hgs_kernel, CostEvaluator, distPenalty))
        .def("penalised_cost",
             &CostEvaluator::penalisedCost<Solution>,
             py::arg("solution"),
             DOC(setp_hgs_kernel, CostEvaluator, penalisedCost))
        .def("cost",
             &CostEvaluator::cost<Solution>,
             py::arg("solution"),
             DOC(setp_hgs_kernel, CostEvaluator, cost));

    py::class_<PopulationParams>(
        m, "PopulationParams", DOC(setp_hgs_kernel, PopulationParams))
        .def(py::init<size_t, size_t, size_t, size_t, double, double>(),
             py::arg("min_pop_size") = 25,
             py::arg("generation_size") = 40,
             py::arg("num_elite") = 4,
             py::arg("num_close") = 5,
             py::arg("lb_diversity") = 0.1,
             py::arg("ub_diversity") = 0.5)
        .def(py::self == py::self, py::arg("other"))  // this is __eq__
        .def_readonly("min_pop_size", &PopulationParams::minPopSize)
        .def_readonly("generation_size", &PopulationParams::generationSize)
        .def_property_readonly("max_pop_size",
                               &PopulationParams::maxPopSize,
                               DOC(setp_hgs_kernel, PopulationParams, maxPopSize))
        .def_readonly("num_elite", &PopulationParams::numElite)
        .def_readonly("num_close", &PopulationParams::numClose)
        .def_readonly("lb_diversity", &PopulationParams::lbDiversity)
        .def_readonly("ub_diversity", &PopulationParams::ubDiversity);

    py::class_<SubPopulation::Item>(m, "SubPopulationItem")
        .def_readonly("solution",
                      &SubPopulation::Item::solution,
                      py::return_value_policy::reference_internal,
                      R"doc(
                            Solution for this SubPopulationItem.

                            Returns
                            -------
                            Solution
                                Solution for this SubPopulationItem.
                      )doc")
        .def_readonly("fitness",
                      &SubPopulation::Item::fitness,
                      R"doc(
                Fitness value for this SubPopulationItem.

                Returns
                -------
                float
                    Fitness value for this SubPopulationItem.

                .. warning::

                This is a cached property that is not automatically updated.
                Before accessing the property, 
                :meth:`~SubPopulation.update_fitness` should be called unless 
                the population has not changed since the last call.
            )doc")
        .def("avg_distance_closest",
             &SubPopulation::Item::avgDistanceClosest,
             R"doc(
                Determines the average distance of the solution wrapped by this
                item to a number of solutions that are most similar to it. This 
                provides a measure of the relative 'diversity' of the wrapped
                solution.

                Returns
                -------
                float
                    The average distance/diversity of the wrapped solution.
             )doc");

    py::class_<SubPopulation>(m, "SubPopulation", DOC(setp_hgs_kernel, SubPopulation))
        .def(py::init<setp_hgs_kernel::diversity::DiversityMeasure,
                      PopulationParams const &>(),
             py::arg("diversity_op"),
             py::arg("params"),
             py::keep_alive<1, 3>())  // keep params alive
        .def("add",
             &SubPopulation::add,
             py::arg("solution"),
             py::arg("cost_evaluator"),
             DOC(setp_hgs_kernel, SubPopulation, add))
        .def("__len__", &SubPopulation::size)
        .def(
            "__getitem__",
            [](SubPopulation const &subPop, int idx)
            {
                // int so we also support negative offsets from the end.
                idx = idx < 0 ? subPop.size() + idx : idx;
                if (idx < 0 || static_cast<size_t>(idx) >= subPop.size())
                    throw py::index_error();
                return subPop[idx];
            },
            py::arg("idx"),
            py::return_value_policy::reference_internal)
        .def(
            "__iter__",
            [](SubPopulation const &subPop)
            { return py::make_iterator(subPop.cbegin(), subPop.cend()); },
            py::return_value_policy::reference_internal)
        .def("purge",
             &SubPopulation::purge,
             py::arg("cost_evaluator"),
             DOC(setp_hgs_kernel, SubPopulation, purge))
        .def("update_fitness",
             &SubPopulation::updateFitness,
             py::arg("cost_evaluator"),
             DOC(setp_hgs_kernel, SubPopulation, updateFitness));

    py::class_<LoadSegment>(m, "LoadSegment", DOC(setp_hgs_kernel, LoadSegment))
        .def(py::init<setp_hgs_kernel::Load, setp_hgs_kernel::Load, setp_hgs_kernel::Load, setp_hgs_kernel::Load>(),
             py::arg("delivery"),
             py::arg("pickup"),
             py::arg("load"),
             py::arg("excess_load") = 0)
        .def("delivery",
             &LoadSegment::delivery,
             DOC(setp_hgs_kernel, LoadSegment, delivery))
        .def("pickup", &LoadSegment::pickup, DOC(setp_hgs_kernel, LoadSegment, pickup))
        .def("load", &LoadSegment::load, DOC(setp_hgs_kernel, LoadSegment, load))
        .def("excess_load",
             &LoadSegment::excessLoad,
             py::arg("capacity"),
             DOC(setp_hgs_kernel, LoadSegment, excessLoad))
        .def("finalise",
             &LoadSegment::finalise,
             py::arg("capacity"),
             DOC(setp_hgs_kernel, LoadSegment, finalise))
        .def_static(
            "merge", &LoadSegment::merge, py::arg("first"), py::arg("second"))
        .def("__str__",
             [](LoadSegment const &segment)
             {
                 std::stringstream stream;
                 stream << segment;
                 return stream.str();
             });

    py::class_<DurationSegment>(
        m, "DurationSegment", DOC(setp_hgs_kernel, DurationSegment))
        .def(py::init<setp_hgs_kernel::Duration,
                      setp_hgs_kernel::Duration,
                      setp_hgs_kernel::Duration,
                      setp_hgs_kernel::Duration,
                      setp_hgs_kernel::Duration,
                      setp_hgs_kernel::Duration,
                      setp_hgs_kernel::Duration,
                      setp_hgs_kernel::Duration>(),
             py::arg("duration"),
             py::arg("time_warp"),
             py::arg("start_early"),
             py::arg("start_late"),
             py::arg("release_time"),
             py::arg("cum_duration") = 0,
             py::arg("cum_time_warp") = 0,
             py::arg("prev_end_late")
             = std::numeric_limits<setp_hgs_kernel::Duration>::max())
        .def("duration",
             &DurationSegment::duration,
             DOC(setp_hgs_kernel, DurationSegment, duration))
        .def("finalise_back",
             &DurationSegment::finaliseBack,
             DOC(setp_hgs_kernel, DurationSegment, finaliseBack))
        .def("finalise_front",
             &DurationSegment::finaliseFront,
             DOC(setp_hgs_kernel, DurationSegment, finaliseFront))
        .def("start_early",
             &DurationSegment::startEarly,
             DOC(setp_hgs_kernel, DurationSegment, startEarly))
        .def("start_late",
             &DurationSegment::startLate,
             DOC(setp_hgs_kernel, DurationSegment, startLate))
        .def("end_early",
             &DurationSegment::endEarly,
             DOC(setp_hgs_kernel, DurationSegment, endEarly))
        .def("end_late",
             &DurationSegment::endLate,
             DOC(setp_hgs_kernel, DurationSegment, endLate))
        .def("prev_end_late",
             &DurationSegment::prevEndLate,
             DOC(setp_hgs_kernel, DurationSegment, prevEndLate))
        .def("release_time",
             &DurationSegment::releaseTime,
             DOC(setp_hgs_kernel, DurationSegment, releaseTime))
        .def("slack",
             &DurationSegment::slack,
             DOC(setp_hgs_kernel, DurationSegment, slack))
        .def("time_warp",
             &DurationSegment::timeWarp,
             py::arg("max_duration")
             = std::numeric_limits<setp_hgs_kernel::Duration>::max(),
             DOC(setp_hgs_kernel, DurationSegment, timeWarp))
        .def_static("merge",
                    &DurationSegment::merge,
                    py::arg("edge_duration"),
                    py::arg("first"),
                    py::arg("second"))
        .def("__str__",
             [](DurationSegment const &segment)
             {
                 std::stringstream stream;
                 stream << segment;
                 return stream.str();
             });

    py::class_<RandomNumberGenerator>(
        m, "RandomNumberGenerator", DOC(setp_hgs_kernel, RandomNumberGenerator))
        .def(py::init<uint32_t>(), py::arg("seed"))
        .def(py::init<std::array<uint32_t, 4>>(), py::arg("state"))
        .def("min", &RandomNumberGenerator::min)
        .def("max", &RandomNumberGenerator::max)
        .def("__call__", &RandomNumberGenerator::operator())
        .def("rand", &RandomNumberGenerator::rand)
        .def("randint", &RandomNumberGenerator::randint<int>, py::arg("high"))
        .def("state", &RandomNumberGenerator::state);
}
