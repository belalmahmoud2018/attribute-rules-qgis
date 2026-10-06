"""Rules are stored inside the data file in the table ar_rules (GDAL/OGR, all three formats)."""
import functools
import os

from osgeo import gdal, ogr

MIN_GDAL_FGDB = 3060000
TABLE = "ar_rules"
COLUMNS = [
    ("rule_name", ogr.OFTString, 254), ("lyr_name", ogr.OFTString, 254), ("rule_type", ogr.OFTString, 32),
    ("field_name", ogr.OFTString, 254), ("expr", ogr.OFTString, 4000), ("on_update", ogr.OFTInteger, 0),
    ("message", ogr.OFTString, 1000), ("strict", ogr.OFTInteger, 0), ("enabled", ogr.OFTInteger, 0),
    ("rule_order", ogr.OFTInteger, 0),
]
HELPER_TABLES = {
    TABLE, "sd_domains", "sd_domain_values", "sd_layers", "sd_subtypes", "sd_rules",
    "feature_datasets", "feature_dataset_members", "layer_styles",
}
SPATIALITE_INTERNAL = (
    "sqlite_", "idx_", "spatial_ref_sys", "geometry_columns", "spatialite_", "views_", "virts_",
    "vector_layers", "data_licenses", "sql_statements_log", "elementarygeometries",
    "geom_cols_ref_sys", "raster_coverages", "knn", "iso_metadata", "stored_", "topologies",
    "networks", "se_", "wms_", "spatialindex", "rl2map_", "virtualxpath", "sqlite_stat",
)


class DataError(Exception):
    pass


