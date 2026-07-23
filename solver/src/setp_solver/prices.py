from __future__ import annotations

from dataclasses import dataclass

from .charging_curve import L100_CONTROL


# ---------------------------------------------------------------------------
# 区块A: Goeke 物理与能耗参数
# 本区块全部参数取自算例基准文献, 与生成算例的物理基础保持一致, 审计时以此为准。
# 主参考文献:
#   GOEKE D, SCHNEIDER M. Routing a mixed fleet of electric and conventional
#   vehicles[J]. European Journal of Operational Research, 2015, 245(1): 81-99.
#   DOI:10.1016/j.ejor.2015.01.049.
# 原始参数来源:
#   DEMIR E, BEKTAS T, LAPORTE G. An adaptive large neighborhood search
#   heuristic for the pollution-routing problem[J]. European Journal of
#   Operational Research, 2012, 223(2): 346-359.
#   DOI:10.1016/j.ejor.2012.06.044.
# ---------------------------------------------------------------------------

g0 = 9.81  # m/s^2, 重力加速度。Goeke(2015)Table 4: g=9.81。参考文献: GOEKE D, SCHNEIDER M. Routing a mixed fleet of electric and conventional vehicles[J]. European Journal of Operational Research, 2015, 245(1): 81-99. DOI:10.1016/j.ejor.2015.01.049; DEMIR E, BEKTAS T, LAPORTE G. An adaptive large neighborhood search heuristic for the pollution-routing problem[J]. European Journal of Operational Research, 2012, 223(2): 346-359. DOI:10.1016/j.ejor.2012.06.044.
rho_a = 1.2041  # kg/m^3, 空气密度。Goeke(2015)Table 4 原值。参考文献: GOEKE D, SCHNEIDER M. Routing a mixed fleet of electric and conventional vehicles[J]. European Journal of Operational Research, 2015, 245(1): 81-99. DOI:10.1016/j.ejor.2015.01.049; DEMIR E, BEKTAS T, LAPORTE G. An adaptive large neighborhood search heuristic for the pollution-routing problem[J]. European Journal of Operational Research, 2012, 223(2): 346-359. DOI:10.1016/j.ejor.2012.06.044.
c_d = 0.7  # 无量纲, 空气阻力系数。Goeke(2015)Table 4 原值。参考文献: GOEKE D, SCHNEIDER M. Routing a mixed fleet of electric and conventional vehicles[J]. European Journal of Operational Research, 2015, 245(1): 81-99. DOI:10.1016/j.ejor.2015.01.049; DEMIR E, BEKTAS T, LAPORTE G. An adaptive large neighborhood search heuristic for the pollution-routing problem[J]. European Journal of Operational Research, 2012, 223(2): 346-359. DOI:10.1016/j.ejor.2012.06.044.
c_r = 0.01  # 无量纲, 滚动阻力系数。Goeke(2015)Table 4 原值。参考文献: GOEKE D, SCHNEIDER M. Routing a mixed fleet of electric and conventional vehicles[J]. European Journal of Operational Research, 2015, 245(1): 81-99. DOI:10.1016/j.ejor.2015.01.049; DEMIR E, BEKTAS T, LAPORTE G. An adaptive large neighborhood search heuristic for the pollution-routing problem[J]. European Journal of Operational Research, 2012, 223(2): 346-359. DOI:10.1016/j.ejor.2012.06.044.
A_frontal = 3.912  # m^2, 迎风面积。Goeke(2015)Table 4 原值。参考文献: GOEKE D, SCHNEIDER M. Routing a mixed fleet of electric and conventional vehicles[J]. European Journal of Operational Research, 2015, 245(1): 81-99. DOI:10.1016/j.ejor.2015.01.049; DEMIR E, BEKTAS T, LAPORTE G. An adaptive large neighborhood search heuristic for the pollution-routing problem[J]. European Journal of Operational Research, 2012, 223(2): 346-359. DOI:10.1016/j.ejor.2012.06.044.
m_curb = 6350.0  # kg, 整车整备质量。Goeke(2015)Table 4: mc=6350。参考文献: GOEKE D, SCHNEIDER M. Routing a mixed fleet of electric and conventional vehicles[J]. European Journal of Operational Research, 2015, 245(1): 81-99. DOI:10.1016/j.ejor.2015.01.049; DEMIR E, BEKTAS T, LAPORTE G. An adaptive large neighborhood search heuristic for the pollution-routing problem[J]. European Journal of Operational Research, 2012, 223(2): 346-359. DOI:10.1016/j.ejor.2012.06.044.
m_unit = 1.0  # kg, 单位货物质量。Goeke(2015)Table 4: mu=1。参考文献: GOEKE D, SCHNEIDER M. Routing a mixed fleet of electric and conventional vehicles[J]. European Journal of Operational Research, 2015, 245(1): 81-99. DOI:10.1016/j.ejor.2015.01.049; DEMIR E, BEKTAS T, LAPORTE G. An adaptive large neighborhood search heuristic for the pollution-routing problem[J]. European Journal of Operational Research, 2012, 223(2): 346-359. DOI:10.1016/j.ejor.2012.06.044.
Q_capacity = 3650.0  # kg, 车辆载重容量。Goeke(2015)Table 4: Q=3650。09r 后按用户确认的车辆数硬上限口径恢复 Goeke 容量；历史本地生成器曾用 ScenarioConfig.vehicle_capacity=1600, 非 Goeke 原值，若作 UK light-van 场景需另行成文解释。参考文献: GOEKE D, SCHNEIDER M. Routing a mixed fleet of electric and conventional vehicles[J]. European Journal of Operational Research, 2015, 245(1): 81-99. DOI:10.1016/j.ejor.2015.01.049; DEMIR E, BEKTAS T, LAPORTE G. An adaptive large neighborhood search heuristic for the pollution-routing problem[J]. European Journal of Operational Research, 2012, 223(2): 346-359. DOI:10.1016/j.ejor.2012.06.044.
v_speed_ms = 25.0  # m/s, 固定速度=90 km/h。Goeke(2015)6.2 节采用 PRP 速度上限 90 km/h; 09h 判定该值保留为跨城/高速 regime, 40 km/h 仅作为 urban/local fork。参考文献: GOEKE D, SCHNEIDER M. Routing a mixed fleet of electric and conventional vehicles[J]. European Journal of Operational Research, 2015, 245(1): 81-99. DOI:10.1016/j.ejor.2015.01.049.
k_engine = 0.2  # kJ/(rev·L), 发动机摩擦因子。Goeke(2015)Table 4 原值。参考文献: GOEKE D, SCHNEIDER M. Routing a mixed fleet of electric and conventional vehicles[J]. European Journal of Operational Research, 2015, 245(1): 81-99. DOI:10.1016/j.ejor.2015.01.049; DEMIR E, BEKTAS T, LAPORTE G. An adaptive large neighborhood search heuristic for the pollution-routing problem[J]. European Journal of Operational Research, 2012, 223(2): 346-359. DOI:10.1016/j.ejor.2012.06.044.
xi_fuel_air = 1.0  # 无量纲, 燃空质量比。Goeke(2015)Table 4 原值。参考文献: GOEKE D, SCHNEIDER M. Routing a mixed fleet of electric and conventional vehicles[J]. European Journal of Operational Research, 2015, 245(1): 81-99. DOI:10.1016/j.ejor.2015.01.049; DEMIR E, BEKTAS T, LAPORTE G. An adaptive large neighborhood search heuristic for the pollution-routing problem[J]. European Journal of Operational Research, 2012, 223(2): 346-359. DOI:10.1016/j.ejor.2012.06.044.
eta_diesel = 0.9  # 无量纲, 柴油机效率。Goeke(2015)Table 4 原值。参考文献: GOEKE D, SCHNEIDER M. Routing a mixed fleet of electric and conventional vehicles[J]. European Journal of Operational Research, 2015, 245(1): 81-99. DOI:10.1016/j.ejor.2015.01.049; DEMIR E, BEKTAS T, LAPORTE G. An adaptive large neighborhood search heuristic for the pollution-routing problem[J]. European Journal of Operational Research, 2012, 223(2): 346-359. DOI:10.1016/j.ejor.2012.06.044.
eta_tf = 0.4  # 无量纲, 传动系效率。Goeke(2015)Table 4 原值。参考文献: GOEKE D, SCHNEIDER M. Routing a mixed fleet of electric and conventional vehicles[J]. European Journal of Operational Research, 2015, 245(1): 81-99. DOI:10.1016/j.ejor.2015.01.049; DEMIR E, BEKTAS T, LAPORTE G. An adaptive large neighborhood search heuristic for the pollution-routing problem[J]. European Journal of Operational Research, 2012, 223(2): 346-359. DOI:10.1016/j.ejor.2012.06.044.
kappa_heat = 44.0  # kJ/g, 柴油热值。Goeke(2015)Table 4 原值。参考文献: GOEKE D, SCHNEIDER M. Routing a mixed fleet of electric and conventional vehicles[J]. European Journal of Operational Research, 2015, 245(1): 81-99. DOI:10.1016/j.ejor.2015.01.049; DEMIR E, BEKTAS T, LAPORTE G. An adaptive large neighborhood search heuristic for the pollution-routing problem[J]. European Journal of Operational Research, 2012, 223(2): 346-359. DOI:10.1016/j.ejor.2012.06.044.
psi_conv = 737.0  # g/L, 燃油率克转升转换因子。Goeke(2015)Table 4 原值。参考文献: GOEKE D, SCHNEIDER M. Routing a mixed fleet of electric and conventional vehicles[J]. European Journal of Operational Research, 2015, 245(1): 81-99. DOI:10.1016/j.ejor.2015.01.049; DEMIR E, BEKTAS T, LAPORTE G. An adaptive large neighborhood search heuristic for the pollution-routing problem[J]. European Journal of Operational Research, 2012, 223(2): 346-359. DOI:10.1016/j.ejor.2012.06.044.
N_engine = 33.0  # rev/s, 发动机转速。Goeke(2015)Table 4 原值。参考文献: GOEKE D, SCHNEIDER M. Routing a mixed fleet of electric and conventional vehicles[J]. European Journal of Operational Research, 2015, 245(1): 81-99. DOI:10.1016/j.ejor.2015.01.049; DEMIR E, BEKTAS T, LAPORTE G. An adaptive large neighborhood search heuristic for the pollution-routing problem[J]. European Journal of Operational Research, 2012, 223(2): 346-359. DOI:10.1016/j.ejor.2012.06.044.
D_displace = 5.0  # L, 发动机排量。Goeke(2015)Table 4 原值。参考文献: GOEKE D, SCHNEIDER M. Routing a mixed fleet of electric and conventional vehicles[J]. European Journal of Operational Research, 2015, 245(1): 81-99. DOI:10.1016/j.ejor.2015.01.049; DEMIR E, BEKTAS T, LAPORTE G. An adaptive large neighborhood search heuristic for the pollution-routing problem[J]. European Journal of Operational Research, 2012, 223(2): 346-359. DOI:10.1016/j.ejor.2012.06.044.
phi_d = 1.184692  # 无量纲, 电机放电效率系数。Goeke(2015)Table 4 原值, 见其 3.1 节回归。参考文献: GOEKE D, SCHNEIDER M. Routing a mixed fleet of electric and conventional vehicles[J]. European Journal of Operational Research, 2015, 245(1): 81-99. DOI:10.1016/j.ejor.2015.01.049.
varphi_d = 1.112434  # 无量纲, 电池放电效率系数。Goeke(2015)Table 4 原值, 见其 3.1 节回归。参考文献: GOEKE D, SCHNEIDER M. Routing a mixed fleet of electric and conventional vehicles[J]. European Journal of Operational Research, 2015, 245(1): 81-99. DOI:10.1016/j.ejor.2015.01.049.
alpha_e = phi_d * varphi_d  # 无量纲, 论文 eq:electricity 的单系数 alpha_k^e 取两级放电系数乘积。平地无下坡, 再生制动系数 phi^r/varphi^r 不实现。参考文献: GOEKE D, SCHNEIDER M. Routing a mixed fleet of electric and conventional vehicles[J]. European Journal of Operational Research, 2015, 245(1): 81-99. DOI:10.1016/j.ejor.2015.01.049.
B_battery_kwh = 80.0  # kWh, EV 电池容量。Goeke(2015)Table 4 / Davis & Figliozzi 2013 原值为 80 kWh。09h-09l 曾诊断 280 kWh 现代中型电动配送卡车情景(Volvo FL/FE Electric 公开证据边界), 但 09s 为对齐 Goeke 基线并修正实体车辆硬上限语义, 暂恢复 80 kWh 为默认值。


