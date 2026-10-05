import os

try:
    from qgis.PyQt.QtGui import QAction  # Qt6
except ImportError:
    from qgis.PyQt.QtWidgets import QAction  # Qt5

from qgis.PyQt.QtGui import QIcon

from . import engine
from .dialogs import HubDialog

MENU = "&Attribute Rules Manager"


class AttributeRulesPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        engine.HOOK.watcher.iface = iface

    def initGui(self):
        icon = QIcon(os.path.join(os.path.dirname(__file__), "icon.png"))
        self.action = QAction(icon, "Attribute Rules Manager...", self.iface.mainWindow())
        self.action.triggered.connect(lambda _checked=False: self.run())
        self.iface.addPluginToMenu(MENU, self.action)
        self.iface.addToolBarIcon(self.action)
        engine.HOOK.connect()
        engine.HOOK.apply_project()

    def unload(self):
        engine.HOOK.disconnect()
        if self.action is not None:
            self.iface.removePluginMenu(MENU, self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action = None

    def run(self):
        HubDialog(self.iface, self.iface.mainWindow()).exec()
