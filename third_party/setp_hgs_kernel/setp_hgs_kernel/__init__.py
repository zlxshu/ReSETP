import logging
import sys

__version__ = "0.12.2"

from .GeneticAlgorithm import GeneticAlgorithm as GeneticAlgorithm
from .GeneticAlgorithm import GeneticAlgorithmParams as GeneticAlgorithmParams
from .Model import Edge as Edge
from .Model import Model as Model
from .Model import Profile as Profile
from .PenaltyManager import PenaltyManager as PenaltyManager
from .PenaltyManager import PenaltyParams as PenaltyParams
from .Population import Population as Population
from .Population import PopulationParams as PopulationParams
from .Result import Result as Result
from .Statistics import Statistics as Statistics
from ._setp_hgs_kernel import Client as Client
from ._setp_hgs_kernel import ClientGroup as ClientGroup
from ._setp_hgs_kernel import CostEvaluator as CostEvaluator
from ._setp_hgs_kernel import Depot as Depot
from ._setp_hgs_kernel import DynamicBitset as DynamicBitset
from ._setp_hgs_kernel import ProblemData as ProblemData
from ._setp_hgs_kernel import RandomNumberGenerator as RandomNumberGenerator
from ._setp_hgs_kernel import Route as Route
from ._setp_hgs_kernel import Solution as Solution
from ._setp_hgs_kernel import Trip as Trip
from ._setp_hgs_kernel import VehicleType as VehicleType
from .minimise_fleet import minimise_fleet as minimise_fleet
from .read import read as read
from .read import read_solution as read_solution
from .show_versions import show_versions as show_versions
from .solve import SolveParams as SolveParams
from .solve import solve as solve

# Sets up basic logging to stdout for PyVRP, of INFO and up. This replaces
# previous print() statements, and allows easier integration into calling
# code's own logging configuration.
_logger = logging.getLogger("setp_hgs_kernel")
_logger.addHandler(logging.StreamHandler(stream=sys.stdout))
_logger.setLevel(logging.INFO)
