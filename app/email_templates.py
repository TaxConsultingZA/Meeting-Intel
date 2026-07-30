"""
Tax Consulting SA — Meeting Intelligence Email Template
Table-based, inline-styled HTML for full Outlook compatibility.
Brand colours: Navy #003366 | Gold #C9A52C | White | Light grey
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Meeting

# ── Brand colours ─────────────────────────────────────────────────────────────
_NAVY    = "#003366"
_GOLD    = "#C9A52C"
_WHITE   = "#FFFFFF"
_LIGHT   = "#F4F6F9"
_BORDER  = "#CCCCCC"
_TEXT    = "#1A1A1A"
_MUTED   = "#555555"
_TH_BG   = "#003366"
_TH_TEXT = "#FFFFFF"
_ROW_ALT = "#EEF2F7"


def _section_heading(title: str) -> str:
    """Render a gold-left-bordered section heading row for use inside the email table."""
    return f"""
    <tr>
      <td style="padding:24px 0 8px 0;">
        <table width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr>
            <td style="border-left:4px solid {_GOLD};padding-left:12px;
                font-size:15px;font-weight:700;color:{_NAVY};
                font-family:Arial,sans-serif;letter-spacing:0.3px;">
              {title}
            </td>
          </tr>
          <tr>
            <td style="padding-top:6px;border-bottom:1px solid {_BORDER};"></td>
          </tr>
        </table>
      </td>
    </tr>"""


def _th(text: str, width: str = "") -> str:
    """Render a navy-background table header ``<td>`` with optional fixed width."""
    w = f'width="{width}"' if width else ""
    return (
        f'<td {w} style="background:{_TH_BG};color:{_TH_TEXT};font-size:12px;'
        f'font-weight:700;padding:9px 12px;font-family:Arial,sans-serif;'
        f'border:1px solid {_NAVY};">{text}</td>'
    )


def _td(text: str, alt: bool = False, bold: bool = False) -> str:
    """Render a data ``<td>`` with optional alternating row background and bold text.

    Empty strings are replaced with an em-dash placeholder styled in grey.
    """
    bg     = _ROW_ALT if alt else _WHITE
    weight = "600" if bold else "400"
    val    = text if text else "<span style='color:#AAAAAA;'>—</span>"
    return (
        f'<td style="background:{bg};color:{_TEXT};font-size:13px;'
        f'font-weight:{weight};padding:8px 12px;font-family:Arial,sans-serif;'
        f'border:1px solid {_BORDER};vertical-align:top;">{val}</td>'
    )


def _detail_table(rows: list[tuple[str, str]]) -> str:
    """Render a two-column label/value detail table (e.g. Meeting Details section)."""
    html = '<table width="100%" cellpadding="0" cellspacing="0" border="0">'
    for i, (label, value) in enumerate(rows):
        alt = i % 2 == 1
        bg  = _ROW_ALT if alt else _WHITE
        val = value if value else "<span style='color:#AAAAAA;'>—</span>"
        html += f"""
        <tr>
          <td width="180" style="background:{bg};font-size:13px;font-weight:700;
              color:{_NAVY};padding:8px 12px;border:1px solid {_BORDER};
              font-family:Arial,sans-serif;vertical-align:top;">{label}</td>
          <td style="background:{bg};font-size:13px;color:{_TEXT};
              padding:8px 12px;border:1px solid {_BORDER};
              font-family:Arial,sans-serif;vertical-align:top;">{val}</td>
        </tr>"""
    html += "</table>"
    return html


def _empty_row(cols: int) -> str:
    """Render a full-width italic "None identified" placeholder row spanning *cols* columns."""
    return (
        f'<tr><td colspan="{cols}" style="text-align:center;color:#AAAAAA;'
        f'font-size:12px;font-style:italic;padding:12px;border:1px solid {_BORDER};'
        f'font-family:Arial,sans-serif;">None identified</td></tr>'
    )


def build_welcome_email(upn: str, display_name: str | None, business_unit: str | None,
                        app_url: str) -> tuple[str, str]:
    """Return (subject, html_body) for the registration welcome / invitation email."""
    name = display_name or upn.split("@")[0].replace(".", " ").title()
    bu_line = f"<strong>{business_unit}</strong>" if business_unit else "your business unit"
    subject = "You've been registered on Meeting Intelligence"
    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:{_LIGHT};font-family:Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{_LIGHT};padding:28px 16px;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" border="0" style="max-width:600px;width:100%;">

  <!-- HEADER -->
  <tr>
    <td style="background:{_NAVY};border-bottom:4px solid {_GOLD};padding:28px 32px;border-radius:6px 6px 0 0;">
      <p style="margin:0 0 4px 0;font-size:11px;color:rgba(255,255,255,0.6);
          letter-spacing:1.5px;text-transform:uppercase;font-family:Arial,sans-serif;">
        Tax Consulting SA &mdash; Meeting Intelligence
      </p>
      <h1 style="margin:0;font-size:22px;font-weight:700;color:{_WHITE};font-family:Arial,sans-serif;">
        Welcome to Meeting Intelligence
      </h1>
    </td>
  </tr>

  <!-- BODY -->
  <tr>
    <td style="background:{_WHITE};padding:36px 32px;
        border-left:1px solid {_BORDER};border-right:1px solid {_BORDER};">
      <table width="100%" cellpadding="0" cellspacing="0" border="0">
        <tr>
          <td style="font-size:15px;color:{_TEXT};font-family:Arial,sans-serif;line-height:1.8;padding-bottom:24px;">
            Hi <strong>{name}</strong>,<br><br>
            Your account has been registered on the <strong>TaxConsulting SA Meeting Intelligence</strong>
            platform under {bu_line}.<br><br>
            From now on, your recorded Microsoft Teams meetings will be automatically transcribed,
            summarised, and made available for your review — no manual effort required.
          </td>
        </tr>

        <!-- CTA -->
        <tr>
          <td align="center" style="padding:8px 0 28px 0;">
            <a href="{app_url}"
               style="display:inline-block;background:{_GOLD};color:{_NAVY};font-weight:700;
                      font-size:15px;padding:14px 32px;border-radius:6px;
                      text-decoration:none;font-family:Arial,sans-serif;letter-spacing:0.3px;">
              Go to My Dashboard &rarr;
            </a>
          </td>
        </tr>

        <!-- What to expect -->
        <tr>
          <td style="border-top:1px solid {_BORDER};padding-top:24px;">
            <p style="margin:0 0 12px 0;font-size:13px;font-weight:700;color:{_NAVY};
                font-family:Arial,sans-serif;letter-spacing:0.3px;">WHAT TO EXPECT</p>
            <table width="100%" cellpadding="0" cellspacing="0" border="0">
              {''.join(f"""<tr>
                <td width="28" style="vertical-align:top;padding:4px 0;">
                  <span style="color:{_GOLD};font-size:16px;font-weight:700;">&#8226;</span>
                </td>
                <td style="font-size:13px;color:{_TEXT};font-family:Arial,sans-serif;
                    line-height:1.7;padding:4px 0;">{item}</td>
              </tr>""" for item in [
                "Meetings you host or attend that are recorded will appear automatically on your dashboard.",
                "You can review AI-extracted notes, edit action items, and approve the summary before it is shared.",
                "You can share a transcript with any <strong>@taxconsulting.co.za</strong> colleague.",
                "Recordings that happened before your registration are accessible on request — if you were listed as an attendee.",
              ])}
            </table>
          </td>
        </tr>
      </table>
    </td>
  </tr>

  <!-- FOOTER -->
  <tr>
    <td style="background:{_NAVY};padding:16px 32px;border-radius:0 0 6px 6px;">
      <p style="margin:0;font-size:11px;color:rgba(255,255,255,0.65);
          line-height:1.6;font-family:Arial,sans-serif;">
        This email was generated automatically by the Tax Consulting SA Meeting Intelligence system.
        Processed in accordance with POPIA (Protection of Personal Information Act, 2013).
        Questions? Contact
        <a href="mailto:privacy@taxconsulting.co.za"
           style="color:{_GOLD};text-decoration:none;">privacy@taxconsulting.co.za</a>
      </p>
    </td>
  </tr>

</table>
</td></tr>
</table>
</body>
</html>"""
    return subject, html


