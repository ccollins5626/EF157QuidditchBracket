import csv
import html
import io
import json
import os
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nicegui import Client, app, ui
from supabase import create_client

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
STORAGE_SECRET = os.getenv("STORAGE_SECRET")
PORT = int(os.getenv("PORT", "8080"))
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "team-logos")

if not ADMIN_PASSWORD:
    raise RuntimeError("Missing ADMIN_PASSWORD environment variable.")
if not STORAGE_SECRET:
    raise RuntimeError("Missing STORAGE_SECRET environment variable.")
if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError(
        "Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY environment variable."
    )

# This client is server-side only. Never expose the service-role key to browsers.
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

SECTION_IDS = [f"section_{n}" for n in range(1, 8)]
SECTION_LABELS = {f"section_{n}": f"Section {n}" for n in range(1, 8)}

# Matches are calculated from this dependency graph.
# M1/M2: opening round; M3/M4: seeds 1/2 enter; M5: winners final.
# LB1/LB2: first losers-bracket round; LB3: losers-bracket semifinal;
# LB4: losers-bracket final; GF: grand final; RESET: conditional reset final.
MATCHES = [
    ("M1", "Match 1", "Winners Bracket"),
    ("M2", "Match 2", "Winners Bracket"),
    ("M3", "Match 3", "Winners Bracket"),
    ("M4", "Match 4", "Winners Bracket"),
    ("M5", "Match 5", "Winners Bracket Final"),
    ("LB1", "Losers Match 1", "Losers Bracket"),
    ("LB2", "Losers Match 2", "Losers Bracket"),
    ("LB3", "Losers Match 3", "Losers Bracket"),
    ("LB4", "Losers Match 4", "Losers Bracket Final"),
    ("GF", "Match 6", "Grand Final"),
    ("RESET", "L6 Option — Championship Reset", "Grand Final"),
]


# Display priority for the public "Up Next" panel. A match only appears once
# both participants are known and the match has not already been completed.
NEXT_MATCH_ORDER = ["M1", "M2", "M3", "M4", "LB1", "LB2", "M5", "LB3", "LB4", "GF", "RESET"]
MATCH_TITLES = {key: title for key, title, _ in MATCHES}


def next_ready_matches(state: dict[str, Any], limit: int = 2) -> list[tuple[str, str, str]]:
    """Return the next ready matches as (key, team A id, team B id)."""
    ready: list[tuple[str, str, str]] = []
    for key in NEXT_MATCH_ORDER:
        a, b = participants(state, key)
        if not a or not b or result_winner(state, key):
            continue
        if key == "RESET":
            gf_winner = result_winner(state, "GF")
            losers_bracket_finalist = participants(state, "GF")[1]
            if not gf_winner or gf_winner != losers_bracket_finalist:
                continue
        ready.append((key, a, b))
        if len(ready) >= limit:
            break
    return ready


EXPORT_COLUMNS = [
    "Section", "Round", "Match", "Team 1", "Team 1 Seed", "Score 1",
    "Team 2", "Team 2 Seed", "Score 2", "Winner", "Champion",
]


def completed_export_rows(section_id: str, state: dict[str, Any]) -> list[dict[str, Any]]:
    """Build completed-match rows from the same JSON state used by the live bracket."""
    rows: list[dict[str, Any]] = []
    champion = team_by_id(state, state.get("champion_id"))
    champion_name = champion["name"] if champion else ""
    for key, title, round_name in MATCHES:
        result = state.get("results", {}).get(key, {})
        if not result.get("winner_id"):
            continue
        team_a = team_by_id(state, result.get("team_a_id"))
        team_b = team_by_id(state, result.get("team_b_id"))
        winner = team_by_id(state, result.get("winner_id"))
        rows.append({
            "Section": SECTION_LABELS[section_id],
            "Round": round_name,
            "Match": title,
            "Team 1": team_a["name"] if team_a else "Unknown",
            "Team 1 Seed": team_a["seed"] if team_a else "",
            "Score 1": result.get("score_a", ""),
            "Team 2": team_b["name"] if team_b else "Unknown",
            "Team 2 Seed": team_b["seed"] if team_b else "",
            "Score 2": result.get("score_b", ""),
            "Winner": winner["name"] if winner else "Unknown",
            "Champion": champion_name,
        })
    return rows


