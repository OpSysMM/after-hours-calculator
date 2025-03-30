from flask import Flask, render_template, request
import math

app = Flask(__name__)

# -------------------------------------------------------------------------
# 1. Hardcoded Dictionaries & Default Settings
# -------------------------------------------------------------------------

CITY_CONDITIONS = {
    'Chicago':      {'temp': 50, 'rh': 70},
    'Miami':        {'temp': 75, 'rh': 75},
    'Dallas':       {'temp': 65, 'rh': 65},
    'Los Angeles':  {'temp': 64, 'rh': 65},
    'New York':     {'temp': 55, 'rh': 70},
    'Seattle':      {'temp': 52, 'rh': 80},
    'Phoenix':      {'temp': 77, 'rh': 35},
    'Atlanta':      {'temp': 63, 'rh': 68},
    'Denver':       {'temp': 50, 'rh': 55},
    'Boston':       {'temp': 51, 'rh': 66},
    'San Francisco':{'temp': 59, 'rh': 75}
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

# Approx ASHRAE-based infiltration presets (CFM/ft²)
INFILTRATION_PRESETS = {
    'Low (Tight Building)': 0.04,
    'Medium': 0.09,
    'High (Leaky Building)': 0.18
}

# Occupant latent presets (BTU/h per occupant)
OCCUPANT_LATENT_PRESETS = {
    'Low Activity (Seated, Quiet)': 150,
    'Medium Activity (Typical Office/Retail)': 200,
    'High Activity (Active, Light Exercise)': 300
}

# Fixed occupant sensible load (BTU/h per occupant)
OCCUPANT_SENSIBLE_GAIN = 350

# Indoor setpoint & RH
INDOOR_SETPOINT = 72.0  # °F
INDOOR_RH = 50.0        # %

BTU_PER_KWH = 3412

# -----------------------------------------------------------------------------
# 2. Psychrometric Helper Functions (Simplified)
# -----------------------------------------------------------------------------

def saturation_pressure_h2o(temp_f):
    """ Simplified Buck-like equation for saturation vapor pressure (kPa). """
    t_c = (temp_f - 32) * 5.0 / 9.0
    c1 = 18.678
    c2 = 257.14
    c3 = 234.5
    psat_kpa = 0.61121 * math.exp((c1 - (t_c/c3)) * (t_c/(c2 + t_c)))
    return psat_kpa

def humidity_ratio(temp_f, rh_percent, pressure_atm=1.0):
    """ Returns approximate humidity ratio (lb_water / lb_dry_air). """
    psat_kpa = saturation_pressure_h2o(temp_f)
    pwater_kpa = (rh_percent / 100.0) * psat_kpa
    ptotal_kpa = 101.325 * pressure_atm
    if pwater_kpa >= (ptotal_kpa - 0.1):
        pwater_kpa = ptotal_kpa * 0.99
    w = 0.622 * (pwater_kpa / (ptotal_kpa - pwater_kpa))
    return w

# -----------------------------------------------------------------------------
# 3. Flask App
# -----------------------------------------------------------------------------

@app.route('/', methods=['GET', 'POST'])
def index():
    # Default form data
    form_data = {
        'city': 'Chicago',
        'building_type': 'Office',
        'area': '',
        'window_area': '',
        'num_tenancies': '',
        'electric_rate': '',
        'hvac_system': 'Rooftop Unit',
        'hvac_efficiency': '',
        'insulation_level': 'Medium',
        'occupancy_count': '',
        'hvac_capital_cost': '',
        'hvac_lifespan_years': '',
        'annual_operating_hours': '',
        'infiltration_preset': '',
        'infiltration_cfm': '',
        'occupant_latent_preset': ''  # No custom occupant latent field
    }

    cost_per_hour = None
    cost_per_tenant = None
    debug_info = {}

    if request.method == 'POST':
        # Parse inputs
        def float_or_zero(val):
            try:
                return float(val)
            except ValueError:
                return 0.0

        def int_or_zero(val):
            try:
                return int(val)
            except ValueError:
                return 0

        city = request.form.get('city', 'Chicago')
        building_type = request.form.get('building_type', 'Office')
        hvac_system = request.form.get('hvac_system', 'Rooftop Unit')
        insulation_level = request.form.get('insulation_level', 'Medium')

        area = float_or_zero(request.form.get('area', 0.0))
        window_area = float_or_zero(request.form.get('window_area', 0.0))
        num_tenancies = int_or_zero(request.form.get('num_tenancies', 1))
        electric_rate = float_or_zero(request.form.get('electric_rate', 0.0))
        hvac_eff_override = float_or_zero(request.form.get('hvac_efficiency', 0.0))
        occupancy_count = int_or_zero(request.form.get('occupancy_count', 0))
        hvac_capital_cost = float_or_zero(request.form.get('hvac_capital_cost', 0.0))
        hvac_lifespan_years = float_or_zero(request.form.get('hvac_lifespan_years', 1.0))
        annual_operating_hours = float_or_zero(request.form.get('annual_operating_hours', 1.0))

        # Infiltration
        infiltration_preset = request.form.get('infiltration_preset', '')
        infiltration_cfm_text = request.form.get('infiltration_cfm', '')
        try:
            infiltration_cfm_custom = float(infiltration_cfm_text)
        except ValueError:
            infiltration_cfm_custom = 0.0

        # Occupant latent (preset only)
        occupant_latent_preset_key = request.form.get('occupant_latent_preset', '')

        # Clamps
        area = max(area, 0)
        num_tenancies = max(num_tenancies, 1)
        electric_rate = max(electric_rate, 0)
        hvac_lifespan_years = max(hvac_lifespan_years, 1)
        annual_operating_hours = max(annual_operating_hours, 1)

        # Validate dictionary lookups
        if city not in CITY_CONDITIONS:
            city = 'Chicago'
        if building_type not in BUILDING_TYPE_BASE_LOAD:
            building_type = 'Office'
        if hvac_system not in HVAC_SYSTEM_COP:
            hvac_system = 'Rooftop Unit'
        if insulation_level not in INSULATION_FACTOR:
            insulation_level = 'Medium'

        # Determine COP
        default_cop = HVAC_SYSTEM_COP[hvac_system]
        cop = hvac_eff_override if hvac_eff_override > 0 else default_cop

        # ---------------------------------------------------------------------
        # Outdoor & Indoor Conditions
        # ---------------------------------------------------------------------
        outdoor_temp = CITY_CONDITIONS[city]['temp']
        outdoor_rh = CITY_CONDITIONS[city]['rh']
        indoor_temp = INDOOR_SETPOINT
        indoor_rh = INDOOR_RH

        delta_t = outdoor_temp - indoor_temp
        mode = "Cooling" if delta_t > 0 else "Heating"

        # ---------------------------------------------------------------------
        # Envelope & Sensible Load
        # ---------------------------------------------------------------------
        base_load = BUILDING_TYPE_BASE_LOAD[building_type]
        insulation_mult = INSULATION_FACTOR[insulation_level]
        window_mult = 1.0 + 0.002 * window_area

        envelope_load_per_ft2 = base_load * insulation_mult * window_mult * abs(delta_t)
        envelope_load_btu_h = envelope_load_per_ft2 * area

        # Occupant sensible
        if delta_t > 0:   # Cooling
            occupant_sensible_load = occupancy_count * OCCUPANT_SENSIBLE_GAIN
        else:             # Heating
            occupant_sensible_load = -occupancy_count * OCCUPANT_SENSIBLE_GAIN

        total_sensible_load_btu_h = envelope_load_btu_h + occupant_sensible_load
        if total_sensible_load_btu_h < 0:
            total_sensible_load_btu_h = 0

        # ---------------------------------------------------------------------
        # Infiltration: Preset vs. Custom
        # ---------------------------------------------------------------------
        if infiltration_cfm_custom > 0:
            infiltration_cfm = infiltration_cfm_custom
            infiltration_preset_rate = None
        else:
            if infiltration_preset in INFILTRATION_PRESETS:
                infiltration_preset_rate = INFILTRATION_PRESETS[infiltration_preset]
                infiltration_cfm = infiltration_preset_rate * area
            else:
                infiltration_preset_rate = 0.0
                infiltration_cfm = 0.0

        # ---------------------------------------------------------------------
        # Humidity Ratios
        # ---------------------------------------------------------------------
        w_out = humidity_ratio(outdoor_temp, outdoor_rh)
        w_in = humidity_ratio(indoor_temp, indoor_rh)

        # ---------------------------------------------------------------------
        # Infiltration Latent Load
        # ---------------------------------------------------------------------
        mass_flow_dry_air_per_hr = infiltration_cfm * 60.0 * 0.075
        delta_w = w_out - w_in

        if delta_t > 0:
            # Cooling mode: remove moisture if outdoor is more humid
            infiltration_latent_btu_h = mass_flow_dry_air_per_hr * max(delta_w, 0) * 1061.0
        else:
            # Heating mode: ignoring humidification cost
            infiltration_latent_btu_h = mass_flow_dry_air_per_hr * max(w_in - w_out, 0) * 1061.0

        if infiltration_latent_btu_h < 0:
            infiltration_latent_btu_h = 0

        # ---------------------------------------------------------------------
        # Occupant Latent (Preset only)
        # ---------------------------------------------------------------------
        if occupant_latent_preset_key in OCCUPANT_LATENT_PRESETS:
            occupant_latent_per_person = OCCUPANT_LATENT_PRESETS[occupant_latent_preset_key]
        else:
            # If invalid or blank, default to 200
            occupant_latent_per_person = 200

        if delta_t > 0:
            occupant_latent_load_btu_h = occupancy_count * occupant_latent_per_person
        else:
            occupant_latent_load_btu_h = 0

        total_latent_load_btu_h = infiltration_latent_btu_h + occupant_latent_load_btu_h

        # ---------------------------------------------------------------------
        # Combined Total Load
        # ---------------------------------------------------------------------
        total_load_btu_h = total_sensible_load_btu_h + total_latent_load_btu_h
        if cop <= 0:
            cop = default_cop
        power_input_kW = total_load_btu_h / (BTU_PER_KWH * cop)

        # ---------------------------------------------------------------------
        # Costs
        # ---------------------------------------------------------------------
        energy_cost_per_hour = power_input_kW * electric_rate
        depreciation_cost_per_hour = hvac_capital_cost / (hvac_lifespan_years * annual_operating_hours)
        cost_per_hour = energy_cost_per_hour + depreciation_cost_per_hour
        cost_per_tenant = cost_per_hour / num_tenancies

        # ---------------------------------------------------------------------
        # Debug Output
        # ---------------------------------------------------------------------
        debug_info = {
            'Selected City': city,
            'Outdoor Temp (°F)': outdoor_temp,
            'Outdoor RH (%)': outdoor_rh,
            'Indoor Temp (°F)': indoor_temp,
            'Indoor RH (%)': indoor_rh,
            'Temperature Difference': f"{delta_t:.2f} ({mode})",

            'Base Envelope Load (BTU/h/ft²/°F)': base_load,
            'Insulation Level': insulation_level,
            'Insulation Multiplier': f"{insulation_mult:.2f}",
            'Window Area (%)': f"{window_area:.1f}",
            'Window Multiplier': f"{window_mult:.3f}",
            'Envelope Load (BTU/h)': f"{envelope_load_btu_h:.1f}",

            'Occupant Count': occupancy_count,
            'Occupant Sensible (BTU/h)': f"{occupant_sensible_load:.1f}",
            'Total Sensible Load (BTU/h)': f"{total_sensible_load_btu_h:.1f}",

            'Infiltration Preset': infiltration_preset,
            'Preset Rate (CFM/ft²)': (f"{infiltration_preset_rate:.3f}" 
                                       if infiltration_preset_rate else "N/A"),
            'Custom Infiltration (CFM)': f"{infiltration_cfm_custom:.1f}",
            'Final Infiltration (CFM)': f"{infiltration_cfm:.1f}",
            'Infiltration Latent (BTU/h)': f"{infiltration_latent_btu_h:.1f}",

            'Occupant Latent Preset': occupant_latent_preset_key,
            'Occupant Latent (BTU/h/person)': f"{occupant_latent_per_person:.1f}",
            'Occupant Latent Load (BTU/h)': f"{occupant_latent_load_btu_h:.1f}",

            'Total Latent Load (BTU/h)': f"{total_latent_load_btu_h:.1f}",
            'Total Load (BTU/h)': f"{total_load_btu_h:.1f}",

            'HVAC System': hvac_system,
            'Default COP': f"{default_cop:.2f}",
            'User COP Override': f"{hvac_eff_override:.2f}" if hvac_eff_override > 0 else "N/A",
            'Effective COP': f"{cop:.2f}",
            'Power Input (kW)': f"{power_input_kW:.2f}",

            'Electric Rate ($/kWh)': f"{electric_rate:.3f}",
            'Energy Cost/hr ($)': f"{energy_cost_per_hour:.2f}",
            'Depreciation/hr ($)': f"{depreciation_cost_per_hour:.2f}",
            'Total Cost/hr ($)': f"{cost_per_hour:.2f}",
            'Number of Tenancies': num_tenancies,
            'Cost/Tenant ($/hr)': f"{cost_per_tenant:.2f}"
        }

        # Preserve the form data
        form_data = {
            'city': city,
            'building_type': building_type,
            'area': request.form.get('area', ''),
            'window_area': request.form.get('window_area', ''),
            'num_tenancies': request.form.get('num_tenancies', ''),
            'electric_rate': request.form.get('electric_rate', ''),
            'hvac_system': hvac_system,
            'hvac_efficiency': request.form.get('hvac_efficiency', ''),
            'insulation_level': insulation_level,
            'occupancy_count': request.form.get('occupancy_count', ''),
            'hvac_capital_cost': request.form.get('hvac_capital_cost', ''),
            'hvac_lifespan_years': request.form.get('hvac_lifespan_years', ''),
            'annual_operating_hours': request.form.get('annual_operating_hours', ''),

            'infiltration_preset': infiltration_preset,
            'infiltration_cfm': infiltration_cfm_text,

            'occupant_latent_preset': occupant_latent_preset_key
        }

        cost_per_hour = cost_per_hour
        cost_per_tenant = cost_per_tenant

    # Render the page
    return render_template(
        'index.html',
        form_data=form_data,
        cost_per_hour=cost_per_hour,
        cost_per_tenant=cost_per_tenant,
        debug_info=debug_info
    )

import os
from flask import Flask, render_template, request

app = Flask(__name__)

# All your route logic here...

@app.route('/', methods=['GET', 'POST'])
def hvac_calculator():
    return render_template('index.html')
