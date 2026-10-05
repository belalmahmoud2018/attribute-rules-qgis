"""Pure helpers for attribute rules (no QGIS / GDAL imports).

rule : {"name", "layer", "type": "calculation"|"constraint"|"validation", "field",
        "expression", "on_update": bool, "message", "strict": bool, "enabled": bool, "order": int}
Expressions are QGIS expressions. [[table]] means "the layer `table` of the same file".
"""
import re

TYPES = ("calculation", "constraint", "validation")
TYPE_LABELS = {"calculation": "Calculation", "constraint": "Constraint", "validation": "Validation"}
LAYER_REF = re.compile(r"\[\[([^\[\]]+)\]\]")
# 'name' as the layer argument of functions that take a layer
LAYER_ARG = re.compile(
    r"((?:overlay_\w+|aggregate|get_feature|get_feature_by_id)\(\s*(?:layer\s*:=\s*)?)'((?:[^']|'')+)'",
    re.IGNORECASE)

# (label, type, expression, needs another layer, hint shown after "Use template")
_LAT = "y(transform(centroid($geometry), @layer_crs, 'EPSG:4326'))"
_LON = "x(transform(centroid($geometry), @layer_crs, 'EPSG:4326'))"
_UNIQUE = ("array_length(array_remove_all(aggregate(@layer, 'array_agg', $id, "
           "filter:={field} = attribute(@parent, '{name}')), $id)) = 0")
_NO_OVERLAP = ("array_length(array_filter(overlay_intersects(@layer, $id), @element <> $id AND "
               "area(intersection(geometry(get_feature_by_id(@layer, @element)), $geometry)) > 0.0001)) = 0")