# ---------------------------------------------------------------------------
# 区块B: UK 2025 价格与碳参数
# 本区块为本研究情景(英国 2025)的经济与碳参数, 与 Goeke 原文的美国 2013
# 价格无关; Goeke 的 cIC/cE/cD 价格不采用。带“代理值”标注者为公开可核实
# 代理, 论文须如实表述为 proxy。
# ---------------------------------------------------------------------------

diesel_price = 1.4331  # £/L, 英国政府周度道路燃油价 ULSD 2025-11 真值。参考文献: 英国能源安全与净零部. 道路燃油周度价格[EB/OL]. (2025)[2026-06-11]. https://www.gov.uk/government/statistics/weekly-road-fuel-prices.
electricity_price = 0.82  # £/kWh, 公共快充代理值, GRIDSERVE 2025-11 DC 充电 82-89p/kWh 取低端。参考文献: GRIDSERVE. Charging tariffs[EB/OL]. (2025)[2026-06-11]. https://www.gridserve.com/.
# v2026-06-12: Q2 separates public-station and depot pre-departure charging prices.
station_electricity_price = electricity_price  # £/kWh, public station charging price; kept equal to legacy electricity_price.
depot_electricity_price = 0.1853  # £/kWh, DESNZ Quarterly Energy Prices June 2025, manufacturing non-domestic electricity 18.53 p/kWh. https://assets.publishing.service.gov.uk/media/685a9f35db207fc18744d608/quarterly-energy-prices-june-2025.pdf
depot_charge_power_kw = 22.0  # kW, depot overnight AC proxy, Mer UK fast AC depot charging 7-22 kW. https://uk.mer.eco/chargers/commercial-ev-chargers/
initial_ev_battery_kwh = 0.0  # kWh, paper bbar default for fresh static Q2/Q3 solver probes before depot precharge.
# Every new run names its charging law explicitly.  L100 is the historical
# constant-power control; nonlinear scenarios replace these three fields
# together and are validated by the shared charging kernel.
charging_curve_id = L100_CONTROL.curve_id
charging_soc_breakpoints = L100_CONTROL.soc_breakpoints
charging_relative_powers = L100_CONTROL.relative_powers
carbon_price = 0.05034  # £/kgCO2e, 主值, 折合 £50.34/tCO2e, UK ETS 2025 二级市场约 £50/t。参考文献: International Carbon Action Partnership. UK Emissions Trading System[EB/OL]. [2026-06-11]. https://icapcarbonaction.com/en/ets/uk-emissions-trading-scheme-uk-ets.
carbon_price_low = 0.04184  # £/kgCO2e, 敏感性低值, 折合 £41.84/tCO2e, UK ETS 2025 民事处罚碳价官方真值。参考文献: 英国能源安全与净零部. UK ETS civil penalty carbon price 2025[EB/OL]. (2025)[2026-06-11]. https://www.gov.uk/government/publications/participating-in-the-uk-ets/how-to-comply-with-the-uk-ets.
diesel_ef = 2.57082  # kgCO2e/L, 英国 2025 温室气体转换因子, 零售柴油(含约 3% 生物柴油混合)真值。参考文献: 英国环境食品与乡村事务部, 能源安全与净零部. 2025 government greenhouse gas conversion factors for company reporting[DB/OL]. (2025)[2026-06-11]. https://www.gov.uk/government/publications/greenhouse-gas-reporting-conversion-factors-2025.
vehicle_fixed_cost = 80.0  # £/班次, 中型柴油货车单班次启用成本代理值, 英国货车日租代理。参考文献: 代理值说明, 研究情景参数, 需在论文中明确标为 proxy.
occupancy_fee = 0.50  # £/min, 公共充电桩超时占用费代理值, 英国快充网络。参考文献: 代理值说明, 研究情景参数, 需在论文中明确标为 proxy.
# 主值=完全共享基线；95 为历史上无来源的高摩擦代理，只保留在 0/10/25/50/95 敏感性轴。
# 相关协同文献更常见成本共担/利润分配或按实际跨场往返收费；本项目不把 95 当现实标定值。
cross_site_cost = 0.0  # £/客户服务, c_tr 主值；非零档位仅作无现实标定的摩擦敏感性代理。
# v2026-06-12: V0 profit-fairness revenue proxy. National Pallets lists a
# 250 kg UK quarter-pallet shipment at £47.34 exc VAT, so rho=47.34/250.
revenue_per_kg = 0.18936  # £/kg, public UK pallet-delivery revenue proxy. https://www.nationalpallets.co.uk/pallet-delivery/uk
fairness_theta = 1.0  # dimensionless, individual-rationality default: cooperative depot profit must match independent baseline.
c_km = 0.35  # £/km, 非能源里程成本代理值, 由英国货车总运营成本中点约 65p/mile 扣除能源成本约 13.5p/mile 反推后统一取 0.35。参考文献: 代理值说明, 研究情景参数, 需在论文中明确标为 proxy.


