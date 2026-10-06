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
_OVERLAP_GEOM = "intersection($geometry, collect_geometries(overlay_intersects('[[layer]]', $geometry)))"
_UNIQUE_PAIR = ("array_length(array_remove_all(aggregate(@layer, 'array_agg', $id, "
                "filter:=concat(\"field_a\", '|', \"field_b\") = "
                "concat(attribute(@parent, 'field_a'), '|', attribute(@parent, 'field_b'))), $id)) = 0")
_NO_OVERLAP_OTHER = ("array_length(array_filter(overlay_intersects('[[layer]]', $geometry), "
                     "area(intersection(@element, $geometry)) > 0.0001)) = 0")
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
    ("Area (square feet)", "calculation", "$area * 10.7639", False, ""),
    ("Area (acres)", "calculation", "$area / 4046.86", False, ""),
    ("Area rounded to 2 decimals", "calculation", "round($area, 2)", False, ""),
    ("Area in the layer's own units (no ellipsoid)", "calculation", "area($geometry)", False, ""),
    ("Perimeter (kilometers)", "calculation", "$perimeter / 1000", False, ""),
    ("Compactness (1 = circle)", "calculation", "4 * pi() * $area / ($perimeter ^ 2)", False, ""),
    ("X of the line start", "calculation", "x(start_point($geometry))", False, ""),
    ("Y of the line start", "calculation", "y(start_point($geometry))", False, ""),
    ("X of the line end", "calculation", "x(end_point($geometry))", False, ""),
    ("Y of the line end", "calculation", "y(end_point($geometry))", False, ""),
    ("Line direction (degrees from north)", "calculation",
     "degrees(azimuth(start_point($geometry), end_point($geometry)))", False, ""),
    ("Elevation (Z) of a point", "calculation", "z($geometry)", False, "Only for 3D layers; empty otherwise."),
    ("Geometry type", "calculation", "geometry_type($geometry)", False, "Use a text field."),
    ("Latitude in degrees, minutes, seconds", "calculation", "to_dms(" + _LAT + ", 'y', 2)", False,
     "Use a text field."),
    ("Longitude in degrees, minutes, seconds", "calculation", "to_dms(" + _LON + ", 'x', 2)", False,
     "Use a text field."),
    ("UTM zone number", "calculation", "to_int(floor((" + _LON + " + 180) / 6) + 1)", False, ""),
    ("Next code with a prefix (P-00001)", "calculation",
     "'P-' || lpad(to_string(coalesce(maximum(to_int(substr({field}, 3))), 0) + 1), 5, '0')", False,
     "Text field. Change 'P-' to your prefix; if its length is not 2, change substr(..., 3) to the length + 1; "
     "5 is the number of digits."),
    ("Days remaining until a date", "calculation", "day(age(to_date(\"end_date\"), to_date(now())))", False,
     "Replace \"end_date\" with your date field; negative = already passed."),
    ("Status from an end date (Active / Expired)", "calculation",
     "CASE WHEN \"end_date\" IS NULL THEN NULL WHEN \"end_date\" < to_date(now()) THEN 'Expired' ELSE 'Active' END",
     False, "Replace \"end_date\"; you can write other words instead of 'Active' and 'Expired'. Tick 'Recalculate'."),
    ("Year of a date field", "calculation", "year(\"date_field\")", False, "Replace \"date_field\" with your date field."),
    ("Upper-case copy of another field", "calculation", "upper(\"source_field\")", False,
     "Replace \"source_field\" with the field to copy."),
    ("Copy of another field without extra spaces", "calculation", "trim(\"source_field\")", False,
     "Replace \"source_field\" with the field to copy."),
    ("Join two fields", "calculation", "concat(\"field_a\", ' - ', \"field_b\")", False,
     "Replace \"field_a\" and \"field_b\"; change ' - ' to the separator you want."),
    ("Number of characters of another field", "calculation", "length(\"source_field\")", False,
     "Replace \"source_field\" with the text field."),
    ("Another field rounded to 2 decimals", "calculation", "round(\"source_field\", 2)", False,
     "Replace \"source_field\" with the numeric field."),
    ("Percentage of two fields", "calculation",
     "CASE WHEN \"total\" IS NULL OR \"total\" = 0 THEN NULL ELSE \"part\" / \"total\" * 100 END", False,
     "Replace \"part\" and \"total\" with your two numeric fields."),
    ("Price per square meter", "calculation", "\"price\" / $area", False, "Replace \"price\" with your price field."),
    ("Value from a lookup layer (by code)", "calculation",
     "attribute(get_feature('[[layer]]', 'code', \"code\"), 'name')", True,
     "get_feature(layer, its key field, this layer's key field); then the field to bring. Replace 'code', \"code\" "
     "and 'name' with your field names."),
    ("Count of features of another layer within 100 m", "calculation",
     "array_length(overlay_nearest('[[layer]]', $id, limit:=-1, max_distance:=100))", True,
     "Change 100 to your distance (layer CRS units)."),
    ("Overlap area with another layer", "calculation", "coalesce(area(" + _OVERLAP_GEOM + "), 0)", True, ""),
    ("Percent of the area covered by another layer", "calculation",
     "coalesce(100 * area(" + _OVERLAP_GEOM + ") / $area, 0)", True, ""),
    ("Length of lines of another layer inside it", "calculation",
     "coalesce(length(intersection(collect_geometries(overlay_intersects('[[layer]]', $geometry)), $geometry)), 0)",
     True, "Choose a line layer as the other layer."),
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
    ("Whole number, no decimals", "constraint", "{field} IS NULL OR {field} = round({field})", False, ""),
    ("At least 3 characters", "constraint", "{field} IS NULL OR length({field}) >= 3", False,
     "Change 3 to your minimum."),
    ("Must start with a prefix", "constraint", "{field} IS NULL OR left({field}, 2) = 'P-'", False,
     "Change 'P-' to your prefix and 2 to its number of characters."),
    ("Upper case only", "constraint", "{field} IS NULL OR {field} = upper({field})", False, ""),
    ("Digits only", "constraint", "{field} IS NULL OR regexp_match(to_string({field}), '^[0-9]+$')", False, ""),
    ("Arabic letters only", "constraint", "{field} IS NULL OR regexp_match({field}, '^[\\\\x{0600}-\\\\x{06FF}\\\\s]+$')",
     False, "Spaces are allowed."),
    ("English letters only", "constraint", "{field} IS NULL OR regexp_match({field}, '^[A-Za-z\\\\s]+$')", False,
     "Spaces are allowed."),
    ("No spaces at the start or end", "constraint", "{field} IS NULL OR {field} = trim({field})", False, ""),
    ("No double spaces", "constraint", "{field} IS NULL OR strpos({field}, '  ') = 0", False, ""),
    ("Date not before 1900", "constraint", "{field} IS NULL OR year({field}) >= 1900", False, ""),
    ("Date must be today or later", "constraint", "{field} IS NULL OR {field} >= to_date(now())", False,
     "Useful for end dates of new contracts or permits."),
    ("If one field is filled, the other must be too", "constraint", "\"field_a\" IS NULL OR \"field_b\" IS NOT NULL",
     False, "Replace \"field_a\" (the first field) and \"field_b\" (the field that must then be filled)."),
    ("Unique combination of two fields", "constraint", _UNIQUE_PAIR, False,
     "Replace field_a and field_b everywhere with your two fields (4 places)."),
    ("Value must exist in another layer (lookup)", "constraint",
     "{field} IS NULL OR get_feature('[[layer]]', 'code', {field}) IS NOT NULL", True,
     "Replace 'code' with the key field of the other layer."),
    ("Value agrees with the layer it falls in", "constraint",
     "{field} IS NULL OR {field} = array_first(overlay_intersects('[[layer]]', \"name\"))", True,
     "Replace \"name\" with the field of the other layer to compare with."),
    ("Must not overlap another layer (touching allowed)", "constraint", _NO_OVERLAP_OTHER, True, ""),
    ("Must be within 50 m of another layer", "constraint", "overlay_nearest('[[layer]]', max_distance:=50)", True,
     "Change 50 to your distance (layer CRS units)."),
    ("Must lie on another layer (snapped, within 1 cm)", "constraint",
     "overlay_nearest('[[layer]]', max_distance:=0.01)", True,
     "Example: valves must be on a pipe line. 0.01 = 1 cm in a meter-based CRS."),
    ("Must contain at least one feature of another layer", "constraint", "overlay_contains('[[layer]]')", True, ""),
    ("Not a sliver / very thin polygon", "constraint", "$area = 0 OR 4 * pi() * $area / ($perimeter ^ 2) >= 0.05",
     False, "Change 0.05 if needed."),
    ("Not too many vertices", "constraint", "num_points($geometry) <= 1000", False, "Change 1000 to your limit."),
    # ---------------------------------------------------------------- validation
    # attributes
    ("Field must be filled (check existing data)", "validation", "{field} IS NOT NULL", False, ""),
    ("Not empty or only spaces (check existing data)", "validation",
     "length(trim(coalesce(to_string({field}), ''))) > 0", False, ""),
    ("No duplicates in the field (check existing data)", "validation",
     "count({field}, group_by:={field}) = 1", False, "Empty values are reported too."),
    ("Unique combination of two fields (check existing data)", "validation",
     "count($id, group_by:=concat(\"field_a\", '|', \"field_b\")) = 1", False,
     "Replace \"field_a\" and \"field_b\" with your two fields."),
    ("If one field is filled, the other must be too (check existing data)", "validation",
     "\"field_a\" IS NULL OR \"field_b\" IS NOT NULL", False,
     "Replace \"field_a\" (the first field) and \"field_b\" (the field that must then be filled)."),
    ("Must be one of a list of values (check existing data)", "validation",
     "{field} IN ('A', 'B', 'C')", False, "Replace 'A', 'B', 'C' with the allowed values."),
    # text
    ("Text at most 50 characters (check existing data)", "validation",
     "{field} IS NULL OR length({field}) <= 50", False, "Change 50 to your limit."),
    ("Valid e-mail address (check existing data)", "validation",
     "{field} IS NULL OR regexp_match({field}, '^[^@\\\\s]+@[^@\\\\s]+\\\\.[^@\\\\s]+$')", False, ""),
    ("Phone number of 10 digits (check existing data)", "validation",
     "{field} IS NULL OR regexp_match({field}, '^[0-9]{10}$')", False, "Change {10} to the number of digits."),
    ("Digits only (check existing data)", "validation",
     "{field} IS NULL OR regexp_match(to_string({field}), '^[0-9]+$')", False, ""),
    ("Arabic letters only (check existing data)", "validation",
     "{field} IS NULL OR regexp_match({field}, '^[\\\\x{0600}-\\\\x{06FF}\\\\s]+$')", False,
     "Spaces are allowed; digits and Latin letters are reported."),
    ("English letters only (check existing data)", "validation",
     "{field} IS NULL OR regexp_match({field}, '^[A-Za-z\\\\s]+$')", False,
     "Spaces are allowed; digits and Arabic letters are reported."),
    ("No spaces at the start or end (check existing data)", "validation",
     "{field} IS NULL OR {field} = trim({field})", False, ""),
    ("No double spaces (check existing data)", "validation",
     "{field} IS NULL OR strpos({field}, '  ') = 0", False, ""),
    # numbers
    ("Must be greater than zero (check existing data)", "validation", "{field} > 0", False, ""),
    ("Must not be negative (check existing data)", "validation", "{field} IS NULL OR {field} >= 0", False, ""),
    ("Must be between two values (check existing data)", "validation",
     "{field} IS NULL OR ({field} >= 1 AND {field} <= 100)", False, "Change 1 and 100 to your limits."),
    ("Whole number, no decimals (check existing data)", "validation",
     "{field} IS NULL OR {field} = round({field})", False, ""),
    ("No extreme values / outliers (check existing data)", "validation",
     "{field} IS NULL OR stdev({field}) = 0 OR abs({field} - mean({field})) <= 3 * stdev({field})", False,
     "Reports values more than 3 standard deviations from the average; change 3 to be stricter or looser."),
    ("Stored area matches the real area (check existing data)", "validation",
     "{field} IS NULL OR abs({field} - $area) <= 0.01 * $area", False,
     "Choose the field that holds the area in square meters; a difference of more than 1% is reported."),
    ("Stored length matches the real length (check existing data)", "validation",
     "{field} IS NULL OR abs({field} - $length) <= 0.01 * $length", False,
     "Choose the field that holds the length in meters; a difference of more than 1% is reported."),
    # dates
    ("Date must not be in the future (check existing data)", "validation", "{field} IS NULL OR {field} <= now()",
     False, ""),
    ("Date has not passed yet (check existing data)", "validation", "{field} IS NULL OR {field} >= now()", False,
     "Useful for end dates: lists contracts or permits that have already expired."),
    ("Date not before 1900 (check existing data)", "validation", "{field} IS NULL OR year({field}) >= 1900", False,
     "Finds dates typed by mistake; change 1900 if needed."),
    ("End date not before start date (check existing data)", "validation",
     "\"end_date\" IS NULL OR \"start_date\" IS NULL OR \"end_date\" >= \"start_date\"", False,
     "Replace \"end_date\" and \"start_date\" with your two date fields."),
    # geometry
    ("Geometry must be valid (check existing data)", "validation", "is_valid($geometry)", False, ""),
    ("Geometry must not be empty (check existing data)", "validation",
     "$geometry IS NOT NULL AND NOT is_empty($geometry)", False, ""),
    ("No duplicate geometries (check existing data)", "validation",
     "count(geom_to_wkt($geometry), group_by:=geom_to_wkt($geometry)) = 1", False,
     "Can be slow on very large layers."),
    ("Must be a single part (check existing data)", "validation", "num_geometries($geometry) = 1", False, ""),
    ("Polygon must not have holes (check existing data)", "validation", "num_interior_rings($geometry) = 0", False, ""),
    ("Area at least 100 m2 (check existing data)", "validation", "$area >= 100", False, "Change 100 to your minimum."),
    ("Line at least 1 m long (check existing data)", "validation", "$length >= 1", False, "Change 1 to your minimum."),
    ("Not a sliver / very thin polygon (check existing data)", "validation",
     "$area = 0 OR 4 * pi() * $area / ($perimeter ^ 2) >= 0.05", False,
     "0.05 is the minimum compactness (a circle = 1, a 100 x 1 strip = 0.03); change it if needed."),
    ("Not too many vertices (check existing data)", "validation", "num_points($geometry) <= 1000", False,
     "Change 1000 to your limit."),
    ("Polygons must not overlap each other (check existing data)", "validation", _NO_OVERLAP, False, ""),
    ("Points at least 1 m apart (check existing data)", "validation", _POINTS_APART, False, ""),
    # other layers
    ("Must be inside another layer (check existing data)", "validation", "overlay_within('[[layer]]')", True, ""),
    ("Must not intersect another layer (check existing data)", "validation",
     "NOT overlay_intersects('[[layer]]')", True, ""),
    ("Must touch or intersect another layer (check existing data)", "validation",
     "overlay_intersects('[[layer]]')", True, ""),
    ("Must not be within 10 m of another layer (check existing data)", "validation",
     "NOT overlay_nearest('[[layer]]', max_distance:=10)", True, "Change 10 to your distance (layer CRS units)."),
    ("Must be within 50 m of another layer (check existing data)", "validation",
     "overlay_nearest('[[layer]]', max_distance:=50)", True, "Change 50 to your distance (layer CRS units)."),
    ("Must contain at least one feature of another layer (check existing data)", "validation",
     "overlay_contains('[[layer]]')", True, "Example: every parcel must contain a building point."),
    ("Value agrees with the layer it falls in (check existing data)", "validation",
     "{field} = array_first(overlay_intersects('[[layer]]', \"name\"))", True,
     "Replace \"name\" with the field of the other layer to compare with; features outside it are reported."),
    ("At least 3 characters (check existing data)", "validation", "{field} IS NULL OR length({field}) >= 3", False,
     "Change 3 to your minimum."),
    ("Must start with a prefix (check existing data)", "validation", "{field} IS NULL OR left({field}, 2) = 'P-'",
     False, "Change 'P-' to your prefix and 2 to its number of characters."),
    ("Upper case only (check existing data)", "validation", "{field} IS NULL OR {field} = upper({field})", False, ""),
    ("Value must exist in another layer (check existing data)", "validation",
     "{field} IS NULL OR get_feature('[[layer]]', 'code', {field}) IS NOT NULL", True,
     "Replace 'code' with the key field of the other layer. Finds orphan codes."),
    ("Must not overlap another layer, touching allowed (check existing data)", "validation", _NO_OVERLAP_OTHER, True,
     ""),
    ("Must lie on another layer (check existing data)", "validation",
     "overlay_nearest('[[layer]]', max_distance:=0.01)", True, "0.01 = 1 cm in a meter-based CRS."),
]


