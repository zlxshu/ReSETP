#include "Genetic.h"

#include <cmath>
#include <cstdlib>
#include <iomanip>
#include <limits>
#include <numeric>

namespace
{
constexpr double INF = 1.e30;
}

void Genetic::run()
{
	/* INITIAL POPULATION: unchanged official HGS procedure. */
	population.generatePopulation();

	int nbIter;
	int nbIterNonProd = 1;
	if (params.verbose) std::cout << "----- STARTING MECHANISM-EXPERT HGS-ALNS" << std::endl;
	for (nbIter = 0;
		 nbIterNonProd <= params.ap.nbIter
		 && (params.ap.timeLimit == 0
		     || (double)(clock() - params.startTime) / (double)CLOCKS_PER_SEC < params.ap.timeLimit);
		 nbIter++)
	{
		/* SELECTION AND CROSSOVER: unchanged official HGS procedure. */
		crossoverOX(
			offspring,
			population.getBinaryTournament(),
			population.getBinaryTournament());

		/* ORDINARY HGS EDUCATION. */
		localSearch.run(offspring, params.penaltyCapacity, params.penaltyDuration);

		/*
		 * ALNS-style expert education.
		 *
		 * It is deliberately sparse and charged to the same HGS CPU-time limit.
		 * A failed expert leaves the official-HGS offspring byte-for-byte
		 * unchanged. The three available experts are:
		 *   0: dissolve one weak route and rebuild it;
		 *   1: remove the largest detours and reinsert by regret;
		 *   2: remove related route strings and reinsert by regret.
		 */
		const bool timeRemains =
			params.ap.timeLimit == 0
			|| (double)(clock() - params.startTime) / (double)CLOCKS_PER_SEC
			   < params.ap.timeLimit - 0.001;
		const clock_t elapsedTicks = clock() - params.startTime;
		const bool expertShareRemains =
			elapsedTicks <= 0
			|| (double)expertCpuTicks / (double)elapsedTicks < expertMaxCpuShare;
		if (expertEnabled
			&& timeRemains
			&& expertShareRemains
			&& nbIterNonProd >= expertMinStagnation
			&& expertConsecutiveFailures < expertFailureStop
			&& nbIter % expertInterval == 0)
		{
			const clock_t expertStarted = clock();
			applyMechanismExpert(offspring);
			expertCpuTicks += clock() - expertStarted;
		}

		bool isNewBest = population.addIndividual(offspring, true);
		if (!offspring.eval.isFeasible && params.ran() % 2 == 0)
		{
			localSearch.run(
				offspring,
				params.penaltyCapacity * 10.,
				params.penaltyDuration * 10.);
			if (offspring.eval.isFeasible)
				isNewBest = population.addIndividual(offspring, false) || isNewBest;
		}

		if (isNewBest)
		{
			nbIterNonProd = 1;
			/* A changed HGS incumbent reopens the expert lane. */
			expertConsecutiveFailures = 0;
		}
		else nbIterNonProd++;

		if (nbIter % params.ap.nbIterPenaltyManagement == 0) population.managePenalties();
		if (nbIter % params.ap.nbIterTraces == 0) population.printState(nbIter, nbIterNonProd);

		if (params.ap.timeLimit != 0 && nbIterNonProd == params.ap.nbIter)
		{
			population.restart();
			nbIterNonProd = 1;
		}
	}

	/*
	 * Publish the best expert result only after the ordinary HGS trajectory has
	 * finished. This keeps failed or merely different expert moves from
	 * perturbing the official population search during the development gate.
	 */
	const Individual * hgsBest = population.getBestFound();
	if (hgsBest != nullptr) finalHgsBestCost = hgsBest->eval.penalizedCost;
	if (expertBest != nullptr && expertBest->eval.isFeasible)
	{
		finalExpertBestCost = expertBest->eval.penalizedCost;
		population.addIndividual(*expertBest, false);
	}
	finalIterations = nbIter;

	if (params.verbose)
	{
		std::cout << "----- GENETIC ALGORITHM FINISHED AFTER " << nbIter
		          << " ITERATIONS. TIME SPENT: "
		          << (double)(clock() - params.startTime) / (double)CLOCKS_PER_SEC
		          << std::endl;
		printExpertDiagnostics();
	}
}

