import re
from typing import Optional


# === Checksum weight table (positions 1-17, letters I,O,Q forbidden) ===

TRANSLITERATION = {
    'A': 1, 'B': 2, 'C': 3, 'D': 4, 'E': 5, 'F': 6, 'G': 7, 'H': 8,
    'J': 1, 'K': 2, 'L': 3, 'M': 4, 'N': 5, 'P': 7, 'R': 9,
    'S': 2, 'T': 3, 'U': 4, 'V': 5, 'W': 6, 'X': 7, 'Y': 8, 'Z': 9,
    '0': 0, '1': 1, '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, '9': 9,
}

WEIGHTS = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]


# === ISO 3780: First character → Region / Country ===

VIN_REGION = {
    # Africa (A-H)
    'A': ("Africa", "South Africa"), 'B': ("Africa", "Angola/Kenya/Tanzania"),
    'C': ("Africa", "Benin/Madagascar/Tunisia"), 'D': ("Africa", "Egypt/Morocco/Zambia"),
    'E': ("Africa", "Ethiopia/Mozambique"), 'F': ("Africa", "Ghana/Nigeria"),
    'G': ("Africa", "Ivory Coast"), 'H': ("Africa", "Africa (other)"),
    # Asia (J-R)
    'J': ("Asia", "Japan"), 'K': ("Asia", "South Korea"),
    'L': ("Asia", "China"), 'M': ("Asia", "India/Indonesia/Thailand"),
    'N': ("Asia", "Iran/Pakistan/Turkey"), 'P': ("Asia", "Philippines"),
    'R': ("Asia", "Taiwan/UAE"),
    # Europe (S-Z)
    'S': ("Europe", "United Kingdom"),
    'T': ("Europe", "Switzerland/Czech Republic/Hungary/Portugal"),
    'U': ("Europe", "Denmark/Ireland/Romania"),
    'V': ("Europe", "Austria/France/Spain"),
    'W': ("Europe", "Germany"),
    'X': ("Europe", "Russia/Netherlands/Luxembourg/CIS"),
    'Y': ("Europe", "Belgium/Finland/Sweden"),
    'Z': ("Europe", "Italy/Slovenia"),
    # North America (1-5)
    '1': ("North America", "United States"), '2': ("North America", "Canada"),
    '3': ("North America", "Mexico"), '4': ("North America", "United States"),
    '5': ("North America", "United States"),
    # Oceania (6-7)
    '6': ("Oceania", "Australia"), '7': ("Oceania", "New Zealand"),
    # South America (8-9)
    '8': ("South America", "Argentina/Chile/Venezuela"),
    '9': ("South America", "Brazil/Colombia"),
}


# === WMI → Manufacturer database (~300 entries) ===
# Format: "WMI": {"make": "Brand", "country": "Country"}

