/*MIT License

Copyright(c) 2020 Thibaut Vidal
Mechanism-expert additions copyright(c) 2026 ReSETP contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files(the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions :

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.*/

#ifndef GENETIC_H
#define GENETIC_H

#include "Population.h"
#include "Individual.h"
#include <array>
#include <memory>

class Genetic
{
private:

	struct ExpertDiagnostics
	{
		long attempts = 0;
		long accepted = 0;
		std::array<long, 3> attemptsByKind = {0, 0, 0};
		std::array<long, 3> acceptedByKind = {0, 0, 0};
	};

	ExpertDiagnostics expertDiagnostics;
	std::array<double, 3> expertWeights = {1.0, 1.0, 1.0};
	std::minstd_rand expertRan;
	bool expertEnabled = true;
	int expertInterval = 10;
	int expertMinStagnation = 50;
	int expertFixedKind = -1;
	int expertRemovalCount = 0;
	int expertFailureStop = 40;
	int expertConsecutiveFailures = 0;
	double expertMaxCpuShare = 0.10;
	clock_t expertCpuTicks = 0;
	std::unique_ptr<Individual> expertBest;
	double finalHgsBestCost = 1.e30;
	double finalExpertBestCost = 1.e30;
	long finalIterations = 0;

	int chooseExpert();
	bool applyMechanismExpert(Individual & indiv);
	bool ruinAndRecreate(Individual & candidate, int expertKind);
	bool regretRepair(std::vector<std::vector<int>> & routes, std::vector<int> & removed);
	std::vector<std::vector<int>> compactRoutes(const Individual & indiv) const;
	void flattenRoutes(const std::vector<std::vector<int>> & routes, Individual & indiv) const;
	double routeLoad(const std::vector<int> & route) const;
	double insertionDelta(const std::vector<int> & route, int position, int customer) const;
	int configuredInt(const char * name, int fallback) const;
	double configuredDouble(const char * name, double fallback) const;
	void printExpertDiagnostics() const;

public:

	Params & params;
	Split split;
	LocalSearch localSearch;
	Population population;
	Individual offspring;

	void crossoverOX(Individual & result, const Individual & parent1, const Individual & parent2);
	void run();
	Genetic(Params & params);
};

#endif