void Genetic::crossoverOX(
	Individual & result,
	const Individual & parent1,
	const Individual & parent2)
{
	std::vector<bool> freqClient(params.nbClients + 1, false);

	std::uniform_int_distribution<> distr(0, params.nbClients - 1);
	int start = distr(params.ran);
	int end = distr(params.ran);
	while (end == start) end = distr(params.ran);

	int j = start;
	while (j % params.nbClients != (end + 1) % params.nbClients)
	{
		result.chromT[j % params.nbClients] = parent1.chromT[j % params.nbClients];
		freqClient[result.chromT[j % params.nbClients]] = true;
		j++;
	}

	for (int i = 1; i <= params.nbClients; i++)
	{
		int temp = parent2.chromT[(end + i) % params.nbClients];
		if (!freqClient[temp])
		{
			result.chromT[j % params.nbClients] = temp;
			j++;
		}
	}

	split.generalSplit(result, parent1.eval.nbRoutes);
}

int Genetic::chooseExpert()
{
	if (expertFixedKind >= 0 && expertFixedKind <= 2) return expertFixedKind;

	/*
	 * The generic CVRP development lane adapts between the two mechanisms that
	 * showed a coherent structural rationale: weak-route dissolution and
	 * related-string rebuilding. Worst-detour removal stays available as a
	 * named ablation (kind 1), but is not mixed into the default controller.
	 */
	const double total = expertWeights[0] + expertWeights[2];
	const double draw =
		(double)expertRan() / (double)expertRan.max() * total;
	return draw <= expertWeights[0] ? 0 : 2;
}

bool Genetic::applyMechanismExpert(Individual & indiv)
{
	(void)indiv;
	const int kind = chooseExpert();
	expertDiagnostics.attempts++;
	expertDiagnostics.attemptsByKind[kind]++;

	/*
	 * Deepen the incumbent, not the fresh offspring. This mirrors the
	 * elite-education role of tailored LNS in HGS and prevents an unsuccessful
	 * expert from replacing a useful diverse offspring.
	 */
	const Individual * hgsIncumbent = population.getBestFound();
	const Individual * incumbent = hgsIncumbent;
	if (expertBest != nullptr
		&& expertBest->eval.isFeasible
		&& (incumbent == nullptr
			|| expertBest->eval.penalizedCost
			   < incumbent->eval.penalizedCost - MY_EPSILON))
	{
		incumbent = expertBest.get();
	}
	Individual candidate = incumbent == nullptr ? indiv : *incumbent;
	const bool built = ruinAndRecreate(candidate, kind);
	bool accepted = false;
	if (built)
	{
		const bool beatsIncumbent =
			candidate.eval.isFeasible
			&& (incumbent == nullptr
				|| candidate.eval.penalizedCost
				   < incumbent->eval.penalizedCost - MY_EPSILON);
		if (beatsIncumbent)
		{
			expertBest = std::make_unique<Individual>(candidate);
			accepted = true;
			expertConsecutiveFailures = 0;
			expertDiagnostics.accepted++;
			expertDiagnostics.acceptedByKind[kind]++;
		}
	}
	if (!accepted) expertConsecutiveFailures++;

	/* Ropke-Pisinger-style reaction: useful experts become more likely. */
	const double reward = accepted ? 5.0 : (built ? 0.5 : 0.0);
	expertWeights[kind] = 0.8 * expertWeights[kind] + 0.2 * reward;
	expertWeights[kind] = std::max(0.05, expertWeights[kind]);
	return accepted;
}