def build_meeting_email(meeting: "Meeting") -> tuple[str, str]:
    """Returns (subject, html_body). Reads from extracted_json when available,
    falls back to legacy summary + action_items for older records."""

    title      = (meeting.title or "Meeting Recording").replace(".mp4", "").strip()
    organizer  = meeting.organizer_upn or ""
    today      = datetime.now(timezone.utc).strftime("%d %B %Y")
    data       = meeting.extracted_json or {}

    # ── pull structured data ──────────────────────────────────────────────────
    objective          = data.get("objective") or meeting.summary or ""
    meeting_time       = data.get("meeting_time") or ""
    attendees          = ", ".join(data.get("attendees") or []) or ""
    apologies          = ", ".join(data.get("apologies") or []) or ""
    platform           = data.get("platform") or "Microsoft Teams"
    speaker_highlights = data.get("speaker_highlights") or []
    discussion_points  = data.get("discussion_points") or []
    action_items       = data.get("action_items") or []
    deliverables       = data.get("deliverables") or []
    risks              = data.get("risks") or []
    next_steps         = data.get("next_steps") or []
    nm                 = data.get("next_meeting") or {}

    subject = f"Meeting Notes & Action Items — {title}"

    # ── speaker highlights cards ──────────────────────────────────────────────
    if speaker_highlights:
        cards = ""
        colours = [_NAVY, "#1A5276", "#154360", "#0E3460", "#1B2A4A"]
        for idx, sh in enumerate(speaker_highlights):
            speaker   = sh.get("speaker", f"Speaker {idx+1}")
            role      = sh.get("role") or "Participant"
            points    = sh.get("key_points") or []
            col       = colours[idx % len(colours)]
            pts_html  = "".join(
                f'<tr><td style="padding:3px 0 3px 0;font-size:13px;color:#1A1A1A;'
                f'font-family:Arial,sans-serif;line-height:1.6;">'
                f'<span style="color:{_GOLD};font-weight:700;padding-right:6px;">&#8226;</span>'
                f'{pt}</td></tr>'
                for pt in points
            ) or f'<tr><td style="font-size:12px;color:#AAAAAA;font-style:italic;font-family:Arial,sans-serif;">No key points captured</td></tr>'
            cards += f"""
            <td width="33%" style="vertical-align:top;padding:6px;">
              <table width="100%" cellpadding="0" cellspacing="0" border="0"
                     style="border-top:3px solid {col};background:#F8F9FA;border-radius:0 0 4px 4px;">
                <tr>
                  <td style="background:{col};padding:10px 14px;">
                    <p style="margin:0;font-size:13px;font-weight:700;color:{_WHITE};
                        font-family:Arial,sans-serif;">{speaker}</p>
                    <p style="margin:2px 0 0 0;font-size:11px;color:rgba(255,255,255,0.7);
                        font-family:Arial,sans-serif;">{role}</p>
                  </td>
                </tr>
                <tr>
                  <td style="padding:12px 14px;">
                    <table width="100%" cellpadding="0" cellspacing="0" border="0">
                      {pts_html}
                    </table>
                  </td>
                </tr>
              </table>
            </td>"""

        # Group into rows of 3
        all_cards = [sh for sh in speaker_highlights]
        rows_html = ""
        for i in range(0, len(all_cards), 3):
            batch = all_cards[i:i+3]
            row_cells = ""
            colours2 = [_NAVY, "#1A5276", "#154360", "#0E3460", "#1B2A4A"]
            for idx2, sh in enumerate(batch):
                real_idx = i + idx2
                speaker   = sh.get("speaker", f"Speaker {real_idx+1}")
                role      = sh.get("role") or "Participant"
                points    = sh.get("key_points") or []
                col       = colours2[real_idx % len(colours2)]
                pts_html2 = "".join(
                    f'<tr><td style="padding:3px 0;font-size:13px;color:#1A1A1A;'
                    f'font-family:Arial,sans-serif;line-height:1.6;">'
                    f'<span style="color:{_GOLD};font-weight:700;padding-right:6px;">&#8226;</span>'
                    f'{pt}</td></tr>'
                    for pt in points
                ) or f'<tr><td style="font-size:12px;color:#AAAAAA;font-style:italic;">No key points</td></tr>'
                row_cells += f"""
                <td width="33%" style="vertical-align:top;padding:4px;">
                  <table width="100%" cellpadding="0" cellspacing="0" border="0"
                         style="border-top:3px solid {col};background:#F8F9FA;">
                    <tr><td style="background:{col};padding:10px 14px;">
                      <p style="margin:0;font-size:13px;font-weight:700;color:{_WHITE};font-family:Arial,sans-serif;">{speaker}</p>
                      <p style="margin:2px 0 0;font-size:11px;color:rgba(255,255,255,0.7);font-family:Arial,sans-serif;">{role}</p>
                    </td></tr>
                    <tr><td style="padding:10px 14px;">
                      <table width="100%" cellpadding="0" cellspacing="2" border="0">{pts_html2}</table>
                    </td></tr>
                  </table>
                </td>"""
            # Pad to 3 cols
            for _ in range(3 - len(batch)):
                row_cells += '<td width="33%" style="padding:4px;"></td>'
            rows_html += f'<tr>{row_cells}</tr>'

        speaker_section_html = f"""
        <table width="100%" cellpadding="0" cellspacing="0" border="0">
          {rows_html}
        </table>"""
    else:
        speaker_section_html = f'<p style="color:#AAAAAA;font-size:12px;font-style:italic;font-family:Arial,sans-serif;">No speaker data captured</p>'

    # ── discussion points table ───────────────────────────────────────────────
    dp_rows = ""
    if discussion_points:
        for i, dp in enumerate(discussion_points):
            alt = i % 2 == 1
            dp_rows += f"<tr>{_td(dp.get('topic',''), alt, bold=True)}{_td(dp.get('summary',''), alt)}{_td(dp.get('outcome',''), alt)}</tr>"
    else:
        dp_rows = _empty_row(3)

    discussion_table = f"""
    <table width="100%" cellpadding="0" cellspacing="0" border="0">
      <tr>{_th('Topic')}{_th('Discussion Summary')}{_th('Outcome / Decision')}</tr>
      {dp_rows}
    </table>"""

    # ── action items table ────────────────────────────────────────────────────
    ai_rows = ""
    if action_items:
        for i, ai in enumerate(action_items):
            alt = i % 2 == 1
            ai_rows += (
                f"<tr>"
                f"{_td(ai.get('action') or ai.get('task',''), alt, bold=True)}"
                f"{_td(ai.get('assigned_to') or ai.get('owner',''), alt)}"
                f"{_td(ai.get('department',''), alt)}"
                f"{_td(ai.get('reason',''), alt)}"
                f"{_td(ai.get('expected_outcome',''), alt)}"
                f"{_td(ai.get('due_date') or ai.get('deadline_text',''), alt)}"
                f"</tr>"
            )
    else:
        ai_rows = _empty_row(6)

    action_table = f"""
    <table width="100%" cellpadding="0" cellspacing="0" border="0">
      <tr>
        {_th('Action Required')}{_th('Assigned To')}{_th('Department / Team')}
        {_th('Reason / Objective')}{_th('Expected Outcome')}{_th('Due Date')}
      </tr>
      {ai_rows}
    </table>"""

    # ── deliverables table ────────────────────────────────────────────────────
    del_rows = ""
    if deliverables:
        for i, d in enumerate(deliverables):
            alt = i % 2 == 1
            del_rows += (
                f"<tr>"
                f"{_td(d.get('deliverable',''), alt, bold=True)}"
                f"{_td(d.get('responsible',''), alt)}"
                f"{_td(d.get('delivery_method',''), alt)}"
                f"{_td(d.get('due_date',''), alt)}"
                f"{_td(d.get('expected_outcome',''), alt)}"
                f"</tr>"
            )
    else:
        del_rows = _empty_row(5)

    deliverables_table = f"""
    <table width="100%" cellpadding="0" cellspacing="0" border="0">
      <tr>
        {_th('Deliverable')}{_th('Responsible Person')}{_th('Delivery Method')}
        {_th('Due Date')}{_th('Expected Outcome')}
      </tr>
      {del_rows}
    </table>"""

    # ── risks table ───────────────────────────────────────────────────────────
    risk_rows = ""
    if risks:
        for i, r in enumerate(risks):
            alt = i % 2 == 1
            risk_rows += (
                f"<tr>"
                f"{_td(r.get('item',''), alt, bold=True)}"
                f"{_td(r.get('impact',''), alt)}"
                f"{_td(r.get('resolution',''), alt)}"
                f"{_td(r.get('owner',''), alt)}"
                f"</tr>"
            )
    else:
        risk_rows = _empty_row(4)

    risks_table = f"""
    <table width="100%" cellpadding="0" cellspacing="0" border="0">
      <tr>
        {_th('Item')}{_th('Impact')}{_th('Required Support / Resolution')}{_th('Owner')}
      </tr>
      {risk_rows}
    </table>"""

    # ── next steps list ───────────────────────────────────────────────────────
    if next_steps:
        ns_items = "".join(
            f'<tr><td style="padding:5px 0;font-size:13px;color:{_TEXT};'
            f'font-family:Arial,sans-serif;">'
            f'<span style="color:{_GOLD};font-weight:700;padding-right:8px;">&#8226;</span>{step}'
            f'</td></tr>'
            for step in next_steps
        )
        next_steps_html = f'<table width="100%" cellpadding="0" cellspacing="4" border="0">{ns_items}</table>'
    else:
        next_steps_html = f'<p style="color:#AAAAAA;font-size:12px;font-style:italic;font-family:Arial,sans-serif;">None noted</p>'

    # ── next meeting table ────────────────────────────────────────────────────
    next_meeting_table = _detail_table([
        ("Proposed Date", nm.get("proposed_date", "")),
        ("Proposed Time", nm.get("proposed_time", "")),
        ("Agenda Focus",  nm.get("agenda_focus", "")),
    ])

    # ── full HTML ─────────────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:{_LIGHT};font-family:Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{_LIGHT};padding:28px 16px;">
