"""Patient Records - vaccination data collection (PyQt5 + PyQt-Fluent-Widgets), v5.

Install:  pip install PyQt5 "PyQt-Fluent-Widgets"
Font:     drop Inter (or any .ttf family) into a "fonts" folder next to this file.

Same CSV schema as v2, so existing data files and downstream tools keep working.
"""
import csv
import os
import re
import shutil
import sys
import tempfile
from collections import Counter
from datetime import date

from PyQt5.QtCore import QDate, QRegExp, QSettings, QTime, Qt
from PyQt5.QtGui import (QBrush, QColor, QFont, QFontDatabase, QIcon, QKeySequence, QPainter,
                         QPixmap, QRegExpValidator)
from PyQt5.QtWidgets import (
    QAbstractItemView, QApplication, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QShortcut, QTableWidgetItem, QVBoxLayout, QWidget,
)
from qfluentwidgets import (
    BodyLabel, CalendarPicker, CaptionLabel, CheckBox, ComboBox, EditableComboBox,
    FluentIcon as FIF, FluentWindow, HeaderCardWidget, IconWidget, InfoBar, InfoBarPosition,
    LineEdit, MessageBox, NavigationItemPosition, PrimaryPushButton, ProgressBar, PushButton,
    ScrollArea, SearchLineEdit, SimpleCardWidget, SpinBox, StrongBodyLabel, TableWidget, Theme,
    TimeEdit, TitleLabel, getFont, isDarkTheme, setFontFamilies, setTheme, setThemeColor,
)

ID_LENGTH = 20  # kept from v2 - change here if your ID format differs

FIELDS = [
    "ID Number", "Name", "Gender", "Age", "Address", "Phone", "Vaccine",
    "Lot Number", "Expiry Date", "Vaccination Location", "Vaccination Date",
    "Vaccination Time", "Administration Site", "Dose", "Antecedents",
]
DEFAULT_ANTECEDENTS = ["Anemia", "Arthritis", "Allergy", "COPD", "Cardiac", "Colopathy",
                       "Dyslipidemia", "Type 1 Diabetes", "Type 2 Diabetes",
                       "Hypertension", "Renal Failure"]
DEFAULT_VACCINES = ["Sputnik V", "Sinopharm", "AstraZeneca", "Johnson & Johnson"]
DEFAULT_LOCATIONS = ["EPSP Annaba", "EPSP Alger", "Clinique Ibn Nafis"]
NO_BACKGROUND = "No Background"


# ----------------------------------------------------------------- paths / storage

def resource_path(relative_path):
    """Read-only bundled resources (works in dev and in PyInstaller)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative_path)


def default_data_dir():
    """Writable data folder next to the .exe / script (NOT the PyInstaller temp dir)."""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "data")


class Store:
    """All CSV reading/writing. Writes are atomic so a crash can't corrupt data."""

    FILES = ("patients_data.csv", "antecedents_list.csv", "vaccines.csv", "locations.csv")

    def __init__(self, data_dir=None):
        self.dir = data_dir or default_data_dir()
        os.makedirs(self.dir, exist_ok=True)
        for name in self.FILES:  # first run: copy bundled starter files if present
            target, bundled = self.path(name), resource_path(os.path.join("data", name))
            if not os.path.exists(target) and os.path.exists(bundled) \
                    and os.path.abspath(bundled) != os.path.abspath(target):
                shutil.copy(bundled, target)

    def path(self, name):
        return os.path.join(self.dir, name)

    @staticmethod
    def _atomic_write(path, write_fn):
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
                write_fn(f)
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

    def load_patients(self):
        try:
            with open(self.path("patients_data.csv"), newline="", encoding="utf-8-sig") as f:
                return [{k: (row.get(k) or "") for k in FIELDS}
                        for row in csv.DictReader(f) if any(row.values())]
        except FileNotFoundError:
            return []

    def save_patients(self, rows):
        def write(f):
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)
        self._atomic_write(self.path("patients_data.csv"), write)

    def load_column(self, name, default):  # one item per line (antecedents)
        try:
            with open(self.path(name), newline="", encoding="utf-8-sig") as f:
                items = [r[0].strip() for r in csv.reader(f) if r and r[0].strip()]
            return items or list(default)
        except FileNotFoundError:
            return list(default)

    def save_column(self, name, items):
        self._atomic_write(self.path(name), lambda f: csv.writer(f).writerows([i] for i in items))

    def load_row(self, name, default):  # single-row format (vaccines, locations)
        try:
            with open(self.path(name), newline="", encoding="utf-8-sig") as f:
                items = [x.strip() for x in next(csv.reader(f), []) if x.strip()]
            return items or list(default)
        except FileNotFoundError:
            return list(default)

    def save_row(self, name, items):
        self._atomic_write(self.path(name), lambda f: csv.writer(f).writerow(items))


