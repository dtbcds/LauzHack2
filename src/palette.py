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
AMBER_BG = "#40342A"

SMALL = 8
MEDIUM = 16
LARGE = 24
GUTTER = 32

MENU_STYLE = dict(
    bgcolor=SURFACE,
    elevation=4,
    shadow_color="#55000000",
    menu_position=ft.PopupMenuPosition.UNDER,
    menu_padding=ft.Padding.symmetric(vertical=4, horizontal=4),
    shape=ft.RoundedRectangleBorder(radius=6, side=ft.BorderSide(1, DIVIDER)),
)


def menu_item(label, value, selected, on_click):
    return ft.PopupMenuItem(
        content=label,
        data=value,
        checked=selected,
        height=32,
        padding=ft.Padding.symmetric(horizontal=SMALL),
        label_text_style=ft.TextStyle(size=13, color=TEXT, weight=ft.FontWeight.W_400),
        on_click=on_click,
    )


def tag(value: str, *, highlighted: bool = False) -> ft.Container:
    return ft.Container(
        ft.Text(value, size=12, color=AMBER if highlighted else MUTED),
        bgcolor=AMBER_BG if highlighted else CONTROL,
        border_radius=4,
        padding=ft.Padding.symmetric(vertical=3, horizontal=SMALL),
    )
