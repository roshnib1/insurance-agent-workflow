"""
Streamlit frontend for the Commercial Property Underwriting Workflow.

Run from the project root:

    streamlit run streamlit_app.py

Purely a presentation layer -- no duplicated business logic. Calls
whichever controller's run_workflow() is picked in the sidebar:

  - v1 (workflow/controller.py): hand-rolled Python orchestration
  - v2 (workflow/property_controller.py): real google.adk.workflow.Workflow graph

Both return the same decision.json shape, so everything below is
controller-agnostic.
"""

import glob
import json
import os
import tempfile

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="Commercial Property Underwriting", page_icon="🏢", layout="wide")

STATUS_STYLE = {
    "COMPLETED": ("✅", "#16a34a"),
    "CONDITIONALLY_APPROVED": ("🟡", "#ca8a04"),
    "REJECTED": ("⛔", "#dc2626"),
    "STOPPED_INCOMPLETE": ("✋", "#ca8a04"),
    "STOPPED_MISMATCH": ("⚠️", "#dc2626"),
    "STOPPED_HUMAN_REVIEW": ("🧑‍⚖️", "#2563eb"),
}
RISK_COLOR = {"LOW": "#16a34a", "MEDIUM": "#ca8a04", "HIGH": "#dc2626"}
MODE_COLOR = {"AUTONOMOUS": "#16a34a", "HUMAN_REVIEW": "#2563eb", "SENIOR_UNDERWRITER": "#7c3aed", "OVERRIDE": "#ca8a04"}


def badge(text, color):
    return (
        f'<span style="background:{color}22;color:{color};border:1px solid {color}66;'
        f'padding:2px 10px;border-radius:999px;font-weight:600;font-size:0.85rem;">{text}</span>'
    )


st.title("🏢 Commercial Property Underwriting Workflow")
st.caption(
    "Google ADK multi-agent proposal review — submission intake, document intelligence, "
    "CAT exposure, risk assessment, pricing, human underwriter, senior underwriter, evidence generation."
)

page = st.sidebar.radio("View", ["▶ Run Case", "📄 Decision Detail"], label_visibility="collapsed")

with st.sidebar:
    st.divider()
    st.header("Proposal Input")

    sample_files = sorted(glob.glob(os.path.join("data", "proposal_*.html")))
    sample_labels = ["— select a sample case —"] + [os.path.basename(f) for f in sample_files]
    chosen_sample = st.selectbox("Use a sample case", sample_labels)

    st.markdown("**— or —**")
    uploaded = st.file_uploader("Upload a proposal (.html or .pdf)", type=["html", "htm", "pdf"])

    st.divider()
    controller_choice = st.radio(
        "Controller",
        options=["v1 — Python controller", "v2 — ADK Workflow graph"],
        help="v1: workflow/controller.py, hand-rolled routing. "
             "v2: workflow/property_controller.py, a real google.adk.workflow.Workflow graph.",
    )

    provider = os.environ.get("MODEL_PROVIDER", "gemini")
    st.caption(f"Model provider: `{provider}`")

    run_clicked = st.button("▶ Run Workflow", type="primary", use_container_width=True)

if "decision" not in st.session_state:
    st.session_state.decision = None
    st.session_state.file_label = None
    st.session_state.live_events = []

if run_clicked:
    file_path, file_label = None, None

    if uploaded is not None:
        suffix = os.path.splitext(uploaded.name)[1]
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.write(uploaded.getvalue())
        tmp.close()
        file_path, file_label = tmp.name, uploaded.name
    elif chosen_sample != sample_labels[0]:
        file_path, file_label = os.path.join("data", chosen_sample), chosen_sample

    if not file_path:
        st.warning("Pick a sample case or upload a file first.")
    else:
        progress_box = st.container()
        progress_box.markdown("#### ⏱️ Live progress")
        progress_log = progress_box.empty()
        st.session_state.live_events = []

        def _on_event(e):
            st.session_state.live_events.append(e)
            lines = [f"`{ev['event']:>9}` **{ev['phase']}** :: {ev['step']}" for ev in st.session_state.live_events[-25:]]
            progress_log.markdown("\n\n".join(lines))

        with st.spinner(f"Running {controller_choice} on {file_label} ..."):
            try:
                if controller_choice.startswith("v2"):
                    from workflow.property_controller import run_workflow
                    decision = run_workflow(file_path)  # v2's own internal tracker; live per-event UI not wired for the graph engine
                else:
                    from workflow.controller import run_workflow
                    from workflow.progress import ProgressTracker
                    tracker = ProgressTracker(on_event=_on_event)
                    decision = run_workflow(file_path, tracker=tracker)

                st.session_state.decision = decision
                st.session_state.file_label = file_label
                st.session_state.controller_used = controller_choice
            except Exception as e:
                st.error(f"Workflow failed: {e}")
                st.session_state.decision = None

