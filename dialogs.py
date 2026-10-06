"""Dialogs for the Attribute Rules Manager."""
import sys
import traceback

from osgeo import gdal
from qgis.core import Qgis, QgsExpression, QgsProject
from qgis.gui import QgsExpressionLineEdit
from qgis.PyQt.QtCore import QT_VERSION_STR
from qgis.PyQt.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from . import engine, logic, store

TITLE = "Attribute Rules Manager"


def _warn(parent, text):
    QMessageBox.warning(parent, TITLE, text)


def plugin_version():
    import configparser
    import os
    parser = configparser.ConfigParser()
    try:
        parser.read(os.path.join(os.path.dirname(__file__), "metadata.txt"), encoding="utf-8")
        return parser["general"].get("version", "?")
    except (KeyError, configparser.Error, OSError):
        return "?"


class ReportDialog(QDialog):
    def __init__(self, title, lines, parent=None, extra=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(620, 420)
        out = QPlainTextEdit()
        out.setReadOnly(True)
        out.setPlainText("\n".join(lines))
        row = QHBoxLayout()
        copy = QPushButton("Copy to clipboard")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(out.toPlainText()))
        row.addWidget(copy)
        for text, fn in (extra or []):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        row.addWidget(close)
        lay = QVBoxLayout(self)
        lay.addWidget(out)
        lay.addLayout(row)


