"""
app.py  ·  Phase 2  (Real local auth, roles, dashboards — ML pipeline unchanged)
======================================================================
AI-Based Multilingual SMS Scam Detection System for Kathmandu

This file is the orchestrator: it wires together the ORIGINAL, UNCHANGED
prediction pipeline (preprocess -> TF-IDF + security features -> model ->
explain) with the UI in ui/. See ENGINEERING_REVIEW.md for the full
account of every redesign/feature pass (v5, v6, v7 phase 1, Phase 2).

Phase 2 replaces Phase 1's single-table "Guest vs Premium" auth stub with
a real local SQLite system: bcrypt-hashed passwords, an email + role
column, a seeded admin account, and role-aware navigation (Guest /
Premium / Admin each see a different sidebar). The UI chrome itself
(cards, colours, typography, spacing) was deliberately left alone this
pass — see ENGINEERING_REVIEW.md §10 for the full account of what changed
and why.

Page flow (Guest / Analyse SMS, top to bottom):
    Navbar -> SMS Input -> Analyse Button -> Demo Mode -> Model Info ->
    How AI Works -> Result -> Explainable AI -> Analyst Report
    (Entities + Threat Intelligence) -> Session History -> Footer

Once logged in, the sidebar additionally routes to: Dashboard, History
(persistent, searchable, favouritable), Export (PDF/CSV/TXT), Premium
(model statistics + feedback history), Settings, About, Logout — and,
for the admin role only, Admin Dashboard.

Backend contract preserved exactly since v4:
    - utils.preprocessing.preprocess()
    - utils.security_features.extract_security_features()
    - utils.explain.find_suspicious_keywords() / build_explanation()
    - predict(): same TF-IDF+security-feature fusion, same SCAM_DECISION_THRESHOLD
      (0.38) compensating for class imbalance, same model files.

Run:  streamlit run app.py
"""

import os
import sys
import csv
import pickle
import time
import datetime

import numpy as np
import scipy.sparse as sp
import streamlit as st

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from utils.preprocessing import preprocess
from utils.security_features import extract_security_features
from utils.explain import find_suspicious_keywords, build_explanation

from ui import styles, components, theme, navbar
from ui.language import detect_language_with_confidence, LANGUAGE_FLAG
from ui.scoring import compute_threat_score
from ui.patterns import detect_indicators, highlight_message
from ui.knowledge import get_recommendation, get_similar_scam_note
from ui.validation import validate_sms
from ui.pdf_report import build_pdf_report
from ui.entities import extract_entities
from ui.threat_intel import build_threat_intelligence
from ui.about import render_about_page
from ui.constants import APP_VERSION as MODEL_VERSION
from ui import database, auth, dashboard, history as history_mod, export as export_mod, profile, admin

MODEL_DIR = os.path.join(ROOT, "model")
DATA_PATH = os.path.join(ROOT, "data", "sms_dataset.csv")
LOG_DIR = os.path.join(ROOT, "logs")
LOG_FILE = os.path.join(LOG_DIR, "predictions.log")
os.makedirs(LOG_DIR, exist_ok=True)
database.init_db(ROOT)
auth.ensure_admin_seed(ROOT)
DEFAULT_CONFIDENCE_THRESHOLD = 0.70
SCAM_DECISION_THRESHOLD = 0.38  # unchanged from v4 — see predict() below

EXAMPLES = {
    "Banking scam (English)":
        "URGENT: Your bank account will be blocked. Verify your details immediately at http://fake-bank-nepal.com/verify",
    "Lottery scam (Roman Nepali)":
        "tapai le lottery jitnu bhayo Rs. 10 lakh! aile nai call garnus 9800000001",
    "OTP scam (Roman Nepali)":
        "tapai ko OTP arulai dinuhos natra khata band huncha 9800098765 ma call garnus",
    "Loan scam (English)":
        "Get a personal loan of Rs. 5 lakh instantly. No documents needed. Call now!",
    "Promotion scam (English)":
        "Congratulations! You've been selected for a FREE Ncell data bonus. "
        "Claim now at http://ncell-bonus-offer.tk before it expires today!",
    "Banking scam (Nepali Unicode)":
        "तपाईंको बैंक खाता बन्द हुनेछ। कृपया तुरुन्त आफ्नो विवरण यहाँ पुष्टि गर्नुहोस्: http://fake-bank.com/verify",
    "Normal financial chat (Roman Nepali)":
        "maile deko paisa firta deu",
    "Normal bank notification (English)":
        "Your salary has been credited. Available balance: Rs. 45,230.",
    "Legitimate OTP (English)":
        "Your OTP for login is 482910. Do not share this with anyone.",
    "Normal paisa conversation":
        "bhai le paisa pathako raicha dhanyabad bhai",
}