# Groups (in display order) for the template list and the guide.
TEMPLATE_GROUPS = [
    ("calculation", "Areas and lengths", [
        "Area (square meters)", "Area (hectares)", "Area (square kilometers)", "Area (dunam = 1000 m2)",
        "Area (feddan = 4200.83 m2)", "Area (square feet)", "Area (acres)", "Area rounded to 2 decimals",
        "Area in the layer's own units (no ellipsoid)", "Perimeter (meters)", "Perimeter (kilometers)",
        "Length of a line (meters)", "Length of a line (kilometers)", "Compactness (1 = circle)"]),
    ("calculation", "Coordinates", [
        "X of the center", "Y of the center", "Longitude of the center", "Latitude of the center",
        "Latitude in degrees, minutes, seconds", "Longitude in degrees, minutes, seconds",
        "Coordinates as text (latitude, longitude)", "Google Maps link", "UTM zone number",
        "X of the line start", "Y of the line start", "X of the line end", "Y of the line end",
        "Line direction (degrees from north)", "Elevation (Z) of a point"]),
    ("calculation", "Geometry information", [
        "Number of vertices", "Number of parts", "Width of the bounding box", "Height of the bounding box",
        "Geometry type"]),
    ("calculation", "Numbering, dates and editors", [
        "Next number (auto ID)", "Next code with a prefix (P-00001)", "Unique identifier (UUID)",
        "Date and time now", "Date only (today)", "Current year", "User name of the editor",
        "Days remaining until a date", "Status from an end date (Active / Expired)", "Year of a date field"]),
    ("calculation", "From other fields", [
        "Upper-case copy of another field", "Copy of another field without extra spaces", "Join two fields",
        "Number of characters of another field", "Another field rounded to 2 decimals", "Percentage of two fields",
        "Price per square meter"]),
    ("calculation", "From other layers", [
        "Value from the layer it falls in", "Value from a lookup layer (by code)",
        "Name of the nearest feature of another layer", "Distance to the nearest feature of another layer",
        "Count of features of another layer inside it", "Count of features of another layer within 100 m",
        "Sum of a field of another layer inside it", "Overlap area with another layer",
        "Percent of the area covered by another layer", "Length of lines of another layer inside it"]),
    ("constraint", "Required and unique values", [
        "Must not be empty", "Must not be empty or only spaces", "Must be unique in the layer",
        "Unique combination of two fields", "If one field is filled, the other must be too",
        "Must be one of a list of values"]),
    ("constraint", "Text", [
        "Text at most 50 characters", "At least 3 characters", "Must start with a prefix", "Upper case only",
        "Valid e-mail address", "Phone number of 10 digits", "Digits only", "Arabic letters only",
        "English letters only", "No spaces at the start or end", "No double spaces"]),
    ("constraint", "Numbers", [
        "Must be greater than zero", "Must not be negative", "Must be between two values",
        "Whole number, no decimals"]),
    ("constraint", "Dates", [
        "Date must not be in the future", "Date must be today or later", "Date not before 1900",
        "End date not before start date"]),
    ("constraint", "Geometry", [
        "Geometry must be valid", "Must be a single part (not multipart)", "Polygon must not have holes",
        "Area must be at least 100 m2", "Line must be at least 1 m long", "Not a sliver / very thin polygon",
        "Not too many vertices", "Polygons of this layer must not overlap each other",
        "Points of this layer must be at least 1 m apart"]),
    ("constraint", "Other layers", [
        "Must NOT be inside or on the edge of another layer", "Must be inside another layer",
        "Must not intersect another layer", "Must not overlap another layer (touching allowed)",
        "Must touch or intersect another layer", "Must not be within 10 m of another layer",
        "Must be within 50 m of another layer", "Must lie on another layer (snapped, within 1 cm)",
        "Must contain at least one feature of another layer", "Value must exist in another layer (lookup)",
        "Value agrees with the layer it falls in"]),
    ("validation", "Required and unique values", [
        "Field must be filled (check existing data)", "Not empty or only spaces (check existing data)",
        "No duplicates in the field (check existing data)", "Unique combination of two fields (check existing data)",
        "If one field is filled, the other must be too (check existing data)",
        "Must be one of a list of values (check existing data)"]),
    ("validation", "Text", [
        "Text at most 50 characters (check existing data)", "At least 3 characters (check existing data)",
        "Must start with a prefix (check existing data)", "Upper case only (check existing data)",
        "Valid e-mail address (check existing data)", "Phone number of 10 digits (check existing data)",
        "Digits only (check existing data)", "Arabic letters only (check existing data)",
        "English letters only (check existing data)", "No spaces at the start or end (check existing data)",
        "No double spaces (check existing data)"]),
    ("validation", "Numbers", [
        "Must be greater than zero (check existing data)", "Must not be negative (check existing data)",
        "Must be between two values (check existing data)", "Whole number, no decimals (check existing data)",
        "No extreme values / outliers (check existing data)", "Stored area matches the real area (check existing data)",
        "Stored length matches the real length (check existing data)"]),
    ("validation", "Dates", [
        "Date must not be in the future (check existing data)", "Date has not passed yet (check existing data)",
        "Date not before 1900 (check existing data)", "End date not before start date (check existing data)"]),
    ("validation", "Geometry", [
        "Geometry must be valid (check existing data)", "Geometry must not be empty (check existing data)",
        "No duplicate geometries (check existing data)", "Must be a single part (check existing data)",
        "Polygon must not have holes (check existing data)", "Area at least 100 m2 (check existing data)",
        "Line at least 1 m long (check existing data)", "Not a sliver / very thin polygon (check existing data)",
        "Not too many vertices (check existing data)", "Polygons must not overlap each other (check existing data)",
        "Points at least 1 m apart (check existing data)"]),
    ("validation", "Other layers", [
        "Must be inside another layer (check existing data)", "Must not intersect another layer (check existing data)",
        "Must not overlap another layer, touching allowed (check existing data)",
        "Must touch or intersect another layer (check existing data)",
        "Must not be within 10 m of another layer (check existing data)",
        "Must be within 50 m of another layer (check existing data)", "Must lie on another layer (check existing data)",
        "Must contain at least one feature of another layer (check existing data)",
        "Value must exist in another layer (check existing data)",
        "Value agrees with the layer it falls in (check existing data)"]),
]