# --------------------------------------------------------------- rule editor
class RuleEditDialog(QDialog):
    def __init__(self, fmt, path, table, fields, tables, rules, rule=None, parent=None, types=None, unsaved=None,
                 geometry=None):
        super().__init__(parent)
        self.fmt, self.path, self.table, self.fields, self.tables = fmt, path, table, fields, tables
        self.geometry = geometry
        self.types, self.unsaved = types or {}, unsaved or []
        self.rules, self.rule = rules, rule
        self.result_rule = None
        self.setWindowTitle(("Edit rule - " if rule else "New rule - ") + table)
        self.setMinimumWidth(640)

        self.name = QLineEdit(rule["name"] if rule else "")
        self.type = QComboBox()
        for t in logic.TYPES:
            self.type.addItem(logic.TYPE_LABELS[t], t)
        self.field = QComboBox()
        self._fill_fields(rule["type"] if rule else "calculation")
        self.field_label = QLabel("Field:")
        self.template = QComboBox()
        self.other = QComboBox()
        for t in tables:
            self.other.addItem(t)
        use = QPushButton("Use template")
        use.clicked.connect(self._use_template)
        trow = QHBoxLayout()
        trow.addWidget(self.template, 1)
        self.other_label = QLabel("other layer:")
        trow.addWidget(self.other_label)
        trow.addWidget(self.other)
        trow.addWidget(use)
        self.expression = QgsExpressionLineEdit()
        ctx_layer = engine.context_layer(fmt, path, table)
        if ctx_layer is not None:
            self.expression.setLayer(ctx_layer)
        self._ctx_layer = ctx_layer
        check = QPushButton("Check expression")
        check.clicked.connect(self._check)
        erow = QHBoxLayout()
        erow.addWidget(self.expression, 1)
        erow.addWidget(check)
        self.on_update = QCheckBox("Recalculate whenever the feature is edited (not only when it is created)")
        self.message = QLineEdit(rule.get("message", "") if rule else "")
        self.message.setPlaceholderText("Text shown to the editor when the rule is broken (optional)")
        self.message_label = QLabel("Error message:")
        self.strict = QCheckBox("Block it: undo map edits that break the rule (the form always refuses to save)")
        self.enabled = QCheckBox("Rule is active")
        self.enabled.setChecked(rule.get("enabled", True) if rule else True)
        self.help = QLabel("")
        self.help.setWordWrap(True)
        self.tpl_hint = QLabel("")
        self.tpl_hint.setWordWrap(True)
        self.tpl_hint.setStyleSheet("color: #b35c00;")
        self.tpl_hint.setVisible(False)

        form = QFormLayout()
        form.addRow("Rule name:", self.name)
        form.addRow("Rule type:", self.type)
        form.addRow(self.field_label, self.field)
        form.addRow("Template:", trow)
        form.addRow("", self.tpl_hint)
        form.addRow("Expression:", erow)
        form.addRow("", self.on_update)
        form.addRow(self.message_label, self.message)
        form.addRow("", self.strict)
        form.addRow("", self.enabled)
        lay = QVBoxLayout(self)
        lay.addWidget(self.help)
        lay.addLayout(form)
        note = QLabel("Tip: another layer is written by its name, e.g. overlay_intersects('Landuse'); "
                      "the plugin links it to that layer of the same file and loads it automatically. "
                      "The button at the end of the expression box opens the QGIS expression builder.")
        note.setWordWrap(True)
        lay.addWidget(note)
        row = QHBoxLayout()
        row.addStretch(1)
        ok = QPushButton("Save")
        cancel = QPushButton("Cancel")
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        row.addWidget(ok)
        row.addWidget(cancel)
        lay.addLayout(row)

        self.type.currentIndexChanged.connect(self._type_changed)
        if rule:
            self.type.blockSignals(True)
            self.type.setCurrentIndex(max(0, self.type.findData(rule["type"])))
            self.type.blockSignals(False)
        self.template.currentIndexChanged.connect(self._template_changed)
        if rule:
            self.type.setCurrentIndex(max(0, self.type.findData(rule["type"])))
            self._fill_fields(rule["type"], rule.get("field"))
            self.expression.setExpression(rule.get("expression") or "")
            self.on_update.setChecked(bool(rule.get("on_update")))
            self.strict.setChecked(bool(rule.get("strict")))
        self._type_changed()

    def _type(self):
        return self.type.currentData()

    def _auto_name(self, rule_type):
        if self.template.currentData():
            return self.template.currentText().strip()
        if rule_type == "calculation" and self.field.currentData():
            return "Calculate %s" % self.field.currentData()
        return "%s rule" % logic.TYPE_LABELS[rule_type]

    def _fill_fields(self, rule_type, keep=None):
        self.field.blockSignals(True)
        self.field.clear()
        for f in self.fields:
            label = f
            if self.types.get(f):
                label += "  (%s)" % self.types[f]
            if f in self.unsaved:
                label += "  - not saved to the file yet"
            self.field.addItem(label, f)
        i = self.field.findData(keep) if keep else 0
        self.field.setCurrentIndex(max(i, 0))
        self.field.blockSignals(False)

    def _type_changed(self, _i=None):
        t = self._type()
        self._fill_fields(t, self.field.currentData())
        self.template.blockSignals(True)
        self.template.clear()
        kind = logic.GEOMETRY_LABELS.get(self.geometry, "")
        groups = logic.grouped_templates(t, self.geometry)
        count = sum(len(items) for _title, items in groups)
        first = "(choose a ready-made rule: %d for this %s layer)" % (count, kind) if kind else "(choose a ready-made rule)"
        self.template.addItem(first, None)
        for title, items in groups:
            self.template.addItem("---- %s ----" % title, None)
            model = self.template.model()
            header = model.item(self.template.count() - 1) if hasattr(model, "item") else None
            if header is not None:
                header.setEnabled(False)
            for label, _tt, expr, needs, hint in items:
                self.template.addItem("    " + label, (expr, needs, hint))
        self.template.blockSignals(False)
        self._template_changed()
        is_calc, is_cons = t == "calculation", t == "constraint"
        self.field.setVisible(is_calc)
        self.field_label.setVisible(is_calc)
        self.field_label.setText("Field to calculate:")
        self.on_update.setVisible(is_calc)
        self.message.setVisible(not is_calc)
        self.message_label.setVisible(not is_calc)
        self.strict.setVisible(is_cons)
        self.help.setText({
            "calculation": "CALCULATION: fills a field automatically with the result of the expression "
                           "when a feature is created (and, if ticked, every time it is edited). Any field "
                           "type works: numbers go into integer or decimal fields, text into text fields.",
            "constraint": "CONSTRAINT: the expression must be TRUE, otherwise QGIS refuses to save the "
                          "feature and shows the error message (and, if 'Block it' is ticked, map edits "
                          "that break it are undone).",
            "validation": "VALIDATION: checks existing data on demand (Validate Data...) and lists the "
                          "features that break the rule; it never blocks editing.",
        }[t])

    def _template_changed(self, _i=None):
        data = self.template.currentData()
        needs = bool(data and data[1])
        self.other.setVisible(needs)
        self.other_label.setVisible(needs)

    def _use_template(self):
        data = self.template.currentData()
        if not data:
            return
        expr, needs, hint = data
        field = self.field.currentData() if self._type() == "calculation" else None
        if "{field}" in expr and not field:
            field = self._pick_field()
            if not field:
                return
        self.expression.setExpression(logic.fill_template(
            expr, field, self.other.currentText() if needs else None))
        if not self.name.text().strip():
            self.name.setText(self.template.currentText().strip())
        self.tpl_hint.setText(("Note: " + hint) if hint else "")
        self.tpl_hint.setVisible(bool(hint))

    def _pick_field(self):
        from qgis.PyQt.QtWidgets import QInputDialog
        if not self.fields:
            _warn(self, "This layer has no fields for this template.")
            return None
        name, ok = QInputDialog.getItem(self, TITLE, "Which field does this rule check?", self.fields, 0, False)
        return name if ok else None

    def _check(self):
        expr = self.expression.expression()
        resolved = engine.resolved(self.fmt, self.path, [{
            "name": "check", "layer": self.table, "type": self._type(), "expression": expr}])[0]["expression"]
        exp = QgsExpression(resolved)
        if exp.hasParserError():
            _warn(self, "The expression has an error:\n%s" % exp.parserErrorString())
            return
        layer = self._ctx_layer
        sample = next(layer.getFeatures(), None) if layer is not None else None
        if sample is None:
            QMessageBox.information(self, TITLE, "The expression is valid (the layer has no feature to test it on).")
            return
        ctx = engine._context(layer)
        ctx.setFeature(sample)
        value = exp.evaluate(ctx)
        if exp.hasEvalError():
            _warn(self, "The expression could not be evaluated:\n%s" % exp.evalErrorString())
            return
        QMessageBox.information(self, TITLE, "Valid. Result on feature %s: %s" % (sample.id(), value))

    def accept(self):
        t = self._type()
        keep_field = self.rule.get("field") if self.rule and self.rule.get("type") == t else None
        name = self.name.text().strip() or self._auto_name(t)
        rule = {
            "name": name, "layer": self.table, "type": t,
            "field": self.field.currentData() if t == "calculation" else keep_field,
            "expression": self.expression.expression().strip(),
            "on_update": t == "calculation" and self.on_update.isChecked(),
            "message": self.message.text().strip() if t != "calculation" else "",
            "strict": t == "constraint" and self.strict.isChecked(),
            "enabled": self.enabled.isChecked(),
            "order": self.rule.get("order", 0) if self.rule else max([r.get("order", 0) for r in self.rules] or [0]) + 1,
        }
        others = [r for r in self.rules if r is not self.rule]
        taken = {r["name"] for r in others if r["layer"] == self.table}
        base, n = rule["name"], 2
        while rule["name"] in taken:
            rule["name"] = "%s (%d)" % (base, n)
            n += 1
        issues = logic.rule_issues(rule, others + [rule], self.fields, self.tables)
        if not issues:
            exp = QgsExpression(engine.resolved(self.fmt, self.path, [rule])[0]["expression"])
            if exp.hasParserError():
                issues.append("Expression error: %s" % exp.parserErrorString())
        if issues:
            _warn(self, "Please fix:\n\n- " + "\n- ".join(issues))
            return
        if t == "calculation" and rule["field"] in self.unsaved:
            QMessageBox.information(self, TITLE, "The rule is saved and already works in QGIS. The field '%s' "
                                    "is not saved to the file yet: save the layer edits so it is kept."
                                    % rule["field"])
        self.result_rule = rule
        super().accept()