WMI_MANUFACTURERS = {
    # ── Germany ──────────────────────────────────────────────
    "WBA": {"make": "BMW", "country": "Germany"},
    "WBS": {"make": "BMW M", "country": "Germany"},
    "WBY": {"make": "BMW i", "country": "Germany"},
    "WBX": {"make": "BMW", "country": "Germany"},
    "WDB": {"make": "Mercedes-Benz", "country": "Germany"},
    "WDC": {"make": "Mercedes-Benz", "country": "Germany"},
    "WDD": {"make": "Mercedes-Benz", "country": "Germany"},
    "WDF": {"make": "Mercedes-Benz (Vans)", "country": "Germany"},
    "W1K": {"make": "Mercedes-Benz", "country": "Germany"},
    "W1N": {"make": "Mercedes-Benz", "country": "Germany"},
    "W1V": {"make": "Mercedes-Benz", "country": "Germany"},
    "WMX": {"make": "Mercedes-AMG", "country": "Germany"},
    "WVW": {"make": "Volkswagen", "country": "Germany"},
    "WVG": {"make": "Volkswagen (SUV)", "country": "Germany"},
    "WV1": {"make": "Volkswagen Commercial", "country": "Germany"},
    "WV2": {"make": "Volkswagen Commercial", "country": "Germany"},
    "WV3": {"make": "Volkswagen Commercial", "country": "Germany"},
    "WAU": {"make": "Audi", "country": "Germany"},
    "WUA": {"make": "Audi (quattro GmbH)", "country": "Germany"},
    "WA1": {"make": "Audi", "country": "Germany"},
    "WP0": {"make": "Porsche", "country": "Germany"},
    "WP1": {"make": "Porsche (SUV)", "country": "Germany"},
    "W0L": {"make": "Opel", "country": "Germany"},
    "W0V": {"make": "Opel", "country": "Germany"},
    "WF0": {"make": "Ford", "country": "Germany"},
    "WF1": {"make": "Ford", "country": "Germany"},
    "WME": {"make": "smart", "country": "Germany"},
    "WKK": {"make": "Karl Kässbohrer (Setra)", "country": "Germany"},
    "WEB": {"make": "Evobus (Mercedes buses)", "country": "Germany"},
    "WMA": {"make": "MAN Truck", "country": "Germany"},
    "WJM": {"make": "Iveco Magirus", "country": "Germany"},

    # ── France ───────────────────────────────────────────────
    "VF1": {"make": "Renault", "country": "France"},
    "VF2": {"make": "Renault", "country": "France"},
    "VF3": {"make": "Peugeot", "country": "France"},
    "VF4": {"make": "Talbot", "country": "France"},
    "VF6": {"make": "Renault Trucks (Volvo)", "country": "France"},
    "VF7": {"make": "Citroën", "country": "France"},
    "VF8": {"make": "Matra/Talbot", "country": "France"},
    "VF9": {"make": "Bugatti", "country": "France"},
    "VN1": {"make": "Renault (Nissan platform)", "country": "France"},
    "VNK": {"make": "Toyota (France)", "country": "France"},
    "VNV": {"make": "Renault", "country": "France"},
    "VR1": {"make": "Dacia (France)", "country": "France"},

    # ── Italy ────────────────────────────────────────────────
    "ZAM": {"make": "Maserati", "country": "Italy"},
    "ZAP": {"make": "Piaggio", "country": "Italy"},
    "ZAR": {"make": "Alfa Romeo", "country": "Italy"},
    "ZCF": {"make": "Iveco", "country": "Italy"},
    "ZDF": {"make": "Ferrari (Dino)", "country": "Italy"},
    "ZFA": {"make": "Fiat", "country": "Italy"},
    "ZFC": {"make": "Fiat V.I.", "country": "Italy"},
    "ZFF": {"make": "Ferrari", "country": "Italy"},
    "ZGA": {"make": "Fiat (LCV)", "country": "Italy"},
    "ZHW": {"make": "Lamborghini", "country": "Italy"},
    "ZLA": {"make": "Lancia", "country": "Italy"},
    "ZN6": {"make": "De Tomaso", "country": "Italy"},
    "ZDM": {"make": "Ducati", "country": "Italy"},

    # ── United Kingdom ───────────────────────────────────────
    "SAJ": {"make": "Jaguar", "country": "United Kingdom"},
    "SAL": {"make": "Land Rover", "country": "United Kingdom"},
    "SAD": {"make": "Jaguar/Daimler", "country": "United Kingdom"},
    "SAR": {"make": "Rover", "country": "United Kingdom"},
    "SBM": {"make": "McLaren", "country": "United Kingdom"},
    "SCA": {"make": "Rolls-Royce", "country": "United Kingdom"},
    "SCB": {"make": "Bentley", "country": "United Kingdom"},
    "SCC": {"make": "Lotus", "country": "United Kingdom"},
    "SCE": {"make": "DeLorean", "country": "United Kingdom"},
    "SCF": {"make": "Aston Martin", "country": "United Kingdom"},
    "SDB": {"make": "Peugeot (UK)", "country": "United Kingdom"},
    "SFD": {"make": "Alexander Dennis (buses)", "country": "United Kingdom"},
    "SHH": {"make": "Honda (UK)", "country": "United Kingdom"},
    "SHS": {"make": "Honda (UK)", "country": "United Kingdom"},
    "SJN": {"make": "Nissan (UK)", "country": "United Kingdom"},
    "SAT": {"make": "Triumph", "country": "United Kingdom"},
    "SKF": {"make": "Toyota (UK)", "country": "United Kingdom"},
    "SUF": {"make": "Fiat (UK)", "country": "United Kingdom"},

    # ── Sweden ───────────────────────────────────────────────
    "YV1": {"make": "Volvo Cars", "country": "Sweden"},
    "YV4": {"make": "Volvo Cars", "country": "Sweden"},
    "YV2": {"make": "Volvo Trucks", "country": "Sweden"},
    "YV3": {"make": "Volvo Buses", "country": "Sweden"},
    "YS3": {"make": "Saab", "country": "Sweden"},
    "YK1": {"make": "Saab-Scania", "country": "Sweden"},
    "YTN": {"make": "Saab", "country": "Sweden"},
    "YS2": {"make": "Scania", "country": "Sweden"},

    # ── Belgium ──────────────────────────────────────────────
    "YA1": {"make": "Volvo (Belgium)", "country": "Belgium"},

    # ── Finland ──────────────────────────────────────────────
    "YCM": {"make": "Valmet Automotive", "country": "Finland"},

    # ── Spain ────────────────────────────────────────────────
    "VSS": {"make": "SEAT", "country": "Spain"},
    "VS6": {"make": "Ford (Spain)", "country": "Spain"},
    "VS7": {"make": "Citroën (Spain)", "country": "Spain"},
    "VSA": {"make": "Mercedes-Benz (Spain)", "country": "Spain"},
    "VSE": {"make": "Suzuki (Spain)", "country": "Spain"},
    "VSK": {"make": "Nissan (Spain)", "country": "Spain"},
    "VSX": {"make": "Opel (Spain)", "country": "Spain"},
    "VWV": {"make": "Volkswagen (Spain)", "country": "Spain"},

    # ── Austria ──────────────────────────────────────────────
    "VA0": {"make": "ÖAF/MAN (Austria)", "country": "Austria"},

    # ── Czech Republic ───────────────────────────────────────
    "TMB": {"make": "Škoda", "country": "Czech Republic"},
    "TMA": {"make": "Hyundai (Czech)", "country": "Czech Republic"},
    "TMK": {"make": "Karosa (buses)", "country": "Czech Republic"},
    "TMP": {"make": "Škoda Trolleybus", "country": "Czech Republic"},
    "TNE": {"make": "TAZ", "country": "Czech Republic"},
    "TN9": {"make": "Karosa", "country": "Czech Republic"},

    # ── Hungary ──────────────────────────────────────────────
    "TRU": {"make": "Audi (Hungary)", "country": "Hungary"},
    "TK9": {"make": "Suzuki (Hungary)", "country": "Hungary"},

    # ── Portugal ─────────────────────────────────────────────
    "TW1": {"make": "Mitsubishi (Portugal)", "country": "Portugal"},

    # ── Switzerland ──────────────────────────────────────────
    "TS0": {"make": "Bucher-Guyer", "country": "Switzerland"},

    # ── Romania ──────────────────────────────────────────────
    "UU1": {"make": "Dacia (Romania)", "country": "Romania"},
    "UU6": {"make": "Daewoo (Romania)", "country": "Romania"},

    # ── Denmark ──────────────────────────────────────────────
    "UH1": {"make": "DAF (Denmark)", "country": "Denmark"},

    # ── Netherlands ──────────────────────────────────────────
    "XLE": {"make": "Volvo (Netherlands)", "country": "Netherlands"},
    "XLR": {"make": "DAF Trucks", "country": "Netherlands"},
    "XLB": {"make": "VDL Bus", "country": "Netherlands"},

    # ── Russia / CIS ─────────────────────────────────────────
    "XTA": {"make": "Lada (AvtoVAZ)", "country": "Russia"},
    "XTT": {"make": "UAZ", "country": "Russia"},
    "XWB": {"make": "Hyundai (Russia)", "country": "Russia"},
    "XWE": {"make": "Volkswagen (Russia)", "country": "Russia"},
    "X4X": {"make": "BMW (Russia)", "country": "Russia"},
    "X7L": {"make": "Renault (Russia)", "country": "Russia"},
    "X7M": {"make": "Hyundai (Russia)", "country": "Russia"},
    "X9F": {"make": "Ford (Russia)", "country": "Russia"},

    # ── Turkey ───────────────────────────────────────────────
    "NMT": {"make": "Toyota (Turkey)", "country": "Turkey"},
    "NM0": {"make": "Ford (Turkey)", "country": "Turkey"},
    "NM4": {"make": "Tofaş/Fiat (Turkey)", "country": "Turkey"},
    "NMB": {"make": "Mercedes-Benz (Turkey)", "country": "Turkey"},

    # ── Japan ────────────────────────────────────────────────
    "JA3": {"make": "Mitsubishi", "country": "Japan"},
    "JA4": {"make": "Mitsubishi", "country": "Japan"},
    "JDA": {"make": "Daihatsu", "country": "Japan"},
    "JF1": {"make": "Subaru (Fuji)", "country": "Japan"},
    "JF2": {"make": "Subaru (Fuji)", "country": "Japan"},
    "JHG": {"make": "Honda", "country": "Japan"},
    "JHL": {"make": "Honda", "country": "Japan"},
    "JHM": {"make": "Honda", "country": "Japan"},
    "JMB": {"make": "Mitsubishi", "country": "Japan"},
    "JMZ": {"make": "Mazda", "country": "Japan"},
    "JN1": {"make": "Nissan", "country": "Japan"},
    "JN3": {"make": "Nissan", "country": "Japan"},
    "JN6": {"make": "Nissan (Truck)", "country": "Japan"},
    "JN8": {"make": "Nissan", "country": "Japan"},
    "JS1": {"make": "Suzuki", "country": "Japan"},
    "JS2": {"make": "Suzuki", "country": "Japan"},
    "JS3": {"make": "Suzuki", "country": "Japan"},
    "JT2": {"make": "Toyota", "country": "Japan"},
    "JTD": {"make": "Toyota", "country": "Japan"},
    "JTE": {"make": "Toyota", "country": "Japan"},
    "JTH": {"make": "Lexus", "country": "Japan"},
    "JTK": {"make": "Toyota", "country": "Japan"},
    "JTL": {"make": "Toyota", "country": "Japan"},
    "JTM": {"make": "Toyota", "country": "Japan"},
    "JTN": {"make": "Toyota", "country": "Japan"},
    "JYA": {"make": "Yamaha", "country": "Japan"},

    # ── South Korea ──────────────────────────────────────────
    "KL1": {"make": "GM Daewoo (Chevrolet)", "country": "South Korea"},
    "KL7": {"make": "Daewoo/Chevrolet", "country": "South Korea"},
    "KMH": {"make": "Hyundai", "country": "South Korea"},
    "KMJ": {"make": "Hyundai (Bus/Truck)", "country": "South Korea"},
    "KNA": {"make": "Kia", "country": "South Korea"},
    "KNB": {"make": "Kia", "country": "South Korea"},
    "KNC": {"make": "Kia", "country": "South Korea"},
    "KND": {"make": "Kia", "country": "South Korea"},
    "KNM": {"make": "Renault Samsung", "country": "South Korea"},
    "KPA": {"make": "SsangYong", "country": "South Korea"},
    "KPT": {"make": "SsangYong", "country": "South Korea"},

    # ── China ────────────────────────────────────────────────
    "LBE": {"make": "Beijing Hyundai", "country": "China"},
    "LBV": {"make": "BMW Brilliance", "country": "China"},
    "LDC": {"make": "Dongfeng Citroën", "country": "China"},
    "LFV": {"make": "FAW-Volkswagen", "country": "China"},
    "LGX": {"make": "BYD", "country": "China"},
    "LHG": {"make": "GAC Honda", "country": "China"},
    "LJD": {"make": "Dongfeng Nissan", "country": "China"},
    "LSG": {"make": "SAIC GM (Chevrolet/Buick)", "country": "China"},
    "LSV": {"make": "SAIC Volkswagen", "country": "China"},
    "LTV": {"make": "Toyota (China)", "country": "China"},
    "LVS": {"make": "Changan Ford", "country": "China"},
    "LVV": {"make": "Chery", "country": "China"},
    "LPS": {"make": "Geely", "country": "China"},

    # ── India ────────────────────────────────────────────────
    "MA1": {"make": "Mahindra", "country": "India"},
    "MA3": {"make": "Suzuki (India/Maruti)", "country": "India"},
    "MA6": {"make": "GM India", "country": "India"},
    "MA7": {"make": "Mitsubishi (India)", "country": "India"},
    "MAJ": {"make": "Ford (India)", "country": "India"},
    "MAK": {"make": "Honda (India)", "country": "India"},
    "MAL": {"make": "Hyundai (India)", "country": "India"},
    "MAT": {"make": "Tata", "country": "India"},
    "MBH": {"make": "Suzuki (India)", "country": "India"},
    "MBJ": {"make": "Toyota (India)", "country": "India"},
    "MBR": {"make": "Mercedes-Benz (India)", "country": "India"},
    "MCA": {"make": "Fiat (India)", "country": "India"},
    "MCB": {"make": "GM India (Halol)", "country": "India"},
    "MEC": {"make": "Daimler India (Truck)", "country": "India"},

    # ── Thailand ──────────────────────────────────────────────
    "MR0": {"make": "Toyota (Thailand)", "country": "Thailand"},
    "MRH": {"make": "Honda (Thailand)", "country": "Thailand"},

    # ── Indonesia ─────────────────────────────────────────────
    "MHF": {"make": "Toyota (Indonesia)", "country": "Indonesia"},

    # ── South Africa ─────────────────────────────────────────
    "AAV": {"make": "Volkswagen (South Africa)", "country": "South Africa"},
    "AHT": {"make": "Toyota (South Africa)", "country": "South Africa"},
    "ADN": {"make": "Nissan (South Africa)", "country": "South Africa"},
    "AC5": {"make": "Hyundai (South Africa)", "country": "South Africa"},

    # ── USA ──────────────────────────────────────────────────
    "1C3": {"make": "Chrysler", "country": "USA"},
    "1C4": {"make": "Chrysler (SUV)", "country": "USA"},
    "1C6": {"make": "Chrysler (Truck)", "country": "USA"},
    "1D7": {"make": "Dodge (Ram)", "country": "USA"},
    "1FA": {"make": "Ford", "country": "USA"},
    "1FB": {"make": "Ford (Bus/Van)", "country": "USA"},
    "1FC": {"make": "Ford (Stripped Chassis)", "country": "USA"},
    "1FD": {"make": "Ford (Truck)", "country": "USA"},
    "1FM": {"make": "Ford (SUV)", "country": "USA"},
    "1FT": {"make": "Ford (Truck)", "country": "USA"},
    "1FU": {"make": "Freightliner", "country": "USA"},
    "1FV": {"make": "Freightliner", "country": "USA"},
    "1G1": {"make": "Chevrolet", "country": "USA"},
    "1G2": {"make": "Pontiac", "country": "USA"},
    "1G3": {"make": "Oldsmobile", "country": "USA"},
    "1G4": {"make": "Buick", "country": "USA"},
    "1G6": {"make": "Cadillac", "country": "USA"},
    "1G8": {"make": "Saturn", "country": "USA"},
    "1GC": {"make": "Chevrolet (Truck)", "country": "USA"},
    "1GM": {"make": "Pontiac (Bus)", "country": "USA"},
    "1GT": {"make": "GMC (Truck)", "country": "USA"},
    "1GY": {"make": "Cadillac (SUV)", "country": "USA"},
    "1HD": {"make": "Harley-Davidson", "country": "USA"},
    "1HG": {"make": "Honda (USA)", "country": "USA"},
    "1J4": {"make": "Jeep", "country": "USA"},
    "1J8": {"make": "Jeep", "country": "USA"},
    "1LN": {"make": "Lincoln", "country": "USA"},
    "1L1": {"make": "Lincoln", "country": "USA"},
    "1ME": {"make": "Mercury", "country": "USA"},
    "1N4": {"make": "Nissan (USA)", "country": "USA"},
    "1N6": {"make": "Nissan (Truck USA)", "country": "USA"},
    "1NX": {"make": "Toyota (NUMMI)", "country": "USA"},
    "1VW": {"make": "Volkswagen (USA)", "country": "USA"},
    "1YV": {"make": "Mazda (USA)", "country": "USA"},
    "1ZV": {"make": "Ford (USA)", "country": "USA"},
    "19U": {"make": "Acura (USA)", "country": "USA"},
    "2C3": {"make": "Chrysler (Canada)", "country": "Canada"},
    "2FA": {"make": "Ford (Canada)", "country": "Canada"},
    "2FM": {"make": "Ford (Canada SUV)", "country": "Canada"},
    "2G1": {"make": "Chevrolet (Canada)", "country": "Canada"},
    "2G2": {"make": "Pontiac (Canada)", "country": "Canada"},
    "2HG": {"make": "Honda (Canada)", "country": "Canada"},
    "2HK": {"make": "Honda (Canada SUV)", "country": "Canada"},
    "2HM": {"make": "Hyundai (Canada)", "country": "Canada"},
    "2T1": {"make": "Toyota (Canada)", "country": "Canada"},
    "2T3": {"make": "Toyota (Canada SUV)", "country": "Canada"},
    "3FA": {"make": "Ford (Mexico)", "country": "Mexico"},
    "3G1": {"make": "Chevrolet (Mexico)", "country": "Mexico"},
    "3GN": {"make": "GMC (Mexico)", "country": "Mexico"},
    "3GT": {"make": "GMC (Mexico Truck)", "country": "Mexico"},
    "3N1": {"make": "Nissan (Mexico)", "country": "Mexico"},
    "3VW": {"make": "Volkswagen (Mexico)", "country": "Mexico"},
    "3VV": {"make": "Volkswagen (Mexico)", "country": "Mexico"},
    "3MY": {"make": "Mitsubishi (Mexico)", "country": "Mexico"},
    "4F2": {"make": "Mazda (USA Flat Rock)", "country": "USA"},
    "4M2": {"make": "Mercury (USA)", "country": "USA"},
    "4S3": {"make": "Subaru (USA)", "country": "USA"},
    "4S4": {"make": "Subaru (USA)", "country": "USA"},
    "4S6": {"make": "Subaru (USA)", "country": "USA"},
    "4T1": {"make": "Toyota (USA)", "country": "USA"},
    "4T3": {"make": "Toyota (USA SUV)", "country": "USA"},
    "4T4": {"make": "Toyota (USA)", "country": "USA"},
    "4US": {"make": "BMW (USA)", "country": "USA"},
    "5FN": {"make": "Honda (USA)", "country": "USA"},
    "5FP": {"make": "Honda (USA)", "country": "USA"},
    "5J6": {"make": "Honda (USA)", "country": "USA"},
    "5J8": {"make": "Acura (USA)", "country": "USA"},
    "5NP": {"make": "Hyundai (USA)", "country": "USA"},
    "5N1": {"make": "Nissan (USA)", "country": "USA"},
    "5TD": {"make": "Toyota (USA)", "country": "USA"},
    "5TE": {"make": "Toyota (USA)", "country": "USA"},
    "5TF": {"make": "Toyota (USA Truck)", "country": "USA"},
    "5UX": {"make": "BMW (USA SUV)", "country": "USA"},
    "5XX": {"make": "Kia (USA)", "country": "USA"},
    "5XY": {"make": "Kia (USA)", "country": "USA"},
    "5YJ": {"make": "Tesla", "country": "USA"},
    "5YM": {"make": "BMW M (USA)", "country": "USA"},

    # ── Brazil ───────────────────────────────────────────────
    "93H": {"make": "Honda (Brazil)", "country": "Brazil"},
    "93Y": {"make": "Renault (Brazil)", "country": "Brazil"},
    "935": {"make": "Citroën (Brazil)", "country": "Brazil"},
    "936": {"make": "Peugeot (Brazil)", "country": "Brazil"},
    "9BD": {"make": "Fiat (Brazil)", "country": "Brazil"},
    "9BG": {"make": "Chevrolet (Brazil)", "country": "Brazil"},
    "9BW": {"make": "Volkswagen (Brazil)", "country": "Brazil"},
    "9BF": {"make": "Ford (Brazil)", "country": "Brazil"},

    # ── Australia ─────────────────────────────────────────────
    "6FP": {"make": "Ford (Australia)", "country": "Australia"},
    "6G1": {"make": "Holden (GM Australia)", "country": "Australia"},
    "6G2": {"make": "Pontiac (Australia)", "country": "Australia"},
    "6T1": {"make": "Toyota (Australia)", "country": "Australia"},

    # ── Slovenia ──────────────────────────────────────────────
    "ZLN": {"make": "Revoz (Renault Slovenia)", "country": "Slovenia"},

    # ── Poland ────────────────────────────────────────────────
    "SUP": {"make": "Solaris Bus & Coach", "country": "Poland"},

    # ── Slovakia ──────────────────────────────────────────────
    "TM1": {"make": "Volkswagen (Slovakia)", "country": "Slovakia"},
}


