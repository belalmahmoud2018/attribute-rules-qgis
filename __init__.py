# Attribute Rules Manager
# Copyright (C) 2026 Belal Mahmoud Abdelmonem
# Licensed under the GNU General Public License v2 or later (see LICENSE).
import sys


def classFactory(iface):
    # After installing a new version over an old one, QGIS can keep old sub-modules in memory.
    for name in [n for n in sys.modules if n.startswith(__name__ + ".")]:
        del sys.modules[name]
    from .plugin import AttributeRulesPlugin
    return AttributeRulesPlugin(iface)