POINT, LINE, POLYGON = "point", "line", "polygon"
ANY_GEOMETRY = frozenset((POINT, LINE, POLYGON))
GEOMETRY_LABELS = {POINT: "point", LINE: "line", POLYGON: "polygon", "none": "table (no geometry)",
                   "unknown": "mixed / unknown geometry"}

# Templates whose geometry types cannot be read from the expression alone.
TEMPLATE_GEOMETRY = {
    "Number of vertices": {LINE, POLYGON},
    "Width of the bounding box": {LINE, POLYGON},
    "Height of the bounding box": {LINE, POLYGON},
    "Not too many vertices": {LINE, POLYGON},
    "Not too many vertices (check existing data)": {LINE, POLYGON},
    "Points of this layer must be at least 1 m apart": {POINT},
    "Points at least 1 m apart (check existing data)": {POINT},
    "Must lie on another layer (snapped, within 1 cm)": {POINT, LINE},
    "Must lie on another layer (check existing data)": {POINT, LINE},
    "Count of features of another layer inside it": {POLYGON},
    "Sum of a field of another layer inside it": {POLYGON},
    "Length of lines of another layer inside it": {POLYGON},
}


def template_geometries(template):
    """Geometry types a template makes sense for, or None when it only uses attributes."""
    label, expr = template[0], template[2]
    if label in TEMPLATE_GEOMETRY:
        return frozenset(TEMPLATE_GEOMETRY[label])
    if any(k in expr for k in ("$area", "area(", "$perimeter", "num_interior_rings", "overlay_contains")):
        return frozenset((POLYGON,))
    if any(k in expr for k in ("$length", "start_point", "end_point")):
        return frozenset((LINE,))
    if "z($geometry)" in expr:
        return frozenset((POINT,))
    if any(k in expr for k in ("$geometry", "$x", "$y", "overlay_")):
        return ANY_GEOMETRY
    return None


