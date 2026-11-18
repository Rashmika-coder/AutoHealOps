"""AutoHealOps - Streamlit dashboard (Person 4).

Run:  streamlit run app.py
"""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

import analytics as an
import config
from data_loader import (check_live_health, filter_window, get_container_status,
                         load_deployments, load_events)

st.set_page_config(page_title="AutoHealOps Dashboard", page_icon="🩺", layout="wide")

GREEN, RED, AMBER, BLUE, GREY = "#4a544f", "#d9534f", "#e0a030", "#3b82f6", "#94a3b8"
STATUS_COLORS = {
    "running": GREEN, "healthy": GREEN, "success": GREEN,
    "exited": RED, "unhealthy": RED, "failed": RED, "dead": RED, "not found": RED,
    "restarting": AMBER, "rolled_back": AMBER, "paused": AMBER,
    "restart": BLUE, "rollback": AMBER, "unknown": GREY,
}
STATE_BADGE = {"healthy": "🟢 Healthy", "unhealthy": "🔴 Unhealthy", "unreachable": "🔴 Unreachable"}
DEPLOY_ICON = {"success": "✅ success", "failed": "❌ failed", "rolled_back": "↩️ rolled back"}
EVENT_LABEL = {
    "failure_detected": "🔴 Failure detected", "restart": "🔄 Restart",
    "rollback": "⏪ Rollback", "recovery_verified": "✅ Recovery verified",
    "recovery_failed": "❌ Recovery failed", "restart_loop_halted": "⛔ Restart loop halted",
}
WINDOWS = {"Last 1 hour": 1, "Last 6 hours": 6, "Last 24 hours": 24,
           "Last 7 days": 168, "All time": None}
PAGES = ["Overview", "Container status", "Deployment history", "Failures",
         "Recovery history", "Analytics"]
TZ_OPTIONS = ["UTC", "Asia/Kolkata", "America/New_York", "Europe/London"]

st.markdown(
    """
    <style>
    [data-testid="stMetric"] {background:#f3f6f9; border-radius:10px; padding:12px 16px;}
    [data-testid="stMetricLabel"] {opacity:.75;}
    </style>
    """,
    unsafe_allow_html=True,
)


# ------------------------------------------------------------------ helpers
def fmt_duration(seconds) -> str:
    if seconds is None or pd.isna(seconds):
        return "—"
    seconds = float(seconds)
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.1f} min"
    return f"{seconds / 3600:.1f} h"


def fmt_pct(value) -> str:
    return "—" if value is None or pd.isna(value) else f"{value:.1f}%"


def span_hours(events: pd.DataFrame) -> float:
    if events.empty:
        return 0.0
    return (events["timestamp"].max() - events["timestamp"].min()).total_seconds() / 3600


def bucket(events: pd.DataFrame, kind: str) -> str:
    """Pick a sensible resample size for the data span."""
    h = span_hours(events)
    table = {
        "uptime": [(2, "2min"), (8, "5min"), (36, "15min"), (192, "1h")],
        "failures": [(2, "5min"), (8, "15min"), (36, "1h"), (192, "6h")],
    }[kind]
    for limit, freq in table:
        if h <= limit:
            return freq
    return "1D" if kind == "failures" else "6h"


def show_table(df: pd.DataFrame, rename: dict | None = None) -> None:
    """Render a dataframe with tidy timestamps and whole-number floats."""
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = out[col].dt.strftime("%Y-%m-%d %H:%M:%S")
        elif pd.api.types.is_float_dtype(out[col]):
            vals = out[col].dropna()
            if len(vals) and (vals % 1 == 0).all():
                out[col] = out[col].astype("Int64")
    if rename:
        out = out.rename(columns=rename)
    st.dataframe(out, hide_index=True, width="stretch")


def style_fig(fig, height: int = 320):
    fig.update_layout(height=height, margin=dict(l=10, r=10, t=40, b=10),
                      legend_title_text="", template="plotly_white")
    return fig


def empty_state(what: str) -> None:
    st.info(f"No {what} yet. Start the monitoring engine, or load demo data with "
            "`python generate_sample_data.py`.")


