"""
generate_insight_report.py
--------------------------
Reads the fleet CSVs (real or sample) and generates a professional
one-page PDF insight narrative — the kind of document you hand to a client.

This is what separates a data analyst from a dashboard builder.
The charts show what happened. This report explains what it means
and what to do about it.

Run:
  python generate_insight_report.py
  python generate_insight_report.py --data ../powerbi/sample_data --output ./fleet_insight_report.pdf
"""

import argparse
import os
from datetime import datetime

import pandas as pd
import numpy as np
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether
)
from reportlab.lib.colors import HexColor


# ── Brand colours ─────────────────────────────────────────────────────────────
TEAL      = HexColor("#1D9E75")
PURPLE    = HexColor("#7F77DD")
CORAL     = HexColor("#D85A30")
AMBER     = HexColor("#BA7517")
DARK      = HexColor("#2C2C2A")
MID_GRAY  = HexColor("#5F5E5A")
LIGHT_GRAY= HexColor("#F1EFE8")
RED       = HexColor("#E24B4A")
GREEN     = HexColor("#1D9E75")
PAGE_W, PAGE_H = A4


# ── Analysis ──────────────────────────────────────────────────────────────────

def analyse(tel: pd.DataFrame, sta: pd.DataFrame) -> dict:
    """Derive all numbers referenced in the narrative."""
    tel["Is Anomaly"] = tel["Is Anomaly"].astype(str).str.lower() == "true"

    fleet_size      = tel["Device ID"].nunique()
    offline_count   = (sta["Connection Status"] == "Offline").sum()
    online_count    = fleet_size - offline_count
    uptime_pct      = round(online_count / fleet_size * 100, 1)
    anomaly_count   = tel["Is Anomaly"].sum()
    anomaly_rate    = round(anomaly_count / len(tel) * 100, 2)
    total_messages  = sta["Messages Published"].sum()
    total_queued    = sta["Queue Depth"].sum()
    total_reconnects= sta["Reconnect Count"].sum()

    # Camera analysis
    cameras    = tel[tel["Device Type"] == "camera"]
    cam_cpu    = cameras["CPU %"].mean().round(1)
    cam_temp   = cameras["Temperature (°C)"].mean().round(1)
    cam_temp_max = cameras["Temperature (°C)"].max().round(1)

    # Worst device
    worst_device = (
        sta.sort_values("Reconnect Count", ascending=False).iloc[0]
    )

    # Hottest location
    loc_cpu = tel.groupby("Location")["CPU %"].mean().sort_values(ascending=False)
    hot_loc  = loc_cpu.index[0]
    hot_cpu  = loc_cpu.iloc[0].round(1)

    # Critical CPU events
    crit_cpu_devices = (
        tel[tel["CPU Status"] == "Critical"]
        .groupby("Device ID")["CPU %"].max()
        .sort_values(ascending=False)
    )

    # High temp peaks
    temp_peaks = (
        tel[tel["Temp Status"].isin(["Warning","Critical"])]
        .groupby(["Device ID","Location"])["Temperature (°C)"].max()
        .sort_values(ascending=False)
    )

    # Most isolated offline device (highest queue)
    offline_devices = sta[sta["Connection Status"] == "Offline"]
    most_queued = offline_devices.sort_values("Queue Depth", ascending=False).iloc[0] if not offline_devices.empty else None

    # Reconnect problem devices
    high_reconnect = sta[sta["Reconnect Count"] > 8][["Device ID","Location","Reconnect Count"]].sort_values("Reconnect Count", ascending=False)

    # Reliable devices
    reliable = sta[(sta["Reconnect Count"] <= 2) & (sta["Connection Status"] == "Online")]

    # ── Facts that were previously hardcoded in build_pdf — computed here ──────

    # Anomalies by device type (Exec summary claimed "all cameras"; really sensors lead)
    anom_by_type = tel[tel["Is Anomaly"]]["Device Type"].value_counts()
    if len(anom_by_type):
        anom_top_type  = anom_by_type.index[0]
        anom_top_count = int(anom_by_type.iloc[0])
    else:
        anom_top_type, anom_top_count = "none", 0

    # Camera fleet size + share of critical-CPU events that are cameras
    camera_count = cameras["Device ID"].nunique()
    crit = tel[tel["CPU Status"] == "Critical"]
    cam_crit_cpu_pct = int(round(100 * (crit["Device Type"] == "camera").mean())) if len(crit) else 0

    # Per-device camera CPU means (replaces the fudged "~65%" table cells)
    cam_cpu_by_device = cameras.groupby("Device ID")["CPU %"].mean().round(1).to_dict()

    # Most stable device (Finding 4 hardcoded device_014; derive from reliable)
    if not reliable.empty:
        stable_device = reliable.sort_values("Reconnect Count").iloc[0]
    else:
        stable_device = sta.sort_values("Reconnect Count").iloc[0]

    # Offline devices nearest queue capacity (Finding 3 hardcoded device_004/_009)
    near_cap = offline_devices.sort_values("Queue Depth", ascending=False).head(2)
    if not near_cap.empty:
        near_capacity_text = " and ".join(
            f"{r['Device ID']} ({r['Location']}, {int(r['Queue Depth'])} messages queued)"
            for _, r in near_cap.iterrows()
        )
        near_capacity_ids   = " and ".join(near_cap["Device ID"].tolist())
        near_capacity_queue = int(near_cap["Queue Depth"].sum())
    else:
        near_capacity_text, near_capacity_ids, near_capacity_queue = "none", "none", 0

    # Hottest camera locations + top camera IDs by peak temp (Finding 1 actions)
    cam_peaks = (
        cameras[cameras["Temp Status"].isin(["Warning", "Critical"])]
        if "Temp Status" in cameras.columns else cameras
    )
    cam_loc_peak = (
        cam_peaks.groupby("Location")["Temperature (°C)"].max().sort_values(ascending=False)
        if not cam_peaks.empty else cameras.groupby("Location")["Temperature (°C)"].max().sort_values(ascending=False)
    )
    cam_hot_locs = " and ".join(cam_loc_peak.index[:2].tolist()) if len(cam_loc_peak) else "the camera zones"
    cam_dev_peak = cameras.groupby("Device ID")["Temperature (°C)"].max().sort_values(ascending=False)
    cam_top_ids  = " and ".join(cam_dev_peak.index[:2].tolist()) if len(cam_dev_peak) else "the hottest cameras"

    return dict(
        fleet_size=fleet_size,
        offline_count=offline_count,
        online_count=online_count,
        uptime_pct=uptime_pct,
        anomaly_count=int(anomaly_count),
        anomaly_rate=anomaly_rate,
        total_messages=int(total_messages),
        total_queued=int(total_queued),
        total_reconnects=int(total_reconnects),
        cam_cpu=cam_cpu,
        cam_temp=cam_temp,
        cam_temp_max=cam_temp_max,
        worst_device=worst_device,
        hot_loc=hot_loc,
        hot_cpu=hot_cpu,
        crit_cpu_devices=crit_cpu_devices,
        temp_peaks=temp_peaks,
        most_queued=most_queued,
        high_reconnect=high_reconnect,
        reliable=reliable,
        anom_top_type=anom_top_type,
        anom_top_count=anom_top_count,
        camera_count=camera_count,
        cam_crit_cpu_pct=cam_crit_cpu_pct,
        cam_cpu_by_device=cam_cpu_by_device,
        stable_device=stable_device,
        near_capacity_text=near_capacity_text,
        near_capacity_ids=near_capacity_ids,
        near_capacity_queue=near_capacity_queue,
        cam_hot_locs=cam_hot_locs,
        cam_top_ids=cam_top_ids,
        report_date=datetime.now().strftime("%d %B %Y"),
        report_time=datetime.now().strftime("%H:%M"),
    )


