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


def build_remote_sections(entities):
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
            "entity": remote,
            "name": name,
            "icon": "mdi:" + icon,
            "show_state": False,
            "tap_action": action("remote.send_command", remote, command=command, num_repeats=1),
            "hold_action": {"action": "none"},
        }
        return button

    def grid(buttons, columns=3):
        return {"type": "grid", "columns": columns, "square": False, "cards": buttons}

    cards = []
    if entities.get("media_player"):
        cards.append({"type": "media-control", "entity": entities["media_player"]})
    cards.append(
        grid(
            [
                {
                    "type": "button",
                    "entity": remote,
                    "show_state": False,
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
                "type": "entities",
                "show_header_toggle": False,
                "entities": [{"entity": entities["audio_only_mode"], "name": "Только звук"}],
            }
        )
    elif screen_buttons:
        cards.append(grid(screen_buttons, 2))
    if entities.get("input"):
        cards.append({
            "type": "entities",
            "show_header_toggle": False,
            "entities": [{"entity": entities["input"], "name": "Источник"}],
        })
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
                    ("Перемотка назад", "rewind", "rewind"),
                    ("Пуск", "play", "play"),
                    ("Вперёд", "fast_forward", "fast-forward"),
                    ("Пауза", "pause", "pause"),
                    ("Стоп", "stop", "stop"),
                    ("Субтитры", "subtitle", "subtitles-outline"),
                ]
            ]
        )
    )
    sections = {"main": {"type": "vertical-stack", "title": "Пульт", "cards": cards}}
    rows = [
        entities[k]
        for k in ("picture_mode", "backlight", "motion_smoothing", "local_dimming", "game_mode")
        if entities.get(k)
    ]
    if rows:
        sections["picture"] = {
            "type": "entities", "title": "Изображение", "show_header_toggle": False, "entities": rows
        }
    # Keep zero centered without entity-less placeholder buttons.
    digits = grid([key(str(n), str(n), "numeric-" + str(n)) for n in range(1, 10)])
    zero = grid([key("0", "0", "numeric-0")], 1)
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
    sections["keypad"] = {
        "type": "vertical-stack", "title": "Цифры и цветные кнопки", "cards": [digits, zero, grid(colors, 4)]
    }
    return sections


def build_remote_card(entities):
    """A single native card; each section can also be added independently."""
    return {"type": "vertical-stack", "cards": list(build_remote_sections(entities).values())}
