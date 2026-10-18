"""Native Lovelace remote layout, generated with the installed entity IDs."""

REMOTE_COMMANDS = (
    "up",
    "down",
    "left",
    "right",
    "ok",
    "back",
    "home",
    "menu",
    "exit",
    "volume_up",
    "volume_down",
    "mute",
    "play",
    "pause",
    "stop",
    "rewind",
    "fast_forward",
    "red",
    "green",
    "yellow",
    "blue",
    "subtitle",
    *map(str, range(10)),
)


def build_remote_card(entities):
    """No third-party cards, guessed entity IDs, input cycling or power toggles."""
    remote = entities["remote"]

    def action(service, entity, **data):
        return {
            "action": "perform-action",
            "perform_action": service,
            "target": {"entity_id": entity},
            **({"data": data} if data else {}),
        }

    def key(name, command, icon):
        button = {
            "type": "button",
            "name": name,
            "icon": "mdi:" + icon,
            "show_state": False,
            "tap_action": action("remote.send_command", remote, command=command, num_repeats=1),
            "hold_action": {"action": "none"},
        }
        return button

    def grid(buttons, columns=3):
        return {"type": "grid", "columns": columns, "square": False, "cards": buttons}

    cards = [{"type": "markdown", "content": "## Hisense U7QF"}]
    if entities.get("media_player"):
        cards.append({"type": "media-control", "entity": entities["media_player"]})
    cards.append(
        grid(
            [
                {
                    "type": "button",
                    "name": name,
                    "icon": icon,
                    "tap_action": action(service, remote),
                    "hold_action": {"action": "none"},
                }
                for name, icon, service in [
                    ("Включить", "mdi:power", "remote.turn_on"),
                    ("Выключить", "mdi:power-standby", "remote.turn_off"),
                ]
            ],
            2,
        )
    )
    screen_buttons = [
        {
            "type": "button",
            "name": name,
            "icon": icon,
            "entity": entities[suffix],
            "show_state": False,
            "tap_action": action("button.press", entities[suffix]),
            "hold_action": {"action": "none"},
        }
        for suffix, name, icon in [
            ("screen_off", "Выключить экран", "mdi:television-off"),
            ("screen_on", "Включить экран", "mdi:television"),
        ]
        if entities.get(suffix)
    ]
    if entities.get("audio_only_mode"):
        cards.append(
            {
                "type": "button",
                "name": "Только звук",
                "icon": "mdi:television-off",
                "entity": entities["audio_only_mode"],
                "show_state": True,
                "tap_action": {"action": "toggle"},
                "hold_action": {"action": "none"},
            }
        )
    elif screen_buttons:
        cards.append(grid(screen_buttons, 2))
    cards.append(
        grid(
            [
                key(*args)
                for args in [
                    ("Меню", "menu", "menu"),
                    ("Вверх", "up", "chevron-up"),
                    ("Главная", "home", "home-outline"),
                    ("Влево", "left", "chevron-left"),
                    ("OK", "ok", "circle-outline"),
                    ("Вправо", "right", "chevron-right"),
                    ("Назад", "back", "keyboard-return"),
                    ("Вниз", "down", "chevron-down"),
                    ("Выход", "exit", "exit-to-app"),
                ]
            ]
        )
    )
    cards.append(
        grid(
            [
                key(*args)
                for args in [
                    ("Тише", "volume_down", "volume-minus"),
                    ("Без звука", "mute", "volume-mute"),
                    ("Громче", "volume_up", "volume-plus"),
                    ("Назад", "rewind", "rewind"),
                    ("Пуск", "play", "play"),
                    ("Вперёд", "fast_forward", "fast-forward"),
                    ("Пауза", "pause", "pause"),
                    ("Стоп", "stop", "stop"),
                    ("Субтитры", "subtitle", "subtitles-outline"),
                ]
            ]
        )
    )
    rows = [
        entities[k]
        for k in ("input", "picture_mode", "backlight", "motion_smoothing", "local_dimming", "game_mode")
        if entities.get(k)
    ]
    if rows:
        cards.append({"type": "entities", "title": "Вход и изображение", "show_header_toggle": False, "entities": rows})
    cards.append(grid([key(str(n), str(n), "numeric-" + str(n)) for n in (1, 2, 3, 4, 5, 6, 7, 8, 9, 0)]))
    colors = []
    for name, cmd, color in [
        ("Красная", "red", "#e53935"),
        ("Зелёная", "green", "#43a047"),
        ("Жёлтая", "yellow", "#fdd835"),
        ("Синяя", "blue", "#1e88e5"),
    ]:
        button = key(name, cmd, "circle")
        button["color"] = color
        colors.append(button)
    cards.append(grid(colors, 4))
    return {"type": "vertical-stack", "cards": cards}
