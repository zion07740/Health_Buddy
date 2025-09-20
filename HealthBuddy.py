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
    "bleeding": ("Emergency", KB["emergency_msg"]),
    "weakness": ("Emergency", KB["emergency_msg"]),
    "sore throat": ("Moderate", "Consider a clinic/telemedicine visit within 24–48h."),
    "stomach pain": ("Moderate", "Monitor and consult if it persists or worsens within 24–48h."),
    "child fever": ("Urgent", "Please take the child to the nearest clinic today."),
    "dizzy": ("Urgent", "See a doctor today for further evaluation."),
    "headache": ("Self-care", "Safe to try self‑care now."),
    "cough": ("Self-care", "Safe to try self‑care now."),
}

RED_FLAGS = ["chest pain", "difficulty breathing", "severe bleeding", "unconscious", "confusion", "blue lips"]

def parse_age_and_duration(t: str):
    t = t.lower()
    age = None
    duration_days = None
    tokens = t.replace("/", " ").split()
    for i, tok in enumerate(tokens):
        if tok.isdigit():
            n = int(tok)
            if 0 < n < 120:
                window = " ".join(tokens[max(0, i-1): i+2])
                if any(k in window for k in ["year", "years", "yr", "y/o"]):
                    age = n
        if tok.isdigit() and i+1 < len(tokens) and tokens[i+1].startswith("day"):
            duration_days = int(tok)
    return age, duration_days

# --------------- Triage (severity + suggestions + rule reason) ---------------
def triage(text: str, age_override=None, duration_override=None, severity=None):
    t = (text or "").lower().strip()
    age, duration = parse_age_and_duration(t)
    if age_override is not None and age_override > 0:
        age = age_override
    if duration_override is not None and duration_override > 0:
        duration = duration_override

    # 1) Red flags first
    for rf in RED_FLAGS:
        if rf in t:
            return (
                ("Emergency", KB["emergency_msg"], ["Call 108", "Find nearest ER"], age, duration, severity, KB["emergency_general"]),
                f"red_flag:{rf}"
            )

    # 2) Fever ≥ 3 days (digits or word)
    fever = "fever" in t
    three_days_digit = bool(re.search(r"\b(3|three)\b", t)) and ("day" in t or "days" in t)
    long_duration = duration is not None and duration >= 3
    if fever and (three_days_digit or long_duration):
        if age is not None and age < 5:
            return (
                ("Urgent",
                 "Child with fever ≥3 days should be seen today.",
                 ["Find nearby clinic", "Call clinic"],
                 age, duration, severity, KB["urgent_pediatric_fever3"]),
                "rule:fever_3_days_pediatric"
            )
        return (
            ("Moderate",
             KB["fever_3d_msg"],
             ["Open telemedicine", "Find nearby clinic"],
             age, duration, severity, KB["moderate_fever3"]),
            "rule:fever_3_days"
        )

    # 3) Ordered keyword rules by severity with mapped suggestions
    ordered_rules = [
        ("emergency", ["chest pain", "difficulty breathing", "severe bleeding", "unconscious", "weakness"]),
        ("urgent",    ["dizzy", "child fever"]),
        ("moderate",  ["sore throat", "stomach pain"]),
        ("selfcare",  ["headache", "cough"]),
    ]
    for level, keys in ordered_rules:
        for key in keys:
            if key in t:
                if level == "emergency":
                    return (("Emergency", KB["emergency_msg"], ["Call 108","Find nearest ER"], age, duration, severity, KB["emergency_general"]), f"rule:{level}:{key}")
                if level == "urgent":
                    return (("Urgent", "See a doctor today for further evaluation.", ["Find nearby clinic","Call clinic"], age, duration, severity, KB["urgent_general"]), f"rule:{level}:{key}")
                if level == "moderate":
                    return (("Moderate", "Consider a clinic/telemedicine visit within 24–48h.", ["Open telemedicine","Find nearby clinic"], age, duration, severity, KB["moderate_general"]), f"rule:{level}:{key}")
                # self-care
                points = KB["selfcare_headache"] if key == "headache" else KB["selfcare_cough"]
                return (("Self-care", "Safe to try self‑care now.", ["Self-care tips"], age, duration, severity, points), f"rule:{level}:{key}")

    # 4) Default fallback
    return (
        ("Unknown", KB["fallback_msg"], ["Open telemedicine", "Find nearby clinic"], age, duration, severity, []),
        "fallback"
    )

