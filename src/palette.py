from collections.abc import Callable
from functools import partial

import flet as ft

BACKGROUND = "#1D1D1F"
SURFACE = "#242426"
CONTROL = "#2A2A2D"
SELECTED = "#30343B"
DIVIDER = "#363638"
TEXT = "#E5E4E2"
MUTED = "#A8A6A3"
ACCENT = "#92ACC8"
AMBER = "#D5BA91"
BOTTLENECK = "#D28B88"
BOTTLENECK_BG = "#412E30"

SMALL = 8
MEDIUM = 16
LARGE = 24
GUTTER = 32
CONTROL_HEIGHT = 38
PANE_TITLE = 28
SECTION_TITLE = 17
BODY_TEXT = 14
CONTROL_TEXT = 13
NOTE_TEXT = 12

INPUT_BORDER: dict[ft.ControlState, ft.InputBorder] = {
    ft.ControlState.DEFAULT: ft.OutlineInputBorder(
        side=ft.BorderSide(1, DIVIDER),
        border_radius=5,
    ),
    ft.ControlState.FOCUSED: ft.OutlineInputBorder(
        side=ft.BorderSide(2, ACCENT),
        border_radius=5,
    ),
}


def menu_item(
    label: str,
    value: str,
    selected: bool,
    on_click: Callable[[], None],
) -> ft.PopupMenuItem:
    return ft.PopupMenuItem(
        content=label,
        data=value,
        checked=selected,
        height=32,
        padding=ft.Padding.symmetric(horizontal=SMALL),
        label_text_style=ft.TextStyle(
            size=CONTROL_TEXT, color=TEXT, weight=ft.FontWeight.W_400
        ),
        on_click=on_click,
    )


def control_button_style() -> ft.ButtonStyle:
    return ft.ButtonStyle(
        bgcolor=CONTROL, color=TEXT, shape=ft.RoundedRectangleBorder(radius=6)
    )


def select_menu(
    label: str,
    choices: dict[str, str],
    on_change: Callable[[], None],
    *,
    value: str | None = None,
    expand: bool = False,
    height: int = CONTROL_HEIGHT,
    text_size: int = CONTROL_TEXT,
) -> tuple[ft.PopupMenuButton, Callable[[dict[str, str]], None]]:
    caption = ft.Text(size=text_size, color=TEXT)
    if expand:
        caption.expand = True
        caption.max_lines = 1
        caption.overflow = ft.TextOverflow.ELLIPSIS

    button = ft.PopupMenuButton(
        tooltip=label,
        padding=0,
        data=value,
        content=ft.Container(
            ft.Row(
                [caption, ft.Icon(ft.Icons.EXPAND_MORE, size=16, color=MUTED)],
                spacing=SMALL,
                tight=not expand,
            ),
            height=height,
            padding=ft.Padding.symmetric(horizontal=12),
            bgcolor=CONTROL,
            border=ft.Border.all(1, DIVIDER),
            border_radius=5,
        ),
        bgcolor=SURFACE,
        elevation=4,
        shadow_color="#55000000",
        menu_position=ft.PopupMenuPosition.UNDER,
        menu_padding=ft.Padding.symmetric(vertical=4, horizontal=4),
        shape=ft.RoundedRectangleBorder(radius=6, side=ft.BorderSide(1, DIVIDER)),
    )
    if expand:
        button.expand = True

    def choose(key: str):
        button.data = key
        caption.value = choices[key]
        caption.color = TEXT
        button.tooltip = f"{label} · {choices[key]}"

        for item in button.items:
            item.checked = item.data == key

        on_change()

    def replace_choices(new_choices: dict[str, str]):
        nonlocal choices

        choices = new_choices
        if button.data not in choices:
            button.data = value if value in choices else None

        caption.value = choices.get(button.data, label)
        caption.color = TEXT if button.data is not None else MUTED
        button.tooltip = (
            f"{label} · {caption.value}" if button.data is not None else label
        )
        button.items = [
            menu_item(text, key, key == button.data, partial(choose, key))
            for key, text in choices.items()
        ]

    replace_choices(choices)

    return button, replace_choices


def tag(value: str, *, highlighted: bool = False) -> ft.Container:
    return ft.Container(
        ft.Text(value, size=12, color=BOTTLENECK if highlighted else MUTED),
        bgcolor=BOTTLENECK_BG if highlighted else CONTROL,
        border_radius=4,
        padding=ft.Padding.symmetric(vertical=3, horizontal=SMALL),
    )