decision = st.session_state.decision

if page == "▶ Run Case":
    if decision is None:
        st.info("Select a sample case or upload a file, then click **Run Workflow** in the sidebar.")
        st.stop()

    st.subheader(f"Result — {st.session_state.file_label}")
    st.caption(f"Controller: {st.session_state.get('controller_used', '')}")

    status = decision.get("status", "UNKNOWN")
    icon, color = STATUS_STYLE.get(status, ("❔", "#6b7280"))

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.markdown(f"**Status**<br>{badge(f'{icon} {status}', color)}", unsafe_allow_html=True)
    with col2:
        mode = decision.get("decision_mode")
        st.markdown(f"**Decision Mode**<br>{badge(mode, MODE_COLOR.get(mode, '#6b7280')) if mode else '—'}", unsafe_allow_html=True)
    with col3:
        risk_cat = decision.get("risk_category")
        st.markdown(f"**Risk Category**<br>{badge(risk_cat, RISK_COLOR.get(risk_cat, '#6b7280')) if risk_cat else '—'}", unsafe_allow_html=True)
    with col4:
        st.metric("Risk Score", decision.get("risk_score") if decision.get("risk_score") is not None else "—")
    with col5:
        conf = decision.get("confidence")
        st.metric("Confidence", f"{conf:.2f}" if conf is not None else "—")

    col6, col7, col8 = st.columns(3)
    with col6:
        st.markdown(f"**Decision Maker:** {decision.get('decision_maker') or '—'}")
    with col7:
        rec = decision.get("recommendation", {})
        st.markdown(f"**Recommendation:** {rec.get('action') or '—'}")
    with col8:
        st.markdown(f"**Pricing:** {decision.get('pricing', {}).get('recommendation') or '—'}")

    st.markdown(f"**Application ID:** `{decision.get('application_id') or '—'}`")

    st.divider()
    left, right = st.columns(2)
    with left:
        st.markdown("#### Decision Evidence")
        for item in decision.get("decision_evidence") or []:
            st.markdown(f"- {item}")
    with right:
        st.markdown("#### Audit Trail")
        for step in decision.get("audit_trail", []):
            st.markdown(f"- {step}")

    communication = decision.get("communication", {})
    if communication.get("emails_generated"):
        st.divider()
        st.success(f"✓ {communication['emails_generated']} Email Draft{'s' if communication['emails_generated'] != 1 else ''} Generated")
        for draft in communication.get("drafts", []):
            with st.expander(f"✉️ {draft.get('subject', draft.get('email_id'))} — {draft.get('recipient_role')}"):
                st.caption(f"Status: {draft.get('status')} · {draft.get('reason', '')}")
                email_path = draft.get("file")
                if email_path and os.path.exists(email_path):
                    with open(email_path) as f:
                        email_full = json.load(f)
                    st.text_input("Subject", value=email_full.get("subject", ""), disabled=True, key=f"subj_{draft.get('email_id')}")
                    st.text_area("Body", value=email_full.get("body", ""), height=200, disabled=True, key=f"body_{draft.get('email_id')}")

else:  # 📄 Decision Detail
    if decision is None:
        st.info("Run a case first from the **▶ Run Case** view.")
        st.stop()

    tabs = st.tabs(["Decision", "Audit Trail", "Approval Lineage", "Governance History", "Timeline", "Raw JSON"])

    with tabs[0]:
        st.json({k: decision.get(k) for k in (
            "application_id", "scenario", "status", "current_phase", "decision_mode", "decision_maker",
            "risk_category", "risk_score", "confidence", "cat_exposure", "pricing", "recommendation",
        )})

    with tabs[1]:
        for step in decision.get("audit_trail", []):
            st.markdown(f"- {step}")

    with tabs[2]:
        for entry in decision.get("approval_lineage", []):
            st.markdown(f"- **{entry.get('actor')}** → `{entry.get('action')}`")

    with tabs[3]:
        governance = decision.get("governance_history", [])
        if governance:
            for g in governance:
                st.markdown(f"- **{g.get('check')}** (trigger: `{g.get('trigger')}`) → {g.get('result')}")
        else:
            st.caption("No governance checkpoints triggered on this case.")

    with tabs[4]:
        timeline = decision.get("execution_timeline", [])
        if timeline:
            for e in timeline:
                st.markdown(f"`{e.get('event', ''):>10}` **{e.get('phase', '')}** :: {e.get('step', '')}")
        else:
            st.caption("No execution timeline recorded for this run.")

    with tabs[5]:
        st.json(decision)

    st.download_button(
        "⬇ Download decision.json",
        data=json.dumps(decision, indent=2),
        file_name=f"decision_{(decision.get('application_id') or 'unknown').replace('/', '_')}.json",
        mime="application/json",
    )
