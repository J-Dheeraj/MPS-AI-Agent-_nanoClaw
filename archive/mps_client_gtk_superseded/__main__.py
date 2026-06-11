"""
mps_client/main.py  --  GTK4 application entry point
Run with:  python3 -m mps_client   (from ~/nanoclaw/)
"""
import sys
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio

from .async_bridge import ensure_started
from .login_window import LoginWindow
from .main_window  import MainWindow


class MPSApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="dev.nanoclaw.mps")
        self._main_win = None

    def do_activate(self):
        ensure_started()   # start background asyncio loop
        self._show_login()

    def _show_login(self):
        # Close main window if open
        if self._main_win:
            self._main_win.close()
            self._main_win = None

        win = LoginWindow(app=self, on_success=self._on_login_success)
        win.present()

    def _on_login_success(self):
        # Close all existing windows (login window)
        for win in self.get_windows():
            win.close()

        self._main_win = MainWindow(app=self, on_logout=self._show_login)
        self._main_win.present()


def main():
    app = MPSApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
