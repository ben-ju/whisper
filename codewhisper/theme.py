"""Colour tokens and the Qt stylesheet for the settings window."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

from .config import DATA_DIR

LIGHT = {
    "bg": "#F4F5F7", "sidebar": "#ECEEF1", "surface": "#FFFFFF", "field": "#FFFFFF",
    "ink": "#17191E", "muted": "#666C7A", "faint": "#9AA0AC",
    "line": "#E2E4E9", "line_strong": "#C9CDD5", "hover": "#E3E6EA",
    "accent": "#5546D6", "accent_ink": "#FFFFFF", "accent_soft": "#ECEAFC",
    "ok": "#1F9D5C", "warn": "#C7801A", "bad": "#D9434A",
    "key_top": "#FFFFFF", "key_side": "#D3D6DD", "key_ink": "#2A2D35",
    "scroll": "#CDD1D8",
}

DARK = {
    "bg": "#121317", "sidebar": "#17181D", "surface": "#1D1F25", "field": "#16171C",
    "ink": "#ECEDF0", "muted": "#9AA0AD", "faint": "#6A707C",
    "line": "#2B2E36", "line_strong": "#3B3F49", "hover": "#24262D",
    "accent": "#9A8FFF", "accent_ink": "#14121F", "accent_soft": "#272441",
    "ok": "#4CD08A", "warn": "#F0B44C", "bad": "#FF6B70",
    "key_top": "#2A2D35", "key_side": "#0E0F12", "key_ink": "#E6E7EB",
    "scroll": "#353944",
}


def is_dark(pref: str) -> bool:
    if pref == "dark":
        return True
    if pref == "light":
        return False
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception:
        return False


def tokens(pref: str) -> dict:
    return DARK if is_dark(pref) else LIGHT


def _chevron(color: str) -> str:
    path = DATA_DIR / "ui" / f"chevron-{color.strip('#')}.svg"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 12 12">'
            f'<path d="M3 4.5 6 7.5 9 4.5" fill="none" stroke="{color}" stroke-width="1.5" '
            f'stroke-linecap="round" stroke-linejoin="round"/></svg>', encoding="utf-8")
    return path.as_posix()


def stylesheet(t: dict) -> str:
    chevron = _chevron(t["muted"])
    return f"""
* {{ font-family: "Segoe UI Variable Text", "Segoe UI", "Inter", sans-serif; font-size: 10pt; }}
QWidget {{ color: {t['ink']}; }}
QMainWindow, #Root {{ background: {t['bg']}; }}
#Sidebar {{ background: {t['sidebar']}; border-right: 1px solid {t['line']}; }}
#Brand {{ font-family: "Segoe UI Variable Display", "Segoe UI"; font-size: 12pt; font-weight: 600; }}
#NavButton {{ text-align: left; padding: 8px 12px; border: none; border-radius: 8px;
              background: transparent; color: {t['muted']}; font-size: 10pt; }}
#NavButton:hover {{ background: {t['hover']}; color: {t['ink']}; }}
#NavButton:checked {{ background: {t['surface']}; color: {t['ink']}; font-weight: 600;
                      border: 1px solid {t['line']}; }}
#SideStatus {{ color: {t['muted']}; font-size: 9pt; }}

QScrollArea, #Page {{ background: {t['bg']}; border: none; }}
#H1 {{ font-family: "Segoe UI Variable Display", "Segoe UI"; font-size: 21pt; font-weight: 600; }}
#Lead {{ color: {t['muted']}; font-size: 10.5pt; }}
#H2 {{ font-family: "Segoe UI Variable Display", "Segoe UI"; font-size: 12.5pt; font-weight: 600; }}
#Muted {{ color: {t['muted']}; }}
#Small {{ color: {t['muted']}; font-size: 9pt; }}
#RowTitle {{ font-weight: 600; }}
#Figure {{ font-family: "Segoe UI Variable Display", "Segoe UI"; font-size: 22pt; font-weight: 600; }}
#Ok {{ color: {t['ok']}; }} #Warn {{ color: {t['warn']}; }} #Bad {{ color: {t['bad']}; }}
#Link {{ color: {t['accent']}; }}

#Panel {{ background: {t['surface']}; border: 1px solid {t['line']}; border-radius: 12px; }}
#Panel > QWidget#Row {{ background: transparent; }}
#Divider {{ background: {t['line']}; max-height: 1px; min-height: 1px; border: none; }}

QPushButton {{ background: {t['surface']}; border: 1px solid {t['line_strong']}; border-radius: 8px;
               padding: 6px 14px; }}
QPushButton:hover {{ background: {t['hover']}; }}
QPushButton:pressed {{ background: {t['line']}; }}
QPushButton:disabled {{ color: {t['faint']}; border-color: {t['line']}; }}
QPushButton#Primary {{ background: {t['accent']}; color: {t['accent_ink']}; border: none; font-weight: 600; }}
QPushButton#Primary:hover {{ background: {t['accent']}; }}
QPushButton#Ghost {{ background: transparent; border: none; color: {t['muted']}; padding: 4px 8px; }}
QPushButton#Ghost:hover {{ color: {t['ink']}; background: {t['hover']}; }}
QPushButton#Danger {{ color: {t['bad']}; }}

#Segmented {{ background: {t['sidebar']}; border: 1px solid {t['line']}; border-radius: 10px; }}
#Segment {{ background: transparent; border: none; border-radius: 7px; padding: 6px 14px; color: {t['muted']}; }}
#Segment:hover {{ color: {t['ink']}; }}
#Segment:checked {{ background: {t['surface']}; color: {t['ink']}; border: 1px solid {t['line']}; }}

QLineEdit, QComboBox, QPlainTextEdit, QSpinBox {{
    background: {t['field']}; border: 1px solid {t['line_strong']}; border-radius: 8px;
    padding: 6px 9px; selection-background-color: {t['accent']}; selection-color: {t['accent_ink']}; }}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QSpinBox:focus {{ border: 1px solid {t['accent']}; }}
QComboBox {{ padding-right: 26px; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url("{chevron}"); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: {t['surface']}; border: 1px solid {t['line']};
    selection-background-color: {t['accent_soft']}; selection-color: {t['ink']}; padding: 4px; outline: 0; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 0; border: none; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t['scroll']}; border-radius: 3px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QToolTip {{ background: {t['surface']}; color: {t['ink']}; border: 1px solid {t['line']}; padding: 4px 6px; }}
QMenu {{ background: {t['surface']}; border: 1px solid {t['line']}; padding: 4px; border-radius: 8px; }}
QMenu::item {{ padding: 6px 22px 6px 22px; border-radius: 6px; }}
QMenu::item:selected {{ background: {t['accent_soft']}; color: {t['ink']}; }}
QMenu::item:disabled {{ color: {t['faint']}; }}
QMenu::separator {{ height: 1px; background: {t['line']}; margin: 4px 8px; }}
"""