# Demo Mode — one click auto-fills *and* auto-analyses, for a fast viva
# walkthrough. Scoped to the five scam categories the trained classifier
# actually supports (see model/train_model.py) plus one legit example and
# two language-specific scam examples. Deliberately no "Investment Scam" /
# "Government Scam" demo button: the scam_type model was never trained on
# those classes, and a button implying the system detects them would
# misrepresent what's actually been trained and evaluated.
DEMO_EXAMPLES = [
    ("Bank Scam", "Banking scam (English)"),
    ("Lottery Scam", "Lottery scam (Roman Nepali)"),
    ("OTP Scam", "OTP scam (Roman Nepali)"),
    ("Loan Scam", "Loan scam (English)"),
    ("Promotion Scam", "Promotion scam (English)"),
    ("Legitimate SMS", "Normal bank notification (English)"),
    ("Roman Nepali Scam", "Lottery scam (Roman Nepali)"),
    ("Nepali Unicode Scam", "Banking scam (Nepali Unicode)"),
]

# Nav item -> active_view value, for the role-aware sidebar built below.
PREMIUM_ONLY_VIEWS = {"dashboard", "history", "export", "premium"}
ADMIN_ONLY_VIEWS = {"admin"}


# ─── Page config ────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="SMS Scam Detector – Kathmandu",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ─── Model loading (cached — unchanged behaviour) ─────────────────────────────

@st.cache_resource(show_spinner="Loading AI model …")
def load_models():
    def _l(f):
        p = os.path.join(MODEL_DIR, f)
        if not os.path.exists(p):
            return None
        with open(p, "rb") as fh:
            return pickle.load(fh)
    return {k: _l(v) for k, v in {
        "model": "model.pkl",
        "vectorizer": "vectorizer.pkl",
        "scam_type_model": "scam_type_model.pkl",
        "scam_type_vec": "scam_type_vec.pkl",
        "risk_model": "risk_model.pkl",
        "risk_vec": "risk_vec.pkl",
        "le_label": "le_label.pkl",
        "le_scam_type": "le_scam_type.pkl",
        "le_risk": "le_risk.pkl",
    }.items()}


def models_ok(m):
    return all(v is not None for v in m.values())


# ─── Prediction (UNCHANGED from v4 — see module docstring) ───────────────────

def get_top_tfidf_words(text: str, vec, model, n=8) -> list:
    try:
        proc = preprocess(text)
        tfidf = vec.transform([proc])
        names = vec.get_feature_names_out()
        coef = model.coef_[0] if hasattr(model, "coef_") else None
        if coef is None:
            return []
        tfidf_coef = coef[:len(names)]
        arr = tfidf.toarray()[0]
        scores = arr * tfidf_coef
        idx = np.argsort(np.abs(scores))[::-1][:n]
        return [(names[i], float(scores[i])) for i in idx if arr[i] > 0]
    except Exception:
        return []


