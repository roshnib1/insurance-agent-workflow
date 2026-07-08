"""
Streamlit frontend for the AI Underwriting Workflow.

Drop this file in the project root (same level as app.py) and run:

    streamlit run streamlit_app.py

It reuses workflow/controller.py exactly as app.py does -- no duplicated
business logic, this is purely a presentation layer over run_workflow().
"""

import glob
import json
import os
import tempfile

import streamlit as st

from workflow.controller import run_workflow

st.set_page_config(page_title="AI Underwriting Workflow", page_icon="🛡️", layout="wide")

STATUS_STYLE = {
    "COMPLETED": ("✅", "#16a34a"),
    "STOPPED_INCOMPLETE": ("✋", "#ca8a04"),
    "STOPPED_MISMATCH": ("⚠️", "#dc2626"),
    "STOPPED_HUMAN_REVIEW": ("🧑‍⚖️", "#2563eb"),
}

RISK_COLOR = {"LOW": "#16a34a", "MEDIUM": "#ca8a04", "HIGH": "#dc2626"}


def badge(text, color):
    return (
        f'<span style="background:{color}22;color:{color};border:1px solid {color}66;'
        f'padding:2px 10px;border-radius:999px;font-weight:600;font-size:0.85rem;">{text}</span>'
    )


st.title("🛡️ AI Underwriting Workflow")
st.caption("Google ADK multi-agent proposal review — submission intake, document intelligence, "
           "risk assessment, underwriting recommendation, human review.")

with st.sidebar:
    st.header("Proposal Input")

    sample_files = sorted(glob.glob(os.path.join("data", "*.html"))) + sorted(glob.glob(os.path.join("data", "*.pdf")))
    sample_labels = ["— select a sample —"] + [os.path.basename(f) for f in sample_files]
    chosen_sample = st.selectbox("Use a sample proposal", sample_labels)

    st.markdown("**— or —**")
    uploaded = st.file_uploader("Upload a proposal (.html or .pdf)", type=["html", "htm", "pdf"])

    provider = os.environ.get("MODEL_PROVIDER", "groq")
    st.caption(f"Model provider: `{provider}`")

    run_clicked = st.button("▶ Run Workflow", type="primary", use_container_width=True)

if "decision" not in st.session_state:
    st.session_state.decision = None
    st.session_state.file_label = None

if run_clicked:
    file_path = None
    file_label = None

    if uploaded is not None:
        suffix = os.path.splitext(uploaded.name)[1]
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.write(uploaded.getvalue())
        tmp.close()
        file_path = tmp.name
        file_label = uploaded.name
    elif chosen_sample != sample_labels[0]:
        file_path = os.path.join("data", chosen_sample)
        file_label = chosen_sample

    if not file_path:
        st.warning("Pick a sample proposal or upload a file first.")
    else:
        with st.spinner(f"Running workflow on {file_label} ..."):
            try:
                decision = run_workflow(file_path)
                st.session_state.decision = decision
                st.session_state.file_label = file_label
            except Exception as e:
                st.error(f"Workflow failed: {e}")
                st.session_state.decision = None

decision = st.session_state.decision

if decision is None:
    st.info("Select or upload a proposal, then click **Run Workflow** in the sidebar.")
    st.stop()

st.subheader(f"Result — {st.session_state.file_label}")

status = decision.get("status", "UNKNOWN")
icon, color = STATUS_STYLE.get(status, ("❔", "#6b7280"))

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.markdown(f"**Status**<br>{badge(f'{icon} {status}', color)}", unsafe_allow_html=True)
with col2:
    risk_cat = decision.get("risk_category")
    if risk_cat:
        st.markdown(f"**Risk Category**<br>{badge(risk_cat, RISK_COLOR.get(risk_cat, '#6b7280'))}", unsafe_allow_html=True)
    else:
        st.markdown("**Risk Category**<br>—", unsafe_allow_html=True)
with col3:
    st.metric("Risk Score", decision.get("risk_score") if decision.get("risk_score") is not None else "—")
with col4:
    conf = decision.get("confidence")
    st.metric("Confidence", f"{conf:.2f}" if conf is not None else "—")

col5, col6 = st.columns(2)
with col5:
    st.markdown(f"**Recommendation:** {decision.get('recommendation') or '—'}")
with col6:
    st.markdown(f"**Premium:** {decision.get('premium') or '—'}")

st.markdown(f"**Application ID:** `{decision.get('application_id') or '—'}`")

st.divider()

left, right = st.columns([1, 1])

with left:
    st.markdown("#### Decision Evidence")
    evidence = decision.get("decision_evidence") or []
    if evidence:
        for item in evidence:
            st.markdown(f"- {item}")
    else:
        st.caption("No evidence recorded.")

with right:
    st.markdown("#### Audit Trail")
    for step in decision.get("audit_trail", []):
        st.markdown(f"- {step}")

communication = decision.get("communication")
if communication:
    st.divider()
    st.markdown("#### ✉️ Drafted Communication (not sent)")
    st.caption(f"Trigger: `{communication.get('trigger')}` · Recipient: {communication.get('recipient')}")
    st.text_input("Subject", value=communication.get("subject", ""), disabled=True)
    st.text_area("Body", value=communication.get("body", ""), height=220, disabled=True)

st.divider()
with st.expander("Raw decision.json"):
    st.json(decision)

st.download_button(
    "⬇ Download decision.json",
    data=json.dumps(decision, indent=2),
    file_name=f"decision_{decision.get('application_id', 'unknown').replace('/', '_')}.json",
    mime="application/json",
)