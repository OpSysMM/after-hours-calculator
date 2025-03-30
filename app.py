import os
import math
from flask import Flask, render_template, request

app = Flask(__name__)

CITY_CONDITIONS = {
    'Chicago': {'temp': 50, 'rh': 70},
    'Miami': {'temp': 75, 'rh': 75},
    'Dallas': {'temp': 65, 'rh': 65},
    'Los Angeles': {'temp': 64, 'rh': 65},
    'New York': {'temp': 55, 'rh': 70},
    'Seattle': {'temp': 52, 'rh': 80},
    'Phoenix': {'temp': 77, 'rh': 35},
    'Atlanta': {'temp': 63, 'rh': 68},
    'Denver': {'temp': 50, 'rh': 55},
    'Boston': {'temp': 51, 'rh': 66},
    'San Francisco': {'temp': 59, 'rh': 75}
}

BUILDING_TYPE_BASE_LOAD = {
    'Office': 30,
    'Retail': 35,
    'Warehouse': 20,
    'Data Center': 50
}

INSULATION_FACTOR = {
    'Low': 1.2,
    'Medium': 1.0,
    'High': 0.8
}

HVAC_SYSTEM_COP = {
    'Rooftop Unit': 3.0,
    'Chiller': 4.0,
    'Heat Pump': 3.5,
    'VRF System': 4.5,
    'Geothermal HP': 4.0,
    'DX Split System': 3.2
}

INFILTRATION_PRESETS = {
    'Low (Tight Building)': 0.04,
    'Medium': 0.09,
    'High (Leaky Building)': 0.18
}

OCCUPANT_LATENT_PRESETS = {
    'Low Activity (Seated, Quiet)': 150,
    'Medium Activity (Typical Office/Retail)': 200,
    'High Activity (Active, Light Exercise)': 300
}

OCCUPANT_SENSIBLE_GAIN = 350
INDOOR_SETPOINT = 72.0
INDOOR_RH = 50.0
BTU_PER_KWH = 3412

def saturation_pressure_h2o(temp_f):
    t_c = (temp_f - 32) * 5.0 / 9.0
    c1, c2, c3 = 18.678, 257.14, 234.5
    psat_kpa = 0.61121 * math.exp((c1 - (t_c / c3)) * (t_c / (c2 + t_c)))
    return psat_kpa

def humidity_ratio(temp_f, rh_percent, pressure_atm=1.0):
    psat_kpa = saturation_pressure_h2o(temp_f)
    pwater_kpa = (rh_percent / 100.0) * psat_kpa
    ptotal_kpa = 101.325 * pressure_atm
    if pwater_kpa >= (ptotal_kpa - 0.1):
        pwater_kpa = ptotal_kpa * 0.99
    return 0.622 * (pwater_kpa / (ptotal_kpa - pwater_kpa))