def predict(text: str, m: dict) -> dict:
    """Hybrid prediction: TF-IDF + security features combined.
    Identical logic since v4 — not modified as part of any UI redesign."""
    proc = preprocess(text)
    tfidf_vec = m["vectorizer"].transform([proc])

    sec_feats = extract_security_features(text)
    sec_arr = np.array([list(sec_feats.values())], dtype=float)
    X_combined = sp.hstack([tfidf_vec, sp.csr_matrix(sec_arr)])

    proba = m["model"].predict_proba(X_combined)[0]
    classes = list(m["le_label"].classes_)
    scam_idx = classes.index("Scam")
    legit_idx = 1 - scam_idx
    scam_prob = float(proba[scam_idx])

    if scam_prob >= SCAM_DECISION_THRESHOLD:
        label = "Scam"
        confidence = scam_prob
    else:
        label = "Legit"
        confidence = float(proba[legit_idx])

    if label == "Scam":
        st_tfidf = m["scam_type_vec"].transform([proc])
        st_sec = np.array([list(sec_feats.values())], dtype=float)
        st_X = sp.hstack([st_tfidf, sp.csr_matrix(st_sec)])
        st_idx = m["scam_type_model"].predict(st_X)[0]
        scam_type = m["le_scam_type"].inverse_transform([st_idx])[0]
    else:
        scam_type = "None"

    r_tfidf = m["risk_vec"].transform([proc])
    r_sec = np.array([list(sec_feats.values())], dtype=float)
    r_X = sp.hstack([r_tfidf, sp.csr_matrix(r_sec)])
    r_idx = m["risk_model"].predict(r_X)[0]
    risk = m["le_risk"].inverse_transform([r_idx])[0]
    if label == "Legit":
        risk = "Low"

    return {
        "label": label, "scam_type": scam_type, "risk_level": risk,
        "confidence": confidence, "proba": proba, "sec_feats": sec_feats,
        "scam_probability": scam_prob,
    }


def log_prediction(text, result, language):
    """System-wide usage log (Guest + Premium + Admin alike) — the data
    source for the Admin Dashboard's headline metrics. Gained a
    `threat_score` column in Phase 2 so "Average Threat Score" can be
    computed without re-running inference."""
    try:
        new_file = not os.path.exists(LOG_FILE)
        with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new_file:
                w.writerow(["timestamp", "language", "label", "scam_type", "risk_level", "confidence", "threat_score", "message"])
            w.writerow([
                datetime.datetime.now().isoformat(timespec="seconds"),
                language, result["label"], result["scam_type"],
                result["risk_level"], f"{result['confidence']:.4f}",
                result.get("threat_score", ""), text.replace("\n", " "),
            ])
    except Exception:
        pass


# ─── Session state ─────────────────────────────────────────────────────────────

if "sms_input" not in st.session_state:
    st.session_state["sms_input"] = ""
if "history" not in st.session_state:
    st.session_state["history"] = []
if "current_result" not in st.session_state:
    st.session_state["current_result"] = None
if "confidence_threshold" not in st.session_state:
    st.session_state["confidence_threshold"] = DEFAULT_CONFIDENCE_THRESHOLD
if "active_view" not in st.session_state:
    st.session_state["active_view"] = "analyzer"
if "auth_user" not in st.session_state:
    st.session_state["auth_user"] = None  # Guest Mode by default — no account required

# A widget-bound key (like "sms_input") cannot be reassigned after its widget
# has been instantiated in the same run — Streamlit raises a
# StreamlitAPIException. Restoring a past message from the History panel or
# Demo Mode happens from a callback that fires *after* the text_area already
# exists in that run, so the new value is staged here and applied on the
# *next* run, before the text_area is created below.
if "_pending_sms_input" in st.session_state:
    st.session_state["sms_input"] = st.session_state.pop("_pending_sms_input")

st.markdown(styles.inject_global_css(dark_mode=theme.is_dark_mode()), unsafe_allow_html=True)


def _paste_example():
    choice = st.session_state.get("example_selector")
    if choice in EXAMPLES:
        st.session_state["sms_input"] = EXAMPLES[choice]


def _clear_all():
    st.session_state["sms_input"] = ""
    st.session_state["current_result"] = None


def _select_history(idx: int):
    entry = st.session_state["history"][idx]
    st.session_state["current_result"] = entry
    st.session_state["_pending_sms_input"] = entry["message"]
    st.rerun()


def _delete_history(idx: int):
    """Removes a single entry from session history. If the deleted entry
    is the one currently on screen, clears the result too so the app
    doesn't keep displaying an analysis that's no longer in the history
    list."""
    history = st.session_state["history"]
    if 0 <= idx < len(history):
        deleted = history.pop(idx)
        if st.session_state.get("current_result") is deleted:
            st.session_state["current_result"] = None
    st.rerun()


