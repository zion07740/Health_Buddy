import streamlit as st
import json
import os
from datetime import datetime
from uuid import uuid4
import io, csv, re

# --------------- Config ---------------
LOG_FILE = "healthbuddy_logs.json"
KB_FILE = "healthbuddy_kb.json"

# --------------- Utilities ---------------
def load_logs():
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w") as f:
            json.dump([], f)
    with open(LOG_FILE, "r") as f:
        return json.load(f)

def save_logs(logs):
    with open(LOG_FILE, "w") as f:
        json.dump(logs, f, indent=2)

def load_kb():
    if os.path.exists(KB_FILE):
        try:
            with open(KB_FILE, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
    return {}

def route_links(label: str) -> str:
    if label == "Open telemedicine":
        return "https://example-telemed.demo"
    if label == "Find nearby clinic":
        return "https://www.google.com/maps/search/clinic+near+me"
    if label == "Find nearest ER":
        return "https://www.google.com/maps/search/hospital+emergency+near+me"
    if label == "Call 108":
        return "tel:108"
    if label == "Call clinic":
        return "tel:108"
    if label == "Self-care tips":
        return "https://www.who.int/health-topics"
    return "#"

# --------------- Knowledge Base (defaults) ---------------
KB = {
    "emergency_msg": "This may be an emergency. Call 108 immediately. Do not delay.",
    "fever_3d_msg": "Fever for ≥3 days may need evaluation. Consult telemedicine/clinic within 24h.",
    "fallback_msg": "Symptoms unclear. For safety, consider contacting a clinician or visiting a clinic.",

    # Self-care suggestions
    "selfcare_headache": [
        "Rest in a quiet, dark room.",
        "Hydrate with water or oral rehydration solution.",
        "Limit screens; consider paracetamol as per label if needed.",
        "Seek care if headache becomes severe or there is confusion or weakness."
    ],
    "selfcare_cough": [
        "Sip warm fluids with honey/lemon (if not allergic).",
        "Try steam inhalation for congestion.",
        "Avoid smoke/irritants; rest well.",
        "Seek care if breathing worsens, high fever appears, or cough lasts >2 weeks."
    ],

    # Moderate suggestions
    "moderate_general": [
        "Consult a clinician within 24–48 hours (telemedicine or clinic).",
        "Continue fluids and rest; track temperature and symptoms.",
        "Prepare a brief symptom timeline (onset, duration, severity) for the visit."
    ],
    "moderate_fever3": [
        "Arrange a telemedicine/clinic visit within 24 hours.",
        "Stay hydrated; use temperature control (tepid sponging, light clothing).",
        "Record temperatures and new symptoms to share with the clinician."
    ],

    # Urgent suggestions
    "urgent_general": [
        "Visit a clinic today for evaluation.",
        "Avoid heavy exertion; arrange transport if feeling weak/dizzy.",
        "Bring a medication list and known conditions."
    ],
    "urgent_pediatric_fever3": [
        "Take the child to a pediatric clinic today.",
        "Offer frequent small fluids; check temperature regularly.",
        "Watch for red flags (lethargy, poor feeding, breathing difficulty)."
    ],

    # Emergency suggestions
    "emergency_general": [
        "Call 108 now or go to the nearest emergency department.",
        "Do not drive yourself; have someone accompany you if possible.",
        "Bring ID and any current medications."
    ]
}
kb_overrides = load_kb()
KB.update({k: v for k, v in kb_overrides.items() if v})

# --------------- Rules & Parsing ---------------
RULES = {
    # Do not include a generic "fever 3" key; handled explicitly in triage
    "chest pain": ("Emergency", KB["emergency_msg"]),
    "difficulty breathing": ("Emergency", KB["emergency_msg"]),