def make_csv_export(section_states: list[tuple[str, dict[str, Any]]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=EXPORT_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for section_id, state in section_states:
        writer.writerows(completed_export_rows(section_id, state))
    # UTF-8 BOM helps Excel open team names correctly on Windows.
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def make_excel_export(section_states: list[tuple[str, dict[str, Any]]]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    workbook = Workbook()
    default_sheet = workbook.active
    workbook.remove(default_sheet)
    for section_id, state in section_states:
        sheet_name = SECTION_LABELS[section_id]
        worksheet = workbook.create_sheet(title=sheet_name)
        worksheet.append([f"{sheet_name} Tournament Results"])
        worksheet.append([f"Exported: {datetime.now(timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}"])
        worksheet.append([])
        worksheet.append(EXPORT_COLUMNS[1:])
        for row in completed_export_rows(section_id, state):
            worksheet.append([row[column] for column in EXPORT_COLUMNS[1:]])

        worksheet.freeze_panes = "A5"
        worksheet.auto_filter.ref = f"A4:{get_column_letter(len(EXPORT_COLUMNS) - 1)}{max(4, worksheet.max_row)}"
        for cell in worksheet[4]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="1F4E78")
            cell.alignment = Alignment(horizontal="center")
        for column_cells in worksheet.columns:
            column_letter = get_column_letter(column_cells[0].column)
            max_length = max((len(str(cell.value or "")) for cell in column_cells), default=10)
            worksheet.column_dimensions[column_letter].width = min(max(max_length + 3, 12), 32)
        worksheet.sheet_view.showGridLines = False

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()

DESCENDANTS = {
    "M1": {"M3", "LB1", "LB3", "LB4", "GF", "RESET"},
    "M2": {"M4", "LB1", "LB3", "LB4", "GF", "RESET"},
    "M3": {"M5", "LB2", "LB3", "LB4", "GF", "RESET"},
    "M4": {"M5", "LB2", "LB3", "LB4", "GF", "RESET"},
    "M5": {"LB4", "GF", "RESET"},
    "LB1": {"LB3", "LB4", "GF", "RESET"},
    "LB2": {"LB3", "LB4", "GF", "RESET"},
    "LB3": {"LB4", "GF", "RESET"},
    "LB4": {"GF", "RESET"},
    "GF": {"RESET"},
    "RESET": set(),
}


def blank_section() -> dict[str, Any]:
    return {
        "teams": [
            {"id": str(uuid.uuid4()), "seed": seed, "name": f"Team {seed}", "logo": None}
            for seed in range(1, 7)
        ],
        "results": {},
        "champion_id": None,
    }


def initialize_database() -> None:
    """Create only missing section records; never overwrite existing brackets."""
    for section_id in SECTION_IDS:
        response = (
            supabase.table("sections")
            .select("section_id")
            .eq("section_id", section_id)
            .limit(1)
            .execute()
        )
        if not response.data:
            save_section(section_id, blank_section())


def load_section(section_id: str) -> dict[str, Any]:
    response = (
        supabase.table("sections")
        .select("state_json")
        .eq("section_id", section_id)
        .limit(1)
        .execute()
    )
    if not response.data:
        state = blank_section()
        save_section(section_id, state)
        return state
    # Supabase returns JSONB as a native Python dict.
    return response.data[0]["state_json"]


def save_section(section_id: str, state: dict[str, Any]) -> None:
    supabase.table("sections").upsert(
        {
            "section_id": section_id,
            "state_json": state,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        on_conflict="section_id",
    ).execute()


initialize_database()

# ---------------------------------------------------------------------------
# Bracket engine
# ---------------------------------------------------------------------------

def team_by_id(state: dict[str, Any], team_id: str | None) -> dict | None:
    if not team_id:
        return None
    return next((team for team in state["teams"] if team["id"] == team_id), None)


def result_winner(state: dict[str, Any], key: str) -> str | None:
    result = state["results"].get(key, {})
    return result.get("winner_id")


def result_loser(state: dict[str, Any], key: str) -> str | None:
    result = state["results"].get(key, {})
    a, b, winner = result.get("team_a_id"), result.get("team_b_id"), result.get("winner_id")
    if not winner or not a or not b:
        return None
    return b if winner == a else a


def participants(state: dict[str, Any], key: str) -> tuple[str | None, str | None]:
    teams = sorted(state["teams"], key=lambda team: team["seed"])
    seed = {team["seed"]: team["id"] for team in teams}
    winner = lambda match: result_winner(state, match)
    loser = lambda match: result_loser(state, match)

    mapping = {
        "M1": (seed.get(4), seed.get(5)),
        "M2": (seed.get(3), seed.get(6)),
        "M3": (seed.get(1), winner("M1")),
        "M4": (seed.get(2), winner("M2")),
        "M5": (winner("M3"), winner("M4")),
        "LB1": (loser("M1"), loser("M2")),
        "LB2": (loser("M3"), loser("M4")),
        "LB3": (winner("LB1"), winner("LB2")),
        "LB4": (winner("LB3"), loser("M5")),
        "GF": (winner("M5"), winner("LB4")),
        "RESET": (winner("GF"), loser("GF")),
    }
    return mapping.get(key, (None, None))


def invalidate_descendants(state: dict[str, Any], match_key: str) -> None:
    for descendant in DESCENDANTS.get(match_key, set()):
        state["results"].pop(descendant, None)
    state["champion_id"] = None


def refresh_champion(state: dict[str, Any]) -> None:
    gf_winner = result_winner(state, "GF")
    gf_loser = result_loser(state, "GF")
    if not gf_winner:
        state["champion_id"] = None
        return

    # If the losers-bracket finalist wins the first grand final, both finalists
    # now have one loss, so the reset match is required.
    losers_bracket_champion = participants(state, "GF")[1]
    if gf_winner == losers_bracket_champion:
        state["champion_id"] = result_winner(state, "RESET")
    else:
        state["champion_id"] = gf_winner


def save_match_result(
    section_id: str,
    key: str,
    score_a: int | None,
    score_b: int | None,
    override_winner: str | None = None,
) -> None:
    state = load_section(section_id)
    a, b = participants(state, key)
    if not a or not b:
        raise ValueError("This match is not ready: both teams must be determined first.")
    if score_a is None or score_b is None:
        raise ValueError("Enter both scores before saving.")
    if score_a == score_b and not override_winner:
        raise ValueError("A tied score needs an administrator to select the winner.")
    winner = override_winner
    if winner is None:
        winner = a if score_a > score_b else b
    if winner not in (a, b):
        raise ValueError("The selected winner must be one of the teams in this match.")

    invalidate_descendants(state, key)
    state["results"][key] = {
        "team_a_id": a,
        "team_b_id": b,
        "score_a": score_a,
        "score_b": score_b,
        "winner_id": winner,
    }
    refresh_champion(state)
    save_section(section_id, state)


def clear_match(section_id: str, key: str) -> None:
    state = load_section(section_id)
    state["results"].pop(key, None)
    invalidate_descendants(state, key)
    refresh_champion(state)
    save_section(section_id, state)


# ---------------------------------------------------------------------------
# Shared live refresh
# ---------------------------------------------------------------------------

refresh_callbacks = set()


def broadcast_update(exclude=None) -> None:
    """Refresh connected viewers, optionally leaving the editing browser untouched."""
    for callback in list(refresh_callbacks):
        if callback is exclude:
            continue
        try:
            callback()
        except Exception:
            # A disconnected browser may briefly remain in this set.
            refresh_callbacks.discard(callback)


def is_admin(client: Client) -> bool:
    return bool(app.storage.user.get("is_admin"))


def team_label(state: dict[str, Any], team_id: str | None) -> str:
    team = team_by_id(state, team_id)
    return f"#{team['seed']} {team['name']}" if team else "TBD"


def match_status(state: dict[str, Any], key: str) -> str:
    a, b = participants(state, key)
    if not a or not b:
        return "Waiting for previous results"
    if result_winner(state, key):
        return "Complete"
    return "Ready to play"


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

@ui.page("/")
def main_page(client: Client) -> None:
    selected_section = {"id": "section_1"}
    refresh_self = None
    # Snapshot this browser's own login state into its page closure. A broadcast
    # refresh can be initiated by a different browser, so it must never consult
    # that browser's current app.storage.user context while rebuilding this page.
    admin_session = {"enabled": bool(app.storage.user.get("is_admin"))}

    def current_user_is_admin() -> bool:
        return admin_session["enabled"]

    @ui.refreshable
    def render_application() -> None:
        section_id = selected_section["id"]
        state = load_section(section_id)
        admin = current_user_is_admin()

        with ui.column().classes("w-full max-w-7xl mx-auto p-3 md:p-6 gap-4"):
            with ui.row().classes("w-full items-center justify-between"):
                with ui.column().classes("gap-0"):
                    ui.label("Live Tournament Manager").classes("text-2xl font-bold")
                    ui.label("Six-team double-elimination tournament").classes("text-sm text-gray-500")
                with ui.row().classes("items-center gap-2"):
                    ui.badge("LIVE", color="positive")
                    if admin:
                        ui.badge("ADMIN MODE", color="primary")
                    else:
                        ui.badge("PUBLIC VIEW", color="grey")

            with ui.card().classes("w-full"):
                with ui.row().classes("w-full items-center justify-between"):
                    ui.label("Tournament Section").classes("font-semibold")
                    ui.select(
                        options=SECTION_LABELS,
                        value=section_id,
                        on_change=lambda event: change_section(event.value),
                    ).classes("w-48")

                if admin:
                    team_name_inputs = {}
                    with ui.expansion("Team setup and registration", icon="groups", value=True).classes("w-full"):
                        ui.label("Edit all six names, then save them together. Logo uploads are saved immediately.").classes("text-sm text-gray-500")
                        for team in sorted(state["teams"], key=lambda item: item["seed"]):
                            with ui.row().classes("w-full items-center gap-2"):
                                ui.label(f"Seed {team['seed']}").classes("w-16 text-sm")
                                name_input = ui.input(
                                    value=team["name"],
                                    placeholder="Team name",
                                ).classes("flex-grow")
                                team_name_inputs[team["id"]] = name_input
                                if team.get("logo"):
                                    ui.image(team["logo"]).classes("w-10 h-10 object-contain")
                                ui.upload(
                                    label="Logo",
                                    auto_upload=True,
                                    on_upload=lambda e, tid=team["id"]: upload_logo(
                                        section_id, tid, e
                                    ),
                                ).props("accept=.png,.jpg,.jpeg,.webp max-files=1").classes("max-w-36")

                        def save_team_setup() -> None:
                            if not current_user_is_admin():
                                return
                            latest = load_section(section_id)
                            for tid, field in team_name_inputs.items():
                                team_record = team_by_id(latest, tid)
                                if team_record and field.value and field.value.strip():
                                    team_record["name"] = field.value.strip()
                            save_section(section_id, latest)
                            broadcast_update()
                            ui.notify("Team names saved.", type="positive")

                        ui.button("Save team names", icon="save", on_click=save_team_setup).props("color=primary")


            if not admin:
                with ui.row().classes("w-full items-center justify-between"):
                    ui.label("Tournament bracket").classes("text-xl font-bold")
                    ui.label("Results update automatically across connected devices").classes("text-xs text-gray-500")

            render_match_groups(section_id, state, admin)
            render_up_next_panel(state)

            if state.get("champion_id"):
                champion = team_by_id(state, state["champion_id"])
                with ui.card().classes("w-full bg-green-50 border border-green-200"):
                    ui.label("TOURNAMENT CHAMPION").classes("text-sm font-bold text-green-800")
                    ui.label(champion["name"] if champion else "Champion").classes("text-2xl font-bold text-green-900")

            if admin:
                with ui.card().classes("w-full"):
                    ui.label("Export tournament results").classes("font-semibold")
                    ui.label("Exports use the saved Supabase bracket data and do not modify it.").classes("text-sm text-gray-500")
                    with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                        ui.button("This section · Excel", icon="table_view", on_click=lambda sid=section_id: export_current_excel(sid))
                        ui.button("This section · CSV", icon="description", on_click=lambda sid=section_id: export_current_csv(sid)).props("outline")
                        ui.button("All 7 sections · Excel", icon="library_books", on_click=export_all_excel)
                        ui.button("All 7 sections · CSV", icon="download", on_click=export_all_csv).props("outline")

                with ui.row().classes("w-full justify-end"):
                    ui.button(
                        "Reset this section",
                        icon="restart_alt",
                        color="negative",
                        on_click=lambda: confirm_reset(section_id),
                    ).props("outline")

    def render_up_next_panel(state: dict[str, Any]) -> None:
        """Show the next two ready matches in a persistent bottom-right overlay."""
        upcoming = next_ready_matches(state, limit=2)
        with ui.card().style(
            "position: fixed; right: 18px; bottom: 18px; z-index: 1000; "
            "width: 310px; max-width: calc(100vw - 36px); "
            "box-shadow: 0 8px 28px rgba(15, 23, 42, 0.20); "
            "border: 1px solid #bfdbfe; border-radius: 14px;"
        ).classes("bg-white"):
            with ui.row().classes("w-full items-center justify-between"):
                ui.label("UP NEXT").classes("text-sm font-extrabold tracking-wider text-blue-800")
                ui.icon("schedule", color="primary").classes("text-lg")
            if upcoming:
                for index, (key, team_a_id, team_b_id) in enumerate(upcoming):
                    if index == 1:
                        ui.separator().classes("my-1")
                    heading = "UP NEXT" if index == 0 else "ON DECK"
                    with ui.column().classes("w-full gap-1"):
                        ui.label(f"{heading} · {MATCH_TITLES[key]}").classes(
                            "text-xs font-bold text-gray-500 tracking-wide"
                        )
                        ui.label(team_label(state, team_a_id)).classes(
                            "text-sm font-semibold text-gray-900 leading-tight"
                        )
                        ui.label("vs.").classes("text-xs text-gray-400")
                        ui.label(team_label(state, team_b_id)).classes(
                            "text-sm font-semibold text-gray-900 leading-tight"
                        )
            elif state.get("champion_id"):
                champion = team_by_id(state, state["champion_id"])
                ui.label("Tournament complete").classes("font-semibold text-green-700")
                ui.label(champion["name"] if champion else "Champion determined").classes(
                    "text-sm text-gray-700"
                )
            else:
                ui.label("Waiting for previous match results.").classes(
                    "text-sm text-gray-600"
                )

    def export_current_csv(section_id: str) -> None:
        if not current_user_is_admin():
            ui.notify("Administrator access is required to export results.", type="negative")
            return
        state = load_section(section_id)
        payload = make_csv_export([(section_id, state)])
        ui.download(payload, f"{section_id}_tournament_results.csv")

    def export_current_excel(section_id: str) -> None:
        if not current_user_is_admin():
            ui.notify("Administrator access is required to export results.", type="negative")
            return
        state = load_section(section_id)
        payload = make_excel_export([(section_id, state)])
        ui.download(payload, f"{section_id}_tournament_results.xlsx")

    def export_all_csv() -> None:
        if not current_user_is_admin():
            ui.notify("Administrator access is required to export results.", type="negative")
            return
        states = [(sid, load_section(sid)) for sid in SECTION_IDS]
        payload = make_csv_export(states)
        ui.download(payload, "all_sections_tournament_results.csv")

    def export_all_excel() -> None:
        if not current_user_is_admin():
            ui.notify("Administrator access is required to export results.", type="negative")
            return
        states = [(sid, load_section(sid)) for sid in SECTION_IDS]
        payload = make_excel_export(states)
        ui.download(payload, "all_sections_tournament_results.xlsx")

    def change_section(section_id: str) -> None:
        selected_section["id"] = section_id
        render_application.refresh()

    def update_team_name(section_id: str, team_id: str, name: str) -> None:
        if not current_user_is_admin():
            return
        state = load_section(section_id)
        team = team_by_id(state, team_id)
        if team and name.strip():
            team["name"] = name.strip()
            save_section(section_id, state)
            broadcast_update(exclude=refresh_self)

    async def upload_logo(section_id: str, team_id: str, event) -> None:
        if not current_user_is_admin():
            return
        filename = Path(event.file.name).name
        suffix = Path(filename).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            ui.notify("Unsupported logo format.", type="negative")
            return
        content = await event.file.read()
        if len(content) > 2 * 1024 * 1024:
            ui.notify("Logo files must be 2 MB or smaller.", type="negative")
            return

        content_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }
        content_type = content_types[suffix]
        # A unique path avoids stale CDN-cached images when a logo is replaced.
        object_path = f"{section_id}/{team_id}/{uuid.uuid4().hex}{suffix}"
        supabase.storage.from_(SUPABASE_BUCKET).upload(
            object_path,
            content,
            {"content-type": content_type, "cache-control": "3600"},
        )
        public_url = supabase.storage.from_(SUPABASE_BUCKET).get_public_url(object_path)

        state = load_section(section_id)
        team = team_by_id(state, team_id)
        if team:
            team["logo"] = public_url
            save_section(section_id, state)
        broadcast_update()
        ui.notify("Team logo uploaded.", type="positive")

    def confirm_reset(section_id: str) -> None:
        with ui.dialog() as dialog, ui.card():
            ui.label(f"Reset all matches and scores for {SECTION_LABELS[section_id]}?")
            ui.label("Team names and logos will be preserved.").classes("text-sm text-gray-500")
            with ui.row().classes("justify-end"):
                ui.button("Cancel", on_click=dialog.close).props("flat")
                ui.button(
                    "Reset tournament",
                    color="negative",
                    on_click=lambda: do_reset(section_id, dialog),
                )
        dialog.open()

    def do_reset(section_id: str, dialog) -> None:
        state = load_section(section_id)
        state["results"] = {}
        state["champion_id"] = None
        save_section(section_id, state)
        dialog.close()
        broadcast_update()


    def render_bracket_svg(state: dict[str, Any]) -> str:
        """Responsive, connected bracket diagram following the supplied concept."""
        width, height = 1320, 900
        card_w, card_h = 190, 86
        positions = {
            "M1": (55, 105), "M2": (55, 285),
            "M3": (315, 105), "M4": (315, 285),
            "M5": (575, 195),
            "LB1": (55, 535), "LB2": (55, 725),
            "LB3": (315, 630), "LB4": (575, 535),
            "GF": (845, 365), "RESET": (1100, 365),
        }
        titles = {key: title for key, title, _ in MATCHES}
        svg = [
            f'<div style="width:100%;overflow-x:auto;background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:12px">',
            f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Six-team double elimination bracket" style="display:block;width:100%;min-width:900px;height:auto;font-family:Arial,sans-serif">',
            '<defs><style>.connector{fill:none;stroke:#64748b;stroke-width:2.5;stroke-linecap:round;stroke-linejoin:round}.dash{stroke-dasharray:9 8}.coltitle{font-size:17px;font-weight:700;fill:#334155;letter-spacing:1px}.matchbox{fill:#fff;stroke:#94a3b8;stroke-width:1.5}.matchtitle{font-size:14px;font-weight:700;fill:#475569}.teamname{font-size:14px;fill:#0f172a}.score{font-size:15px;font-weight:700;fill:#0f172a}.winner{font-weight:700;fill:#047857}.muted{fill:#94a3b8}</style></defs>',
            '<text x="55" y="35" class="coltitle">WINNERS BRACKET</text><text x="55" y="475" class="coltitle">LOSERS BRACKET</text><text x="845" y="315" class="coltitle">CHAMPIONSHIP</text>',
        ]
        # Orthogonal connectors, matching the supplied bracket's flow.
        def path_between(src, dst, dashed=False):
            sx, sy = positions[src]; dx, dy = positions[dst]
            x1, y1 = sx + card_w, sy + card_h / 2
            x2, y2 = dx, dy + card_h / 2
            mid = (x1 + x2) / 2
            cls = "connector dash" if dashed else "connector"
            return f'<path class="{cls}" d="M{x1},{y1} H{mid} V{y2} H{x2}"/>'
        for src, dst in [
            ("M1","M3"), ("M2","M4"), ("M3","M5"), ("M4","M5"),
            ("M1","LB1"), ("M2","LB1"), ("M3","LB2"), ("M4","LB2"),
            ("LB1","LB3"), ("LB2","LB3"), ("LB3","LB4"), ("M5","LB4"),
            ("M5","GF"), ("LB4","GF")
        ]:
            svg.append(path_between(src, dst))
        svg.append(path_between("GF", "RESET", True))

        def short_label(team_id):
            team = team_by_id(state, team_id)
            if not team:
                return "TBD"
            return f"#{team['seed']} {team['name']}"

        def match_box(key):
            x, y = positions[key]
            a, b = participants(state, key)
            result = state["results"].get(key, {})
            reset_active = False
            if key == "RESET":
                gf_winner = result_winner(state, "GF")
                lb_finalist = participants(state, "GF")[1]
                reset_active = bool(gf_winner and gf_winner == lb_finalist)
            label = titles[key]
            if key == "GF":
                label = "MATCH 6 · GRAND FINAL"
            if key == "RESET":
                label = "L6 OPTION · RESET"
            if key == "RESET" and not reset_active:
                return (
                    f'<g><rect x="{x}" y="{y}" width="{card_w}" height="{card_h}" rx="9" '
                    f'fill="#fff" stroke="#64748b" stroke-width="2" stroke-dasharray="8 6"/>'
                    f'<text class="matchtitle" x="{x+11}" y="{y+25}">L6 OPTION · RESET</text>'
                    f'<text x="{x+11}" y="{y+51}" font-size="13" fill="#64748b">If lower finalist wins Match 6</text></g>'
                )
            rows = []
            for idx, (team_id, score_key) in enumerate(((a, "score_a"), (b, "score_b"))):
                team = team_by_id(state, team_id)
                name = html.escape(short_label(team_id))
                score = result.get(score_key, "")
                is_winner = bool(team_id and result.get("winner_id") == team_id)
                cls = "teamname winner" if is_winner else "teamname"
                if team and team.get("logo"):
                    logo = html.escape(team["logo"], quote=True)
                    rows.append(f'<image href="{logo}" x="{x+9}" y="{y+29+idx*25}" width="19" height="19" preserveAspectRatio="xMidYMid meet"/>')
                    tx = x + 34
                else:
                    tx = x + 12
                rows.append(f'<text class="{cls}" x="{tx}" y="{y+44+idx*25}">{name[:22]}</text>')
                rows.append(f'<text class="score" text-anchor="end" x="{x+card_w-12}" y="{y+44+idx*25}">{html.escape(str(score))}</text>')
                if is_winner:
                    rows.append(f'<text x="{x+card_w-29}" y="{y+44+idx*25}" font-size="12" fill="#059669">★</text>')
            return (
                f'<g><rect class="matchbox" x="{x}" y="{y}" width="{card_w}" height="{card_h}" rx="9"/>'
                f'<text class="matchtitle" x="{x+11}" y="{y+19}">{html.escape(label)}</text>'
                + "".join(rows) + '</g>'
            )
        for key in positions:
            svg.append(match_box(key))
        # Conditional reset annotation and dashed destination.
        svg.append('<text x="1095" y="485" font-size="16" fill="#64748b">Only if lower-bracket</text><text x="1095" y="506" font-size="16" fill="#64748b">finalist wins Match 6</text>')
        svg.append('<path class="connector dash" d="M1290,408 H1310"/>')
        svg.append('</svg></div>')
        return "".join(svg)

    def render_match_groups(section_id: str, state: dict, admin: bool) -> None:
        ui.html(render_bracket_svg(state), sanitize=False).classes("w-full")
        if admin:
            with ui.expansion("Match controls — enter scores and correct results", icon="edit").classes("w-full"):
                ui.label("Saving a result recalculates later matches. Correcting an earlier result clears affected downstream results.").classes("text-sm text-gray-500")
                groups = [
                    ("Winners bracket", ["M1", "M2", "M3", "M4", "M5"]),
                    ("Losers bracket", ["LB1", "LB2", "LB3", "LB4"]),
                    ("Championship", ["GF", "RESET"]),
                ]
                for group_name, keys in groups:
                    ui.label(group_name).classes("font-bold text-base mt-3")
                    with ui.grid(columns=1).classes("w-full md:grid-cols-2 xl:grid-cols-3 gap-3"):
                        for key in keys:
                            render_match_card(section_id, state, key, admin)

    def render_match_card(section_id: str, state: dict, key: str, admin: bool) -> None:
        a, b = participants(state, key)
        result = state["results"].get(key, {})
        status = match_status(state, key)
        if key == "RESET":
            gf_winner = result_winner(state, "GF")
            lb_finalist = participants(state, "GF")[1]
            if not gf_winner or gf_winner != lb_finalist:
                return

        with ui.card().classes("w-full border"):
            with ui.row().classes("w-full items-center justify-between"):
                ui.label(dict((k, title) for k, title, _ in MATCHES)[key]).classes("font-semibold")
                ui.badge(status, color="positive" if status == "Complete" else "warning" if status == "Ready to play" else "grey")

            for team_id, score_key in ((a, "score_a"), (b, "score_b")):
                team = team_by_id(state, team_id)
                with ui.row().classes("w-full items-center gap-2"):
                    if team and team.get("logo"):
                        ui.image(team["logo"]).classes("w-8 h-8 object-contain")
                    ui.label(team_label(state, team_id)).classes("flex-grow text-sm")
                    if result.get("winner_id") == team_id:
                        ui.icon("emoji_events", color="positive")
                    if result and score_key in result:
                        ui.label(str(result[score_key])).classes("font-bold min-w-6 text-right")

            if admin and a and b:
                with ui.expansion("Enter / edit result", icon="edit").classes("w-full"):
                    score_a = ui.number("Score — " + team_label(state, a), value=result.get("score_a"), min=0, step=1).classes("w-full")
                    score_b = ui.number("Score — " + team_label(state, b), value=result.get("score_b"), min=0, step=1).classes("w-full")
                    winner_options = {
                        a: team_label(state, a),
                        b: team_label(state, b),
                    }
                    override = ui.select(
                        winner_options,
                        label="Winner override (optional)",
                        value=result.get("winner_id"),
                    ).classes("w-full")
                    ui.label("Leave winner override blank to use the higher score.").classes("text-xs text-gray-500")

                    def save_clicked(
                        match_key=key,
                        sa=score_a,
                        sb=score_b,
                        ov=override,
                    ) -> None:
                        try:
                            save_match_result(
                                section_id,
                                match_key,
                                int(sa.value) if sa.value is not None else None,
                                int(sb.value) if sb.value is not None else None,
                                ov.value,
                            )
                            broadcast_update()
                            ui.notify("Match result saved and bracket updated.", type="positive")
                        except (ValueError, TypeError) as error:
                            ui.notify(str(error), type="negative")

                    with ui.row().classes("w-full justify-end"):
                        if result:
                            ui.button(
                                "Clear result",
                                color="negative",
                                on_click=lambda match_key=key: clear_and_refresh(section_id, match_key),
                            ).props("flat")
                        ui.button("Save result", icon="save", on_click=save_clicked)

    def clear_and_refresh(section_id: str, key: str) -> None:
        clear_match(section_id, key)
        broadcast_update()

    # Public header / administrator sign-in
    with ui.column().classes("w-full"):
        with ui.row().classes("w-full justify-end p-3"):
            if current_user_is_admin():
                ui.button(
                    "Log out",
                    icon="logout",
                    on_click=lambda: logout(),
                ).props("flat")
            else:
                with ui.dialog() as login_dialog, ui.card().classes("w-80"):
                    ui.label("TA Administrator Login").classes("text-lg font-bold")
                    password = ui.input("Administrator password", password=True, password_toggle_button=True).classes("w-full")

                    def attempt_login() -> None:
                        if ADMIN_PASSWORD and password.value == ADMIN_PASSWORD:
                            app.storage.user["is_admin"] = True
                            admin_session["enabled"] = True
                            login_dialog.close()
                            render_application.refresh()
                            ui.notify("Administrator access enabled.", type="positive")
                        elif not ADMIN_PASSWORD:
                            ui.notify("Set the ADMIN_PASSWORD environment variable before enabling TA login.", type="negative")
                        else:
                            ui.notify("Incorrect password.", type="negative")

                    ui.button("Sign in", on_click=attempt_login).classes("w-full")
                ui.button("TA Login", icon="lock", on_click=login_dialog.open).props("flat")

    def logout() -> None:
        app.storage.user["is_admin"] = False
        admin_session["enabled"] = False
        render_application.refresh()

    refresh_self = render_application.refresh
    render_application()
    refresh_callbacks.add(refresh_self)
    client.on_disconnect(lambda: refresh_callbacks.discard(refresh_self))


ui.run(
    host="0.0.0.0",
    port=PORT,
    title="Live Tournament Manager",
    storage_secret=STORAGE_SECRET,
    reload=False,
)
