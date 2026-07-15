"""
Apple / macOS-inspired QSS stylesheet for the HiWatch Toolkit UI.

Clean, light design with rounded corners, subtle shadows, and SF-like fonts.
"""

APP_STYLESHEET = """
/* === Global === */
QWidget {
    font-family: -apple-system, "SF Pro Display", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
    color: #1d1d1f;
    background-color: #f5f5f7;
}

/* === Main Window === */
QMainWindow {
    background-color: #f5f5f7;
}

/* === Sidebar === */
QListWidget#sidebar {
    background-color: #e8e8ed;
    border: none;
    border-right: 1px solid #d2d2d7;
    border-radius: 0px;
    padding: 8px 0px;
    font-size: 13px;
    color: #1d1d1f;
    outline: none;
}
QListWidget#sidebar::item {
    padding: 10px 20px;
    margin: 2px 8px;
    border-radius: 6px;
}
QListWidget#sidebar::item:selected {
    background-color: #007aff;
    color: #ffffff;
}
QListWidget#sidebar::item:hover:!selected {
    background-color: #d2d2d7;
}

/* === Page Area === */
QWidget#pageContainer {
    background-color: #ffffff;
    border-radius: 8px;
    margin: 12px;
}

/* === Buttons === */
QPushButton {
    background-color: #007aff;
    color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 8px 20px;
    font-size: 13px;
    font-weight: 500;
    min-height: 20px;
}
QPushButton:hover {
    background-color: #0062cc;
}
QPushButton:pressed {
    background-color: #004999;
}
QPushButton:disabled {
    background-color: #c7c7cc;
    color: #8e8e93;
}
QPushButton#dangerButton {
    background-color: #ff3b30;
}
QPushButton#dangerButton:hover {
    background-color: #d62d20;
}
QPushButton#secondaryButton {
    background-color: #e8e8ed;
    color: #1d1d1f;
}
QPushButton#secondaryButton:hover {
    background-color: #d2d2d7;
}

/* === Input Fields === */
QLineEdit, QSpinBox, QComboBox {
    background-color: #ffffff;
    border: 1px solid #c7c7cc;
    border-radius: 6px;
    padding: 6px 12px;
    font-size: 13px;
    color: #1d1d1f;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    border-color: #007aff;
}
QComboBox::drop-down {
    border: none;
    padding-right: 8px;
}
QComboBox::down-arrow {
    image: none;
    width: 0px;
}

/* === Labels === */
QLabel#titleLabel {
    font-size: 22px;
    font-weight: 700;
    color: #1d1d1f;
    padding-bottom: 4px;
}
QLabel#sectionLabel {
    font-size: 15px;
    font-weight: 600;
    color: #1d1d1f;
    padding-top: 8px;
}
QLabel#infoLabel {
    font-size: 13px;
    color: #6e6e73;
}
QLabel#valueLabel {
    font-size: 15px;
    font-weight: 500;
    color: #1d1d1f;
}
QLabel#statusLabel {
    font-size: 12px;
    color: #6e6e73;
    padding: 4px 0px;
}

/* === Progress Bar === */
QProgressBar {
    background-color: #e8e8ed;
    border: none;
    border-radius: 6px;
    height: 8px;
    text-align: center;
    font-size: 11px;
}
QProgressBar::chunk {
    background-color: #007aff;
    border-radius: 6px;
}

/* === Scroll Area === */
QScrollArea {
    border: none;
    background-color: transparent;
}
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background: #c7c7cc;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #a8a8ad;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

/* === Table / List === */
QTableWidget, QListWidget {
    background-color: #ffffff;
    border: 1px solid #d2d2d7;
    border-radius: 8px;
    alternate-background-color: #f9f9fb;
    selection-background-color: #007aff;
    selection-color: #ffffff;
}

/* === Group Box === */
QGroupBox {
    font-weight: 600;
    font-size: 13px;
    border: 1px solid #d2d2d7;
    border-radius: 8px;
    margin-top: 12px;
    padding: 16px 12px 12px 12px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 4px 8px;
    color: #1d1d1f;
}

/* === Splitter === */
QSplitter::handle {
    background: #d2d2d7;
    width: 1px;
}

/* === Text Edit / Log === */
QPlainTextEdit#logView {
    background-color: #1d1d1f;
    color: #00ff41;
    font-family: "SF Mono", "Menlo", "Consolas", monospace;
    font-size: 12px;
    border: 1px solid #3a3a3c;
    border-radius: 8px;
    padding: 8px;
    selection-background-color: #007aff;
}

/* === Dialog === */
QDialog {
    background-color: #f5f5f7;
}
"""


def apply_theme(app) -> None:
    """Apply the macOS-inspired stylesheet to a QApplication instance."""
    app.setStyleSheet(APP_STYLESHEET)