bool Genetic::ruinAndRecreate(Individual & candidate, int expertKind)
{
	std::vector<std::vector<int>> routes = compactRoutes(candidate);
	if (routes.empty()) return false;

	const int originalRoutes = (int)routes.size();
	const int defaultRemoval =
		std::max(4, (int)std::lround(std::sqrt((double)params.nbClients)));
	const int removalTarget =
		std::max(1, std::min(params.nbClients - 1,
			expertRemovalCount > 0 ? expertRemovalCount : defaultRemoval));
	std::vector<int> removed;
	int maxRoutes = originalRoutes;

	if (expertKind == 0)
	{
		if (originalRoutes <= 1) return false;

		/* Choose one of the three lightest/smallest routes to avoid determinism. */
		std::vector<int> ranked(originalRoutes);
		std::iota(ranked.begin(), ranked.end(), 0);
		std::sort(ranked.begin(), ranked.end(), [&](int lhs, int rhs)
		{
			const double lhsScore =
				routeLoad(routes[lhs]) / params.vehicleCapacity
				+ 0.02 * (double)routes[lhs].size();
			const double rhsScore =
				routeLoad(routes[rhs]) / params.vehicleCapacity
				+ 0.02 * (double)routes[rhs].size();
			return lhsScore < rhsScore;
		});
		const int pool = std::min(3, originalRoutes);
		const int target = ranked[expertRan() % pool];
		removed = routes[target];
		routes.erase(routes.begin() + target);
		maxRoutes = std::max(1, originalRoutes - 1);
	}
	else if (expertKind == 1)
	{
		struct Saving
		{
			double value;
			int customer;
		};
		std::vector<Saving> savings;
		for (const auto & route : routes)
		{
			for (int pos = 0; pos < (int)route.size(); pos++)
			{
				const int pred = pos == 0 ? 0 : route[pos - 1];
				const int customer = route[pos];
				const int succ = pos + 1 == (int)route.size() ? 0 : route[pos + 1];
				const double value =
					params.timeCost[pred][customer]
					+ params.timeCost[customer][succ]
					- params.timeCost[pred][succ];
				savings.push_back({value, customer});
			}
		}
		std::sort(savings.begin(), savings.end(), [](const Saving & lhs, const Saving & rhs)
		{
			return lhs.value > rhs.value;
		});
		const int pool = std::min((int)savings.size(), 3 * removalTarget);
		std::shuffle(savings.begin(), savings.begin() + pool, expertRan);
		for (int rank = 0; rank < std::min(removalTarget, pool); rank++)
			removed.push_back(savings[rank].customer);
		for (auto & route : routes)
			route.erase(
				std::remove_if(route.begin(), route.end(), [&](int customer)
				{
					return std::find(removed.begin(), removed.end(), customer) != removed.end();
				}),
				route.end());
		routes.erase(
			std::remove_if(routes.begin(), routes.end(), [](const std::vector<int> & route)
			{
				return route.empty();
			}),
			routes.end());
	}
	else
	{
		/* Related-string removal: select strings on the routes closest to a random centre. */
		const int centre = 1 + expertRan() % params.nbClients;
		std::vector<std::pair<double, int>> relatedRoutes;
		for (int routeIdx = 0; routeIdx < (int)routes.size(); routeIdx++)
		{
			double closest = INF;
			for (int customer : routes[routeIdx])
				closest = std::min(closest, params.timeCost[centre][customer]);
			relatedRoutes.push_back({closest, routeIdx});
		}
		std::sort(relatedRoutes.begin(), relatedRoutes.end());
		const int selectedRoutes = std::min(2, (int)relatedRoutes.size());
		int remaining = removalTarget;
		for (int selected = 0; selected < selectedRoutes && remaining > 0; selected++)
		{
			auto & route = routes[relatedRoutes[selected].second];
			if (route.empty()) continue;
			int anchor = 0;
			for (int pos = 1; pos < (int)route.size(); pos++)
				if (params.timeCost[centre][route[pos]]
					< params.timeCost[centre][route[anchor]])
					anchor = pos;
			const int take = std::min(
				(int)route.size(),
				std::max(1, remaining / (selectedRoutes - selected)));
			int start = anchor - (int)(expertRan() % take);
			for (int offset = 0; offset < take; offset++)
			{
				int pos = (start + offset) % (int)route.size();
				if (pos < 0) pos += route.size();
				removed.push_back(route[pos]);
			}
			route.erase(
				std::remove_if(route.begin(), route.end(), [&](int customer)
				{
					return std::find(removed.begin(), removed.end(), customer) != removed.end();
				}),
				route.end());
			remaining = removalTarget - (int)removed.size();
		}
		routes.erase(
			std::remove_if(routes.begin(), routes.end(), [](const std::vector<int> & route)
			{
				return route.empty();
			}),
			routes.end());
	}

	if (removed.empty()) return false;
	if (!regretRepair(routes, removed)) return false;

	flattenRoutes(routes, candidate);
	split.generalSplit(candidate, maxRoutes);
	localSearch.run(candidate, params.penaltyCapacity, params.penaltyDuration);
	return true;
}