_POINTS_APART = "array_length(array_remove_all(overlay_nearest(@layer, $id, limit:=2, max_distance:=1), $id)) = 0"
TEMPLATES = [
    # ---------------------------------------------------------------- calculation
    ("Area (square meters)", "calculation", "$area", False, ""),
    ("Area (hectares)", "calculation", "$area / 10000", False, ""),
    ("Area (square kilometers)", "calculation", "$area / 1000000", False, ""),
    ("Area (dunam = 1000 m2)", "calculation", "$area / 1000", False, ""),
    ("Area (feddan = 4200.83 m2)", "calculation", "$area / 4200.83", False, ""),
    ("Perimeter (meters)", "calculation", "$perimeter", False, ""),
    ("Length of a line (meters)", "calculation", "$length", False, ""),
    ("Length of a line (kilometers)", "calculation", "$length / 1000", False, ""),
    ("X of the center", "calculation", "x(centroid($geometry))", False, ""),
    ("Y of the center", "calculation", "y(centroid($geometry))", False, ""),
    ("Longitude of the center", "calculation", _LON, False, ""),
    ("Latitude of the center", "calculation", _LAT, False, ""),
    ("Coordinates as text (latitude, longitude)", "calculation",
     "to_string(round(" + _LAT + ", 6)) || ', ' || to_string(round(" + _LON + ", 6))", False,
     "Use a text field."),
    ("Google Maps link", "calculation",
     "'https://www.google.com/maps?q=' || to_string(round(" + _LAT + ", 6)) || ',' || to_string(round(" + _LON + ", 6))",
     False, "Use a text field (long enough, e.g. 100 characters)."),
    ("Number of vertices", "calculation", "num_points($geometry)", False, ""),
    ("Number of parts", "calculation", "num_geometries($geometry)", False, ""),
    ("Width of the bounding box", "calculation", "bounds_width($geometry)", False, ""),
    ("Height of the bounding box", "calculation", "bounds_height($geometry)", False, ""),
    ("Next number (auto ID)", "calculation", "coalesce(maximum({field}), 0) + 1", False,
     "Do not tick 'Recalculate', so the number never changes."),
    ("Date and time now", "calculation", "now()", False,
     "Without 'Recalculate' = creation date; with it = last edit date."),
    ("Date only (today)", "calculation", "to_date(now())", False, "Use a Date field."),
    ("Current year", "calculation", "year(now())", False, ""),
    ("User name of the editor", "calculation", "@user_account_name", False,
     "Without 'Recalculate' = created by; with it = last edited by."),
    ("Unique identifier (UUID)", "calculation", "uuid()", False, "Use a text field; do not tick 'Recalculate'."),
    ("Value from the layer it falls in", "calculation", "array_first(overlay_intersects('[[layer]]', \"name\"))", True,
     "Replace \"name\" with the field of the other layer whose value you want."),
    ("Count of features of another layer inside it", "calculation",
     "array_length(overlay_intersects('[[layer]]', $id))", True, ""),
    ("Sum of a field of another layer inside it", "calculation",
     "array_sum(overlay_intersects('[[layer]]', \"value\"))", True,
     "Replace \"value\" with the numeric field of the other layer to add up."),
    ("Name of the nearest feature of another layer", "calculation",
     "array_first(overlay_nearest('[[layer]]', \"name\"))", True,
     "Replace \"name\" with the field of the other layer whose value you want."),
    ("Distance to the nearest feature of another layer", "calculation",
     "distance($geometry, array_first(overlay_nearest('[[layer]]', $geometry)))", True,
     "The distance is in the units of the layer's coordinate system."),
    # ---------------------------------------------------------------- constraint
    ("Must not be empty", "constraint", "{field} IS NOT NULL", False, ""),
    ("Must not be empty or only spaces", "constraint", "length(trim(coalesce(to_string({field}), ''))) > 0", False, ""),
    ("Must be unique in the layer", "constraint", _UNIQUE, False, ""),
    ("Must be greater than zero", "constraint", "{field} > 0", False, ""),
    ("Must not be negative", "constraint", "{field} IS NULL OR {field} >= 0", False, ""),
    ("Must be between two values", "constraint", "{field} IS NULL OR ({field} >= 1 AND {field} <= 100)", False,
     "Change 1 and 100 to your limits."),
    ("Must be one of a list of values", "constraint", "{field} IS NULL OR {field} IN ('A', 'B', 'C')", False,
     "Replace 'A', 'B', 'C' with the allowed values."),
    ("Text at most 50 characters", "constraint", "{field} IS NULL OR length({field}) <= 50", False,
     "Change 50 to your limit."),
    ("Valid e-mail address", "constraint",
     "{field} IS NULL OR regexp_match({field}, '^[^@\\\\s]+@[^@\\\\s]+\\\\.[^@\\\\s]+$')", False, ""),
    ("Phone number of 10 digits", "constraint", "{field} IS NULL OR regexp_match({field}, '^[0-9]{10}$')", False,
     "Change {10} to the number of digits you need."),
    ("Date must not be in the future", "constraint", "{field} IS NULL OR {field} <= now()", False, ""),
    ("End date not before start date", "constraint",
     "\"end_date\" IS NULL OR \"start_date\" IS NULL OR \"end_date\" >= \"start_date\"", False,
     "Replace \"end_date\" and \"start_date\" with your two date fields."),
    ("Geometry must be valid", "constraint", "is_valid($geometry)", False, ""),
    ("Must be a single part (not multipart)", "constraint", "num_geometries($geometry) = 1", False, ""),
    ("Polygon must not have holes", "constraint", "num_interior_rings($geometry) = 0", False, ""),
    ("Area must be at least 100 m2", "constraint", "$area >= 100", False, "Change 100 to your minimum."),
    ("Line must be at least 1 m long", "constraint", "$length >= 1", False, "Change 1 to your minimum."),
    ("Polygons of this layer must not overlap each other", "constraint", _NO_OVERLAP, False,
     "Touching edges are allowed; only real overlaps are refused."),
    ("Points of this layer must be at least 1 m apart", "constraint", _POINTS_APART, False,
     "Change max_distance:=1 to your minimum distance."),
    ("Must NOT be inside or on the edge of another layer", "constraint",
     "NOT overlay_nearest('[[layer]]', max_distance:=0.01)", True, ""),
    ("Must be inside another layer", "constraint", "overlay_within('[[layer]]')", True, ""),
    ("Must not be within 10 m of another layer", "constraint",
     "NOT overlay_nearest('[[layer]]', max_distance:=10)", True, "Change 10 to your distance (layer CRS units)."),
    ("Must not intersect another layer", "constraint", "NOT overlay_intersects('[[layer]]')", True, ""),
    ("Must touch or intersect another layer", "constraint", "overlay_intersects('[[layer]]')", True, ""),
    # ---------------------------------------------------------------- validation
    ("Field must be filled (check existing data)", "validation", "{field} IS NOT NULL", False, ""),
    ("No duplicates in the field (check existing data)", "validation",
     "count({field}, group_by:={field}) = 1", False, "Empty values are reported too."),
    ("Must be greater than zero (check existing data)", "validation", "{field} > 0", False, ""),
    ("Must be one of a list of values (check existing data)", "validation",
     "{field} IN ('A', 'B', 'C')", False, "Replace 'A', 'B', 'C' with the allowed values."),
    ("Date must not be in the future (check existing data)", "validation", "{field} IS NULL OR {field} <= now()",
     False, ""),
    ("Geometry must be valid (check existing data)", "validation", "is_valid($geometry)", False, ""),
    ("Geometry must not be empty (check existing data)", "validation",
     "$geometry IS NOT NULL AND NOT is_empty($geometry)", False, ""),
    ("No duplicate geometries (check existing data)", "validation",
     "count(geom_to_wkt($geometry), group_by:=geom_to_wkt($geometry)) = 1", False,
     "Can be slow on very large layers."),
    ("Must be a single part (check existing data)", "validation", "num_geometries($geometry) = 1", False, ""),
    ("Area at least 100 m2 (check existing data)", "validation", "$area >= 100", False, "Change 100 to your minimum."),
    ("Polygons must not overlap each other (check existing data)", "validation", _NO_OVERLAP, False, ""),
    ("Points at least 1 m apart (check existing data)", "validation", _POINTS_APART, False, ""),
    ("Must be inside another layer (check existing data)", "validation", "overlay_within('[[layer]]')", True, ""),
    ("Must not intersect another layer (check existing data)", "validation",
     "NOT overlay_intersects('[[layer]]')", True, ""),
]