def _run_demo(example_key: str):
    """Demo Mode: paste + auto-analyse in one click, for a fast viva
    walkthrough. Stages the message the same way history-restore does
    (see the `_pending_sms_input` note above) and additionally sets
    `_trigger_analysis`, which the Analyse block below treats exactly like
    a real button click."""
    st.session_state["_pending_sms_input"] = EXAMPLES[example_key]
    st.session_state["_trigger_analysis"] = True
    st.rerun()


def _view_saved_history_row(row: dict):
    """Restores a saved (SQLite) History row into the live analyzer view.
    Only the fields the DB actually stores are available (message,
    prediction, confidence, threat_score, risk, scam_type, language) — a
    full Explainable AI re-render needs the original text re-analysed, so
    this stages the message and re-runs analysis rather than faking the
    richer in-memory result shape."""
    st.session_state["_pending_sms_input"] = row["message"]
    st.session_state["_trigger_analysis"] = True
    st.session_state["active_view"] = "analyzer"
    st.rerun()


def run_analysis(text: str) -> dict:
    """The full analysis pipeline for one message. Split out of the button
    handler so the multi-stage st.status() below reads as real progress
    (each stage genuinely corresponds to a chunk of this function), not a
    fake animation."""
    lang_result = detect_language_with_confidence(text)
    raw_result = predict(text, models)
    suspicious = find_suspicious_keywords(text)
    top_words = get_top_tfidf_words(text, models["vectorizer"], models["model"])

    explanation = build_explanation(
        raw_result["label"], raw_result["scam_type"], raw_result["risk_level"],
        suspicious, raw_result["confidence"], raw_result["sec_feats"], top_words,
    )
    highlighted = highlight_message(text, suspicious)
    indicators = detect_indicators(
        text, raw_result["sec_feats"], suspicious,
        raw_result["label"], raw_result["scam_type"],
    )
    threat = compute_threat_score(raw_result["scam_probability"], raw_result["sec_feats"])
    recommendation = (
        get_recommendation(raw_result["scam_type"]) if raw_result["label"] == "Scam"
        else explanation["advice"]
    )
    similar_scam = get_similar_scam_note(raw_result["label"], raw_result["scam_type"])
    entities = extract_entities(text)
    threat_intel = build_threat_intelligence(
        raw_result["label"], raw_result["scam_type"], raw_result["sec_feats"], suspicious,
    )

    return {
        "message": text,
        "label": raw_result["label"],
        "scam_type": raw_result["scam_type"],
        "risk_level": raw_result["risk_level"],
        "confidence": raw_result["confidence"],
        "proba": raw_result["proba"],
        "language": lang_result.language,
        "language_confidence": lang_result.confidence,
        "threat_score": threat.score,
        "threat_severity": threat.severity,
        "indicators": [i.label for i in indicators if i.active],
        "recommendation": recommendation,
        "similar_scam": similar_scam,
        "explanation": explanation,
        "highlighted": highlighted,
        "indicator_objs": indicators,
        "entities": entities,
        "threat_intel": threat_intel,
    }


# ─── Sidebar: role-aware navigation ─────────────────────────────────────────
# Guest  : Analyse SMS, About, Settings, Login (Login is also reachable via
#          the navbar's 👤 badge — kept here too so it's not hidden).
# Premium: Dashboard, Analyse SMS, History, Export, Premium, Settings,
#          About, Logout — exactly the brief's §5 list.
# Admin  : the Premium list, plus Admin Dashboard.
# Example Messages stays visible to everyone — it's a helper control for
# the analyzer, not one of the features the brief restricts for Guests.

def _nav_button(label: str, view: str, active_view: str, key: str):
    is_active = active_view == view
    if st.button(("▶ " if is_active else "") + label, key=key, use_container_width=True,
                 type="primary" if is_active else "secondary"):
        st.session_state["active_view"] = view
        st.rerun()


