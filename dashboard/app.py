"""Public dashboard: display scores and metrics; cloud artifacts stay private."""
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import os
import pandas as pd
import streamlit as st
from google.cloud import storage

st.set_page_config(page_title="Triangle Air Quality", page_icon="🌿", layout="wide")
st.markdown("""<style>
.block-container {max-width:1180px; padding-top:2.2rem}
[data-testid="stMetric"] {background:white;border:1px solid #dbe5eb;border-radius:12px;padding:18px}
h1 {letter-spacing:-0.035em} .eyebrow {color:#0f766e;font-weight:700;letter-spacing:.14em;font-size:.78rem}
</style>""", unsafe_allow_html=True)
st.markdown('<div class="eyebrow">TRIANGLE AIR QUALITY · MODEL OBSERVATORY</div>', unsafe_allow_html=True)
st.title("A clearer view of the air around us")
st.caption("Wake · Durham · Orange counties, North Carolina | Weekly daily anomaly scoring")


@st.cache_data(ttl=120)
def load_artifacts():
    client = storage.Client()
    models = client.bucket(os.environ["MODELS_BUCKET"])
    operational = client.bucket(os.environ["OPERATIONAL_BUCKET"])
    pointer = json.loads(models.blob("active.json").download_as_text())
    run_id = pointer["run_id"]
    if "/" in run_id or run_id in (".", ".."):
        raise ValueError("Invalid model identifier")
    metadata = json.loads(models.blob(f"{run_id}/metadata.json").download_as_text())
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    frames, reports = [], []
    for blob in operational.list_blobs(prefix="scores/"):
        if blob.time_created <= cutoff or not blob.name.endswith(".parquet"):
            continue
        if blob.size > 10_000_000:
            continue
        frame = pd.read_parquet(BytesIO(blob.download_as_bytes(if_generation_match=blob.generation)))
        frame["result_type"] = "Weekly observations" if blob.name.startswith("scores/live/") else "Historical test (2025)"
        frames.append(frame)
    for blob in operational.list_blobs(prefix="reports/"):
        if blob.time_created > cutoff and blob.name.endswith(".json") and blob.size < 100_000:
            reports.append(json.loads(blob.download_as_text(if_generation_match=blob.generation)))
    return metadata, pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(), sorted(reports, key=lambda r: r["week_start"], reverse=True)


try:
    meta, data, reports = load_artifacts()
except Exception:
    st.info("The first model and score artifacts are being prepared. Check back after the initial training job finishes.")
    st.stop()

weekly_tab, model_tab = st.tabs(["Observations & scores", "Model & training"])
with weekly_tab:
    if reports:
        latest = reports[0]
        st.markdown(f"**Latest run:** {latest['week_start']} to {latest['week_end']} · {latest['status'].title()} · {latest['scored_days']}/7 days scored")
        if latest["missing_dates"]:
            st.warning("Missing daily inputs: " + ", ".join(latest["missing_dates"]) + ". No values are filled in or fabricated.")
    else:
        st.info("The weekly job runs Monday at 8:00 AM America/New_York for the previous Monday–Sunday.")
    if data.empty:
        st.info("No score files are currently available within the 30-day retention window.")
    else:
        sources = sorted(data.result_type.unique(), key=lambda s: s != "Weekly observations")
        source = st.selectbox("Results", sources)
        shown = data[data.result_type == source].sort_values("date").drop_duplicates(["date", "model_version"], keep="last")
        if source.startswith("Historical"):
            st.warning("Historical test results from 2025. These are not current-week observations.")
        else:
            st.caption("AirNow preliminary daily data. The regional monitor mix can differ from the EPA AQS training dataset.")
        cols = st.columns(4)
        cols[0].metric("Days scored", len(shown))
        cols[1].metric("Flagged days", int(shown.anomaly.sum()))
        cols[2].metric("Mean PM2.5", f"{shown.pm25.mean():.1f} µg/m³")
        cols[3].metric("Mean 8-hour ozone", f"{shown.ozone_8hr_max.mean():.1f} ppb")
        st.subheader("Anomaly score over time")
        chart = shown.set_index("date")[["reconstruction_error"]].rename(columns={"reconstruction_error": "Reconstruction error"})
        chart["Active model threshold"] = meta["threshold"]
        st.line_chart(chart, color=["#0f766e", "#db7846"])
        st.caption("Above-threshold scores flag unusual combinations of pollutants and seasonality; they do not measure health risk or forecast pollution.")
        left, right = st.columns(2)
        with left:
            st.subheader("PM2.5 · daily regional mean")
            st.line_chart(shown.set_index("date")[["pm25"]], color="#0f766e")
        with right:
            st.subheader("Ozone · regional mean of daily 8-hour peaks")
            st.line_chart(shown.set_index("date")[["ozone_8hr_max"]], color="#597aab")
        columns = [c for c in ("date", "pm25", "ozone_8hr_max", "reconstruction_error", "pm25_reconstruction_error", "ozone_reconstruction_error", "anomaly", "pm25_sites", "ozone_8hr_max_sites", "model_version") if c in shown]
        st.subheader("Daily results")
        st.dataframe(shown[columns], hide_index=True, width="stretch")
        st.download_button("Download displayed scores", shown[columns].to_csv(index=False), file_name="air-quality-scores.csv", mime="text/csv")

with model_tab:
    st.subheader("Dense autoencoder baseline")
    st.write("Four inputs: PM2.5, 8-hour ozone, and sine/cosine annual seasonality. A two-unit latent layer reconstructs those inputs; squared reconstruction errors determine anomaly scores.")
    st.caption(f"Active version: {meta['run_id']}")
    st.markdown("**Training:** 2021–2023 · **Validation:** 2024 · **Untouched test:** 2025")
    rows = [{"Period": name.title(), "Rows": values["rows"], "Reconstruction MSE": values["mse"], "Flagged fraction": values["anomaly_rate"]} for name, values in meta["metrics"].items()]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.subheader("Training progress")
    history = pd.DataFrame(meta["history"])[["loss", "val_loss"]].rename(columns={"loss": "Training loss", "val_loss": "Validation loss"})
    history.index += 1
    history.index.name = "Epoch"
    st.line_chart(history, color=["#0f766e", "#597aab"])
    st.caption(f"Seed {meta['seed']} · early stopping with restored best weights · threshold {meta['threshold']:.4f} (95th percentile of training errors)")
    st.info("Reconstruction loss and flagged fractions describe this model's behavior. Detection accuracy requires labeled events; a low loss alone does not prove useful anomaly detection.")
    st.markdown(f"[Source repository](https://github.com/sejennings/air_quality_tracker) · Code revision `{meta.get('git_commit', 'unknown')[:12]}`")
st.divider()
st.caption("Operational results expire after 30 days. Historical training data and the active model are retained. Public dashboard · private artifact storage.")