# === Model Year decoding (30-year cycle, ISO 3779) ===
# Two cycles: 1980-2009 and 2010-2039
# Disambiguation: if VIN position 7 is a digit → cycle 1 (1980-2009),
#                 if VIN position 7 is a letter → cycle 2 (2010-2039)

_YEAR_CYCLE_1 = {
    'A': 1980, 'B': 1981, 'C': 1982, 'D': 1983, 'E': 1984, 'F': 1985,
    'G': 1986, 'H': 1987, 'J': 1988, 'K': 1989, 'L': 1990, 'M': 1991,
    'N': 1992, 'P': 1993, 'R': 1994, 'S': 1995, 'T': 1996, 'V': 1997,
    'W': 1998, 'X': 1999, 'Y': 2000, '1': 2001, '2': 2002, '3': 2003,
    '4': 2004, '5': 2005, '6': 2006, '7': 2007, '8': 2008, '9': 2009,
}

_YEAR_CYCLE_2 = {
    'A': 2010, 'B': 2011, 'C': 2012, 'D': 2013, 'E': 2014, 'F': 2015,
    'G': 2016, 'H': 2017, 'J': 2018, 'K': 2019, 'L': 2020, 'M': 2021,
    'N': 2022, 'P': 2023, 'R': 2024, 'S': 2025, 'T': 2026, 'V': 2027,
    'W': 2028, 'X': 2029, 'Y': 2030, '1': 2031, '2': 2032, '3': 2033,
    '4': 2034, '5': 2035, '6': 2036, '7': 2037, '8': 2038, '9': 2039,
}