<tr><td align="center">
<table width="680" cellpadding="0" cellspacing="0" border="0" style="max-width:680px;width:100%;">

  <!-- HEADER -->
  <tr>
    <td style="background:{_NAVY};padding:0;border-radius:6px 6px 0 0;">
      <table width="100%" cellpadding="0" cellspacing="0" border="0">
        <tr>
          <td style="border-bottom:4px solid {_GOLD};padding:24px 32px;">
            <p style="margin:0 0 4px 0;font-size:11px;color:rgba(255,255,255,0.6);
                letter-spacing:1.5px;text-transform:uppercase;font-family:Arial,sans-serif;">
              Tax Consulting SA &mdash; Meeting Intelligence
            </p>
            <h1 style="margin:0;font-size:20px;font-weight:700;color:{_WHITE};
                line-height:1.35;font-family:Arial,sans-serif;">
              {title}
            </h1>
          </td>
        </tr>
      </table>
    </td>
  </tr>

  <!-- BODY -->
  <tr>
    <td style="background:{_WHITE};padding:32px;
        border-left:1px solid {_BORDER};border-right:1px solid {_BORDER};">
      <table width="100%" cellpadding="0" cellspacing="0" border="0">

        <!-- Greeting -->
        <tr>
          <td style="padding-bottom:20px;font-size:14px;color:{_TEXT};
              font-family:Arial,sans-serif;line-height:1.7;">
            Good Day,<br><br>
            Please find below the meeting notes and agreed action items from the discussion.
          </td>
        </tr>

        <!-- MEETING DETAILS -->
        {_section_heading("Meeting Details")}
        <tr>
          <td style="padding-top:12px;padding-bottom:4px;">
            {_detail_table([
                ("Meeting Title",    title),
                ("Date",            today),
                ("Time",            meeting_time),
                ("Platform / Venue", platform),
                ("Organiser",       organizer),
                ("Attendees",       attendees),
                ("Apologies",       apologies),
            ])}
          </td>
        </tr>

        <!-- MEETING OBJECTIVE -->
        {_section_heading("Meeting Objective")}
        <tr>
          <td style="padding:12px 0 4px 0;font-size:13px;color:{_TEXT};
              line-height:1.75;font-family:Arial,sans-serif;">
            {objective or '<span style="color:#AAAAAA;font-style:italic;">Not captured</span>'}
          </td>
        </tr>

        <!-- SPEAKER HIGHLIGHTS -->
        {_section_heading("Speaker Highlights")}
        <tr>
          <td style="padding-top:12px;padding-bottom:4px;">
            {speaker_section_html}
          </td>
        </tr>

        <!-- KEY DISCUSSION POINTS -->
        {_section_heading("Key Discussion Points")}
        <tr><td style="padding-top:12px;padding-bottom:4px;">{discussion_table}</td></tr>

        <!-- ACTION ITEMS -->
        {_section_heading("Action Items")}
        <tr><td style="padding-top:12px;padding-bottom:4px;">{action_table}</td></tr>

        <!-- DELIVERABLES -->
        {_section_heading("Deliverables")}
        <tr><td style="padding-top:12px;padding-bottom:4px;">{deliverables_table}</td></tr>

        <!-- RISKS / CHALLENGES / DEPENDENCIES -->
        {_section_heading("Risks / Challenges / Dependencies")}
        <tr><td style="padding-top:12px;padding-bottom:4px;">{risks_table}</td></tr>

        <!-- NEXT STEPS -->
        {_section_heading("Next Steps")}
        <tr><td style="padding-top:12px;padding-bottom:4px;">{next_steps_html}</td></tr>

        <!-- NEXT MEETING -->
        {_section_heading("Next Meeting")}
        <tr><td style="padding-top:12px;padding-bottom:24px;">{next_meeting_table}</td></tr>

        <!-- Sign-off -->
        <tr>
          <td style="padding-top:16px;border-top:1px solid {_BORDER};
              font-size:14px;color:{_TEXT};font-family:Arial,sans-serif;line-height:1.8;">
            Kind Regards,<br>
            <strong style="color:{_NAVY};">Tax Consulting SA</strong><br>
            <span style="font-size:12px;color:{_MUTED};">Meeting Intelligence System</span>
          </td>
        </tr>

      </table>
    </td>
  </tr>

  <!-- FOOTER -->
  <tr>
    <td style="background:{_NAVY};padding:16px 32px;border-radius:0 0 6px 6px;">
      <p style="margin:0;font-size:11px;color:rgba(255,255,255,0.65);
          line-height:1.6;font-family:Arial,sans-serif;">
        This email was generated automatically by the Tax Consulting SA Meeting Intelligence system.
        Processed in accordance with POPIA (Protection of Personal Information Act, 2013).
        Concerns? Contact
        <a href="mailto:privacy@taxconsulting.co.za"
           style="color:{_GOLD};text-decoration:none;">privacy@taxconsulting.co.za</a>
      </p>
    </td>
  </tr>

</table>
</td></tr>
</table>
</body>
</html>"""

    return subject, html