with st.sidebar:
    components.render_sidebar_brand()

    components.render_sidebar_label("Example Messages", "list")
    st.selectbox(
        "Load example", list(EXAMPLES.keys()),
        key="example_selector",
        label_visibility="collapsed",
    )

    st.markdown('<hr class="sidebar-rule">', unsafe_allow_html=True)

    _current_view = st.session_state.get("active_view", "analyzer")
    _user = auth.current_user()

    if _user:
        components.render_sidebar_label("Navigation", "layers")
        _nav_button("📊 Dashboard", "dashboard", _current_view, "nav_dashboard")
        _nav_button("🔍 Analyse SMS", "analyzer", _current_view, "nav_analyzer")
        _nav_button("🕒 History", "history", _current_view, "nav_history")
        _nav_button("📤 Export", "export", _current_view, "nav_export")
        _nav_button("⭐ Premium", "premium", _current_view, "nav_premium")
        _nav_button("⚙️ Settings", "settings", _current_view, "nav_settings")
        _nav_button("ℹ️ About", "about", _current_view, "nav_about")
        if auth.is_admin():
            _nav_button("🛡️ Admin Dashboard", "admin", _current_view, "nav_admin")
        st.markdown('<hr class="sidebar-rule">', unsafe_allow_html=True)
        if st.button("🚪 Logout", key="nav_logout", use_container_width=True):
            auth.clear_session()
            st.session_state["active_view"] = "analyzer"
            st.rerun()
    else:
        components.render_sidebar_label("Navigation", "layers")
        _nav_button("🔍 Analyse SMS", "analyzer", _current_view, "nav_analyzer_guest")
        _nav_button("ℹ️ About", "about", _current_view, "nav_about_guest")
        _nav_button("⚙️ Settings", "settings", _current_view, "nav_settings_guest")
        _nav_button("👤 Login / Register", "login", _current_view, "nav_login_guest")
        st.markdown('<hr class="sidebar-rule">', unsafe_allow_html=True)
        st.caption(
            "Guest Mode: Analyse SMS, view Explainable AI, and use example "
            "messages — no account needed. Log in to save history, export "
            "reports, and view your dashboard."
        )


# ─── Navbar (brand + Help + About + theme toggle + account badge) ───────────

active_view = navbar.render_navbar(st.session_state.get("active_view", "analyzer"), root=ROOT)

# Role gates — a stale active_view (e.g. after logout) falls back to the
# analyzer rather than crashing or leaking a restricted page.
if active_view in PREMIUM_ONLY_VIEWS and not auth.is_premium():
    active_view = "analyzer"
    st.session_state["active_view"] = "analyzer"
if active_view in ADMIN_ONLY_VIEWS and not auth.is_admin():
    active_view = "analyzer"
    st.session_state["active_view"] = "analyzer"
if active_view == "login" and auth.is_logged_in():
    active_view = "analyzer"
    st.session_state["active_view"] = "analyzer"

if active_view == "about":
    render_about_page()
    components.render_footer()
    st.stop()

if active_view == "login":
    auth.render_login_register_page(ROOT)
    components.render_footer()
    st.stop()

if active_view == "settings":
    components.render_settings_page()
    components.render_footer()
    st.stop()

if active_view == "profile":
    if not auth.is_logged_in():
        st.session_state["active_view"] = "login"
        st.rerun()
    profile.render_profile_page(ROOT, auth.current_user())
    components.render_footer()
    st.stop()

if active_view == "dashboard":
    dashboard.render_dashboard_page(ROOT, auth.current_user())
    components.render_footer()
    st.stop()

if active_view == "history":
    history_mod.render_history_page(ROOT, auth.current_user(), on_view=_view_saved_history_row)
    components.render_footer()
    st.stop()

if active_view == "export":
    export_mod.render_export_page(ROOT, auth.current_user())
    components.render_footer()
    st.stop()

if active_view == "premium":
    components.render_premium_page(ROOT, auth.current_user())
    components.render_footer()
    st.stop()

if active_view == "admin":
    admin.render_admin_dashboard(ROOT, auth.current_user())
    components.render_footer()
    st.stop()


# ─── Analyzer view ──────────────────────────────────────────────────────────