def add_unique(items, value):
    """Append value unless present (case-insensitive). Returns True if added."""
    if value and value.lower() not in (i.lower() for i in items):
        items.append(value)
        return True
    return False


# ----------------------------------------------------------------- validation

def validate(v, other_ids, today=None):
    """Return {field_key: message}, ordered like the form. Empty dict = valid."""
    today = today or date.today()
    e = {}
    if not re.fullmatch(rf"[0-9]{{{ID_LENGTH}}}", v["id"]):
        e["id"] = f"ID number must be exactly {ID_LENGTH} digits"
    elif v["id"] in other_ids:
        e["id"] = "A patient with this ID number already exists"
    if not v["name"]:
        e["name"] = "Name is required"
    if not v["gender"]:
        e["gender"] = "Select a gender"
    if not 1 <= v["age"] <= 120:
        e["age"] = "Enter a valid age (1-120)"
    if not v["address"]:
        e["address"] = "Address is required"
    digits = re.sub(r"\D", "", v["phone"])
    if not re.fullmatch(r"\+?[\d\s\-().]+", v["phone"]) or not 8 <= len(digits) <= 15:
        e["phone"] = "Enter a valid phone number"
    if not v["vaccine"]:
        e["vaccine"] = "Select or type a vaccine"
    if not v["lot"]:
        e["lot"] = "Lot number is required"
    if v["expiry"] is None:
        e["expiry"] = "Select the vaccine expiry date"
    elif v["expiry"] < v["vdate"]:
        e["expiry"] = "Vaccine was already expired on the vaccination date"
    if not v["location"]:
        e["location"] = "Vaccination location is required"
    if v["vdate"] > today:
        e["vdate"] = "Vaccination date can't be in the future"
    if not v["site"]:
        e["site"] = "Select the administration site"
    if not v["dose"]:
        e["dose"] = "Select the dose"
    return e



# ----------------------------------------------------------------- appearance settings

APP_NAME = "Patient Records"
FONT_FAMILY = "Poppins"  # <- change to "Poppins", "Nunito", "Manrope"... (put the .ttf files in ./fonts)
FONT_FALLBACKS = ["Segoe UI", "Microsoft YaHei", "Arial"]
ACCENT = QColor("#0d9488")  # teal. Try "#2563eb" (blue), "#7c3aed" (violet), "#e11d48" (rose)
DANGER = QColor("#dc2626")
MUTED_LIGHT, MUTED_DARK = QColor("#64748b"), QColor("#94a3b8")
BADGE_COLORS = ["#0d9488", "#6366f1", "#d97706", "#db2777", "#2563eb"]  # readable in light + dark

GENDERS = ["Male", "Female"]
SITES = ["Left Arm", "Right Arm"]
DOSES = ["1st Dose", "2nd Dose"]


def load_fonts():
    """Register .ttf/.otf files from a 'fonts' folder and apply FONT_FAMILY app-wide."""
    seen = set()
    for base in (os.path.dirname(default_data_dir()), resource_path("")):
        folder = os.path.normpath(os.path.join(base, "fonts"))
        if folder in seen or not os.path.isdir(folder):
            continue
        seen.add(folder)
        for name in sorted(os.listdir(folder)):
            if name.lower().endswith((".ttf", ".otf")):
                QFontDatabase.addApplicationFont(os.path.join(folder, name))
    families = [FONT_FAMILY] + FONT_FALLBACKS
    setFontFamilies(families)  # every Fluent widget
    font = QApplication.font()
    font.setFamilies(families)  # plain Qt widgets (file dialogs etc.)
    QApplication.setFont(font)
    if FONT_FAMILY not in QFontDatabase().families():
        print(f"[fonts] '{FONT_FAMILY}' not found - using a fallback. "
              f"Put its .ttf files in a 'fonts' folder next to this script.")