@app.route('/', methods=['GET', 'POST'])
def hvac_calculator():
    form_data = {
        'city': 'Chicago', 'building_type': 'Office', 'area': '',
        'window_area': '', 'num_tenancies': '', 'electric_rate': '',
        'hvac_system': 'Rooftop Unit', 'hvac_efficiency': '', 'insulation_level': 'Medium',
        'occupancy_count': '', 'hvac_capital_cost': '', 'hvac_lifespan_years': '',
        'annual_operating_hours': '', 'infiltration_preset': '', 'infiltration_cfm': '',
        'occupant_latent_preset': ''
    }

    cost_per_hour = None
    cost_per_tenant = None
    debug_info = {}

    if request.method == 'POST':
        def float_or_zero(val): return float(val) if val else 0.0
        def int_or_zero(val): return int(val) if val else 0

        city = request.form.get('city', 'Chicago')
        building_type = request.form.get('building_type', 'Office')
        hvac_system = request.form.get('hvac_system', 'Rooftop Unit')
        insulation_level = request.form.get('insulation_level', 'Medium')

        area = float_or_zero(request.form.get('area'))
        window_area = float_or_zero(request.form.get('window_area'))
        num_tenancies = int_or_zero(request.form.get('num_tenancies'))
        electric_rate = float_or_zero(request.form.get('electric_rate'))
        hvac_eff_override = float_or_zero(request.form.get('hvac_efficiency'))
        occupancy_count = int_or_zero(request.form.get('occupancy_count'))
        hvac_capital_cost = float_or_zero(request.form.get('hvac_capital_cost'))
        hvac_lifespan_years = float_or_zero(request.form.get('hvac_lifespan_years'))
        annual_operating_hours = float_or_zero(request.form.get('annual_operating_hours'))

        infiltration_preset = request.form.get('infiltration_preset', '')
        infiltration_cfm_text = request.form.get('infiltration_cfm', '')
        try: infiltration_cfm_custom = float(infiltration_cfm_text)
        except ValueError: infiltration_cfm_custom = 0.0

        occupant_latent_preset_key = request.form.get('occupant_latent_preset', '')

        area = max(area, 0)
        num_tenancies = max(num_tenancies, 1)
        electric_rate = max(electric_rate, 0)
        hvac_lifespan_years = max(hvac_lifespan_years, 1)
        annual_operating_hours = max(annual_operating_hours, 1)

        default_cop = HVAC_SYSTEM_COP.get(hvac_system, 3.0)
        cop = hvac_eff_override if hvac_eff_override > 0 else default_cop

        outdoor_temp = CITY_CONDITIONS.get(city, {'temp': 60})['temp']
        outdoor_rh = CITY_CONDITIONS.get(city, {'rh': 60})['rh']
        delta_t = outdoor_temp - INDOOR_SETPOINT
        mode = "Cooling" if delta_t > 0 else "Heating"

        base_load = BUILDING_TYPE_BASE_LOAD.get(building_type, 30)
        insulation_mult = INSULATION_FACTOR.get(insulation_level, 1.0)
        window_mult = 1.0 + 0.002 * window_area
        envelope_load_per_ft2 = base_load * insulation_mult * window_mult * abs(delta_t)
        envelope_load_btu_h = envelope_load_per_ft2 * area

        occupant_sensible_load = occupancy_count * OCCUPANT_SENSIBLE_GAIN * (1 if delta_t > 0 else -1)
        total_sensible_load_btu_h = max(envelope_load_btu_h + occupant_sensible_load, 0)

        if infiltration_cfm_custom > 0:
            infiltration_cfm = infiltration_cfm_custom
        else:
            preset_rate = INFILTRATION_PRESETS.get(infiltration_preset, 0)
            infiltration_cfm = preset_rate * area

        w_out = humidity_ratio(outdoor_temp, outdoor_rh)
        w_in = humidity_ratio(INDOOR_SETPOINT, INDOOR_RH)
        mass_flow_dry_air_per_hr = infiltration_cfm * 60.0 * 0.075

        if delta_t > 0:
            infiltration_latent_btu_h = mass_flow_dry_air_per_hr * max(w_out - w_in, 0) * 1061.0
        else:
            infiltration_latent_btu_h = mass_flow_dry_air_per_hr * max(w_in - w_out, 0) * 1061.0

        occupant_latent = OCCUPANT_LATENT_PRESETS.get(occupant_latent_preset_key, 200)
        occupant_latent_load = occupancy_count * occupant_latent if delta_t > 0 else 0

        total_latent_load_btu_h = infiltration_latent_btu_h + occupant_latent_load
        total_load_btu_h = total_sensible_load_btu_h + total_latent_load_btu_h
        power_input_kW = total_load_btu_h / (BTU_PER_KWH * cop) if cop > 0 else 0

        energy_cost_per_hour = power_input_kW * electric_rate
        depreciation_cost_per_hour = hvac_capital_cost / (hvac_lifespan_years * annual_operating_hours)
        cost_per_hour = energy_cost_per_hour + depreciation_cost_per_hour
        cost_per_tenant = cost_per_hour / num_tenancies

        form_data.update({k: request.form.get(k, '') for k in form_data})
        debug_info = {
            'City': city,
            'Outdoor Temp (°F)': outdoor_temp,
            'Delta T': f"{delta_t:.1f}",
            'Sensible Load (BTU/h)': f"{total_sensible_load_btu_h:.0f}",
            'Latent Load (BTU/h)': f"{total_latent_load_btu_h:.0f}",
            'Total Load (BTU/h)': f"{total_load_btu_h:.0f}",
            'COP Used': f"{cop:.2f}",
            'kW Input': f"{power_input_kW:.2f}",
            'Cost/hr': f"${cost_per_hour:.2f}",
            'Cost/Tenant': f"${cost_per_tenant:.2f}"
        }

    return render_template(
        'index.html',
        form_data=form_data,
        cost_per_hour=cost_per_hour,
        cost_per_tenant=cost_per_tenant,
        debug_info=debug_info
    )

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
