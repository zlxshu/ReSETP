# 09h Parameter Evidence Brief: speed, battery, and scale

Date: 2026-06-23

Purpose: preserve the parameter evidence gathered after 09f, and prevent the next agent from treating the 09f fixed-replay `v_speed_ms=11.1` result as permission to relabel a cross-city benchmark as urban delivery without evidence.

## Bottom line

The 09f result is useful but not sufficient for changing the main E2 scenario. It shows that, on `e2-threeshift-200c-01`, a 40 km/h fixed-replay scenario can make mixed fleet cheaper than all-CV, while 160 kWh battery, depot-priced public charging, and zero occupancy fee are all near-flips. That is mechanism evidence, not a scenario decision.

The user's correction is right: these large E2 instances are cross-city/large-region instances, so 90 km/h is not automatically unreasonable. UK Strategic Road Network average speeds are close to 90 km/h, and goods-vehicle motorway limits are often around 60 mph for heavier trucks and higher for lighter vans. By contrast, 40 km/h belongs to an urban/local-A-road/last-mile regime, not to the default cross-city highway regime.

The more defensible suspect is battery capacity, but even that must be vehicle-class-specific. 80 kWh is a defensible literature value for Goeke-era and urban/light-duty studies, and still close to some modern large vans. It is small for modern medium/heavy electric distribution trucks, where official product data now commonly sit in the hundreds of kWh. A future parameter update must therefore match three things together: instance geography, vehicle class/mass/payload, and battery/range.

## Current repo facts

`solver/src/setp_solver/prices.py` currently defines:

| field | current value | current provenance/comment |
| --- | ---: | --- |
| `m_curb` | 6350 kg | Goeke and Schneider vehicle mass / PRP lineage |
| `Q_capacity` | 1600 kg | Current generated instance capacity, not Goeke original 3650 kg |
| `v_speed_ms` | 25.0 m/s = 90 km/h | Goeke PRP speed upper limit used for feasibility |
| `B_battery_kwh` | 80 kWh | Goeke Table 4, sourced to Davis and Figliozzi 2013 |
| `station_electricity_price` | 0.82 GBP/kWh | UK public fast-charging proxy |
| `depot_electricity_price` | 0.1853 GBP/kWh | UK non-domestic electricity proxy |
| `carbon_price` | 0.05034 GBP/kgCO2e | UK ETS proxy; must remain fixed in this lane |

09f fixed-replay facts from `baselines/e2_alns/largescale_allcv_diagnostic.md`:

| instance | 09f classifier | interpretation |
| --- | --- | --- |
| `e2-threeshift-100c-01` | `MIXED_EXISTS_MEAN_ALLCV` | A good mixed solution already exists, but seed mean is unstable. This is mostly search reliability/variance, not economic impossibility. |
| `e2-threeshift-150c-01` | `MIXED_EXISTS_MEAN_ALLCV` | Same as 100c: mixed best exists, mean and paired wins are unstable. |
| `e2-threeshift-200c-01` | `ALLCV_BEST_AND_MEAN` | This is the true all-CV dominance case under current parameters. |

For 200c, fixed replay says:

| lever | fixed replay result | evidence status |
| --- | --- | --- |
| `v_speed_ms=11.1` | mixed flips below all-CV by about 0.92% | Mechanism proof only; scenario questionable for cross-city. |
| `B_battery_kwh=160` | mixed remains about 0.51% above all-CV | Near-flip; needs vehicle-class evidence and true reopt. |
| `station_electricity_price=0.1853` | mixed remains about 0.89% above all-CV | Near-flip; assumes public charging priced like depot, not generally safe. |
| `occupancy_fee=0` | mixed remains about 0.98% above all-CV | Near-flip; removes a modeled congestion/occupancy penalty. |

## Zotero/local literature evidence

### Goeke and Schneider 2015

Local PDF: `/Users/zhouleixishu/Zotero/storage/PGY3QPNT/Goeke和Schneider _ 2015 _ Routing...pdf`

Goeke and Schneider define the E-VRPTWMF benchmark family over customer groups 10, 15, 20, 25, 50, 75, 100, 150, and 200. The local `prices.py` comments record Goeke-aligned physical parameters: 90 km/h and 80 kWh. Their original objective/economic setting is not the current UK 2025 economic setting, so Goeke BKS or fleet mix cannot be imported as a cost truth. Still, their large instances do include meaningful EV use under their original assumptions, so "large instance" alone does not prove EVs should disappear.

Use this as the physical benchmark lineage, not as UK economic proof.

### Qiu et al. 2024

Local PDF: `/Users/zhouleixishu/Zotero/storage/5EKAGHKW/Qiu 等 _ 2024 _ Routing a mixed fleet...pdf`

