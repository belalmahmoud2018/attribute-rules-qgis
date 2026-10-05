Attribute Rules Manager (v0.4.0)

Install: QGIS > Plugins > Manage and Install Plugins > Install from ZIP, then restart QGIS.
Open:    Plugins > Attribute Rules Manager (or the toolbar icon).

1. Choose the storage format (GeoPackage, SpatiaLite, File Geodatabase) and open the file.
2. Rules...  pick a layer and add rules:
   - Calculation: fills a field automatically when a feature is created (tick the option to
     recalculate on every edit too). Examples: area, coordinates, next ID, date, editor name.
   - Constraint: the expression must be TRUE or the feature form refuses to save. With
     "Block it", map edits that break the rule are undone. Example: a point must not be
     drawn inside or on the edge of a polygon layer.
   - Validation: checks existing data on demand; never blocks editing.
   Use one of the 155 templates (grouped by topic) or write any QGIS expression (expression builder available).
   Another layer is written by its name, e.g. overlay_intersects('Landuse'); the plugin links
   it to that layer of the same file and loads it automatically.
   Constraint and validation rules do not need a field. The error message is the text shown
   to the editor when the rule is broken (optional).
3. The rules apply automatically when the layers load (or press Apply to Loaded Layers).
4. Validate Data...  report of features breaking constraint/validation rules, with selection.
5. Diagnostics...    one report to copy when something does not work.

Rules are stored in the table ar_rules inside the file. They work in QGIS only.
File Geodatabase needs GDAL 3.6+ (QGIS 3.28+).

License: GNU GPL v2 (see LICENSE). Author: Belal Mahmoud Abdelmonem.
