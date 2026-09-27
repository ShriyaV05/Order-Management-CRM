import math
from typing import Dict, List, Any

INDIA_LOCATIONS: Dict[str, List[str]] = {
    "Tamil Nadu": [
        "Chennai", "Coimbatore", "Madurai", "Tiruchirappalli", "Salem", "Tirunelveli", 
        "Tiruppur", "Erode", "Vellore", "Thoothukudi", "Dindigul", "Thanjavur", 
        "Ranipet", "Sivaganga", "Karur", "Ramanathapuram", "Virudhunagar", "Kanchipuram", 
        "Chengalpattu", "Cuddalore", "Dharmapuri", "Kallakurichi", "Kanyakumari", 
        "Krishnagiri", "Mayiladuthurai", "Nagapattinam", "Namakkal", "Nilgiris", 
        "Perambalur", "Pudukkottai", "Tenkasi", "Theni", "Tirupathur", "Tiruvallur", 
        "Tiruvannamalai", "Tiruvarur", "Viluppuram"
    ],
    "Karnataka": [
        "Bengaluru Urban", "Bengaluru Rural", "Mysuru", "Hubballi-Dharwad", "Mangaluru", 
        "Belagavi", "Davanagere", "Ballari", "Kalaburagi", "Udupi", "Shivamogga", 
        "Tumakuru", "Hassan", "Mandya", "Chikkamagaluru", "Bidar"
    ],
    "Kerala": [
        "Thiruvananthapuram", "Ernakulam", "Kozhikode", "Thrissur", "Kollam", 
        "Palakkad", "Alappuzha", "Kannur", "Kottayam", "Malappuram", "Idukki", 
        "Pathanamthitta", "Kasaragod", "Wayanad"
    ],
    "Andhra Pradesh": [
        "Visakhapatnam", "Vijayawada", "Guntur", "Nellore", "Kurnool", "Kakinada", 
        "Tirupati", "Rajamahendravaram", "Kadapa", "Anantapur", "Chittoor", "Eluru", "Ongole"
    ],
    "Telangana": [
        "Hyderabad", "Warangal", "Nizamabad", "Karimnagar", "Khammam", 
        "Ranga Reddy", "Medchal-Malkajgiri", "Sangareddy", "Siddipet", "Mahabubnagar"
    ],
    "Puducherry": [
        "Puducherry", "Karaikal", "Mahe", "Yanam"
    ],
    "Maharashtra": [
        "Mumbai", "Navi Mumbai", "Pune", "Nagpur", "Thane", "Nashik", "Aurangabad", 
        "Solapur", "Kolhapur", "Amravati", "Nanded", "Jalgaon"
    ],
    "Delhi": [
        "Central Delhi", "East Delhi", "New Delhi", "North Delhi", "North East Delhi", 
        "North West Delhi", "South Delhi", "South East Delhi", "South West Delhi", "West Delhi"
    ],
    "Gujarat": [
        "Ahmedabad", "Surat", "Vadodara", "Rajkot", "Bhavnagar", "Jamnagar", "Gandhinagar", "Junagadh"
    ],
    "Rajasthan": [
        "Jaipur", "Jodhpur", "Kota", "Bikaner", "Ajmer", "Udaipur", "Bhilwara", "Alwar"
    ],
    "Uttar Pradesh": [
        "Lucknow", "Kanpur", "Varanasi", "Agra", "Prayagraj", "Ghaziabad", "Noida", "Meerut", "Bareilly", "Aligarh"
    ],
    "West Bengal": [
        "Kolkata", "Howrah", "Durgapur", "Asansol", "Siliguri", "Bardhaman", "Kharagpur"
    ],
    "Punjab": [
        "Ludhiana", "Amritsar", "Jalandhar", "Patiala", "Bathinda", "Mohali"
    ],
    "Haryana": [
        "Gurugram", "Faridabad", "Panipat", "Ambala", "Karnal", "Hisar", "Rohtak"
    ],
    "Madhya Pradesh": [
        "Bhopal", "Indore", "Jabalpur", "Gwalior", "Ujjain", "Sagar"
    ],
    "Bihar": [
        "Patna", "Gaya", "Bhagalpur", "Muzaffarpur", "Purnia", "Darbhanga"
    ],
    "Odisha": [
        "Bhubaneswar", "Cuttack", "Rourkela", "Berhampur", "Sambalpur", "Puri"
    ],
    "Assam": [
        "Guwahati", "Silchar", "Dibrugarh", "Jorhat", "Nagaon", "Tinsukia"
    ],
    "Goa": [
        "North Goa", "South Goa"
    ],
    "Chandigarh": [
        "Chandigarh"
    ],
    "Uttarakhand": [
        "Dehradun", "Haridwar", "Roorkee", "Haldwani", "Rishikesh"
    ],
    "Himachal Pradesh": [
        "Shimla", "Dharamshala", "Mandi", "Solan", "Kullu"
    ],
    "Jharkhand": [
        "Ranchi", "Jamshedpur", "Dhanbad", "Bokaro", "Deoghar"
    ],
    "Chhattisgarh": [
        "Raipur", "Bhilai", "Bilaspur", "Korba", "Durg"
    ]
}