bool Genetic::regretRepair(
	std::vector<std::vector<int>> & routes,
	std::vector<int> & removed)
{
	if (routes.empty())
	{
		routes.push_back({removed.back()});
		removed.pop_back();
	}

	while (!removed.empty())
	{
		int chosenRemoved = -1;
		int chosenRoute = -1;
		int chosenPosition = -1;
		double chosenRegret = -INF;
		double chosenBestCost = INF;

		for (int removedIdx = 0; removedIdx < (int)removed.size(); removedIdx++)
		{
			const int customer = removed[removedIdx];
			double best = INF;
			double second = INF;
			int bestRoute = -1;
			int bestPosition = -1;

			for (int routeIdx = 0; routeIdx < (int)routes.size(); routeIdx++)
			{
				const double load = routeLoad(routes[routeIdx]);
				const double oldExcess = std::max(0., load - params.vehicleCapacity);
				const double newExcess = std::max(
					0.,
					load + params.cli[customer].demand - params.vehicleCapacity);
				const double loadPenalty =
					params.penaltyCapacity * 4.0 * (newExcess - oldExcess);

				for (int pos = 0; pos <= (int)routes[routeIdx].size(); pos++)
				{
					const double cost =
						insertionDelta(routes[routeIdx], pos, customer) + loadPenalty;
					if (cost < best)
					{
						second = best;
						best = cost;
						bestRoute = routeIdx;
						bestPosition = pos;
					}
					else if (cost < second)
					{
						second = cost;
					}
				}
			}

			if (bestRoute < 0) continue;
			const double regret = second >= INF / 2. ? 1.e12 : second - best;
			if (regret > chosenRegret + MY_EPSILON
				|| (std::abs(regret - chosenRegret) <= MY_EPSILON
					&& best < chosenBestCost))
			{
				chosenRemoved = removedIdx;
				chosenRoute = bestRoute;
				chosenPosition = bestPosition;
				chosenRegret = regret;
				chosenBestCost = best;
			}
		}

		if (chosenRemoved < 0) return false;
		const int customer = removed[chosenRemoved];
		routes[chosenRoute].insert(
			routes[chosenRoute].begin() + chosenPosition,
			customer);
		removed.erase(removed.begin() + chosenRemoved);
	}
	return true;
}

std::vector<std::vector<int>> Genetic::compactRoutes(const Individual & indiv) const
{
	std::vector<std::vector<int>> routes;
	for (const auto & route : indiv.chromR)
		if (!route.empty()) routes.push_back(route);
	return routes;
}

