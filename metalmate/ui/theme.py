"""MetalMate design system: colours, type and the app stylesheet. Dark, quiet, one mint accent."""
from PySide6.QtGui import QColor, QFont, QPalette

BG = "#0b0c0f"          # window
SIDEBAR = "#0e1014"
SURFACE = "#13151a"     # cards
SURFACE_2 = "#1a1d23"   # inputs, raised
SURFACE_3 = "#22262e"   # hover
BORDER = "#252931"
BORDER_SOFT = "#1c1f26"
TEXT = "#eceef1"
TEXT_2 = "#a5abb6"
TEXT_3 = "#6c727e"
ACCENT = "#4ade9b"
ACCENT_HOVER = "#6ff0b4"
ACCENT_DIM = "#153024"
ACCENT_TEXT = "#062014"
DANGER = "#f87171"
WARN = "#fbbf24"
INFO = "#60a5fa"
PURPLE = "#c084fc"

WIN, DRAW, LOSS, UNFINISHED = ACCENT, "#8b93a1", DANGER, "#3c414b"
OUTCOME_COLORS = {"win": WIN, "loss": LOSS, "draw": DRAW, "unfinished": UNFINISHED}
OUTCOME_LETTER = {"win": "W", "loss": "L", "draw": "D", "unfinished": "–"}
LEVEL_COLORS = {"ok": ACCENT, "info": TEXT_3, "warn": WARN, "error": DANGER}
SERIES = [ACCENT, INFO, WARN, PURPLE, "#f472b6", "#2dd4bf"]

RADIUS = 14


def font(px: int, weight: QFont.Weight = QFont.Weight.Normal, spacing: float | None = None) -> QFont:
    f = QFont()
    f.setPixelSize(px)
    f.setWeight(weight)
    if spacing is not None:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return f