# ---------------------------------------------------------------- rule list
class RulesDialog(QDialog):
    def __init__(self, fmt, path, rules, parent=None):
        super().__init__(parent)
        self.fmt, self.path, self.rules = fmt, path, rules
        self.setWindowTitle("Rules - " + fmt.label)
        self.setMinimumSize(760, 460)
        self.layer_combo = QComboBox()
        refresh = QPushButton("Refresh fields")
        refresh.clicked.connect(self._load_layers)
        top = QHBoxLayout()
        top.addWidget(QLabel("Layer:"))
        top.addWidget(self.layer_combo, 1)
        top.addWidget(refresh)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Rule", "Type", "Field", "When / message", "Active"])
        self.table.horizontalHeader().setStretchLastSection(True)
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.table)
        row = QHBoxLayout()
        for text, fn in (("Add rule...", self._add), ("Edit...", self._edit), ("Delete", self._delete),
                         ("Move up", lambda: self._move(-1)), ("Move down", lambda: self._move(1))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)
        self.layer_combo.currentIndexChanged.connect(self._fill)
        self._load_layers()

    def _load_layers(self):
        engine.flush_file(self.path)
        keep = self.layer_combo.currentText()
        self.info = {t["name"]: t for t in store.list_layers(self.fmt, self.path)}
        self.layer_combo.blockSignals(True)
        self.layer_combo.clear()
        for n in sorted(self.info):
            self.layer_combo.addItem(n)
        i = self.layer_combo.findText(keep)
        self.layer_combo.setCurrentIndex(max(i, 0))
        self.layer_combo.blockSignals(False)
        self._fill()

    def _mine(self):
        return logic.active([dict(r, enabled=True) for r in self.rules], self.layer_combo.currentText())

    def _rule_objects(self):
        table = self.layer_combo.currentText()
        return sorted([r for r in self.rules if r["layer"] == table], key=lambda r: (r.get("order", 0), r["name"]))

    def _fill(self, _i=None):
        rows = self._rule_objects()
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            when = ("insert + update" if r.get("on_update") else "insert") if r["type"] == "calculation" else (
                r.get("message") or "")
            if r["type"] == "constraint" and r.get("strict"):
                when += " (blocks map edits)"
            for c, text in enumerate((r["name"], logic.TYPE_LABELS[r["type"]], r.get("field") or "-", when,
                                      "yes" if r.get("enabled", True) else "no")):
                self.table.setItem(i, c, QTableWidgetItem(str(text)))

    def _selected(self):
        r = self.table.currentRow()
        rows = self._rule_objects()
        return rows[r] if 0 <= r < len(rows) else None

    def _save(self):
        try:
            engine.flush_file(self.path)
            store.save_rules(self.fmt, self.path, self.rules)
            engine.flush_file(self.path)
            engine.HOOK.apply_project(self.path)
        except store.DataError as e:
            _warn(self, str(e))
        self._fill()

    def _editor(self, rule=None):
        table = self.layer_combo.currentText()
        if not table:
            _warn(self, "No layer found in this file.")
            return None
        names, types, unsaved = engine.layer_fields(self.fmt, self.path, self.info[table])
        dlg = RuleEditDialog(self.fmt, self.path, table, names, sorted(self.info), self.rules, rule, self,
                             types=types, unsaved=unsaved, geometry=self.info[table].get("geometry"))
        return dlg.result_rule if dlg.exec() else None

    def _add(self):
        rule = self._editor()
        if rule:
            self.rules.append(rule)
            self._save()

    def _edit(self):
        old = self._selected()
        if old is None:
            _warn(self, "Select a rule first.")
            return
        rule = self._editor(old)
        if rule:
            self.rules[self.rules.index(old)] = rule
            self._save()

    def _delete(self):
        old = self._selected()
        if old is None:
            _warn(self, "Select a rule first.")
            return
        self.rules.remove(old)
        self._save()

    def _move(self, step):
        rows = self._rule_objects()
        r = self.table.currentRow()
        if not (0 <= r < len(rows)) or not (0 <= r + step < len(rows)):
            return
        for i, rule in enumerate(rows):
            rule["order"] = i
        rows[r]["order"], rows[r + step]["order"] = rows[r + step]["order"], rows[r]["order"]
        self._save()
        self.table.setCurrentCell(r + step, 0)


