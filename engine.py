"""QGIS side: apply rules to layers, watch edits, run validation."""
import contextlib
import re
import time
import traceback

from qgis.core import (
    Qgis,
    QgsDefaultValue,
    QgsExpression,
    QgsExpressionContext,
    QgsExpressionContextUtils,
    QgsFieldConstraints,
    QgsMessageLog,
    QgsProject,
    QgsSettings,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QTimer

from . import logic, store

TAG = "Attribute Rules"
SETTING = "AttributeRulesManager/auto_apply"


# ------------------------------------------------------------------ compat
def constraint_flag():
    value = getattr(QgsFieldConstraints, "ConstraintExpression", None)
    if value is None:  # QGIS 4 / scoped enums
        value = QgsFieldConstraints.Constraint.ConstraintExpression
    return value


def _level(name):
    value = getattr(Qgis, name, None)
    return value if value is not None else getattr(Qgis.MessageLevel, name)


def log(message, warning=False):
    QgsMessageLog.logMessage(message, TAG, _level("Warning" if warning else "Info"))


def is_auto():
    return QgsSettings().value(SETTING, True, type=bool)


def set_auto(value):
    QgsSettings().setValue(SETTING, bool(value))


# ------------------------------------------------------------ layer finding
def _norm(p):
    return (p or "").replace("\\", "/").rstrip("/").lower()


def split_source(src):
    if src.startswith("dbname="):
        db = re.search(r"dbname='([^']*)'", src)
        tbl = re.search(r'table="([^"]*)"', src)
        return (db.group(1) if db else ""), (tbl.group(1) if tbl else "")
    parts = src.split("|")
    name = ""
    for p in parts[1:]:
        if p.lower().startswith("layername="):
            name = p.split("=", 1)[1]
    return parts[0], name


def find_loaded(path, table):
    for layer in QgsProject.instance().mapLayers().values():
        with contextlib.suppress(Exception):
            lpath, lname = split_source(layer.source())
            if _norm(lpath) == _norm(path) and lname == table:
                return layer
    return None


def load_layer(fmt, path, table, in_legend=True):
    layer = find_loaded(path, table)
    if layer is not None:
        return layer
    layer = QgsVectorLayer(fmt.uri(path, table), table, "ogr")
    if not layer.isValid():
        return None
    QgsProject.instance().addMapLayer(layer, in_legend)
    return layer


def context_layer(fmt, path, table):
    """A layer object for expression builders: the loaded one, or a temporary one."""
    layer = find_loaded(path, table)
    if layer is None:
        layer = QgsVectorLayer(fmt.uri(path, table), table, "ogr")
    return layer if layer.isValid() else None


PK_NAMES = {"fid", "ogc_fid", "objectid", "ogr_fid"}


def layer_fields(fmt, path, info):
    """Fields of a layer: those in the file plus any added in QGIS and not saved yet.

    Returns (names, {name: type label}, names not saved to the file yet).
    """
    names = list(info["fields"])
    types = dict(info.get("types", {}))
    unsaved = []
    layer = find_loaded(path, info["name"])
    if layer is not None:
        pks = {layer.fields().at(i).name() for i in layer.primaryKeyAttributes()} if hasattr(
            layer, "primaryKeyAttributes") else set()
        lower = {n.lower() for n in names}
        for fld in layer.fields():
            n = fld.name()
            if n in pks or n.lower() in PK_NAMES:
                continue
            if n.lower() not in lower:
                names.append(n)
                unsaved.append(n)
            friendly = fld.friendlyTypeString() if hasattr(fld, "friendlyTypeString") else ""
            types[n] = fld.typeName() or friendly or types.get(n, "")
    return names, types, unsaved


def flush_file(path):
    """Let QGIS write what it holds for this file so GDAL readers/writers see the same data."""
    for layer in list(QgsProject.instance().mapLayers().values()):
        with contextlib.suppress(Exception):
            lpath, _name = split_source(layer.source())
            if _norm(lpath) != _norm(path) or layer.isModified():
                continue
            provider = layer.dataProvider()
            if provider is not None:
                provider.reloadData()


def resolved(fmt, path, rules):
    """Copies of `rules` with [[table]] replaced by the ids of (hidden-)loaded layers."""
    ids, out = {}, []
    for r in rules:
        for t in logic.referenced_layers(r["expression"]):
            if t not in ids:
                lyr = load_layer(fmt, path, t, in_legend=False)
                if lyr is not None:
                    ids[t] = lyr.id()
        copy = dict(r)
        copy["expression"] = logic.resolve(r["expression"], ids)
        out.append(copy)
    return out


# ------------------------------------------------------------------ apply
def apply_layer(layer, fmt, path, rules):
    """Configure calculation and constraint rules on `layer`. Returns report notes."""
    _lpath, table = split_source(layer.source())
    mine = resolved(fmt, path, logic.active(rules, table))
    fields = layer.fields()
    notes, touched = [], set()
    for r in [x for x in mine if x["type"] == "calculation"]:
        idx = fields.lookupField(r["field"] or "")
        if idx < 0:
            notes.append("[X] %s: field %s not found" % (r["name"], r["field"]))
            continue
        layer.setDefaultValueDefinition(idx, QgsDefaultValue(r["expression"], bool(r["on_update"])))
        touched.add(fields.at(idx).name())
        when = "on insert and update" if r["on_update"] else "on insert"
        notes.append("%s: %s = %s (%s)" % (r["name"], r["field"], r["expression"], when))
    first = fields.at(0).name() if fields.count() else None
    for x in mine:
        if x["type"] == "constraint" and not x.get("field"):
            x["_target"] = first  # rules without a field are shown on the first field (fid in GeoPackage)
            if first is None:
                notes.append("%s: the layer has no fields, so the form cannot check it - map edits are "
                             "checked%s" % (x["name"], " and undone" if x.get("strict") else " (warning only)"))
    for fname in sorted({x.get("field") or x.get("_target") for x in mine
                         if x["type"] == "constraint" and (x.get("field") or x.get("_target"))}):
        idx = fields.lookupField(fname)
        if idx < 0:
            notes.append("[X] constraint field %s not found" % fname)
            continue
        expr, desc = logic.combined_constraint(mine, table, fname)
        layer.setConstraintExpression(idx, expr, desc)
        layer.setFieldConstraint(idx, constraint_flag())
        touched.add(fields.at(idx).name())
        notes.append("constraint on %s: %s" % (fname, desc))
    previous = [f for f in (layer.customProperty("ar/fields") or "").split("|") if f]
    for fname in previous:
        idx = fields.lookupField(fname)
        if fname in touched or idx < 0:
            continue
        layer.setDefaultValueDefinition(idx, QgsDefaultValue())
        layer.removeFieldConstraint(idx, constraint_flag())
        layer.setConstraintExpression(idx, "")
    layer.setCustomProperty("ar/fields", "|".join(sorted(touched)))
    return notes


# ------------------------------------------------------------ rule checking
def _context(layer):
    return QgsExpressionContext(QgsExpressionContextUtils.globalProjectLayerScopes(layer))


def broken_rules(layer, feature, rules):
    """Rules (resolved) that `feature` does not satisfy."""
    out = []
    ctx = _context(layer)
    ctx.setFeature(feature)
    for r in rules:
        exp = QgsExpression(r["expression"])
        value = exp.evaluate(ctx)
        if exp.hasEvalError() or exp.hasParserError():
            log("Rule %s could not be evaluated: %s" % (r["name"], exp.evalErrorString() or exp.parserErrorString()),
                warning=True)
            continue
        if not value:
            out.append(r)
    return out


def validate(fmt, path, rules, tables=None):
    """Check existing data. Returns (lines, problems, {table: [fids]})."""
    lines, problems, found = [], 0, {}
    layer_names = sorted({r["layer"] for r in rules if r.get("enabled", True)
                          and r["type"] in ("constraint", "validation")})
    if tables:
        layer_names = [n for n in layer_names if n in tables]
    if not layer_names:
        return ["No constraint or validation rules yet."], 0, {}
    for table in layer_names:
        layer = context_layer(fmt, path, table)
        lines.append("Layer: %s" % table)
        if layer is None:
            lines.append("    [X] could not open the layer")
            problems += 1
            continue
        checks = [r for r in resolved(fmt, path, logic.active(rules, table))
                  if r["type"] in ("constraint", "validation")]
        ctx = _context(layer)
        prepared = []
        for r in checks:
            exp = QgsExpression(r["expression"])
            exp.prepare(ctx)
            prepared.append((r, exp, {"count": 0, "fids": []}))
        for feat in layer.getFeatures():
            ctx.setFeature(feat)
            for r, exp, stats in prepared:
                if not exp.evaluate(ctx) and not exp.hasEvalError():
                    stats["count"] += 1
                    stats["fids"].append(feat.id())
        for r, exp, stats in prepared:
            if exp.hasParserError() or exp.hasEvalError():
                lines.append("    [X] %s: expression error - %s" % (
                    r["name"], exp.parserErrorString() or exp.evalErrorString()))
                problems += 1
            elif stats["count"]:
                problems += stats["count"]
                found.setdefault(table, []).extend(stats["fids"])
                shown = ", ".join(str(f) for f in stats["fids"][:15])
                lines.append("    [X] %s (%s): %d feature(s) - FID %s%s" % (
                    r["name"], r.get("message") or r["type"], stats["count"], shown,
                    " ..." if stats["count"] > 15 else ""))
            else:
                lines.append("    [OK] %s" % r["name"])
        lines.append("")
    return lines, problems, found


# --------------------------------------------------------- live edit watch
class Watcher:
    """Checks constraint rules while editing (also edits made without the form) and
    undoes geometry/feature edits that break a rule marked 'strict'."""

    def __init__(self, iface=None):
        self.iface = iface
        self.layers = {}  # layer id -> (layer, rules, slots)
        self._busy = False

    def watch(self, layer, fmt, path, rules):
        _lpath, table = split_source(layer.source())
        mine = [r for r in resolved(fmt, path, logic.active(rules, table)) if r["type"] == "constraint"]
        old = self.layers.pop(layer.id(), None)
        if old:
            self._disconnect(old)
        if not mine:
            return
        slots = (
            (layer.featureAdded, lambda fid, lid=layer.id(): self._check(lid, fid, "added")),
            (layer.geometryChanged, lambda fid, _g, lid=layer.id(): self._check(lid, fid, "geometry")),
        )
        for signal, slot in slots:
            signal.connect(slot)
        self.layers[layer.id()] = (layer, mine, slots)

    @staticmethod
    def _disconnect(entry):
        for signal, slot in entry[2]:
            with contextlib.suppress(TypeError, RuntimeError):
                signal.disconnect(slot)

    def unwatch_all(self):
        for entry in self.layers.values():
            self._disconnect(entry)
        self.layers = {}

    def _check(self, layer_id, fid, what):
        if self._busy:
            return
        entry = self.layers.get(layer_id)
        if not entry:
            return
        layer, rules, _slots = entry
        try:
            if not layer.isEditable():
                return
            feat = layer.getFeature(fid)
            if not feat.isValid():
                return
            broken = broken_rules(layer, feat, rules)
        except Exception:
            log("Rule check failed\n%s" % traceback.format_exc(), warning=True)
            return
        if not broken:
            return
        text = "; ".join("%s: %s" % (r["name"], r.get("message") or "rule broken") for r in broken)
        strict = any(r.get("strict") for r in broken)
        if strict:
            text += " - the edit was undone."
            QTimer.singleShot(0, lambda: self._undo(layer))
        if self.iface is not None:
            self.iface.messageBar().pushCritical(TAG, text) if strict else self.iface.messageBar().pushWarning(TAG, text)
        log("%s (%s, feature %s)" % (text, layer.name(), fid), warning=True)

    def _undo(self, layer):
        self._busy = True
        try:
            with contextlib.suppress(RuntimeError):
                layer.undoStack().undo()
        finally:
            self._busy = False


# ------------------------------------------------------------ auto apply
_CACHE = {}


def cached_rules(fmt, path):
    key = _norm(path)
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < 15:
        return hit[1]
    rules = store.load_rules(fmt, path)
    _CACHE[key] = (time.time(), rules)
    return rules


def invalidate(path=None):
    if path is None:
        _CACHE.clear()
    else:
        _CACHE.pop(_norm(path), None)


class Hook:
    def __init__(self, iface=None):
        self.watcher = Watcher(iface)
        self.connected = False

    def apply_to_layers(self, layers, only_path=None):
        count = 0
        for layer in layers:
            try:
                if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
                    continue
                if layer.providerType() not in ("ogr", "spatialite"):
                    continue
                path, table = split_source(layer.source())
                if not table or (only_path and _norm(path) != _norm(only_path)):
                    continue
                fmt = store.detect_format(path)
                if fmt is None or not fmt.is_valid(path) or table.lower() in store.HELPER_TABLES:
                    continue
                rules = cached_rules(fmt, path)
                if not any(r["layer"] == table for r in rules):
                    if layer.customProperty("ar/fields"):
                        apply_layer(layer, fmt, path, rules)  # clears what an older setup left
                    continue
                apply_layer(layer, fmt, path, rules)
                self.watcher.watch(layer, fmt, path, rules)
                count += 1
            except Exception:
                log("Could not apply rules\n%s" % traceback.format_exc(), warning=True)
        return count

    def apply_project(self, path=None):
        invalidate(path)
        return self.apply_to_layers(list(QgsProject.instance().mapLayers().values()), path)

    def connect(self):
        if self.connected:
            return
        QgsProject.instance().layersAdded.connect(self._added)
        QgsProject.instance().readProject.connect(self._read)
        self.connected = True

    def disconnect(self):
        self.watcher.unwatch_all()
        if not self.connected:
            return
        for signal, slot in ((QgsProject.instance().layersAdded, self._added),
                             (QgsProject.instance().readProject, self._read)):
            with contextlib.suppress(TypeError):
                signal.disconnect(slot)
        self.connected = False

    def _added(self, layers):
        if not is_auto():
            return
        ids = [lyr.id() for lyr in layers]
        QTimer.singleShot(0, lambda: self.apply_to_layers(
            [QgsProject.instance().mapLayer(i) for i in ids if QgsProject.instance().mapLayer(i) is not None]))

    def _read(self, *_args):
        if is_auto():
            QTimer.singleShot(0, self.apply_project)


HOOK = Hook()
