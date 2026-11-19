NAMES = {
    "AE": "United Arab Emirates", "AL": "Albania", "AM": "Armenia", "AR": "Argentina",
    "AT": "Austria", "AU": "Australia", "AZ": "Azerbaijan", "BA": "Bosnia and Herzegovina",
    "BE": "Belgium", "BG": "Bulgaria", "BH": "Bahrain", "BR": "Brazil", "BY": "Belarus",
    "CA": "Canada", "CH": "Switzerland", "CL": "Chile", "CO": "Colombia", "CR": "Costa Rica",
    "CY": "Cyprus", "CZ": "Czechia", "DE": "Germany", "DK": "Denmark", "EC": "Ecuador",
    "EE": "Estonia", "EG": "Egypt", "ES": "Spain", "FI": "Finland", "FR": "France",
    "GB": "United Kingdom", "GE": "Georgia", "GR": "Greece", "HK": "Hong Kong",
    "HR": "Croatia", "HU": "Hungary", "ID": "Indonesia", "IE": "Ireland", "IL": "Israel",
    "IM": "Isle of Man", "IN": "India", "IQ": "Iraq", "IS": "Iceland", "IT": "Italy",
    "JP": "Japan", "KE": "Kenya", "KG": "Kyrgyzstan", "KH": "Cambodia", "KR": "South Korea",
    "KZ": "Kazakhstan", "LT": "Lithuania", "LU": "Luxembourg", "LV": "Latvia", "MA": "Morocco",
    "MD": "Moldova", "ME": "Montenegro", "MK": "North Macedonia", "MM": "Myanmar",
    "MX": "Mexico", "MY": "Malaysia", "NG": "Nigeria", "NL": "Netherlands", "NO": "Norway",
    "NP": "Nepal", "NZ": "New Zealand", "PE": "Peru", "PH": "Philippines", "PK": "Pakistan",
    "PL": "Poland", "PR": "Puerto Rico", "PT": "Portugal", "QA": "Qatar", "RO": "Romania",
    "RS": "Serbia", "RU": "Russia", "SA": "Saudi Arabia", "SE": "Sweden", "SG": "Singapore",
    "SI": "Slovenia", "SK": "Slovakia", "TH": "Thailand", "TR": "Turkey", "TW": "Taiwan",
    "UA": "Ukraine", "US": "United States", "UZ": "Uzbekistan", "VE": "Venezuela",
    "VN": "Vietnam", "ZA": "South Africa",
}


def name(code):
    return NAMES.get((code or "").upper(), (code or "").upper())