SOUTH_INDIA_STATES = {"karnataka", "kerala", "andhra pradesh", "telangana", "puducherry"}

# Delivery Rates Table
# | Zone | Up to 250g | 250 to 500g | 500g to 1kg | Over 1kg per +500g |
DELIVERY_RATES = {
    "Chennai": {
        "tier1": 40.0,  # <= 250g
        "tier2": 42.0,  # 251g - 500g
        "tier3": 45.0,  # 501g - 1000g
        "excess_per_500g": 20.0
    },
    "Tamil Nadu": {
        "tier1": 65.0,
        "tier2": 65.0,
        "tier3": 70.0,
        "excess_per_500g": 30.0
    },
    "South India": {
        "tier1": 75.0,
        "tier2": 78.0,
        "tier3": 80.0,
        "excess_per_500g": 35.0
    },
    "North/East/West": {
        "tier1": 100.0,
        "tier2": 150.0,
        "tier3": 230.0,
        "excess_per_500g": 80.0
    }
}

def determine_zone(state: str, district: str) -> str:
    st = (state or "").strip().lower()
    dist = (district or "").strip().lower()

    # Rule: Chennai Priority
    if dist == "chennai":
        return "Chennai"
    
    # Rule: Tamil Nadu
    if st == "tamil nadu":
        return "Tamil Nadu"
    
    # Rule: South India
    if st in SOUTH_INDIA_STATES:
        return "South India"
    
    # Otherwise: North/East/West
    return "North/East/West"

def calculate_delivery_fee(state: str, district: str, total_bottles: int) -> Dict[str, Any]:
    if total_bottles <= 0:
        return {
            "weight_grams": 0,
            "weight_display": "0g",
            "zone": "Tamil Nadu",
            "slab": "None",
            "fee": 0.0,
            "notes": "No bottles selected"
        }
    
    weight_grams = total_bottles * 110
    zone = determine_zone(state, district)
    rates = DELIVERY_RATES.get(zone, DELIVERY_RATES["North/East/West"])

    if weight_grams >= 1000:
        weight_display = f"{weight_grams / 1000:.2f}kg"
    else:
        weight_display = f"{weight_grams}g"

    if weight_grams <= 250:
        fee = rates["tier1"]
        slab = "Up to 250g"
        notes = f"{zone} standard rate (<=250g)"
    elif weight_grams <= 500:
        fee = rates["tier2"]
        slab = "250g to 500g"
        notes = f"{zone} standard rate (251-500g)"
    elif weight_grams <= 1000:
        fee = rates["tier3"]
        slab = "500g to 1kg"
        notes = f"{zone} standard rate (501-1000g)"
    else:
        # Over 1kg: explicitly handled
        excess_grams = weight_grams - 1000
        excess_units = math.ceil(excess_grams / 500.0)
        surcharge = excess_units * rates["excess_per_500g"]
        fee = rates["tier3"] + surcharge
        slab = f"> 1kg ({weight_display})"
        notes = f"{zone} 1kg base (Rs.{rates['tier3']:.0f}) + Rs.{surcharge:.0f} excess weight ({excess_units} x 500g slab)"

    return {
        "weight_grams": weight_grams,
        "weight_display": weight_display,
        "zone": zone,
        "slab": slab,
        "fee": float(fee),
        "notes": notes
    }