def decode_model_year(vin: str) -> dict:
    """Decode model year from VIN position 10, disambiguated by position 7.

    Returns dict with 'model_year' (best guess) and 'model_year_range' (both options).
    """
    year_char = vin[9]  # position 10 (0-indexed)
    pos7 = vin[6]       # position 7 (0-indexed)

    year1 = _YEAR_CYCLE_1.get(year_char)
    year2 = _YEAR_CYCLE_2.get(year_char)

    # Disambiguation: position 7 is digit → cycle 1 (1980-2009), letter → cycle 2 (2010-2039)
    if pos7.isdigit():
        model_year = year1
    else:
        model_year = year2

    # Build range of possibilities
    possible = [y for y in [year1, year2] if y is not None]

    return {
        "model_year": model_year,
        "model_year_range": possible if len(possible) > 1 else None,
    }


def validate_vin(vin: str) -> tuple[bool, Optional[str]]:
    """Validate VIN: format + checksum. Returns (valid, error_message)."""
    vin = vin.upper().strip()

    if len(vin) != 17:
        return False, f"VIN musi mieć dokładnie 17 znaków (ma {len(vin)})"

    invalid = set(vin) - set(TRANSLITERATION.keys())
    if invalid:
        return False, f"Niedozwolone znaki: {', '.join(sorted(invalid))} (I, O, Q są zabronione)"

    # Checksum (mandatory for North American vehicles)
    wmi = vin[:3]
    if wmi[0] in "12345":
        total = sum(TRANSLITERATION[c] * WEIGHTS[i] for i, c in enumerate(vin))
        check = total % 11
        expected = "X" if check == 10 else str(check)
        if vin[8] != expected:
            return False, f"Niepoprawny checksum (pozycja 9: '{vin[8]}', oczekiwano '{expected}')"

    return True, None