# --------------- UI ---------------
st.title("🩺 HealthBuddy")

# Blue focus ring and high-contrast card styles
st.markdown("""
<style>
.stTextInput > div > div > input:focus {
  outline: none !important;
  border-color: #2563eb !important;
  box-shadow: 0 0 0 3px rgba(37,99,235,0.25) !important;
}
/* High-contrast card text for dark themes */
.health-card { 
  border: 1px solid var(--neutral-border, #e5e7eb);
  border-radius: 10px;
  padding: 14px;
}
@media (prefers-color-scheme: dark) {
  .health-card .headline { color: #e5e7eb !important; }
  .health-card .section-title { color: #f3f4f6 !important; }
  .health-card ul { color: #e5e7eb !important; }
  .health-card li { color: #e5e7eb !important; }
}
@media (prefers-color-scheme: light) {
  .health-card .headline { color: #111827 !important; }
  .health-card .section-title { color: #374151 !important; }
  .health-card ul { color: #111827 !important; }
  .health-card li { color: #111827 !important; }
}
/* Always ensure bullets are fully opaque */
.health-card li { opacity: 1 !important; }
</style>
""", unsafe_allow_html=True)

# Safety notice
st.warning(
    "This assistant does not provide medical diagnosis or treatment. In emergencies, call 108 or visit the nearest ER.",
    icon="⚠️",
)

with st.expander("About / Safety"):
    st.markdown("""
- Purpose: Rapid symptom guidance toward self-care, clinic, or emergency.
- How it works: Keyword rules + duration/age hints; red flags always escalate.
- Safety: Not a diagnosis. Emergency guidance and clear consent are built-in.
- Roadmap: Add Rasa/LLM NLU, WhatsApp channel, clinician KB, analytics & pilot.
""")

# Demo scenarios
with st.expander("Demo scenarios"):
    demo_cases = {
        "Emergency: chest pain": (55, 0, "Severe", "Severe chest pain and sweating"),
        "Moderate: fever 3 days": (28, 3, "Moderate", "Fever for 3 days and sore throat"),
        "Self-care: mild headache": (21, 1, "Mild", "Mild headache since morning"),
        "Unknown: unclear": (30, 0, "Mild", "feeling off idk"),
    }
    pick = st.selectbox("Pick a scenario", list(demo_cases.keys()))
    if st.button("Run scenario"):
        a, d, s, txt = demo_cases[pick]
        st.session_state["symptoms_input"] = txt
        st.session_state["age_prefill"] = a
        st.session_state["dur_prefill"] = d
        st.info(f"Scenario set: age {a}, duration {d} days, severity {s}. Enter or adjust details below.")

# Structured intake form
prefill_age = st.session_state.get("age_prefill", 0)
prefill_dur = st.session_state.get("dur_prefill", 0)

with st.form("triage_form", enter_to_submit=True):
    st.markdown("#### Describe your symptoms")
    col1, col2, col3 = st.columns([1,1,1])
    with col1:
        age_input = st.number_input("Age", min_value=0, max_value=120, step=1, value=int(prefill_age))
    with col2:
        duration_days = st.number_input("Duration (days)", min_value=0, max_value=60, step=1, value=int(prefill_dur))
    with col3:
        severity = st.selectbox("Severity", ["Mild", "Moderate", "Severe"])
    user_input = st.text_input(
        "Additional details",
        value=st.session_state.get("symptoms_input",""),
        placeholder="e.g., sore throat, cough, fever spikes at night",
        label_visibility="collapsed",
        key="symptoms_input"
    )
    st.caption("Tip: include main symptom, duration, severity, and notable conditions.")
    submitted = st.form_submit_button("Check Health")

# Inline validation nudges
if submitted and (not user_input or len(user_input.strip()) < 8):
    st.info("Add a few more details so guidance is accurate (e.g., main symptom + duration).")
if submitted and duration_days == 0 and "day" in (user_input or "").lower():
    st.caption("If duration is known, set it above to improve results.")

# Compute results
if submitted:
    (result, rule_reason) = triage(
        user_input,
        age_override=age_input,
        duration_override=duration_days,
        severity=severity,
    )
    urgency, advice_headline, routes, age_hint, duration_hint, sev, advice_points = result
    st.session_state.last_result = (urgency, advice_headline, routes, user_input, age_hint, duration_hint, sev, advice_points, rule_reason)