def fits_geometry(template, geometry):
    """True when `template` should be offered for a layer of `geometry`
    ("point", "line", "polygon", "none" for tables, "unknown"/None to show everything)."""
    allowed = template_geometries(template)
    if allowed is None or geometry in (None, "unknown"):
        return True
    if geometry == "none":
        return False
    return geometry in allowed


def grouped_templates(rule_type, geometry=None):
    """[(group title, [template tuples])] in display order; ungrouped templates go last.

    With `geometry`, only the templates that make sense for that geometry type are returned.
    """
    by_label = {t[0]: t for t in TEMPLATES if t[1] == rule_type and fits_geometry(t, geometry)}
    out, used = [], set()
    for gtype, title, labels in TEMPLATE_GROUPS:
        if gtype != rule_type:
            continue
        items = [by_label[x] for x in labels if x in by_label]
        used.update(x[0] for x in items)
        if items:
            out.append((title, items))
    rest = [t for lbl, t in by_label.items() if lbl not in used]
    if rest:
        out.append(("Other", rest))
    return out


def q_ident(name):
    return '"%s"' % str(name).replace('"', '""')


def q_str(text):
    return "'%s'" % str(text).replace("'", "''")


def templates_for(rule_type, geometry=None):
    return [t for _title, items in grouped_templates(rule_type, geometry) for t in items]


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