def decode_vin_basic(vin: str) -> dict:
    """Comprehensive offline VIN decoding (no API calls)."""
    vin = vin.upper().strip()

    wmi = vin[:3]
    vds = vin[3:9]
    vis = vin[9:17]

    # Region & country from first character
    region_info = VIN_REGION.get(vin[0], ("Unknown", "Unknown"))
    region = region_info[0]
    country_from_char = region_info[1]

    # Manufacturer from WMI (3-char exact match first, then 2-char prefix)
    mfr = WMI_MANUFACTURERS.get(wmi)
    if not mfr:
        # Try 2-char prefix for less specific matches
        for code, info in WMI_MANUFACTURERS.items():
            if code[:2] == wmi[:2]:
                mfr = info
                break

    make = mfr["make"] if mfr else None
    country = mfr["country"] if mfr else country_from_char

    # Model year
    year_info = decode_model_year(vin)

    # Plant code
    plant = vin[10]

    result = {
        "vin": vin,
        "wmi": wmi,
        "vds": vds,
        "vis": vis,
        "region": region,
        "country_of_manufacture": country,
        "model_year": year_info["model_year"],
        "plant_code": plant,
    }

    if make:
        result["make"] = make

    if year_info["model_year_range"]:
        result["model_year_range"] = year_info["model_year_range"]

    return result