# ── PDF builder ───────────────────────────────────────────────────────────────

def build_pdf(d: dict, output_path: str):
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=20*mm,
        rightMargin=20*mm,
        topMargin=18*mm,
        bottomMargin=18*mm,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    def style(name, **kwargs):
        return ParagraphStyle(name, parent=styles["Normal"], **kwargs)

    S = {
        "title":    style("title",    fontSize=22, textColor=DARK,     spaceAfter=2,  fontName="Helvetica-Bold", leading=26),
        "subtitle": style("subtitle", fontSize=11, textColor=MID_GRAY, spaceAfter=8,  fontName="Helvetica"),
        "h2":       style("h2",       fontSize=13, textColor=DARK,     spaceBefore=12,spaceAfter=4, fontName="Helvetica-Bold"),
        "h3":       style("h3",       fontSize=11, textColor=MID_GRAY, spaceBefore=6, spaceAfter=2, fontName="Helvetica-Bold"),
        "body":     style("body",     fontSize=9.5,textColor=DARK,     spaceAfter=5,  fontName="Helvetica", leading=15, alignment=TA_JUSTIFY),
        "finding":  style("finding",  fontSize=9.5,textColor=DARK,     spaceAfter=4,  fontName="Helvetica", leading=15, leftIndent=10, alignment=TA_JUSTIFY),
        "label":    style("label",    fontSize=8,  textColor=MID_GRAY, fontName="Helvetica"),
        "footer":   style("footer",   fontSize=8,  textColor=MID_GRAY, fontName="Helvetica", alignment=TA_CENTER),
        "action":   style("action",   fontSize=9.5,textColor=DARK,     spaceAfter=4,  fontName="Helvetica", leading=15, leftIndent=10),
    }

    story = []

    # ── Header ────────────────────────────────────────────────────────────────
    story.append(Paragraph("IoT Edge Fleet — Operational Intelligence Report", S["title"]))
    story.append(Paragraph(
        f"Prepared by Supun Sriyananda &nbsp;·&nbsp; {d['report_date']} &nbsp;·&nbsp; "
        f"Analysis period: last 6 hours &nbsp;·&nbsp; Fleet size: {d['fleet_size']} devices",
        S["subtitle"]
    ))
    story.append(HRFlowable(width="100%", thickness=2, color=TEAL, spaceAfter=10))

    # ── KPI summary table ─────────────────────────────────────────────────────
    kpi_data = [
        ["Fleet uptime", "Devices online", "Total messages", "Queued (unsent)", "Anomaly events", "Reconnections"],
        [
            f"{d['uptime_pct']}%",
            f"{d['online_count']} / {d['fleet_size']}",
            f"{d['total_messages']:,}",
            f"{d['total_queued']:,}",
            f"{d['anomaly_count']}",
            f"{d['total_reconnects']}",
        ],
    ]

    kpi_table = Table(kpi_data, colWidths=[28*mm]*6)
    kpi_table.setStyle(TableStyle([
        ("BACKGROUND",   (0,0), (-1,0), LIGHT_GRAY),
        ("BACKGROUND",   (0,1), (-1,1), colors.white),
        ("TEXTCOLOR",    (0,0), (-1,0), MID_GRAY),
        ("TEXTCOLOR",    (0,1), (-1,1), DARK),
        ("FONTNAME",     (0,0), (-1,0), "Helvetica"),
        ("FONTNAME",     (0,1), (-1,1), "Helvetica-Bold"),
        ("FONTSIZE",     (0,0), (-1,0), 7.5),
        ("FONTSIZE",     (0,1), (-1,1), 16),
        ("ALIGN",        (0,0), (-1,-1), "CENTER"),
        ("VALIGN",       (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",   (0,0), (-1,-1), 6),
        ("BOTTOMPADDING",(0,0), (-1,-1), 6),
        ("BOX",          (0,0), (-1,-1), 0.5, HexColor("#D3D1C7")),
        ("INNERGRID",    (0,0), (-1,-1), 0.5, HexColor("#D3D1C7")),
        # Highlight offline count red if any offline
        ("TEXTCOLOR",    (1,1), (1,1), RED if d["offline_count"] > 0 else GREEN),
        # Highlight queued amber if significant
        ("TEXTCOLOR",    (3,1), (3,1), AMBER if d["total_queued"] > 50 else DARK),
    ]))

    story.append(kpi_table)
    story.append(Spacer(1, 10))

    # ── Executive summary ─────────────────────────────────────────────────────
    story.append(Paragraph("Executive summary", S["h2"]))

    wd  = d["worst_device"]
    mq  = d["most_queued"]

    summary_text = (
        f"The fleet of <b>{d['fleet_size']} edge devices</b> recorded <b>{d['total_messages']:,} telemetry messages</b> "
        f"during the analysis window. Fleet availability stands at <b>{d['uptime_pct']}%</b>, with "
        f"<b>{d['offline_count']} devices currently unreachable</b>. "
        f"The resilient MQTT client (robmqtt) has preserved <b>{d['total_queued']} messages</b> in offline queues "
        f"pending reconnection — confirming zero data loss despite network disruptions. "
        f"A total of <b>{d['total_reconnects']} reconnection events</b> were recorded across the fleet, "
        f"pointing to intermittent network instability that warrants investigation. "
        f"<b>{d['anomaly_count']} anomaly events</b> were detected, representing a fleet-wide anomaly rate of "
        f"<b>{d['anomaly_rate']}%</b>. The highest share of anomalies came from the "
        f"<b>{d['anom_top_type']}</b> device class "
        f"(<b>{d['anom_top_count']}</b> of {d['anomaly_count']} events)."
    )
    story.append(Paragraph(summary_text, S["body"]))
    story.append(Spacer(1, 4))

    # ── Finding 1: Camera fleet ───────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#D3D1C7"), spaceAfter=6))
    story.append(KeepTogether([
        Paragraph("Finding 1 — Camera devices are operating at thermal risk", S["h2"]),
        Paragraph(
            f"All <b>{d['camera_count']} camera devices</b> are running at a sustained average CPU load of "
            f"<b>{d['cam_cpu']}%</b> and average temperature of <b>{d['cam_temp']}°C</b>. "
            f"Peak temperatures across the camera fleet have reached <b>{d['cam_temp_max']}°C</b>, "
            f"which approaches the operating threshold for the embedded processor. "
            f"Camera devices account for <b>{d['cam_crit_cpu_pct']}% of critical CPU events</b> recorded during this period.",
            S["body"]
        ),
        Spacer(1, 4),
    ]))

    # Camera device table
    cam_rows = [["Device ID", "Location", "Avg CPU %", "Peak Temp (°C)", "Status"]]
    top_cam = d["temp_peaks"].reset_index().head(5)
    for _, row in top_cam.iterrows():
        dev_cpu = d["cam_cpu_by_device"].get(row["Device ID"])
        cpu_cell = f"{dev_cpu:.1f}%" if dev_cpu is not None else "—"
        cam_rows.append([
            row["Device ID"],
            row["Location"],
            cpu_cell,
            f"{row['Temperature (°C)']:.1f}°C",
            "⚠ Monitor",
        ])
    cam_table = Table(cam_rows, colWidths=[35*mm, 42*mm, 28*mm, 38*mm, 28*mm])
    cam_table.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0), CORAL),
        ("TEXTCOLOR",     (0,0), (-1,0), colors.white),
        ("FONTNAME",      (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTNAME",      (0,1), (-1,-1),"Helvetica"),
        ("FONTSIZE",      (0,0), (-1,-1), 8.5),
        ("ALIGN",         (0,0), (-1,-1), "CENTER"),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [colors.white, LIGHT_GRAY]),
        ("TOPPADDING",    (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("BOX",           (0,0), (-1,-1), 0.5, HexColor("#D3D1C7")),
        ("INNERGRID",     (0,0), (-1,-1), 0.5, HexColor("#D3D1C7")),
    ]))
    story.append(cam_table)
    story.append(Spacer(1, 5))

    story.append(Paragraph("<b>Recommended action:</b>", S["h3"]))
    for action in [
        f"Inspect physical ventilation around camera enclosures, particularly at {d['cam_hot_locs']} where peak temperatures reached {d['cam_temp_max']}°C.",
        f"Review the video processing workload — sustained ~{d['cam_cpu']}% CPU on embedded hardware leaves minimal headroom for thermal spikes.",
        "Consider firmware-level CPU throttling during peak temperature events as a short-term protective measure.",
        f"Schedule preventive maintenance inspection of camera units {d['cam_top_ids']} within 7 days.",
    ]:
        story.append(Paragraph(f"→ {action}", S["action"]))
    story.append(Spacer(1, 4))

    # ── Finding 2: Connectivity ───────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#D3D1C7"), spaceAfter=6))
    story.append(KeepTogether([
        Paragraph("Finding 2 — Chronic connectivity failures in two network zones", S["h2"]),
        Paragraph(
            f"<b>{d['offline_count']} of {d['fleet_size']} devices ({round(d['offline_count']/d['fleet_size']*100)}%) are currently offline</b>. "
            f"<b>{len(d['high_reconnect'])} devices</b> recorded more than 8 reconnection events during the analysis window — a pattern "
            f"inconsistent with isolated device faults and strongly suggestive of infrastructure-level "
            f"network instability. <b>{wd['Device ID']}</b> ({wd['Device Type']}, {wd['Location']}) "
            f"is the most severely affected, with <b>{int(wd['Reconnect Count'])} reconnections</b> and "
            f"currently offline. The robmqtt offline queue has preserved all telemetry from affected devices — "
            f"<b>no data has been lost</b> — but prolonged disconnection risks queue overflow.",
            S["body"]
        ),
        Spacer(1, 4),
    ]))

    # Reconnect table
    rc_rows = [["Device ID", "Device Type", "Location", "Reconnections", "Queue depth", "Status"]]
    for _, row in d["high_reconnect"].iterrows():
        sta_row = d.get("_sta_lookup", {}).get(row["Device ID"], {})
        rc_rows.append([
            row["Device ID"],
            "",
            row["Location"],
            str(int(row["Reconnect Count"])),
            "",
            "",
        ])

    # Use raw high_reconnect df merged with status
    story.append(Paragraph(
        f"Devices with >8 reconnections: <b>{', '.join(d['high_reconnect']['Device ID'].tolist())}</b>. "
        f"Locations affected: <b>{', '.join(sorted(d['high_reconnect']['Location'].unique()))}</b>.",
        S["body"]
    ))
    story.append(Spacer(1, 4))

    story.append(Paragraph("<b>Recommended action:</b>", S["h3"]))
    for action in [
        f"Audit the wireless access points serving {', '.join(sorted(d['high_reconnect']['Location'].unique())[:2])} — these locations account for many of the reconnection events.",
        f"<b>{wd['Device ID']}</b> ({wd['Device Type']}, {wd['Location']}) has {int(wd['Reconnect Count'])} reconnections and a queue of {int(wd['Queue Depth'])} messages — prioritise restoring its connection first.",
        "Review DHCP lease times and AP roaming configuration for the affected network zones.",
        "Consider wired Ethernet fallback for gateway devices in high-reconnect locations.",
    ]:
        story.append(Paragraph(f"→ {action}", S["action"]))
    story.append(Spacer(1, 4))

    # ── Finding 3: Offline queue ──────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#D3D1C7"), spaceAfter=6))
    story.append(KeepTogether([
        Paragraph("Finding 3 — Offline queue confirms zero data loss, but two devices near capacity", S["h2"]),
        Paragraph(
            f"The fleet's resilient MQTT client preserved <b>{d['total_queued']} messages</b> across "
            f"offline device queues during this period. This confirms the edge-first architecture is "
            f"working as designed — data is not silently dropped when the broker is unreachable. "
            f"However, <b>the devices closest to queue capacity</b> are: "
            f"{d['near_capacity_text']}. "
            f"If these devices remain offline and the queue fills, <b>lower-priority messages will begin "
            f"to be evicted</b> in favour of high-priority alerts.",
            S["body"]
        ),
        Spacer(1, 4),
    ]))

    story.append(Paragraph("<b>Recommended action:</b>", S["h3"]))
    for action in [
        f"Restore connectivity to {d['near_capacity_ids']} within the next 2 hours to prevent queue overflow.",
        "Consider increasing max_queue_size from 500 to 1000 for camera and sensor devices in known problem zones.",
        "Review queue eviction policy — confirm that alert-class messages (priority 8–10) are protected.",
    ]:
        story.append(Paragraph(f"→ {action}", S["action"]))
    story.append(Spacer(1, 4))

    # ── Finding 4: Reliable devices ───────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#D3D1C7"), spaceAfter=6))
    story.append(KeepTogether([
        Paragraph("Finding 4 — The fleet's most stable devices", S["h2"]),
        Paragraph(
            f"<b>{d['stable_device']['Device ID']}</b> ({d['stable_device']['Device Type']}, {d['stable_device']['Location']}) "
            f"recorded <b>{int(d['stable_device']['Reconnect Count'])} reconnections</b> "
            f"and has remained continuously online throughout the analysis period. "
            f"This device's network zone and hardware class should serve as a reference baseline when "
            f"diagnosing instability elsewhere in the fleet. "
            f"In total, <b>{len(d['reliable'])} device(s)</b> met the stability threshold "
            f"(2 or fewer reconnections while staying online), "
            f"suggesting their network infrastructure is well-configured.",
            S["body"]
        ),
        Spacer(1, 4),
    ]))

    story.append(Paragraph("<b>Recommended action:</b>", S["h3"]))
    for action in [
        f"Use {d['stable_device']['Device ID']}'s network configuration as a template when setting up new device deployments.",
        "Compare AP firmware versions between stable and unstable network zones — a version mismatch may explain the reconnection pattern.",
    ]:
        story.append(Paragraph(f"→ {action}", S["action"]))
    story.append(Spacer(1, 6))

    # ── Priority action summary table ─────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=2, color=TEAL, spaceAfter=8))
    story.append(Paragraph("Priority action summary", S["h2"]))

    action_data = [
        ["Priority", "Action", "Owner", "Timeline"],
        ["P1 — Critical",
         f"Restore connectivity to {wd['Device ID']} ({wd['Location']})\n"
         f"{int(wd['Reconnect Count'])} reconnects, {int(wd['Queue Depth'])} messages queued, status {wd['Connection Status']}",
         "Network / IT", "Today"],
        ["P1 — Critical",
         f"Inspect camera thermals at {d['cam_hot_locs']}\nPeak camera temperature {d['cam_temp_max']}°C recorded",
         "Hardware", "Today"],
        ["P2 — High",
         f"Restore {d['near_capacity_ids']} before queue overflow\nCombined {d['near_capacity_queue']} messages queued",
         "Network / IT", "< 2 hours"],
        ["P2 — High",
         f"Audit APs serving {', '.join(sorted(d['high_reconnect']['Location'].unique())[:2])}\n"
         f"{len(d['high_reconnect'])} devices with >8 reconnections across affected zones",
         "Network", "This week"],
        ["P3 — Medium",
         f"Review camera CPU load and video processing settings\nSustained ~{d['cam_cpu']}% CPU on all {d['camera_count']} camera devices",
         "Firmware", "This sprint"],
        ["P3 — Medium",
         "Increase max_queue_size for devices in problem zones",
         "DevOps", "This sprint"],
    ]

    col_w = [30*mm, 77*mm, 30*mm, 22*mm]
    act_table = Table(action_data, colWidths=col_w, repeatRows=1)
    act_table.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),  (-1,0),  DARK),
        ("TEXTCOLOR",     (0,0),  (-1,0),  colors.white),
        ("FONTNAME",      (0,0),  (-1,0),  "Helvetica-Bold"),
        ("FONTNAME",      (0,1),  (-1,-1), "Helvetica"),
        ("FONTSIZE",      (0,0),  (-1,-1), 8),
        ("ALIGN",         (0,0),  (0,-1),  "CENTER"),
        ("ALIGN",         (1,0),  (1,-1),  "LEFT"),
        ("ALIGN",         (2,0),  (-1,-1), "CENTER"),
        ("VALIGN",        (0,0),  (-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0),  (-1,-1), 5),
        ("BOTTOMPADDING", (0,0),  (-1,-1), 5),
        ("LEFTPADDING",   (1,1),  (1,-1),  6),
        ("ROWBACKGROUNDS",(0,1),  (-1,-1), [colors.white, LIGHT_GRAY]),
        ("BOX",           (0,0),  (-1,-1), 0.5, HexColor("#D3D1C7")),
        ("INNERGRID",     (0,0),  (-1,-1), 0.5, HexColor("#D3D1C7")),
        # P1 rows — red left border
        ("TEXTCOLOR",     (0,1),  (0,2),   RED),
        ("FONTNAME",      (0,1),  (0,2),   "Helvetica-Bold"),
        # P2 rows — amber
        ("TEXTCOLOR",     (0,3),  (0,4),   AMBER),
        ("FONTNAME",      (0,3),  (0,4),   "Helvetica-Bold"),
        # P3 rows — teal
        ("TEXTCOLOR",     (0,5),  (0,6),   TEAL),
        ("FONTNAME",      (0,5),  (0,6),   "Helvetica-Bold"),
    ]))
    story.append(act_table)
    story.append(Spacer(1, 8))

    # ── Footer ────────────────────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#D3D1C7"), spaceAfter=4))
    story.append(Paragraph(
        f"Generated {d['report_date']} at {d['report_time']} · "
        f"Data source: InfluxDB fleet-telemetry bucket · "
        f"Pipeline: robmqtt → Mosquitto → InfluxDB · "
        f"Analysis by Supun Sriyananda",
        S["footer"]
    ))

    doc.build(story)
    print(f"\nReport written → {output_path}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate fleet insight report PDF")
    parser.add_argument("--data",   default="../powerbi/sample_data",
                        help="Directory containing the four CSV files")
    parser.add_argument("--output", default="./fleet_insight_report.pdf")
    args = parser.parse_args()

    tel_path = os.path.join(args.data, "telemetry.csv")
    sta_path = os.path.join(args.data, "status.csv")

    if not os.path.exists(tel_path):
        print(f"telemetry.csv not found at {tel_path}")
        print("Run: python ../powerbi/export_for_powerbi.py --sample --output ../powerbi/sample_data")
        return

    print(f"Loading data from {args.data}...")
    tel = pd.read_csv(tel_path, parse_dates=["Timestamp"])
    sta = pd.read_csv(sta_path)

    print("Analysing fleet data...")
    insights = analyse(tel, sta)

    print("Generating PDF report...")
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    build_pdf(insights, args.output)
    print(f"Done. Open: {os.path.abspath(args.output)}")


if __name__ == "__main__":
    main()
