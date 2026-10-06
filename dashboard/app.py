"""Public dashboard: display scores and metrics; cloud artifacts stay private."""
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import os
import pandas as pd
import streamlit as st
from google.cloud import storage
from evaluation import evaluate

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

def reconstruction_comparison(frame, key):
    st.subheader("Observed versus model reconstruction")
    st.caption("Same-day reconstruction, not a forecast. Errors below are in pollutant units; smaller values mean a closer reconstruction, not better anomaly detection. Flagged days are selected using error, so their errors will generally be larger.")
    required = {"pm25_reconstructed", "ozone_reconstructed"}
    if not required.issubset(frame.columns):
        st.info("Reconstruction concentrations will appear after these scores are refreshed.")
        return
    if frame.empty:
        st.info("No days match this selection.")
        return
    rows = []
    for label, actual, reconstructed, unit in [("PM2.5", "pm25", "pm25_reconstructed", "µg/m³"), ("Ozone", "ozone_8hr_max", "ozone_reconstructed", "ppb")]:
        error = frame[actual] - frame[reconstructed]
        rows.append({"Pollutant": label, "Days": len(frame), "MAE": error.abs().mean(), "RMSE": (error.pow(2).mean()) ** .5, "Mean bias (reconstructed − observed)": -error.mean(), "Units": unit})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    left, right = st.columns(2)
    with left:
        st.write("**PM2.5 · observed and reconstructed**")
        st.line_chart(frame.set_index("date")[["pm25", "pm25_reconstructed"]].rename(columns={"pm25": "Observed", "pm25_reconstructed": "Reconstructed"}), color=["#0f766e", "#db7846"])
    with right:
        st.write("**Ozone · observed and reconstructed**")
        st.line_chart(frame.set_index("date")[["ozone_8hr_max", "ozone_reconstructed"]].rename(columns={"ozone_8hr_max": "Observed", "ozone_reconstructed": "Reconstructed"}), color=["#597aab", "#db7846"])
    comparison = frame[["date", "pm25", "pm25_reconstructed", "ozone_8hr_max", "ozone_reconstructed", "reconstruction_error", "anomaly_threshold", "anomaly"]].copy()
    comparison["PM2.5 absolute error (µg/m³)"] = (frame.pm25 - frame.pm25_reconstructed).abs()
    comparison["Ozone absolute error (ppb)"] = (frame.ozone_8hr_max - frame.ozone_reconstructed).abs()
    st.dataframe(comparison, hide_index=True, width="stretch")
    st.download_button("Download concentration comparison", comparison.to_csv(index=False), file_name="concentration-comparison.csv", mime="text/csv", key=key)


weekly_tab, historical_tab, model_tab = st.tabs(["Observations & scores", "Historical flags", "Model & training"])
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
        reconstruction_comparison(shown, "weekly-comparison")