models = load_models()
if not models_ok(models):
    st.error("Models not found. Train first:\n```bash\npython model/train_model.py\n```", icon="🚨")
    st.stop()


# ─── SMS Input (the focal point — full width, no competing side column) ─────

st.markdown('<div class="card">', unsafe_allow_html=True)
st.markdown('<div class="card-title">📱 Enter SMS Message</div>', unsafe_allow_html=True)
st.text_area(
    "SMS", key="sms_input", height=140,
    placeholder="Paste any SMS here — English, Nepali, or Roman Nepali …",
    label_visibility="collapsed",
)

current_text = st.session_state["sms_input"]
if current_text.strip():
    lang_preview = detect_language_with_confidence(current_text.strip())
    st.caption(
        f"{LANGUAGE_FLAG.get(lang_preview.language, '❓')} Detected language: "
        f"**{lang_preview.language}** ({lang_preview.confidence*100:.0f}% confidence)"
    )

analyse_clicked = st.button("🔍  Analyse Message", type="primary", use_container_width=True)

btn_col1, btn_col2, btn_col3 = st.columns(3)
with btn_col1:
    st.button("🗑️ Clear", on_click=_clear_all, use_container_width=True)
with btn_col2:
    st.button("📋 Paste Example", on_click=_paste_example, use_container_width=True)
with btn_col3:
    copy_input_clicked = st.button("📄 Copy Input", use_container_width=True)
if copy_input_clicked:
    components.render_copy_button(current_text, key="input_text", label="📄 Copy Input Text")
st.markdown("</div>", unsafe_allow_html=True)

with st.expander("🎬 Demo Mode — one-click examples for a viva presentation"):
    st.markdown(
        '<div class="demo-hint">Click any example below to auto-fill and immediately '
        'analyse it — useful for a live walkthrough without retyping messages.</div>',
        unsafe_allow_html=True,
    )
    demo_cols = st.columns(4)
    for i, (demo_label, example_key) in enumerate(DEMO_EXAMPLES):
        with demo_cols[i % 4]:
            if st.button(demo_label, key=f"demo_{i}", use_container_width=True):
                _run_demo(example_key)

components.render_model_info_strip()

with st.expander("🧠 How AI Works — Analysis Pipeline"):
    components.render_pipeline(active=bool(st.session_state["current_result"]))


# ─── Validation + analysis ─────────────────────────────────────────────────────

trigger_analysis = analyse_clicked or st.session_state.pop("_trigger_analysis", False)

if trigger_analysis:
    text = st.session_state["sms_input"].strip()
    validation = validate_sms(text)

    if not validation.is_valid:
        st.warning(validation.error, icon="✍️")
        st.session_state["current_result"] = None
    else:
        with st.status("Analysing message…", expanded=False) as status:
            start_time = time.perf_counter()
            status.update(label="Analysing message…")
            result = run_analysis(text)
            status.update(label="Generating explanation…")
            result["detection_time_seconds"] = time.perf_counter() - start_time
            log_prediction(text, {
                "label": result["label"], "scam_type": result["scam_type"],
                "risk_level": result["risk_level"], "confidence": result["confidence"],
                "threat_score": result["threat_score"],
            }, result["language"])
            status.update(label="Analysis complete", state="complete")

        result["time_label"] = datetime.datetime.now().strftime("%H:%M:%S")
        st.session_state["current_result"] = result
        st.session_state["history"].append(result)
        st.session_state["_just_saved"] = False


# ─── Result + Explainable AI ───────────────────────────────────────────────────

result = st.session_state.get("current_result")

if not result:
    components.render_empty_state()