# Show results
if "last_result" in st.session_state and st.session_state.last_result:
    urgency, advice_headline, routes, last_input, age_hint, duration_hint, sev, advice_points, rule_reason = st.session_state.last_result

    # Severity badge colors
    badge_colors = {"Emergency":"#ef4444","Urgent":"#f59e0b","Moderate":"#10b981","Self-care":"#3b82f6","Unknown":"#6b7280"}
    color = badge_colors.get(urgency, "#6b7280")

    # Build HTML bullets for advice points inside the card
    items = "".join([f"<li style='margin:4px 0'>{item}</li>" for item in advice_points]) if advice_points else ""
    advice_html = f"""
    <div style="margin-top:8px">
      <div class="section-title" style="font-weight:600;margin-bottom:4px">Suggested next steps</div>
      <ul style="margin:0 0 0 18px;padding:0">
        {items}
      </ul>
    </div>
    """ if items else ""

    # Single compact card with badge + headline + steps
    card_html = f"""
    <div class="health-card">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
        <span style="background:{color};color:white;padding:4px 10px;border-radius:999px;font-weight:600">{urgency}</span>
        <span style="opacity:.8">Result</span>
      </div>
      <div class="headline" style="margin:6px 0">{advice_headline}</div>
      {advice_html}
    </div>
    """
    st.markdown(card_html, unsafe_allow_html=True)

    # Optional debug line (hide if not needed)
    st.caption(f"Debug: {rule_reason}")

    # Meta row
    meta_bits = []
    if age_hint is not None:
        meta_bits.append(f"Age: {age_hint}")
    if duration_hint is not None:
        meta_bits.append(f"Duration: {duration_hint} days")
    if sev:
        meta_bits.append(f"Severity: {sev}")
    if meta_bits:
        st.caption(" | ".join(meta_bits))

    # Divider before route buttons
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # Links
    cols = st.columns(len(routes))
    for i, label in enumerate(routes):
        with cols[i]:
            st.link_button(label, route_links(label), use_container_width=True)
    st.caption("If call links do not open on desktop, dial 108 manually or use a phone.")

    # Log once per new input
    if st.session_state.get("logged_for_input") != last_input:
        logs = load_logs()
        review_id = str(uuid4())
        primary_symptom = (last_input.lower().split(",")[0].split(" and ")[0]) if last_input else ""
        logs.append({
            "id": review_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "symptoms": last_input,
            "primary_symptom": primary_symptom.strip(),
            "urgency": urgency,
            "advice": advice_headline,
            "advice_points": advice_points,
            "age_hint": age_hint,
            "duration_days_hint": duration_hint,
            "severity_user": sev,
            "status": "Pending Review",
            "rule_reason": rule_reason
        })
        save_logs(logs)
        st.session_state["logged_for_input"] = last_input

    # One-click copy summary
    summary = f"{datetime.utcnow().isoformat()}Z • {last_input} • Urgency: {urgency} • Advice: {advice_headline} • Age:{age_hint} • Dur:{duration_hint} • Sev:{sev}"
    st.text_area("Copy summary", summary, height=60)

    # CSAT feedback
    with st.expander("Feedback"):
        colf1, colf2 = st.columns(2)
        if colf1.button("👍 Helpful"):
            logs = load_logs()
            if logs:
                logs[-1]["csat"] = "good"
                save_logs(logs)
            st.success("Thanks for the feedback.")
        if colf2.button("👎 Not helpful"):
            logs = load_logs()
            if logs:
                logs[-1]["csat"] = "bad"
                save_logs(logs)
            st.info("Feedback recorded.")

# Download recent CSV
with st.expander("Download recent (CSV)"):
    logs = load_logs()
    if logs:
        output = io.StringIO()
        fieldnames = sorted({k for row in logs for k in row.keys()})
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(logs[-50:])
        st.download_button(
            "Download last 50 entries",
            data=output.getvalue().encode("utf-8"),
            file_name=f"healthbuddy_recent_{datetime.utcnow().date()}.csv",
            mime="text/csv"
        )
    else:
        st.caption("No logs yet.")

st.markdown("<hr/>", unsafe_allow_html=True)
st.caption("HealthBuddy — Hackathon MVP • Built with Streamlit.")