# ---------------------------------------------------------------------------
# 区块C: 派生与单位换算说明
# CMEM 油耗率(Demir et al. 2012, Goeke 3.2 节):
#   FR = (xi / (kappa * psi)) * (k * N * D + P_M / (eta * eta_tf))   [L/s]
#   本实现中 P_M 先由 W 转为 kJ/s, 再代入上式以保持量纲一致, 且下限截 0。
#   弧油耗 f_ij = FR * t_ij, 其中 t_ij = d_ij / v。
# CMEM 机械功率(平地, 加速度=0, sin(alpha)=0, cos(alpha)=1; Goeke 式(1)):
#   P_M = (0.5 * c_d * rho_a * A * v^2 + (m_curb + m_unit * u) * g0 * c_r) * v   [W]
#   其中 u 为该弧载重(kg) = 该弧之后所有未服务客户 demand 之和。
# EV 弧电耗(Goeke 式(2), 放电):
#   b_ij = alpha_e * P_M * t_ij   [J], 转 kWh 时除以 3.6e6。
# 速度: v = 90 km/h = 25 m/s; 距离矩阵单位为 m。
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PriceParameters:
    g0: float = g0
    rho_a: float = rho_a
    c_d: float = c_d
    c_r: float = c_r
    A_frontal: float = A_frontal
    m_curb: float = m_curb
    m_unit: float = m_unit
    Q_capacity: float = Q_capacity
    v_speed_ms: float = v_speed_ms
    k_engine: float = k_engine
    xi_fuel_air: float = xi_fuel_air
    eta_diesel: float = eta_diesel
    eta_tf: float = eta_tf
    kappa_heat: float = kappa_heat
    psi_conv: float = psi_conv
    N_engine: float = N_engine
    D_displace: float = D_displace
    phi_d: float = phi_d
    varphi_d: float = varphi_d
    alpha_e: float = alpha_e
    B_battery_kwh: float = B_battery_kwh
    initial_ev_battery_kwh: float = initial_ev_battery_kwh
    diesel_price: float = diesel_price
    # Optional route-origin city overrides. The empty tuple preserves every
    # historical/default scenario; China81 formal bundles provide a complete
    # nine-city tuple and fail closed when a route-origin city is absent.
    diesel_price_by_city: tuple[tuple[str, float], ...] = ()
    electricity_price: float = electricity_price
    station_electricity_price: float = station_electricity_price
    depot_electricity_price: float = depot_electricity_price
    depot_charge_power_kw: float = depot_charge_power_kw
    carbon_price: float = carbon_price
    carbon_price_low: float = carbon_price_low
    diesel_ef: float = diesel_ef
    vehicle_fixed_cost: float = vehicle_fixed_cost
    occupancy_fee: float = occupancy_fee
    cross_site_cost: float = cross_site_cost
    revenue_per_kg: float = revenue_per_kg
    fairness_theta: float = fairness_theta
    c_km: float = c_km
    charging_curve_id: str = charging_curve_id
    charging_soc_breakpoints: tuple[float, ...] = charging_soc_breakpoints
    charging_relative_powers: tuple[float, ...] = charging_relative_powers

    @property
    def charging_occupancy_fee(self) -> float:
        return self.occupancy_fee

    @property
    def cross_site_service_cost(self) -> float:
        return self.cross_site_cost

    @property
    def diesel_emission_factor(self) -> float:
        return self.diesel_ef

    @property
    def unit_distance_cost_per_meter(self) -> float:
        return self.c_km / 1000.0


DEFAULT_PRICES = PriceParameters()
