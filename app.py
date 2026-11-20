import os
from nicegui import Client, ui

# Shared state in server memory (visible to all connected computers)
bracket = {
    "sf1": ["Team A", "Team B"],
    "sf2": ["Team C", "Team D"],
    "finals": ["TBD", "TBD"],
    "champion": "TBD",
}

# Store all active refreshable UI callbacks across connected browsers
refresh_callbacks = set()


def broadcast_update():
    for callback in list(refresh_callbacks):
        callback()


def advance_team(match_key: str, slot_index: int, team_name: str):
    if team_name == "TBD":
        return

    if match_key == "finals":
        bracket["finals"][slot_index] = team_name
    elif match_key == "champion":
        bracket["champion"] = team_name

    # Immediately push the updated UI to all connected computers
    broadcast_update()


def reset_bracket():
    bracket["finals"] = ["TBD", "TBD"]
    bracket["champion"] = "TBD"
    broadcast_update()


@ui.page("/")
def main_page(client: Client):
    @ui.refreshable
    def render_bracket():
        with ui.row().classes("gap-12 items-center p-6"):
            # Round 1: Semifinals
            with ui.column().classes("gap-8"):
                ui.label("Semifinals").classes("text-lg font-bold")

                # Match 1
                with ui.card().classes("w-48"):
                    for team in bracket["sf1"]:
                        ui.button(
                            team,
                            on_click=lambda t=team: advance_team("finals", 0, t),
                        ).classes("w-full")

                # Match 2
                with ui.card().classes("w-48"):
                    for team in bracket["sf2"]:
                        ui.button(
                            team,
                            on_click=lambda t=team: advance_team("finals", 1, t),
                        ).classes("w-full")

            # Round 2: Finals
            with ui.column().classes("gap-4"):
                ui.label("Finals").classes("text-lg font-bold")
                with ui.card().classes("w-48"):
                    for team in bracket["finals"]:
                        ui.button(
                            team,
                            on_click=lambda t=team: advance_team("champion", 0, t),
                        ).classes("w-full")

            # Champion Display
            with ui.column().classes("gap-4"):
                ui.label("Champion").classes("text-lg font-bold text-green-600")
                with ui.card().classes("w-48 bg-green-50 items-center"):
                    ui.label(bracket["champion"]).classes("text-xl font-bold")

    # Register this browser tab for global updates and remove it on disconnect
    refresh_callbacks.add(render_bracket.refresh)
    client.on_disconnect(lambda: refresh_callbacks.discard(render_bracket.refresh))

    # Main Page Layout
    ui.label("Live Tournament Bracket").classes("text-2xl font-bold px-6 pt-6")
    render_bracket()
    ui.button("Reset Bracket", on_click=reset_bracket, color="red").classes("mx-6")


# Bind to Render's assigned PORT (defaults to 8080 locally)
port = int(os.environ.get("PORT", 8080))
ui.run(host="0.0.0.0", port=port)