# ------------------------------------------------------------------ main
class HubDialog(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.fmt = store.FORMATS[0]
        self.rules = []
        self.setWindowTitle("%s %s" % (TITLE, plugin_version()))
        self.setMinimumWidth(580)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("<b>1. Choose the storage format</b>"))
        self.radios = []
        for f in store.FORMATS:
            r = QRadioButton(f.label)
            r.toggled.connect(lambda checked, fm=f: self._format_changed(checked, fm))
            lay.addWidget(r)
            self.radios.append(r)
        lay.addWidget(QLabel("<b>2. Choose the file</b>"))
        row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.editingFinished.connect(self._reload)
        b = QPushButton("Open existing...")
        b.clicked.connect(self._open)
        row.addWidget(self.path_edit, 1)
        row.addWidget(b)
        lay.addLayout(row)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        lay.addWidget(QLabel("<b>3. Rules</b>"))
        for group in ((("Rules...", self._rules_dialog), ("Apply to Loaded Layers", self._apply)),
                      (("Validate Data...", self._validate), ("Diagnostics...", self._diagnostics))):
            arow = QHBoxLayout()
            for text, fn in group:
                btn = QPushButton(text)
                btn.clicked.connect(fn)
                arow.addWidget(btn)
            lay.addLayout(arow)
        self.auto = QCheckBox("Apply the rules automatically whenever layers of a configured file are loaded "
                              "(recommended)")
        self.auto.setChecked(engine.is_auto())
        self.auto.toggled.connect(engine.set_auto)
        lay.addWidget(self.auto)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        lay.addWidget(close)
        self.radios[0].setChecked(True)

    def _format_changed(self, checked, fmt):
        if checked:
            self.fmt = fmt
            self.path_edit.clear()
            self._reload()

    def _open(self):
        start = self.path_edit.text()
        if self.fmt.directory:
            path = QFileDialog.getExistingDirectory(self, "Select the .gdb folder", start)
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Select file", start, self.fmt.open_filter)
        if path:
            self.path_edit.setText(path)
            self._reload()

    def _reload(self):
        path = self.path_edit.text().strip()
        self.rules = []
        if not path:
            self.status.setText("")
            return
        if not self.fmt.is_valid(path):
            self.status.setText("File not found or not a valid %s." % self.fmt.label)
            return
        try:
            engine.flush_file(path)
            self.rules = store.load_rules(self.fmt, path)
        except store.DataError as e:
            self.status.setText("Could not read the file: %s" % e)
            return
        layers = sorted({r["layer"] for r in self.rules})
        self.status.setText("%d rule(s) on %d layer(s)%s" % (
            len(self.rules), len(layers), (": " + ", ".join(layers)) if layers else "."))

    def _need(self):
        path = self.path_edit.text().strip()
        if not self.fmt.is_valid(path):
            _warn(self, "Choose an existing %s first." % self.fmt.label)
            return None
        return path

    def _rules_dialog(self):
        path = self._need()
        if not path:
            return
        try:
            dlg = RulesDialog(self.fmt, path, self.rules, self)
        except store.DataError as e:
            _warn(self, str(e))
            return
        if not dlg.info:
            _warn(self, "No layers found in this file.")
            return
        dlg.exec()
        self._reload()

    def _apply(self):
        path = self._need()
        if not path:
            return
        self._reload()
        lines = []
        for table in sorted({r["layer"] for r in self.rules}):
            layer = engine.load_layer(self.fmt, path, table)
            if layer is None:
                lines.append("[X] %s: could not load the layer" % table)
                continue
            try:
                notes = engine.apply_layer(layer, self.fmt, path, self.rules)
                engine.HOOK.watcher.watch(layer, self.fmt, path, self.rules)
                lines.append("[OK] %s" % table)
                lines += ["      - " + n for n in notes]
            except Exception:
                lines.append("[X] %s:" % table)
                lines += ["      " + ln for ln in traceback.format_exc().splitlines()]
        ReportDialog("Apply to Loaded Layers", lines or ["No rules yet."], self).exec()

    def _validate(self):
        path = self._need()
        if not path:
            return
        self._reload()
        try:
            lines, problems, found = engine.validate(self.fmt, path, self.rules)
        except Exception:
            ReportDialog("Validate failed - send this text", traceback.format_exc().splitlines(), self).exec()
            return
        lines.append("Result: %s" % ("everything respects the rules." if not problems
                                     else "%d problem(s) found." % problems))

        def select():
            for table, fids in found.items():
                layer = engine.load_layer(self.fmt, path, table)
                if layer is not None:
                    layer.selectByIds(fids)
            QMessageBox.information(self, TITLE, "The features with problems are now selected.")

        extra = [("Select features with problems", select)] if found else []
        ReportDialog("Validate Data", lines, self, extra).exec()

    def _diagnostics(self):
        path = self.path_edit.text().strip()
        lines = [
            "Plugin version: %s" % plugin_version(),
            "QGIS: %s | GDAL: %s | Python: %s | Qt: %s" % (
                Qgis.version(), gdal.__version__, sys.version.split()[0], QT_VERSION_STR),
            "Format: %s | Path: %s | valid: %s" % (self.fmt.label, path, self.fmt.is_valid(path)),
            "Automatic apply: %s" % ("on" if engine.is_auto() else "off"), "",
        ]
        try:
            if self.fmt.is_valid(path):
                engine.flush_file(path)
                rules = store.load_rules(self.fmt, path)
                for t in store.list_layers(self.fmt, path):
                    lines.append("Layer in file: %s | fields: %s" % (t["name"], ", ".join(t["fields"])))
                for r in rules:
                    lines.append("Rule %s on %s: %s | field=%s | expr=%s | update=%s strict=%s active=%s" % (
                        r["name"], r["layer"], r["type"], r.get("field"), r["expression"],
                        r.get("on_update"), r.get("strict"), r.get("enabled")))
                lines.append("")
                for lyr in QgsProject.instance().mapLayers().values():
                    lpath, table = engine.split_source(lyr.source())
                    if engine._norm(lpath) != engine._norm(path):
                        continue
                    lines.append("Loaded: %s (table %s) watched=%s" % (
                        lyr.name(), table, lyr.id() in engine.HOOK.watcher.layers))
                    for i in range(lyr.fields().count()):
                        d = lyr.defaultValueDefinition(i).expression()
                        c = lyr.constraintExpression(i)
                        if d or c:
                            lines.append("    %s: default=%s | constraint=%s" % (
                                lyr.fields().at(i).name(), d or "-", c or "-"))
        except Exception:
            lines += traceback.format_exc().splitlines()
        ReportDialog("Diagnostics - copy this text and send it", lines, self).exec()