def setup_theme():
    saved = str(QSettings("PatientForm", "App").value("theme", "auto"))
    setTheme({"light": Theme.LIGHT, "dark": Theme.DARK}.get(saved, Theme.AUTO), save=False)
    setThemeColor(ACCENT, save=False)


def make_app_icon():
    pm = QPixmap(128, 128)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(ACCENT)
    p.drawRoundedRect(8, 8, 112, 112, 28, 28)
    p.setBrush(QColor("white"))
    p.drawRoundedRect(54, 30, 20, 68, 8, 8)
    p.drawRoundedRect(30, 54, 68, 20, 8, 8)
    p.end()
    return QIcon(pm)


def badge_color(text):
    fixed = {"1st Dose": 0, "2nd Dose": 1}
    return BADGE_COLORS[fixed.get(text, sum(map(ord, text)) % len(BADGE_COLORS))]


def combo_value(cb):
    """Current text of a (possibly editable) Fluent combo box; '' when nothing chosen."""
    if isinstance(cb, EditableComboBox):
        return cb.text().strip()
    return cb.currentText().strip() if cb.currentIndex() >= 0 else ""


# ----------------------------------------------------------------- main window

class PatientForm(FluentWindow):
    def __init__(self):
        super().__init__()
        self.setWindowIcon(make_app_icon())
        self.setWindowTitle(APP_NAME)
        self.resize(1320, 860)
        self.setMinimumSize(1100, 700)
        geo = QApplication.primaryScreen().availableGeometry()
        self.move((geo.width() - self.width()) // 2, (geo.height() - self.height()) // 2)

        self.store = Store()
        self.patients = self.store.load_patients()
        self.antecedents = self.store.load_column("antecedents_list.csv", DEFAULT_ANTECEDENTS)
        self.vaccines = self.store.load_row("vaccines.csv", DEFAULT_VACCINES)
        self.locations = self.store.load_row("locations.csv", DEFAULT_LOCATIONS)
        self.editing_id = None
        self.fields, self.field_labels, self.field_errors = {}, {}, {}
        self.ant_boxes = {}
        self.stat_values = {}

        self.dash_page = self._build_dashboard_page()
        self.form_page = self._build_form_page()
        self.list_page = self._build_list_page()
        self._init_navigation()
        self.stackedWidget.currentChanged.connect(self._on_page_changed)

        self._refresh_table()
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.submit)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self._focus_search)

    # ---- navigation / theme / notifications

    def _init_navigation(self):
        self.addSubInterface(self.dash_page, FIF.HOME, "Dashboard")
        self.addSubInterface(self.form_page, FIF.ADD, "New patient")
        self.addSubInterface(self.list_page, FIF.PEOPLE, "Patients")
        self.navigationInterface.addItem(
            routeKey="theme", icon=FIF.CONSTRACT, text="Dark / light mode",
            onClick=self.toggle_theme, selectable=False, position=NavigationItemPosition.BOTTOM)
        self.navigationInterface.setExpandWidth(250)

    def toggle_theme(self):
        dark = not isDarkTheme()
        setTheme(Theme.DARK if dark else Theme.LIGHT, save=False)
        QSettings("PatientForm", "App").setValue("theme", "dark" if dark else "light")

    def _on_page_changed(self, _index):
        if self.stackedWidget.currentWidget() is self.dash_page:
            self._refresh_dashboard()

    def notify(self, title, content="", kind="success"):
        bar = {"success": InfoBar.success, "error": InfoBar.error,
               "warning": InfoBar.warning, "info": InfoBar.info}[kind]
        bar(title=title, content=content, orient=Qt.Horizontal, isClosable=True,
            position=InfoBarPosition.TOP_RIGHT, duration=3500 if kind != "error" else 6000, parent=self)

    # ---- construction helpers

    @staticmethod
    def _muted(label):
        label.setTextColor(MUTED_LIGHT, MUTED_DARK)
        return label

    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                PatientForm._clear_layout(item.layout())

    def _page(self, name, title, subtitle, scroll=True):
        """Returns (page, body_layout, header_layout); add header buttons to header_layout."""
        page = QWidget()
        page.setObjectName(name)  # required by addSubInterface
        outer = QVBoxLayout(page)
        outer.setContentsMargins(36, 20, 28, 20)
        outer.setSpacing(18)
        head = QHBoxLayout()
        head.setSpacing(10)
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(TitleLabel(title))
        col.addWidget(self._muted(CaptionLabel(subtitle)))
        head.addLayout(col)
        head.addStretch()
        outer.addLayout(head)
        if scroll:
            area = ScrollArea()
            area.setWidgetResizable(True)
            area.enableTransparentBackground()
            inner = QWidget()
            inner.setObjectName("scrollView")
            inner.setStyleSheet("#scrollView { background: transparent; }")
            body = QVBoxLayout(inner)
            body.setContentsMargins(0, 4, 12, 12)
            body.setSpacing(18)
            area.setWidget(inner)
            outer.addWidget(area, 1)
        else:
            body = outer
        return page, body, head

    def _card(self, title, hint=None):
        """Returns (card, body_layout)."""
        card = HeaderCardWidget()
        card.setTitle(title)
        body = QVBoxLayout()
        body.setSpacing(14)
        if hint:
            body.addWidget(self._muted(CaptionLabel(hint)))
        card.viewLayout.addLayout(body)
        return card, body

    @staticmethod
    def _combo(items, editable=False, placeholder=""):
        cb = EditableComboBox() if editable else ComboBox()
        cb.addItems(items)
        cb.setPlaceholderText(placeholder)
        if editable:
            cb.setText("")
        else:
            cb.setCurrentIndex(-1)  # show the placeholder instead of the first item
        return cb

    def _field(self, label, key, required=True):
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(5)
        lab = self._muted(CaptionLabel(label + (" *" if required else "")))
        err = CaptionLabel()
        err.setTextColor(DANGER, QColor("#f87171"))
        err.hide()
        self.field_labels[key], self.field_errors[key] = lab, err
        lay.addWidget(lab)
        lay.addWidget(self.fields[key])
        lay.addWidget(err)
        return box

    def _form_card(self, title, hint, items):
        card, body = self._card(title, hint)
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(12)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        r = c = 0
        for label, key, required, span in items:
            if span == 2 and c == 1:
                r, c = r + 1, 0
            grid.addWidget(self._field(label, key, required), r, c, 1, span)
            c += span
            if c >= 2:
                r, c = r + 1, 0
        body.addLayout(grid)
        return card

    # ---- dashboard

    def _build_dashboard_page(self):
        page, body, _ = self._page("dashboardInterface", "Dashboard",
                                   "An overview of your vaccination records")
        stats = QHBoxLayout()
        stats.setSpacing(18)
        for key, icon, label in (("total", FIF.PEOPLE, "Total patients"),
                                 ("today", FIF.CALENDAR, "Vaccinated today"),
                                 ("second", FIF.ACCEPT, "Second doses"),
                                 ("top", FIF.HEART, "Most used vaccine")):
            stats.addWidget(self._stat_card(key, icon, label), 1)
        body.addLayout(stats)

        row = QHBoxLayout()
        row.setSpacing(18)
        vaccine_card, vbody = self._card("By vaccine", "Share of all recorded patients")
        recent_card, rbody = self._card("Recently added", "The last five patients")
        self.vaccine_body, self.recent_body = QVBoxLayout(), QVBoxLayout()
        self.vaccine_body.setSpacing(16)
        self.recent_body.setSpacing(14)
        vbody.addLayout(self.vaccine_body)
        rbody.addLayout(self.recent_body)
        row.addWidget(vaccine_card, 3, Qt.AlignTop)
        row.addWidget(recent_card, 2, Qt.AlignTop)
        body.addLayout(row)
        body.addStretch()
        return page

    def _stat_card(self, key, icon, label):
        card = SimpleCardWidget()
        card.setMinimumHeight(112)
        row = QHBoxLayout(card)
        row.setContentsMargins(22, 18, 22, 18)
        row.setSpacing(16)
        badge = QFrame()
        badge.setObjectName("statBadge")
        badge.setFixedSize(52, 52)
        badge.setStyleSheet(
            f"#statBadge {{ background: rgba({ACCENT.red()}, {ACCENT.green()}, {ACCENT.blue()}, 0.16);"
            f" border-radius: 16px; }}")
        inner = QHBoxLayout(badge)
        inner.setContentsMargins(0, 0, 0, 0)
        ic = IconWidget(icon)
        ic.setFixedSize(24, 24)
        inner.addWidget(ic, 0, Qt.AlignCenter)
        col = QVBoxLayout()
        col.setSpacing(2)
        value = TitleLabel("0")
        col.addStretch()
        col.addWidget(value)
        col.addWidget(self._muted(CaptionLabel(label)))
        col.addStretch()
        row.addWidget(badge)
        row.addLayout(col, 1)
        self.stat_values[key] = value
        return card

    def _refresh_dashboard(self):
        ps = self.patients
        counts = Counter(p["Vaccine"] for p in ps if p["Vaccine"])
        today = date.today().isoformat()
        self.stat_values["total"].setText(str(len(ps)))
        self.stat_values["today"].setText(str(sum(p["Vaccination Date"] == today for p in ps)))
        self.stat_values["second"].setText(str(sum(p["Dose"] == "2nd Dose" for p in ps)))
        self.stat_values["top"].setText(counts.most_common(1)[0][0] if counts else "—")

        self._clear_layout(self.vaccine_body)
        self._clear_layout(self.recent_body)
        if not ps:
            for layout in (self.vaccine_body, self.recent_body):
                layout.addWidget(self._muted(BodyLabel("No patients yet. Add the first one from “New patient”.")))
            return

        total = len(ps)
        for name, n in counts.most_common(6):
            pct = round(n * 100 / total)
            line = QHBoxLayout()
            line.setSpacing(14)
            lab = BodyLabel(name)
            lab.setMinimumWidth(130)
            bar = ProgressBar()
            bar.setRange(0, 100)
            bar.setValue(pct)
            num = self._muted(CaptionLabel(f"{n}  ·  {pct}%"))
            num.setMinimumWidth(80)
            num.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            line.addWidget(lab)
            line.addWidget(bar, 1)
            line.addWidget(num)
            self.vaccine_body.addLayout(line)

        for p in reversed(ps[-5:]):
            line = QHBoxLayout()
            line.setSpacing(12)
            avatar = QLabel((p["Name"][:1] or "?").upper())
            avatar.setObjectName("avatar")
            avatar.setFixedSize(38, 38)
            avatar.setAlignment(Qt.AlignCenter)
            avatar.setStyleSheet(f"#avatar {{ background: {ACCENT.name()}; color: white;"
                                 f" border-radius: 19px; font-weight: 600; }}")
            info = QVBoxLayout()
            info.setSpacing(0)
            info.addWidget(StrongBodyLabel(p["Name"]))
            info.addWidget(self._muted(CaptionLabel(f"{p['Vaccine']}  ·  {p['Vaccination Date']}")))
            line.addWidget(avatar)
            line.addLayout(info, 1)
            line.addWidget(self._muted(CaptionLabel(p["Dose"])))
            self.recent_body.addLayout(line)

    # ---- form page

    def _build_form_page(self):
        page, body, head = self._page("formInterface", "New patient", "Fields marked * are required")
        f = self.fields
        f["id"] = LineEdit()
        f["id"].setMaxLength(ID_LENGTH)
        f["id"].setValidator(QRegExpValidator(QRegExp(r"[0-9]*")))
        f["id"].setPlaceholderText(f"{ID_LENGTH} digits")
        f["name"] = LineEdit()
        f["name"].setPlaceholderText("First and last name")
        f["gender"] = self._combo(GENDERS, placeholder="Select…")
        f["age"] = SpinBox()
        f["age"].setRange(0, 120)
        f["age"].setSuffix(" yrs")
        f["address"] = LineEdit()
        f["phone"] = LineEdit()
        f["phone"].setPlaceholderText("+213 …")
        f["phone"].setValidator(QRegExpValidator(QRegExp(r"[0-9+\s\-().]*")))

        f["vaccine"] = self._combo(self.vaccines, True, "Select or type a new one")
        f["lot"] = LineEdit()
        f["expiry"] = CalendarPicker()
        f["expiry"].setDateFormat("dd/MM/yyyy")
        f["dose"] = self._combo(DOSES, placeholder="Select…")
        f["vdate"] = CalendarPicker()
        f["vdate"].setDateFormat("dd/MM/yyyy")
        f["vdate"].setDate(QDate.currentDate())
        f["vtime"] = TimeEdit()
        f["vtime"].setDisplayFormat("HH:mm")
        f["vtime"].setTime(QTime.currentTime())
        f["location"] = self._combo(self.locations, True, "Select or type a new one")
        f["site"] = self._combo(SITES, placeholder="Select…")

        cols = QHBoxLayout()
        cols.setSpacing(18)
        left = QVBoxLayout()
        left.setSpacing(18)
        left.addWidget(self._form_card("Patient", "Personal information", [
            ("ID number", "id", True, 2), ("Full name", "name", True, 2),
            ("Gender", "gender", True, 1), ("Age", "age", True, 1),
            ("Phone", "phone", True, 1), ("Address", "address", True, 1)]))
        left.addWidget(self._form_card("Vaccination", "Vaccine and administration details", [
            ("Vaccine", "vaccine", True, 1), ("Lot number", "lot", True, 1),
            ("Expiry date", "expiry", True, 1), ("Dose", "dose", True, 1),
            ("Vaccination date", "vdate", True, 1), ("Time", "vtime", False, 1),
            ("Location", "location", True, 1), ("Administration site", "site", True, 1)]))
        left.addStretch()
        cols.addLayout(left, 3)
        cols.addWidget(self._build_antecedents_card(), 2, Qt.AlignTop)
        body.addLayout(cols)
        body.addStretch()

        self.cancel_btn = PushButton(FIF.CANCEL, "Cancel edit")
        self.cancel_btn.clicked.connect(self.clear_form)
        self.cancel_btn.hide()
        clear_btn = PushButton(FIF.BROOM, "Clear")
        clear_btn.clicked.connect(self.clear_form)
        self.submit_btn = PrimaryPushButton(FIF.ADD, "Add patient")
        self.submit_btn.clicked.connect(self.submit)
        for b in (self.cancel_btn, clear_btn, self.submit_btn):
            head.addWidget(b)
        return page

    def _build_antecedents_card(self):
        card, body = self._card("Medical history", "Select all that apply")
        self.ant_layout = QVBoxLayout()
        self.ant_layout.setSpacing(4)
        body.addLayout(self.ant_layout)
        for name in self.antecedents:
            self._add_antecedent_box(name)
        self.custom_input = LineEdit()
        self.custom_input.setPlaceholderText("Other condition…")
        self.custom_input.returnPressed.connect(self.add_custom_antecedent)
        add_btn = PushButton("Add")
        add_btn.clicked.connect(self.add_custom_antecedent)
        row = QHBoxLayout()
        row.addWidget(self.custom_input, 1)
        row.addWidget(add_btn)
        body.addLayout(row)
        return card

    def _add_antecedent_box(self, name, checked=False):
        cb = CheckBox(name)
        cb.setChecked(checked)
        self.ant_boxes[name] = cb
        self.ant_layout.addWidget(cb)

    def add_custom_antecedent(self):
        name = self.custom_input.text().strip()
        if not name:
            return
        existing = next((n for n in self.ant_boxes if n.lower() == name.lower()), None)
        if existing:
            self.ant_boxes[existing].setChecked(True)
        else:
            self.antecedents.append(name)
            self._add_antecedent_box(name, checked=True)
            self._safe(lambda: self.store.save_column("antecedents_list.csv", self.antecedents))
        self.custom_input.clear()

    # ---- patients list page

    def _build_list_page(self):
        page, body, head = self._page("patientsInterface", "Patients",
                                      "Search, edit or export your records", scroll=False)
        export_btn = PushButton(FIF.DOWNLOAD, "Export CSV")
        export_btn.clicked.connect(self.export_csv)
        head.addWidget(export_btn)

        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.search = SearchLineEdit()
        self.search.setPlaceholderText("Search any field…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        self.count_label = self._muted(CaptionLabel(""))
        edit_btn = PushButton(FIF.EDIT, "Edit")
        edit_btn.clicked.connect(self.edit_selected)
        del_btn = PushButton(FIF.DELETE, "Delete")
        del_btn.clicked.connect(self.delete_selected)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.count_label)
        bar.addWidget(edit_btn)
        bar.addWidget(del_btn)
        body.addLayout(bar)

        t = TableWidget()
        t.setColumnCount(len(FIELDS))
        t.setHorizontalHeaderLabels(FIELDS)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setSelectionMode(QAbstractItemView.SingleSelection)
        t.setWordWrap(False)
        t.verticalHeader().hide()
        t.verticalHeader().setDefaultSectionSize(46)
        t.horizontalHeader().setStretchLastSection(True)
        if hasattr(t, "setBorderVisible"):
            t.setBorderVisible(True)
        if hasattr(t, "setBorderRadius"):
            t.setBorderRadius(8)
        t.setSortingEnabled(True)
        t.doubleClicked.connect(lambda _: self.edit_selected())
        self.table = t
        body.addWidget(t, 1)
        return page

    # ---- form logic

    def _gather(self):
        f = self.fields
        expiry, vdate = f["expiry"].date, f["vdate"].date
        return {
            "id": f["id"].text().strip(), "name": f["name"].text().strip(),
            "gender": combo_value(f["gender"]), "age": f["age"].value(),
            "address": f["address"].text().strip(), "phone": f["phone"].text().strip(),
            "vaccine": combo_value(f["vaccine"]), "lot": f["lot"].text().strip(),
            "expiry": expiry.toPyDate() if expiry.isValid() else None,
            "location": combo_value(f["location"]),
            "vdate": vdate.toPyDate() if vdate.isValid() else date.today(),
            "vtime": f["vtime"].time().toString("HH:mm"),
            "site": combo_value(f["site"]), "dose": combo_value(f["dose"]),
        }

    def _mark_invalid(self, errors):
        for key, widget in self.fields.items():
            msg = errors.get(key)
            if msg:
                self.field_errors[key].setText(msg)
                self.field_errors[key].show()
            else:
                self.field_errors[key].hide()
            if hasattr(widget, "setError"):
                widget.setError(bool(msg))
        if errors:
            self.fields[next(iter(errors))].setFocus()

    def submit(self):
        if self.stackedWidget.currentWidget() is not self.form_page:
            return
        v = self._gather()
        other_ids = {p["ID Number"] for p in self.patients if p["ID Number"] != self.editing_id}
        errors = validate(v, other_ids)
        self._mark_invalid(errors)
        if errors:
            self.notify("Please fix the highlighted fields", f"{len(errors)} field(s) need attention.", "error")
            return

        chosen = [n for n, cb in self.ant_boxes.items() if cb.isChecked()]
        record = {
            "ID Number": v["id"], "Name": v["name"], "Gender": v["gender"], "Age": str(v["age"]),
            "Address": v["address"], "Phone": v["phone"], "Vaccine": v["vaccine"],
            "Lot Number": v["lot"], "Expiry Date": v["expiry"].isoformat(),
            "Vaccination Location": v["location"], "Vaccination Date": v["vdate"].isoformat(),
            "Vaccination Time": v["vtime"], "Administration Site": v["site"], "Dose": v["dose"],
            "Antecedents": ", ".join(chosen) if chosen else NO_BACKGROUND,
        }

        editing = self.editing_id is not None
        if editing:
            idx = next(i for i, p in enumerate(self.patients) if p["ID Number"] == self.editing_id)
            self.patients[idx] = record
        else:
            self.patients.append(record)
        if not self._safe(lambda: self.store.save_patients(self.patients)):
            return

        if add_unique(self.vaccines, v["vaccine"]):
            self._safe(lambda: self.store.save_row("vaccines.csv", self.vaccines))
            self.fields["vaccine"].addItem(v["vaccine"])
        if add_unique(self.locations, v["location"]):
            self._safe(lambda: self.store.save_row("locations.csv", self.locations))
            self.fields["location"].addItem(v["location"])

        self._refresh_table()
        self.clear_form()
        self.notify("Patient updated" if editing else "Patient added", record["Name"])
        if editing:
            self.switchTo(self.list_page)

    def clear_form(self):
        f = self.fields
        for key in ("id", "name", "address", "phone", "lot"):
            f[key].clear()
        for key in ("gender", "dose", "site"):
            f[key].setCurrentIndex(-1)
        for key in ("vaccine", "location"):
            f[key].setText("")
        f["age"].setValue(0)
        f["expiry"].reset()
        f["vdate"].setDate(QDate.currentDate())
        f["vtime"].setTime(QTime.currentTime())
        for cb in self.ant_boxes.values():
            cb.setChecked(False)
        self.editing_id = None
        self.submit_btn.setText("Add patient")
        self.submit_btn.setIcon(FIF.ADD)
        self.cancel_btn.hide()
        self._mark_invalid({})
        f["id"].setFocus()

    def _load_into_form(self, p):
        f = self.fields
        f["id"].setText(p["ID Number"])
        f["name"].setText(p["Name"])
        f["age"].setValue(int(p["Age"] or 0))
        f["address"].setText(p["Address"])
        f["phone"].setText(p["Phone"])
        f["lot"].setText(p["Lot Number"])
        for key, col, options in (("gender", "Gender", GENDERS), ("site", "Administration Site", SITES),
                                  ("dose", "Dose", DOSES)):
            f[key].setCurrentIndex(options.index(p[col]) if p[col] in options else -1)
        f["vaccine"].setText(p["Vaccine"])
        f["location"].setText(p["Vaccination Location"])
        exp = QDate.fromString(p["Expiry Date"], "yyyy-MM-dd")
        f["expiry"].setDate(exp) if exp.isValid() else f["expiry"].reset()
        vd = QDate.fromString(p["Vaccination Date"], "yyyy-MM-dd")
        f["vdate"].setDate(vd if vd.isValid() else QDate.currentDate())
        vt = QTime.fromString(p["Vaccination Time"], "HH:mm")
        f["vtime"].setTime(vt if vt.isValid() else QTime.currentTime())
        selected = {a.strip() for a in p["Antecedents"].split(",")}
        for name in selected - set(self.ant_boxes) - {NO_BACKGROUND, ""}:
            self._add_antecedent_box(name)  # condition no longer in the list
        for name, cb in self.ant_boxes.items():
            cb.setChecked(name in selected)

    # ---- patients list

    def _refresh_table(self):
        t = self.table
        t.setSortingEnabled(False)
        t.setRowCount(len(self.patients))
        bold = getFont(13, QFont.DemiBold)
        for r, p in enumerate(self.patients):
            for c, key in enumerate(FIELDS):
                item = QTableWidgetItem(p[key])
                if key in ("Vaccine", "Dose") and p[key]:
                    item.setForeground(QBrush(QColor(badge_color(p[key]))))
                    item.setFont(bold)
                t.setItem(r, c, item)
        t.setSortingEnabled(True)
        t.resizeColumnsToContents()
        self._apply_filter()
        self._refresh_dashboard()

    def _apply_filter(self):
        q = self.search.text().strip().lower()
        shown = 0
        for r in range(self.table.rowCount()):
            text = " ".join(self.table.item(r, c).text().lower() for c in range(len(FIELDS)))
            hide = bool(q) and q not in text
            self.table.setRowHidden(r, hide)
            shown += not hide
        self.count_label.setText(f"{shown} of {len(self.patients)}")

    def _focus_search(self):
        self.switchTo(self.list_page)
        self.search.setFocus()
        self.search.selectAll()

    def _selected_id(self):
        row = self.table.currentRow()
        if row < 0 or self.table.item(row, 0) is None:
            self.notify("Select a patient first", "Click a row in the table.", "warning")
            return None
        return self.table.item(row, 0).text()  # look up by ID, never by row number

    def edit_selected(self):
        pid = self._selected_id()
        patient = next((p for p in self.patients if p["ID Number"] == pid), None)
        if patient:
            self.clear_form()
            self._load_into_form(patient)
            self.editing_id = pid
            self.submit_btn.setText("Save changes")
            self.submit_btn.setIcon(FIF.ACCEPT)
            self.cancel_btn.show()
            self.switchTo(self.form_page)

    def delete_selected(self):
        pid = self._selected_id()
        patient = next((p for p in self.patients if p["ID Number"] == pid), None)
        if not patient:
            return
        box = MessageBox("Delete patient", f"Delete {patient['Name']} ({pid})?\nThis can't be undone.", self)
        box.yesButton.setText("Delete")
        box.cancelButton.setText("Cancel")
        if box.exec_():
            self.patients.remove(patient)
            if self._safe(lambda: self.store.save_patients(self.patients)):
                self._refresh_table()
                self.notify("Patient deleted", patient["Name"], "info")

    def export_csv(self):
        default = f"patients_{date.today().isoformat()}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", default, "CSV Files (*.csv)")
        if not path:
            return

        def write():
            # utf-8-sig so Excel displays Arabic/French characters correctly
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=FIELDS)
                w.writeheader()
                w.writerows(self.patients)
        if self._safe(write):
            self.notify("Export complete", f"{len(self.patients)} patients saved.")

    # ---- helpers

    def _safe(self, action):
        """Run a file operation; show a readable error instead of crashing."""
        try:
            action()
            return True
        except OSError as exc:
            self.notify("Couldn't write the file", str(exc), "error")
            return False


if __name__ == "__main__":
    if hasattr(Qt, "HighDpiScaleFactorRoundingPolicy"):
        QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    load_fonts()
    setup_theme()
    window = PatientForm()
    window.show()
    sys.exit(app.exec_())