def q_ident(name):
    return '"%s"' % str(name).replace('"', '""')


def q_str(text):
    return "'%s'" % str(text).replace("'", "''")


def templates_for(rule_type):
    return [t for t in TEMPLATES if t[1] == rule_type]


def fill_template(expression, field=None, layer=None):
    out = expression.replace("{name}", str(field or "field").replace("'", "''"))
    out = out.replace("{field}", q_ident(field) if field else '"field"')
    if layer:
        out = out.replace("[[layer]]", str(layer).replace("'", "''"))
    return out


def referenced_layers(expression):
    names = set(LAYER_REF.findall(expression or ""))
    names |= {m.group(2).replace("''", "'") for m in LAYER_ARG.finditer(expression or "")}
    names.discard("[[layer]]")
    return sorted(names)


def resolve(expression, layer_ids):
    """Point layer names / [[table]] at the QGIS layer ids of the same file.

    Names that are not layers of the file are left alone (QGIS then looks them up by name).
    """
    def repl_ref(match):
        lid = layer_ids.get(match.group(1))
        return q_str(lid) if lid else q_str(match.group(1))

    def repl_arg(match):
        lid = layer_ids.get(match.group(2).replace("''", "'"))
        return match.group(1) + q_str(lid) if lid else match.group(0)

    return LAYER_ARG.sub(repl_arg, LAYER_REF.sub(repl_ref, expression or ""))


def active(rules, layer, rule_type=None):
    out = [r for r in rules if r["layer"] == layer and r.get("enabled", True)]
    if rule_type:
        out = [r for r in out if r["type"] == rule_type]
    return sorted(out, key=lambda r: (r.get("order", 0), r["name"]))


def combined_constraint(rules, layer, field):
    """(expression, description) of all enabled constraint rules shown on `field`.

    `rules` may carry an "_target" key: the field a rule without its own field is shown on.
    """
    mine = [r for r in active(rules, layer, "constraint") if (r.get("field") or r.get("_target")) == field]
    if not mine:
        return None, None
    expr = " AND ".join("(%s)" % r["expression"] for r in mine)
    desc = " | ".join("%s: %s" % (r["name"], r.get("message") or "rule broken") for r in mine)
    return expr, desc


def rule_issues(rule, rules, field_names, table_names):
    """Problems with one rule before saving it (list of messages)."""
    issues = []
    if rule["type"] not in TYPES:
        issues.append("Unknown rule type.")
    if not (rule.get("expression") or "").strip():
        issues.append("The rule needs an expression.")
    if rule["type"] == "calculation" and not rule.get("field"):
        issues.append("Choose the field to calculate.")
    if rule.get("field") and rule["field"] not in field_names:
        issues.append("Field '%s' does not exist in the layer." % rule["field"])
    for other in rules:
        if other is rule or other["layer"] != rule["layer"]:
            continue
        if (rule["type"] == "calculation" and other["type"] == "calculation" and other.get("enabled", True)
                and rule.get("enabled", True) and other.get("field") == rule.get("field")):
            issues.append("Field '%s' already has a calculation rule ('%s')." % (rule["field"], other["name"]))
    for t in LAYER_REF.findall(rule.get("expression") or ""):
        if t != "layer" and t not in table_names:
            issues.append("[[%s]] is not a layer of this file." % t)
    if "[[layer]]" in (rule.get("expression") or ""):
        issues.append("Pick the other layer for this template ('[[layer]]' is still in the expression).")
    return issues