void Genetic::flattenRoutes(
	const std::vector<std::vector<int>> & routes,
	Individual & indiv) const
{
	int position = 0;
	for (const auto & route : routes)
		for (int customer : route)
			indiv.chromT[position++] = customer;
	if (position != params.nbClients)
		throw std::string("Mechanism expert lost or duplicated customers");
}

double Genetic::routeLoad(const std::vector<int> & route) const
{
	double load = 0.;
	for (int customer : route) load += params.cli[customer].demand;
	return load;
}

double Genetic::insertionDelta(
	const std::vector<int> & route,
	int position,
	int customer) const
{
	const int pred = position == 0 ? 0 : route[position - 1];
	const int succ = position == (int)route.size() ? 0 : route[position];
	return params.timeCost[pred][customer]
		+ params.timeCost[customer][succ]
		- params.timeCost[pred][succ];
}

int Genetic::configuredInt(const char * name, int fallback) const
{
	const char * raw = std::getenv(name);
	if (raw == nullptr || *raw == '\0') return fallback;
	return std::atoi(raw);
}

double Genetic::configuredDouble(const char * name, double fallback) const
{
	const char * raw = std::getenv(name);
	if (raw == nullptr || *raw == '\0') return fallback;
	return std::atof(raw);
}

void Genetic::printExpertDiagnostics() const
{
	const clock_t totalTicks = clock() - params.startTime;
	std::cout
		<< "ME_HGS_ALNS_DIAGNOSTICS"
		<< " attempts=" << expertDiagnostics.attempts
		<< " accepted=" << expertDiagnostics.accepted
		<< " route_attempts=" << expertDiagnostics.attemptsByKind[0]
		<< " route_accepted=" << expertDiagnostics.acceptedByKind[0]
		<< " detour_attempts=" << expertDiagnostics.attemptsByKind[1]
		<< " detour_accepted=" << expertDiagnostics.acceptedByKind[1]
		<< " string_attempts=" << expertDiagnostics.attemptsByKind[2]
		<< " string_accepted=" << expertDiagnostics.acceptedByKind[2]
		<< " consecutive_failures=" << expertConsecutiveFailures
		<< " failure_stop=" << expertFailureStop
		<< " expert_cpu_seconds="
		<< (double)expertCpuTicks / (double)CLOCKS_PER_SEC
		<< " expert_cpu_share="
		<< (totalTicks <= 0
			? 0.
			: (double)expertCpuTicks / (double)totalTicks)
		<< " iterations=" << finalIterations
		<< " hgs_best=" << finalHgsBestCost
		<< " expert_best=" << finalExpertBestCost
		<< " weights="
		<< std::setprecision(4)
		<< expertWeights[0] << ","
		<< expertWeights[1] << ","
		<< expertWeights[2]
		<< std::endl;
}

Genetic::Genetic(Params & params)
	: expertRan((unsigned int)(params.ap.seed + 104729)),
	  params(params),
	  split(params),
	  localSearch(params),
	  population(params, this->split, this->localSearch),
	  offspring(params)
{
	expertEnabled = configuredInt("RESET_ME_EXPERT_ENABLED", 1) != 0;
	expertInterval = std::max(1, configuredInt("RESET_ME_EXPERT_INTERVAL", 10));
	expertMinStagnation = std::max(
		0,
		configuredInt("RESET_ME_EXPERT_STAGNATION", 50));
	expertFixedKind = configuredInt("RESET_ME_EXPERT_KIND", -1);
	expertRemovalCount = std::max(
		0,
		configuredInt("RESET_ME_EXPERT_REMOVAL", 0));
	expertFailureStop = std::max(
		1,
		configuredInt("RESET_ME_EXPERT_FAILURE_STOP", 40));
	expertMaxCpuShare = std::min(
		0.50,
		std::max(
			0.0,
			configuredDouble("RESET_ME_EXPERT_MAX_CPU_SHARE", 0.10)));
}