QSS = f"""
* {{ font-size: 13px; outline: none; }}
QWidget {{ color: {TEXT}; }}
QMainWindow, QWidget#root, QStackedWidget, QDialog {{ background: {BG}; }}
QWidget#sidebar {{ background: {SIDEBAR}; border-right: 1px solid {BORDER_SOFT}; }}
QFrame#card {{ background: {SURFACE}; border: 1px solid {BORDER_SOFT}; border-radius: {RADIUS}px; }}
QFrame#cardFlat {{ background: {SURFACE}; border: none; border-radius: {RADIUS}px; }}
QFrame#sep {{ background: {BORDER_SOFT}; max-height: 1px; min-height: 1px; border: none; }}
QFrame#vsep {{ background: {BORDER_SOFT}; max-width: 1px; min-width: 1px; border: none; }}
QFrame#notice {{ background: #1c1a10; border: 1px solid #3d3415; border-radius: 12px; }}
QFrame#selectionBar {{ background: {ACCENT_DIM}; border: 1px solid #22513a; border-radius: 12px; }}

QLabel {{ background: transparent; }}
QLabel[role="muted"] {{ color: {TEXT_2}; }}
QLabel[role="faint"] {{ color: {TEXT_3}; font-size: 12px; }}
QLabel[role="title"] {{ font-size: 24px; font-weight: 700; }}
QLabel[role="h2"] {{ font-size: 15px; font-weight: 600; }}
QLabel[role="h3"] {{ font-size: 13px; font-weight: 600; }}
QLabel[role="caption"] {{ color: {TEXT_3}; font-size: 11px; font-weight: 600; }}
QLabel[role="kpi"] {{ font-size: 26px; font-weight: 700; }}
QLabel[role="hero"] {{ font-size: 40px; font-weight: 750; }}

QPushButton {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 9px; padding: 6px 14px; }}
QPushButton:hover {{ background: {SURFACE_3}; }}
QPushButton:pressed {{ background: {SURFACE}; }}
QPushButton:disabled {{ color: {TEXT_3}; background: {SURFACE}; }}
QPushButton:checked {{ background: {ACCENT_DIM}; border-color: #22513a; color: {ACCENT}; }}
QPushButton::menu-indicator {{ image: none; width: 0; }}
QPushButton[kind="primary"] {{ background: {ACCENT}; color: {ACCENT_TEXT}; border: none; font-weight: 700; }}
QPushButton[kind="primary"]:hover {{ background: {ACCENT_HOVER}; }}
QPushButton[kind="primary"]:disabled {{ background: #23382d; color: #50675a; }}
QPushButton[kind="stop"] {{ background: #2a1517; color: #fca5a5; border: 1px solid #4c2226; font-weight: 700; }}
QPushButton[kind="stop"]:hover {{ background: #351a1d; }}
QPushButton[kind="danger"] {{ background: transparent; color: {DANGER}; border: 1px solid #4c2226; }}
QPushButton[kind="danger"]:hover {{ background: #2a1517; }}
QPushButton[kind="danger"]:disabled {{ color: {TEXT_3}; border-color: {BORDER}; }}
QPushButton[kind="ghost"] {{ background: transparent; border: none; color: {TEXT_2}; padding: 5px 9px; }}
QPushButton[kind="ghost"]:hover {{ background: {SURFACE_2}; color: {TEXT}; }}
QPushButton[kind="pill"] {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 16px; padding: 6px 12px 6px 10px;
    text-align: left; }}
QPushButton[kind="pill"]:hover {{ background: {SURFACE_3}; }}
QPushButton[kind="nav"] {{ background: transparent; border: none; border-radius: 9px; padding: 8px 10px;
    text-align: left; font-size: 13px; color: {TEXT_2}; }}
QPushButton[kind="nav"]:hover {{ background: #15181d; color: {TEXT}; }}
QPushButton[kind="nav"]:checked {{ background: {SURFACE_2}; color: {TEXT}; font-weight: 600; }}
QPushButton[kind="seg"] {{ background: transparent; border: none; border-radius: 7px; padding: 5px 12px; color: {TEXT_2}; }}
QPushButton[kind="seg"]:hover {{ color: {TEXT}; }}
QPushButton[kind="seg"]:checked {{ background: {SURFACE_3}; color: {TEXT}; font-weight: 600; }}
QToolButton {{ background: transparent; border: none; border-radius: 9px; padding: 6px; }}
QToolButton:hover {{ background: {SURFACE_2}; }}
QToolButton:checked {{ background: {ACCENT_DIM}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{ background: {SURFACE_2};
    border: 1px solid {BORDER}; border-radius: 8px; padding: 6px 9px; selection-background-color: {ACCENT};
    selection-color: {ACCENT_TEXT}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: #2f6b4d; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{ background: {SURFACE_2}; border: 1px solid {BORDER}; selection-background-color: {ACCENT_DIM};
    selection-color: {TEXT}; padding: 4px; outline: none; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 16px; border: none; }}

QTableWidget, QListWidget, QTreeWidget, QListView, QTableView {{ background: transparent; border: none; outline: none; }}
QTableWidget::item {{ padding: 3px 6px; border-radius: 6px; }}
QTableWidget::item:selected {{ background: {ACCENT_DIM}; color: {TEXT}; }}
QListWidget::item {{ border-radius: 10px; margin: 1px 0px; }}
QListWidget::item:hover {{ background: #171a1f; }}
QListWidget::item:selected {{ background: {SURFACE_2}; color: {TEXT}; }}
QHeaderView::section {{ background: transparent; color: {TEXT_3}; border: none; padding: 4px 6px; font-weight: 600;
    font-size: 11px; }}
QTableCornerButton::section {{ background: transparent; border: none; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #2a2e36; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #363b45; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #2a2e36; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ width: 0; height: 0; background: none; }}

QCheckBox {{ spacing: 8px; }}
QSlider::groove:horizontal {{ height: 4px; background: {BORDER}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {TEXT}; width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; }}
QToolTip {{ background: {SURFACE_2}; color: {TEXT}; border: 1px solid {BORDER}; padding: 5px 7px; border-radius: 6px; }}
QMenu {{ background: {SURFACE_2}; border: 1px solid {BORDER}; padding: 5px; border-radius: 10px; }}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {SURFACE_3}; }}
QMenu::item:disabled {{ color: {TEXT_3}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 5px 8px; }}
QProgressBar {{ background: {SURFACE_2}; border: none; border-radius: 3px; height: 6px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
QMessageBox {{ background: {SURFACE}; }}
"""


def palette() -> QPalette:
    pal = QPalette()
    for role, color in [
        (QPalette.ColorRole.Window, BG), (QPalette.ColorRole.WindowText, TEXT),
        (QPalette.ColorRole.Base, SURFACE_2), (QPalette.ColorRole.AlternateBase, SURFACE),
        (QPalette.ColorRole.Text, TEXT), (QPalette.ColorRole.Button, SURFACE_2),
        (QPalette.ColorRole.ButtonText, TEXT), (QPalette.ColorRole.Highlight, ACCENT),
        (QPalette.ColorRole.HighlightedText, ACCENT_TEXT), (QPalette.ColorRole.ToolTipBase, SURFACE_2),
        (QPalette.ColorRole.ToolTipText, TEXT), (QPalette.ColorRole.PlaceholderText, TEXT_3),
        (QPalette.ColorRole.Link, ACCENT),
    ]:
        pal.setColor(role, QColor(color))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(TEXT_3))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(TEXT_3))
    return pal