else:
    confidence = result["confidence"]
    threshold = st.session_state["confidence_threshold"]
    is_scam = result["label"] == "Scam"

    if is_scam and confidence < threshold:
        display_label = "UNCERTAIN"
    elif is_scam:
        display_label = "SCAM"
    else:
        display_label = "LEGIT"

    components.render_verdict_banner(display_label, confidence)

    col_left, col_right = st.columns([1, 1], gap="large")
    with col_left:
        components.render_result_metrics(result)
    with col_right:
        components.render_threat_gauge(result["threat_score"], result["threat_severity"])

    # ── Explainable AI: distinct cards, not one container ─────────────────
    # Available to EVERYONE, Guest included — the brief's Guest restriction
    # list explicitly allows "View Explainable AI".
    components.render_section_heading("Explainable AI", "brain", "why the model reached this verdict")

    components.render_xai_summary(result["explanation"]["summary"])

    col_a, col_b = st.columns([1, 1], gap="large")
    with col_a:
        components.render_indicators(result["indicator_objs"])
        components.render_xai_reasons(result["explanation"]["reasons"])
    with col_b:
        classes = models["le_label"].classes_
        pal = theme.get_palette()
        class_colors = {"Scam": pal["DANGER"], "Legit": pal["SUCCESS"]}
        class_probs = [(cls, float(p), class_colors.get(cls, pal["PRIMARY"]))
                       for cls, p in zip(classes, result["proba"])]
        components.render_probability_bars(class_probs)
        fb = result["explanation"]["feature_breakdown"]
        components.render_xai_feature_breakdown(fb["increases_scam"], fb["reduces_scam"])

    components.render_message_preview(result["highlighted"])
    components.render_xai_tfidf_words(result["explanation"]["tfidf_words"])
    components.render_xai_recommendation(result["recommendation"])

    if result["similar_scam"]:
        components.render_knowledge_base_note(result["similar_scam"])

    # ── Analyst Report: extracted entities + threat intelligence ──────────
    components.render_section_heading("Analyst Report", "activity", "structured artefacts and attack-pattern matching")
    col_ent, col_intel = st.columns([1, 1], gap="large")
    with col_ent:
        components.render_entities_card(result["entities"])
    with col_intel:
        components.render_threat_intel_card(result["threat_intel"])

    # ── Save / Export & feedback ────────────────────────────────────────────
    # "Save Analysis" and file export (PDF/CSV/TXT) are Premium/Admin-only,
    # per the brief's explicit Guest restriction list ("Guests cannot: Save
    # history, Export reports"). Copy-to-clipboard is a plain-text
    # convenience, not a file export, so it stays available to everyone.
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<div class="card-title">📤 Save &amp; Export</div>', unsafe_allow_html=True)

    if auth.is_premium():
        _user = auth.current_user()
        export_col1, export_col2, export_col3 = st.columns([1, 1, 1])
        with export_col1:
            if st.button("💾 Save Analysis", use_container_width=True, key="save_analysis_btn"):
                history_mod.save_analysis(ROOT, _user["id"], result)
                st.session_state["_just_saved"] = True
            if st.session_state.get("_just_saved"):
                st.caption("Saved — view it under History.")
        with export_col2:
            pdf_bytes = build_pdf_report(result)
            st.download_button(
                "⬇️ PDF Report", data=pdf_bytes,
                file_name=f"scam_report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                mime="application/pdf", use_container_width=True,
            )
        with export_col3:
            components.render_copy_button(
                components.build_copy_summary(result), key="main_result",
            )
    else:
        st.caption(
            "**Log in to unlock:** Save Analysis, PDF/CSV/TXT export, and your "
            "personal Dashboard. You can still copy this result as text below."
        )
        components.render_copy_button(
            components.build_copy_summary(result), key="main_result",
        )
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="card">', unsafe_allow_html=True)
    components.render_feedback_widget(
        ROOT, result["message"], result, widget_key="main",
        user_id=(auth.current_user() or {}).get("id"),
    )
    st.markdown("</div>", unsafe_allow_html=True)


# ─── Analysis History (session-only panel — everyone, Guest included) ──────

components.render_section_heading("Session History", "history", "this session only — nothing is stored after you close the tab")
st.markdown('<div class="card">', unsafe_allow_html=True)
components.render_history_panel(st.session_state["history"], on_select=_select_history, on_delete=_delete_history)
st.markdown("</div>", unsafe_allow_html=True)

if not auth.is_premium():
    st.caption(
        "This list clears when you close the tab. Log in to permanently "
        "**Save Analysis** results — they'll appear under History, "
        "searchable and exportable, across sessions."
    )


# ─── Footer ────────────────────────────────────────────────────────────────────

components.render_footer()