Extracted facts:

| item | value |
| --- | --- |
| DOI | `10.1080/00207543.2023.2296017` |
| instance lineage | Schneider/Stenger/Goeke/Solomon-derived benchmark cases |
| instance sizes | examples include 5, 10, 15, and 100 customers, with 2/3/4/20 stations |
| vehicle count | 8 ICEVs and 8 EVs |
| speed | 60 km/h |
| EV battery | 60 kWh |
| charging speed | 33 kWh/h |
| electricity price | 0.82 yuan/kWh |

This is strong post-2020 evidence that mixed-fleet EVRP papers still use 60 km/h and 60 kWh in benchmark-style instances. But it is not a reason to set a cross-city UK large instance to 40 km/h. It is closer to an urban/regional benchmark convention.

### Chen et al. 2023

Local PDF: `/Users/zhouleixishu/Zotero/storage/392IDBJI/陈婉茹 等 _ 2023 _ 碳交易机制下多中心混合车队配送路径和速度优化研究.pdf`

Extracted facts:

| item | value |
| --- | --- |
| scenario | multi-depot mixed-fleet routing and speed optimization under carbon trading |
| benchmark scale | 20 MDVRPTW instances, roughly 48/4 to 288/6 customers/depots |
| case study | Chang-Zhu-Tan supermarket distribution, 6 depots, 71 stores |
| speed bound | 30 to 60 km/h |
| EV battery | 80 kWh |
| electricity price | 0.7 yuan/kWh |
| carbon price | 0.5 yuan/kg |
| charging assumption | EVs do not recharge en route in the described model |

This supports 30-60 km/h and 80 kWh for an urban/multi-depot Chinese distribution setting. It does not support changing a cross-city UK highway benchmark to 40 km/h unless the paper explicitly reframes the scenario as city/local distribution.

### Li Ying et al. 2020

Local PDF: `/Users/zhouleixishu/Zotero/storage/3BZESE7Z/李英 等 _ 2020 _ 电动汽车传统汽车混合车队配置及路径优化模型.pdf`

Extracted facts:

| item | value |
| --- | --- |
| benchmark case | `r101-21`, 100 customers and 20 charging facilities |
| reported fleet pattern | EV:CV around 5:3 in the discussed case |
| charging behavior | EVs rely on charging facilities; one extracted case has 12 charging-facility visits |
| qualitative result | EVs need long routes to amortize fixed cost, but range limits force charging; increased range reduces charging dependence |

This supports the mechanism seen in 09f: charging dependence and route length can dominate fleet choice. It does not by itself identify a UK cross-city battery value.

## Current industry evidence

These are official or government sources checked for current vehicle/speed ranges. The purpose is not to copy a product spec into the model blindly, but to bound realistic scenario choices.

