"""Map AEMO CDEII energy-source labels onto a small set of fuel groups."""

FUEL_GROUPS: dict[str, str] = {
    "Solar": "Solar",
    "Wind": "Wind",
    "Hydro": "Hydro",
    "Battery Storage": "Battery",
    "Black coal": "Black coal",
    "Brown coal": "Brown coal",
    "Natural Gas (Pipeline)": "Gas",
    "Coal seam methane": "Gas",
    "Coal Seam Methane": "Gas",
    "Coal mine waste gas": "Gas",
    "Ethane": "Gas",
    "Diesel oil": "Liquid fuel",
    "Kerosene - non aviation": "Liquid fuel",
    "Landfill biogas methane": "Biomass/biogas",
    "Biomass and industrial materials": "Biomass/biogas",
    "Bagasse": "Biomass/biogas",
    "Other Biofuels": "Biomass/biogas",
}

RENEWABLE_GROUPS = {"Solar", "Wind", "Hydro", "Biomass/biogas"}


def fuel_group(energy_source: str) -> str:
    return FUEL_GROUPS.get(energy_source.strip(), "Other")
