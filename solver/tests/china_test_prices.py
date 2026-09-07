"""China price fixture shared by solver unit tests.

Values are copied field-for-field from the production DEPOTSEARCH loading path
for ``cn-jjj-50c-01-DEPOTSEARCH-d996f755bd``.  They were printed from
``_load_v3_suite_bundle`` on 2026-08-30 using the sealed final-suite package,
the shared China81 runtime authority, and its declared endogenous fleet class.
"""

from setp_solver.prices import PriceParameters


CHINA_TEST_PRICES = PriceParameters(
    g0=9.81,
    rho_a=1.2041,
    c_d=0.45,
    c_r=0.01,
    A_frontal=4.6376,
    m_curb=2565.0,
    m_unit=1.0,
    Q_capacity=1735.0,
    v_speed_ms=25.0,
    k_engine=0.2,
    xi_fuel_air=1.0,
    eta_diesel=0.9,
    eta_tf=0.4,
    kappa_heat=44.0,
    psi_conv=737.0,
    N_engine=33.0,
    D_displace=5.0,
    phi_d=1.184692,
    varphi_d=1.112434,
    alpha_e=1.317891660328,
    B_battery_kwh=77.28,
    initial_ev_battery_kwh=0.0,
    diesel_price=7.48,
    diesel_price_by_city=(("beijing", 7.48),),
    electricity_price=1.2494500833333333,
    station_electricity_price=1.2494500833333333,
    depot_electricity_price=0.8494500833333333,
    depot_charge_power_kw=60.0,
    carbon_price=0.07502,
    carbon_price_low=0.05632,
    diesel_ef=2.6419028944,
    vehicle_fixed_cost=170.0,
    revenue_per_kg=1.5,
    fairness_theta=1.0,
    c_km=0.78,
    charging_curve_id="M17_FAST_SHAPE_SCALED_60KW_PWL",
    charging_soc_breakpoints=(0.0, 0.85, 0.95, 1.0),
    charging_relative_powers=(
        0.9970674486803518,
        0.45454545454545436,
        0.15151515151515166,
    ),
    depot_charging_curve_id="M17_FAST_SHAPE_SCALED_60KW_PWL",
    depot_charging_soc_breakpoints=(0.0, 0.85, 0.95, 1.0),
    depot_charging_relative_powers=(
        0.9970674486803518,
        0.45454545454545436,
        0.15151515151515166,
    ),
    public_charging_curve_id="M17_FAST_SHAPE_SCALED_60KW_PWL",
    public_charging_soc_breakpoints=(0.0, 0.85, 0.95, 1.0),
    public_charging_relative_powers=(
        0.9970674486803518,
        0.45454545454545436,
        0.15151515151515166,
    ),
)