with historical_tab:
    st.subheader("Historical days flagged by the model")
    st.write("Compare the model's decisions across the held-out 2025 test period. A model flag means reconstruction error exceeded its threshold; it does not confirm a real pollution event.")
    historical = data[data.result_type == "Historical test (2025)"].sort_values("date") if not data.empty else pd.DataFrame()
    if historical.empty:
        st.info("Historical test scores are unavailable or have expired under the 30-day operational retention policy.")
    else:
        historical = historical.drop_duplicates(["date", "model_version"], keep="last").copy()
        historical["Model decision"] = historical.anomaly.map({True: "Flagged", False: "Not flagged"})
        st.subheader("Accuracy against observed concentration thresholds")
        st.write("An observed exceedance day has PM2.5 or ozone at or above the limits below. This reference is calculated from observed concentrations, independently of reconstruction error. Regional averages provide a comparison benchmark, not an official station AQI or verified event record.")
        left, right = st.columns(2)
        pm_limit = left.number_input("Observed PM2.5 limit (µg/m³)", min_value=0.1, value=35.5, step=0.1)
        ozone_limit = right.number_input("Observed ozone limit (ppb)", min_value=1.0, value=71.0, step=1.0)
        st.caption("Defaults use the concentration breakpoints at the start of EPA's Unhealthy for Sensitive Groups AQI category. Limits apply directly to our regional daily values; this is not an AQI calculation. Choose limits before interpreting performance, rather than adjusting them to improve scores.")
        st.markdown("[EPA concentration breakpoint reference](https://document.airnow.gov/technical-assistance-document-for-the-reporting-of-daily-air-quailty.pdf)")
        available = ["Model anomaly flags"]
        if {"pm25_reconstructed", "ozone_reconstructed"}.issubset(historical.columns):
            available.insert(0, "Reconstructed concentration exceedances")
        method = st.selectbox("Decision to compare with observed exceedances", available)
        historical, counts = evaluate(historical, pm_limit, ozone_limit, reconstructed=method.startswith("Reconstructed"))
        st.caption("Reconstructed concentration decisions apply the same concentration limits to model outputs. Model anomaly flags use the existing reconstruction-error threshold. Both are compared with the independently calculated observed exceedance rule.")
        outcomes = st.columns(4)
        for column, label in zip(outcomes, ["Correctly flagged", "Missed days", "False alarms", "Correctly unflagged"]):
            column.metric(label, counts[label])
        measures = st.columns(3)
        for column, label in zip(measures, ["Accuracy", "Precision", "Recall"]):
            value = counts[label]
            column.metric(label, f"{value:.1%}" if value is not None else "Undefined")
        st.write(f"Observed exceedance days: **{counts['Observed exceedance days']} of {len(historical)}**. Accuracy includes correctly unflagged days; precision measures how many flags matched exceedances, and recall measures how many observed exceedances were detected.")
        if counts['Observed exceedance days'] == 0:
            st.warning("No observed days exceed these limits. Recall is undefined, and high accuracy here does not demonstrate detection of exceedance events.")
        historical["Observed rule"] = historical['Observed exceedance'].map({True: "Observed exceedance", False: "Below concentration limits"})
        flagged = historical[historical.anomaly]
        cols = st.columns(2)
        cols[0].metric("Historical days scored", len(historical))
        cols[1].metric("Historical model flags", len(flagged))
        st.bar_chart(historical.set_index("date")[["anomaly"]].astype(int).rename(columns={"anomaly": "Model flag (1 = flagged)"}), color="#db7846")
        only_flagged = st.checkbox("Show flagged days only", value=True)
        displayed = flagged if only_flagged else historical
        columns = ["date", "Model decision", "Observed rule", "Compared decision", "Outcome", "reconstruction_error", "pm25", "ozone_8hr_max", "model_version"]
        st.subheader("All daily comparison outcomes")
        outcome_filter = st.selectbox("Filter comparison outcomes", ["All days", "Correctly flagged", "Missed day", "False alarm", "Correctly unflagged"])
        comparison_days = historical if outcome_filter == "All days" else historical[historical.Outcome == outcome_filter]
        st.dataframe(comparison_days[columns], hide_index=True, width="stretch")
        st.download_button("Download threshold evaluation", comparison_days[columns].to_csv(index=False), file_name="threshold-evaluation.csv", mime="text/csv")
        st.dataframe(displayed[columns], hide_index=True, width="stretch")
        st.download_button("Download historical decisions", displayed[columns].to_csv(index=False), file_name="historical-model-decisions.csv", mime="text/csv")
        reconstruction_comparison(displayed, "historical-comparison")

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
    st.info("Historical flags reports accuracy, precision and recall against an independent observed-concentration rule. Reconstruction loss measures concentration reconstruction quality. The concentration benchmark does not label every kind of unusual seasonal or pollution event.")
    st.markdown(f"[Source repository](https://github.com/sejennings/air_quality_tracker) · Code revision `{meta.get('git_commit', 'unknown')[:12]}`")
st.divider()
st.caption("Operational results expire after 30 days. Historical training data and the active model are retained. Public dashboard · private artifact storage.")

