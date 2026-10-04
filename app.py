"""Thalamus tester app (Streamlit): login, ask any question, verified answers with citations."""
import hmac
import os
import random
import time
import uuid

import streamlit as st

from thalamus.adapters.base import load_configs
from thalamus.pipeline import DEFAULT_PATIENT, ask, fmt_cost, load_serialized
from thalamus.store import make_store

st.set_page_config(page_title="Thalamus", page_icon="🩺", layout="centered")

# Hardcoded on purpose (phase 1, synthetic data only). Replace before any real patient data.
APP_USERNAME = "ajitesh"
APP_PASSWORD = "thalamus"


@st.cache_resource
def load_resources():
    cfgs, default = load_configs()
    return load_serialized(DEFAULT_PATIENT), make_store(), cfgs, default


def enabled_configs(cfgs, default):
    ids = [c.strip() for c in (os.environ.get("ENABLED_CONFIGS") or default).split(",") if c.strip()]
    return [cfgs[i] for i in ids if i in cfgs] or [cfgs[default]]


def caller_info() -> dict:
    """Caller details from request headers (client IP is the last X-Forwarded-For entry, as the host saw it)."""
    try:
        h = st.context.headers
    except Exception:  # noqa: BLE001 - headers unavailable (older Streamlit, tests)
        return {}
    fwd = (h.get("X-Forwarded-For") or "").split(",")[-1].strip()
    return {"client_ip": fwd or None, "origin": (h.get("Origin") or h.get("Host") or "")[:200] or None,
            "user_agent": (h.get("User-Agent") or "")[:400] or None}


def check_login(user: str, password: str) -> bool:
    # Evaluate both comparisons so timing does not reveal which field was wrong.
    ok_user = hmac.compare_digest(user.encode(), APP_USERNAME.encode())
    ok_pass = hmac.compare_digest(password.encode(), APP_PASSWORD.encode())
    return ok_user and ok_pass


st.session_state.setdefault("authed", False)
st.session_state.setdefault("session_id", uuid.uuid4().hex)
st.session_state.setdefault("history", [])  # newest first

if not st.session_state.authed:
    st.title("Thalamus")
    with st.form("login"):
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        if st.form_submit_button("Log in"):
            if check_login(u, p):
                st.session_state.authed = True
                st.rerun()
            time.sleep(1)  # slow down guessing
            st.error("Incorrect username or password.")
    st.stop()

ser, store, cfgs, default_id = load_resources()
enabled = enabled_configs(cfgs, default_id)
blind = (os.environ.get("MODEL_SELECTION") or "blind").lower() != "choose"


def render_run(item: dict, expanded: bool) -> None:
    r = item["result"]
    with st.container(border=True):
        st.caption(item["question"])
        if r.status == "error" or r.answer is None:
            st.error("Sorry, we could not get an answer for this question. Please try again in a moment.")
            if not blind and r.error:
                st.caption(f"{r.config_id}: {r.error}")
            return
        a = r.answer
        total = len(a.claims)
        failed = len({f["claim_index"] for f in (r.verification or {}).get("failures", [])})
        label = f"Citation match {total - failed}/{total}"
        badge = f":green-badge[✓ {label}]" if r.status == "verified" else f":orange-badge[{label}]"
        st.markdown(badge)
        st.markdown(f"### {a.answer}")
        with st.expander("Details and citations"):
            if a.key_caveat:
                st.warning(a.key_caveat)
            for d in a.details:
                st.markdown(f"- {d}")
            cited = list(dict.fromkeys(c for cl in a.claims for c in cl.cites))
            if cited:
                with st.expander(f"Cited rows ({len(cited)})", expanded=False):
                    for rid in cited:
                        row = r.rows.get(rid)
                        with st.expander(rid):
                            st.write(row.text if row else "Row not found in the record.")
            if a.conflicts:
                st.markdown("**Conflicts**")
                for c in a.conflicts:
                    st.markdown(f"- {c.topic}: {', '.join(c.rows)}")
            if a.not_documented:
                st.markdown("**Not documented**")
                for n in a.not_documented:
                    st.markdown(f"- {n}")
            if r.status == "unverified":
                with st.expander("Why some citations did not match"):
                    for f in r.verification.get("failures", []):
                        st.markdown(f"- Claim {f['claim_index'] + 1}: {f['problem']}")
        if not blind:
            st.caption(f"{r.config_id} · {r.model_returned} · in {r.input_tokens} (cached {r.cached_input_tokens}, cache-write {r.cache_write_tokens}) "
                       f"· out {r.output_tokens} · cost {fmt_cost(r.cost_usd)} · {r.latency_ms / 1000:.1f}s")


top = st.columns([4, 1])
top[0].title("Thalamus")
if top[1].button("Log out"):
    st.session_state.authed = False
    st.rerun()

st.text_input("Your name (optional)", key="rater_label")
st.subheader("Ask a question")
cfg = None
if not blind:
    cfg = st.selectbox("Model", enabled, format_func=lambda c: f"{c.id} ({c.model}, {c.effort})")
with st.form("ask", clear_on_submit=True):
    question = st.text_area("Question about this patient", height=100)
    asked = st.form_submit_button("Ask")

if asked:
    if not question.strip():
        st.warning("Type a question first.")
    else:
        chosen = cfg if not blind else random.choice(enabled)
        with st.spinner("Working on it. Answers can take up to a couple of minutes."):
            try:
                result = ask(question.strip(), chosen, source="web", ser=ser, store=store,
                             session_id=st.session_state.session_id, extra=caller_info(),
                             rater_label=st.session_state.get("rater_label") or None)
            except Exception as e:  # noqa: BLE001 - never show a stack trace to testers
                result = None
                st.error("Sorry, something went wrong. Please try again.")
        if result is not None:
            st.session_state.history.insert(0, {"question": question.strip(), "result": result})

if st.session_state.history:
    st.subheader("This session")
    for i, item in enumerate(st.session_state.history):
        render_run(item, expanded=(i == 0))
