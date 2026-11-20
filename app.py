            ("Championship", ["GF", "RESET"]),
        ]
        for group_name, keys in groups:
            with ui.card().classes("w-full"):
                ui.label(group_name).classes("text-lg font-bold")
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
            if is_admin(client):
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
        render_application.refresh()

    render_application()
    refresh_callbacks.add(render_application.refresh)
    client.on_disconnect(lambda: refresh_callbacks.discard(render_application.refresh))


# Serve uploaded logos.
app.add_static_files("/logos", str(LOGO_DIR))

ui.run(
    host="0.0.0.0",
    port=PORT,
    title="Live Tournament Manager",
    storage_secret=STORAGE_SECRET,
    reload=False,