# ------------------------------------------------------------------ pages
def page_overview(events, deploys):
    live = check_live_health()
    container = get_container_status()
    hc = an.health_checks(events)

    st.subheader("Right now")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Application", STATE_BADGE.get(live["state"], live["state"]))
    c2.metric("Response time", "—" if live["response_time_ms"] is None
              else f"{live['response_time_ms']:.0f} ms")
    version = live["version"] or (hc.dropna(subset=["version"]).iloc[-1]["version"]
                                  if not hc.dropna(subset=["version"]).empty else None)
    c3.metric("Running version", version or "—")
    if container["available"]:
        c4.metric("Container", container["status"].capitalize())
    else:
        logged = hc["container_status"].dropna()
        c4.metric("Container (from logs)", logged.iloc[-1].capitalize() if len(logged) else "—")

    if live["state"] != "healthy" and live["message"]:
        st.caption(f"Live check of `{config.HEALTH_ENDPOINT}`: {live['message']}")

    if not hc.empty:
        age = (pd.Timestamp.now(tz="UTC") - hc["timestamp"].max()).total_seconds()
        if age > config.STALE_AFTER_S:
            st.warning(f"No health check has been logged for {fmt_duration(age)}. "
                       "The monitoring engine may be stopped.")

    st.subheader("Selected period")
    stats = an.recovery_stats(events)
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Uptime", fmt_pct(an.uptime_percentage(events)))
    k2.metric("Failures detected", stats["failures_detected"])
    k3.metric("Recovery success rate", fmt_pct(stats["success_rate_pct"]))
    k4.metric("Avg recovery time (MTTR)", fmt_duration(stats["mttr_seconds"]))
    k5.metric("Est. downtime", fmt_duration(an.downtime_seconds(events, config.CHECK_INTERVAL_S)))

    left, right = st.columns([3, 2])
    with left:
        ts = an.uptime_timeseries(events, bucket(events, "uptime"))
        if ts.empty:
            empty_state("health checks")
        else:
            fig = px.area(ts, x="timestamp", y="uptime_pct", title="Uptime over time",
                          color_discrete_sequence=[GREEN])
            fig.update_yaxes(range=[0, 105], title="Uptime %")
            fig.update_xaxes(title="")
            st.plotly_chart(style_fig(fig), width="stretch")
    with right:
        st.markdown("**Latest incident activity**")
        tl = an.incident_timeline(events).head(8)
        if tl.empty:
            st.caption("No failures or recoveries in this period.")
        else:
            tl = tl.assign(event=tl["event"].map(EVENT_LABEL).fillna(tl["event"]))
            show_table(tl[["timestamp", "event", "result"]])


def page_containers(events, deploys):
    st.subheader("Docker container status")
    container = get_container_status()
    if container["available"] and container["status"] != "not found":
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Name", container["name"])
        c2.metric("State", container["status"].capitalize())
        c3.metric("Restart count", container["restart_count"] if container["restart_count"] is not None else "—")
        c4.metric("Image", container["image"] or "—")
        if container["started_at"]:
            st.caption(f"Started at {container['started_at']}")
    elif container["available"]:
        st.warning(f"Container `{container['name']}` was not found. "
                   "Set CONTAINER_NAME if the app container is named differently.")
    else:
        st.info(f"Live Docker status unavailable ({container['error'] or 'no access'}). "
                "Showing container status recorded by the monitoring engine. To enable live "
                "status in Docker, mount `/var/run/docker.sock` into the dashboard container.")

    hist = an.container_status_history(events)
    st.subheader("Status history (from monitoring logs)")
    if hist.empty:
        empty_state("container status records")
        return
    order = [s for s in ["running", "restarting", "paused", "exited", "dead"]
             if s in set(hist["container_status"])]
    order += [s for s in hist["container_status"].unique() if s not in order]
    fig = px.scatter(hist, x="timestamp", y="container_status", color="container_status",
                     color_discrete_map=STATUS_COLORS,
                     category_orders={"container_status": order})
    fig.update_traces(marker=dict(size=7, symbol="square"))
    fig.update_yaxes(title="")
    fig.update_xaxes(title="")
    fig.update_layout(showlegend=False)
    st.plotly_chart(style_fig(fig, 260), width="stretch")

    changes = hist[hist["container_status"] != hist["container_status"].shift()]
    st.markdown("**Status changes**")
    show_table(changes.sort_values("timestamp", ascending=False)
               .rename(columns={"container_status": "new status"}))