def _guard(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except DataError:
            raise
        except (RuntimeError, OSError) as e:
            msg = str(e)
            if "permission denied" in msg.lower() or "locked" in msg.lower():
                msg += ("\n\nClose edit mode and make sure no other program has the file open.")
            raise DataError(msg) from e

    return wrapper


class Fmt:
    def __init__(self, key, label, driver, open_filter, directory=False):
        self.key, self.label, self.driver = key, label, driver
        self.open_filter, self.directory = open_filter, directory

    def is_valid(self, path):
        if not path:
            return False
        if self.directory:
            return path.lower().rstrip("/\\").endswith(".gdb") and os.path.isdir(path)
        return os.path.isfile(path)

    def uri(self, path, name):
        return "%s|layername=%s" % (path, name)


FORMATS = [
    Fmt("gpkg", "GeoPackage (.gpkg)", "GPKG", "GeoPackage (*.gpkg)"),
    Fmt("spatialite", "SpatiaLite (.sqlite)", "SQLite", "SpatiaLite (*.sqlite *.db *.sqlite3 *.spatialite)"),
    Fmt("filegdb", "File Geodatabase (.gdb)", "OpenFileGDB", "", True),
]


def detect_format(path):
    low = (path or "").lower().rstrip("/\\")
    if low.endswith(".gdb"):
        return FORMATS[2]
    if low.endswith(".gpkg"):
        return FORMATS[0]
    if low.endswith((".sqlite", ".db", ".sqlite3", ".spatialite")):
        return FORMATS[1]
    return None


def geometry_kind(geom_type):
    """'point', 'line', 'polygon', 'none' (table) or 'unknown' for an OGR geometry type."""
    if geom_type == ogr.wkbNone:
        return "none"
    linear = ogr.GT_GetLinear(geom_type) if hasattr(ogr, "GT_GetLinear") else geom_type
    flat = ogr.GT_Flatten(linear)
    if flat in (ogr.wkbPoint, ogr.wkbMultiPoint):
        return "point"
    if flat in (ogr.wkbLineString, ogr.wkbMultiLineString):
        return "line"
    if flat in (ogr.wkbPolygon, ogr.wkbMultiPolygon, ogr.wkbPolyhedralSurface, ogr.wkbTIN):
        return "polygon"
    return "unknown"


def hidden(fmt, name):
    low = name.lower()
    if low in HELPER_TABLES:
        return True
    return fmt.key == "spatialite" and low.startswith(SPATIALITE_INTERNAL)


def open_ds(fmt, path, update=False):
    if fmt.directory:
        try:
            version = int(gdal.VersionInfo())
        except Exception:
            version = 0
        if version < MIN_GDAL_FGDB:
            raise DataError("File Geodatabase needs GDAL 3.6 or newer (QGIS 3.28 or newer).")
    flags = [gdal.OF_UPDATE] if update else [gdal.OF_READONLY, gdal.OF_UPDATE]
    last = None
    for flag in flags:
        try:
            # SpatiaLite hides tables without geometry unless asked to list them all
            opts = ["LIST_ALL_TABLES=YES"] if fmt.key == "spatialite" else []
            ds = gdal.OpenEx(path, gdal.OF_VECTOR | flag, allowed_drivers=[fmt.driver], open_options=opts)
        except RuntimeError as e:
            ds, last = None, e
        if ds is not None:
            return ds
        if not fmt.directory:
            break
    raise DataError("Could not open %s%s" % (path, (": %s" % last) if last else "."))


@_guard
def load_rules(fmt, path):
    ds = open_ds(fmt, path)
    rules = []
    lyr = ds.GetLayerByName(TABLE)
    if lyr is not None:
        defn = lyr.GetLayerDefn()
        names = [defn.GetFieldDefn(i).GetName() for i in range(defn.GetFieldCount())]
        lyr.ResetReading()
        for feat in lyr:
            r = {n: (feat.GetField(i) if feat.IsFieldSetAndNotNull(i) else None) for i, n in enumerate(names)}
            if not r.get("rule_name") or not r.get("lyr_name"):
                continue
            rules.append({
                "name": r["rule_name"], "layer": r["lyr_name"], "type": r.get("rule_type") or "constraint",
                "field": r.get("field_name"), "expression": r.get("expr") or "",
                "on_update": bool(r.get("on_update")), "message": r.get("message") or "",
                "strict": bool(r.get("strict")), "enabled": r.get("enabled") is None or bool(r.get("enabled")),
                "order": int(r.get("rule_order") or 0),
            })
    lyr = None
    ds = None
    return rules


@_guard
def save_rules(fmt, path, rules):
    ds = open_ds(fmt, path, update=True)
    try:
        lyr = ds.GetLayerByName(TABLE)
        if lyr is None:
            lyr = ds.CreateLayer(TABLE, None, ogr.wkbNone, [])
            if lyr is None:
                raise DataError("Could not create the table %s." % TABLE)
            for name, ftype, width in COLUMNS:
                fd = ogr.FieldDefn(name, ftype)
                if width:
                    fd.SetWidth(width)
                lyr.CreateField(fd)
        lyr.ResetReading()
        for fid in [f.GetFID() for f in lyr]:
            lyr.DeleteFeature(fid)
        for r in rules:
            feat = ogr.Feature(lyr.GetLayerDefn())
            values = {
                "rule_name": r["name"], "lyr_name": r["layer"], "rule_type": r["type"],
                "field_name": r.get("field"), "expr": r.get("expression") or "",
                "on_update": 1 if r.get("on_update") else 0, "message": r.get("message") or None,
                "strict": 1 if r.get("strict") else 0, "enabled": 1 if r.get("enabled", True) else 0,
                "rule_order": int(r.get("order", 0)),
            }
            for key, value in values.items():
                if value is not None:
                    feat.SetField(key, value)
            if lyr.CreateFeature(feat) != 0:
                raise DataError("Could not write a rule.")
        lyr = None
    finally:
        ds = None


@_guard
def list_layers(fmt, path):
    """[{'name', 'has_geom', 'fields': [names]}] of the user's layers in the file."""
    ds = open_ds(fmt, path)
    out = []
    for i in range(ds.GetLayerCount()):
        lyr = ds.GetLayerByIndex(i)
        name = lyr.GetName()
        if hidden(fmt, name):
            continue
        defn = lyr.GetLayerDefn()
        fds = [defn.GetFieldDefn(j) for j in range(defn.GetFieldCount())]
        out.append({
            "name": name, "has_geom": lyr.GetGeomType() != ogr.wkbNone,
            "geometry": geometry_kind(lyr.GetGeomType()),
            "fields": [fd.GetName() for fd in fds],
            "types": {fd.GetName(): ogr.GetFieldTypeName(fd.GetType()) for fd in fds},
        })
    ds = None
    return out
