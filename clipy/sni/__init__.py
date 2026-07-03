"""System-tray support: a hand-rolled StatusNotifierItem + dbusmenu over Gio D-Bus.

This avoids any dependency on libappindicator, which is not installed on the target
machine. GNOME's AppIndicator extension acts as the StatusNotifierHost and renders the
menu we publish via com.canonical.dbusmenu.
"""