def page_deployments(events, deploys):
    st.subheader("Deployment history")
    if deploys.empty:
        empty_state("deployments")
        return
    s = an.deployment_summary(deploys)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total deployments", s["total"])
    c2.metric("Successful", s["successful"])
    c3.metric("Failed", s["failed"])
    c4.metric("Rolled back", s["rolled_back"])
    c5.metric("Current version", s["current_version"] or "—")

    d = deploys.copy()
    d["status"] = d["status"].map(DEPLOY_ICON).fillna(d["status"])
    fig = px.scatter(deploys, x="timestamp", y="version", color="status",
                     color_discrete_map=STATUS_COLORS, hover_data=["image", "triggered_by", "detail"],
                     title="Version timeline")
    fig.update_traces(marker=dict(size=14))
    fig.update_xaxes(title="")
    fig.update_yaxes(title="")
    st.plotly_chart(style_fig(fig, 280), width="stretch")
    cols = ["timestamp", "version", "status", "image", "commit", "triggered_by", "detail"]
    show_table(d.sort_values("timestamp", ascending=False)[cols])


def page_failures(events, deploys):
    st.subheader("Detected application failures")
    f = an.failures(events)
    if f.empty:
        st.success("No failures detected in this period.")
        return
    c1, c2, c3 = st.columns(3)
    c1.metric("Failures", len(f))
    c2.metric("Most recent", f["timestamp"].iloc[0].strftime("%H:%M:%S"))
    c3.metric("Avg consecutive failed checks", f"{f['consecutive_failures'].mean():.1f}"
              if f["consecutive_failures"].notna().any() else "—")

    left, right = st.columns([3, 2])
    with left:
        ff = an.failure_frequency(events, bucket(events, "failures"))
        fig = px.bar(ff, x="timestamp", y="failures", title="Failure frequency",
                     color_discrete_sequence=[RED])
        fig.update_xaxes(title="")
        fig.update_yaxes(title="Failures", dtick=1)
        st.plotly_chart(style_fig(fig), width="stretch")
    with right:
        br = an.failures_by_reason(events)
        fig = px.bar(br, x="count", y="reason", orientation="h", title="Failures by reason",
                     color_discrete_sequence=[AMBER])
        fig.update_xaxes(dtick=1, title="")
        fig.update_yaxes(title="")
        st.plotly_chart(style_fig(fig), width="stretch")
    show_table(f)


def page_recovery(events, deploys):
    st.subheader("Automatic restart & rollback")
    stats = an.recovery_stats(events)
    if stats["failures_detected"] == 0 and stats["restarts_attempted"] == 0:
        st.success("No recovery activity in this period.")
        return
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Restarts (ok / tried)", f"{stats['restarts_succeeded']} / {stats['restarts_attempted']}")
    r2.metric("Rollbacks (ok / tried)", f"{stats['rollbacks_succeeded']} / {stats['rollbacks_attempted']}")
    r3.metric("Recovery success rate", fmt_pct(stats["success_rate_pct"]))
    r4.metric("Restart loops halted", stats["loop_halts"])

    left, right = st.columns(2)
    with left:
        oc = an.recovery_outcomes(events)
        if oc.empty:
            st.caption("No finished recoveries yet.")
        else:
            fig = px.pie(oc, names="outcome", values="count", hole=0.55,
                         title="Recovery outcomes", color="outcome",
                         color_discrete_map={"Recovered": GREEN, "Recovery failed": RED,
                                             "Restart loop halted": AMBER})
            st.plotly_chart(style_fig(fig), width="stretch")
    with right:
        ms = an.recovery_method_summary(events)
        if ms.empty:
            st.caption("No restart or rollback attempts yet.")
        else:
            fig = px.bar(ms, x="method", y="count", color="result", barmode="group",
                         title="Success vs failure by method", color_discrete_map=STATUS_COLORS)
            fig.update_xaxes(title="")
            fig.update_yaxes(dtick=1, title="")
            st.plotly_chart(style_fig(fig), width="stretch")

    st.markdown("**Restart and rollback history**")
    show_table(an.recovery_actions(events))
    with st.expander("Full incident timeline"):
        tl = an.incident_timeline(events)
        show_table(tl.assign(event=tl["event"].map(EVENT_LABEL).fillna(tl["event"])))


