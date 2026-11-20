# -*- coding: utf-8 -*-
"""
Created on Fri Nov 20 15:02:19 2026

@author: mittr
"""

from nicegui import Client, ui

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

    # Push update to EVERY connected computer
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

 refresh_callbacks.add(render_bracket.refresh)
    client.on_disconnect(lambda: refresh_callbacks.discard(render_bracket.refresh))

    render_bracket()
# Main Page Layout
ui.label("Live Tournament Bracket").classes("text-2xl font-bold px-6 pt-6")
render_bracket()
ui.button("Reset Bracket", on_click=reset_bracket, color="red").classes("mx-6")

# Run on port 8080 (standard for cloud hosting)
ui.run(host="0.0.0.0", port=8080)