| class | source | evidence | implication |
| --- | --- | --- | --- |
| large electric van | [Mercedes-Benz eSprinter](https://www.mbvans.com/en/esprinter) | usable battery options 81 and 113 kWh; range around 150-206 miles depending configuration | 80 kWh is not absurd for a modern large van, but 113 kWh is a stronger modern-van upper option. |
| large electric van | [Ford 2025 E-Transit technical specs PDF](https://www.fromtheroad.ford.com/content/dam/fordmediasite/us/en/library/2025/specs/2025-Transit-Technical-Specs.pdf) | usable energy 89 kWh | Modern vans are often near 80-113 kWh, not hundreds of kWh. |
| electric distribution truck | [Volvo Trucks FL/FE Electric press release](https://www.volvotrucks.com/en-en/news-stories/press-releases/2023/jun/volvo-presents-electric-trucks-with-longer-range.html) | FL Electric battery capacity range 280-565 kWh; FE Electric 280-375 kWh | For medium distribution trucks, 160 kWh is conservative and 280 kWh is a defensible modern lower-bound scenario. |
| heavy electric truck | [Volvo FH Electric](https://www.volvotrucks.com/en-en/trucks/electric/volvo-fh-electric.html) | battery 360-540 kWh; usable battery energy up to 460 kWh; range up to 470 km | Heavy/highway truck scenarios require much larger batteries and likely require revisiting mass, fixed cost, and payload, not only battery kWh. |
| heavy long-haul electric truck | [Daimler Truck eActros 600](https://www.daimlertruck.com/en/newsroom/pressrelease/full-charge-for-the-future-the-first-eactros-600-on-the-road-in-europes-fleets-53166796) | three 207 kWh packs, 621 kWh installed, over 95% usable | Long-haul electric truck evidence is in the 600 kWh class; direct use in ReSETP needs a new vehicle-class calibration. |
| UK highway/regional speed | [UK DfT Strategic Road Network 2025 report](https://www.gov.uk/government/statistics/travel-time-measures-for-the-strategic-road-network-and-local-a-roads-january-to-december-2025/travel-time-measures-for-the-strategic-road-network-january-to-december-2025-report) | average SRN speed in 2025 is reported as 56.6 mph, about 91 km/h | 90 km/h is plausible for cross-city/SRN style travel. |
| UK local/urban speed | [UK DfT local A roads 2025 report](https://www.gov.uk/government/statistics/travel-time-measures-for-the-strategic-road-network-and-local-a-roads-january-to-december-2025/travel-time-measures-for-local-a-roads-january-to-december-2025-report) | urban local A roads are much slower than SRN; extracted value 17.1 mph for urban local A roads | 40 km/h belongs to local/urban road mixtures, not default highway. |
| legal speed limits | [UK speed limits](https://www.gov.uk/speed-limits) | goods-vehicle limits vary by weight and road class; heavier vehicles commonly have lower motorway limits than cars | Scenario speed should depend on vehicle class and road class. |

## Evidence-bound scenario set for the next prompt

Do not run an unlimited parameter grid first. Start with a small, named scenario set whose labels make the assumptions explicit.

| label | speed | battery | status | why it exists |
| --- | ---: | ---: | --- | --- |
| A baseline UK-Goeke hybrid | 90 km/h | 80 kWh | current baseline | Reproduce 09f and keep the source of truth. |
| B modern large van | 90 km/h | 89 or 113 kWh | evidence-bound candidate | Ford/Mercedes van-class evidence; only valid if the model's vehicle mass/payload are interpreted as van/light truck enough. |
| C conservative bridge battery | 90 km/h | 160 kWh | diagnostic candidate | 09f near-flip; not yet strongly product-backed for current mass/payload, so label as bridge/diagnostic unless evidence is added. |
| D modern distribution truck | 90 km/h | 280 kWh | evidence-bound candidate | Volvo FL lower-bound distribution-truck battery; more consistent with medium-duty distribution than 80/160 kWh. |
| E urban/local distribution | 40 km/h | 80/113/160 kWh | scenario fork, not default | Use only if the paper explicitly introduces an urban/local-A-road scenario. |
| F heavy highway electric | 90 km/h | 360/540/621 kWh | future vehicle-class fork | Requires recalibrating mass, payload, fixed cost, and likely charging assumptions; do not treat as a simple battery override. |

## Decision rules

If a 90 km/h modern-battery scenario makes mixed fleet optimal and ALNS can reliably find it, the main cross-city story can probably be preserved by updating the EV battery calibration with evidence.

If only 40 km/h flips the result, do not rewrite the cross-city benchmark to urban speed. Either split out an urban scenario or narrow the paper claim. The 09g urban-speed prompt then becomes a scenario-specific follow-up, not the mainline.

If 100c/150c still show best mixed but unstable mean, keep that in the algorithm-reliability lane. Do not call it economic impossibility.

If 200c remains all-CV under all evidence-bound single-parameter scenarios, write "single-parameter update is insufficient" and consider combinations or a paper-level statement that large cross-city UK economics favor CV under current technology and public charging prices. Do not force a mixed-fleet claim.

## Commands and local evidence trail

Representative local commands used while building this brief:

```bash
git status --short
git log --oneline -8
tail -n 50 HANDOFF.md
sed -n '1,260p' baselines/e2_alns/largescale_allcv_diagnostic.md
sed -n '1,220p' docs/handoff/codex_prompts/09g_urban_reopt_confirmation.md
rg -n "v_speed_ms|B_battery_kwh|m_curb|Q_capacity|electricity_price|carbon_price" solver/src/setp_solver/prices.py
pdftotext -layout "/Users/zhouleixishu/Zotero/storage/5EKAGHKW/Qiu 等 _ 2024 _ Routing a mixed fleet...pdf" -
pdftotext -layout "/Users/zhouleixishu/Zotero/storage/392IDBJI/陈婉茹 等 _ 2023 _ 碳交易机制下多中心混合车队配送路径和速度优化研究.pdf" -
pdftotext -layout "/Users/zhouleixishu/Zotero/storage/3BZESE7Z/李英 等 _ 2020 _ 电动汽车传统汽车混合车队配置及路径优化模型.pdf" -
sqlite3 "file:/Users/zhouleixishu/Zotero/zotero.sqlite?immutable=1" ".tables"
```

Direct write access to the live Zotero sqlite database should not be attempted. Immutable read was sufficient for discovery; PDFs were read through `pdftotext`.