def page_analytics(events, deploys):
    st.subheader("System analytics")
    hc = an.health_checks(events)
    if hc.empty:
        empty_state("health checks")
        return
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Health checks", len(hc))
    c2.metric("Passed", int(hc["healthy"].sum()))
    c3.metric("Failed", int((~hc["healthy"]).sum()))
    rt = an.response_time_series(events)["response_time_ms"]
    c4.metric("Median response", "—" if rt.empty else f"{rt.median():.0f} ms")

    ts = an.uptime_timeseries(events, bucket(events, "uptime"))
    fig = px.line(ts, x="timestamp", y="uptime_pct", markers=True, title="Application uptime",
                  color_discrete_sequence=[GREEN])
    fig.update_yaxes(range=[0, 105], title="Uptime %")
    fig.update_xaxes(title="")
    st.plotly_chart(style_fig(fig), width="stretch")

    left, right = st.columns(2)
    with left:
        ff = an.failure_frequency(events, bucket(events, "failures"))
        if ff.empty:
            st.caption("No failures to chart.")
        else:
            fig = px.bar(ff, x="timestamp", y="failures", title="Failure frequency",
                         color_discrete_sequence=[RED])
            fig.update_xaxes(title="")
            fig.update_yaxes(dtick=1, title="")
            st.plotly_chart(style_fig(fig), width="stretch")
    with right:
        mt = an.mttr_series(events)
        if mt.empty:
            st.caption("No verified recoveries to chart.")
        else:
            fig = px.bar(mt, x="timestamp", y="recovery_time_s", title="Time to recover (s)",
                         color_discrete_sequence=[BLUE])
            fig.update_xaxes(title="")
            fig.update_yaxes(title="seconds")
            st.plotly_chart(style_fig(fig), width="stretch")

    if not rt.empty:
        rts = an.response_time_series(events)
        fig = px.line(rts, x="timestamp", y="response_time_ms", title="Response time (ms)",
                      color_discrete_sequence=[BLUE])
        fig.update_xaxes(title="")
        fig.update_yaxes(title="ms")
        st.plotly_chart(style_fig(fig, 280), width="stretch")


PAGE_FUNCS = {
    "Overview": page_overview, "Container status": page_containers,
    "Deployment history": page_deployments, "Failures": page_failures,
    "Recovery history": page_recovery, "Analytics": page_analytics,
}


def render_page(page: str, hours, tz: str) -> None:
    """Load fresh data and draw one page. Runs again on every auto-refresh."""
    raw_events = load_events()
    events = filter_window(raw_events, hours)
    deploys = filter_window(load_deployments(), hours)
    events["timestamp"] = events["timestamp"].dt.tz_convert(tz)
    deploys["timestamp"] = deploys["timestamp"].dt.tz_convert(tz)

    st.title("🩺 AutoHealOps")
    st.caption(f"Self-healing monitor · {page} · times in {tz} · "
               f"updated {pd.Timestamp.now(tz=tz):%H:%M:%S}")
    PAGE_FUNCS[page](events, deploys)

    skipped = raw_events.attrs.get("skipped", 0)
    if skipped:
        st.caption(f"⚠️ {skipped} unreadable log line(s) were skipped.")


# ------------------------------------------------------------------ layout
with st.sidebar:
    st.header("AutoHealOps")
    page = st.radio("Navigate", PAGES, label_visibility="collapsed")
    st.divider()
    window = st.selectbox("Time range", list(WINDOWS), index=2)
    tz = st.selectbox("Timezone", TZ_OPTIONS,
                      index=TZ_OPTIONS.index(config.DISPLAY_TZ) if config.DISPLAY_TZ in TZ_OPTIONS else 0)
    auto = st.toggle("Auto refresh", value=True)
    interval = st.slider("Refresh every (s)", 5, 60, config.DEFAULT_REFRESH_S, step=5, disabled=not auto)
    st.button("Refresh now", use_container_width=True)
    st.divider()
    st.caption(f"Recovery log: `{config.RECOVERY_LOG.name}`  \nDeploy log: `{config.DEPLOY_LOG.name}`  \n"
               f"Health URL: `{config.HEALTH_ENDPOINT}`")

st.fragment(run_every=interval if auto else None)(render_page)(page, WINDOWS[window], tz)
