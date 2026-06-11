"""widgets/profile_window.py — Profile settings modal (libadwaita 1.1.x compatible)"""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

from .. import api_client as api
from ..async_bridge import run


class ProfileWindow(Adw.Window):
    """Modal profile/settings window — change username or password."""

    def __init__(self, parent, on_username_changed=None):
        super().__init__()
        self._on_username_changed = on_username_changed
        self.set_title("My Profile")
        self.set_modal(True)
        self.set_transient_for(parent)
        self.set_default_size(440, 560)
        self.set_resizable(False)
        self.connect("close-request", lambda w: w.hide() or True)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(root)

        header = Adw.HeaderBar()
        root.append(header)

        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        root.append(scroll)

        clamp = Adw.Clamp(maximum_size=400)
        scroll.set_child(clamp)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        box.set_margin_top(24); box.set_margin_bottom(24)
        box.set_margin_start(16); box.set_margin_end(16)
        clamp.set_child(box)

        # ── Account info banner ───────────────────────────────────────────────
        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        info_box.add_css_class("card")
        info_box.set_margin_bottom(4)
        box.append(info_box)

        self._info_name = Gtk.Label()
        self._info_name.set_markup(
            f"<b>{api.auth.full_name}</b>"
        )
        self._info_name.set_halign(Gtk.Align.START)
        self._info_name.set_margin_top(12)
        self._info_name.set_margin_start(12)
        info_box.append(self._info_name)

        self._info_user = Gtk.Label(
            label=f"@{api.auth.full_name}  ·  {api.auth.role}"
        )
        self._info_user.add_css_class("caption")
        self._info_user.add_css_class("dim-label")
        self._info_user.set_halign(Gtk.Align.START)
        self._info_user.set_margin_start(12)
        self._info_user.set_margin_bottom(12)
        info_box.append(self._info_user)

        # ── Change username ───────────────────────────────────────────────────
        un_group = Adw.PreferencesGroup(title="Change Username")
        box.append(un_group)

        un_row, self._new_username = _entry_row("New username")
        un_group.add(un_row)

        pw_row_un, self._un_confirm_pw = _entry_row("Current password", password=True)
        un_group.add(pw_row_un)

        self._un_error = Gtk.Label(label="")
        self._un_error.add_css_class("error")
        self._un_error.set_visible(False)
        self._un_error.set_wrap(True)
        self._un_error.set_halign(Gtk.Align.START)
        box.append(self._un_error)

        self._un_success = Gtk.Label(label="")
        self._un_success.add_css_class("success")
        self._un_success.set_visible(False)
        self._un_success.set_wrap(True)
        self._un_success.set_halign(Gtk.Align.START)
        box.append(self._un_success)

        un_btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        un_btn_row.set_halign(Gtk.Align.END)
        box.append(un_btn_row)

        self._un_spinner = Gtk.Spinner()
        un_btn_row.append(self._un_spinner)

        self._un_btn = Gtk.Button(label="Change Username")
        self._un_btn.add_css_class("suggested-action")
        self._un_btn.connect("clicked", self._on_change_username)
        un_btn_row.append(self._un_btn)

        box.append(Gtk.Separator())

        # ── Change password ───────────────────────────────────────────────────
        pw_group = Adw.PreferencesGroup(title="Change Password")
        box.append(pw_group)

        cur_row, self._current_pw = _entry_row("Current password", password=True)
        pw_group.add(cur_row)

        new_row, self._new_pw = _entry_row("New password (min 8 chars)", password=True)
        pw_group.add(new_row)

        conf_row, self._confirm_pw = _entry_row("Confirm new password", password=True)
        pw_group.add(conf_row)

        self._pw_error = Gtk.Label(label="")
        self._pw_error.add_css_class("error")
        self._pw_error.set_visible(False)
        self._pw_error.set_wrap(True)
        self._pw_error.set_halign(Gtk.Align.START)
        box.append(self._pw_error)

        self._pw_success = Gtk.Label(label="")
        self._pw_success.add_css_class("success")
        self._pw_success.set_visible(False)
        self._pw_success.set_wrap(True)
        self._pw_success.set_halign(Gtk.Align.START)
        box.append(self._pw_success)

        pw_btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        pw_btn_row.set_halign(Gtk.Align.END)
        box.append(pw_btn_row)

        self._pw_spinner = Gtk.Spinner()
        pw_btn_row.append(self._pw_spinner)

        self._pw_btn = Gtk.Button(label="Change Password")
        self._pw_btn.add_css_class("suggested-action")
        self._pw_btn.connect("clicked", self._on_change_password)
        pw_btn_row.append(self._pw_btn)

    # ── Change username ───────────────────────────────────────────────────────

    def _on_change_username(self, _btn):
        new_un = self._new_username.get_text().strip()
        cur_pw = self._un_confirm_pw.get_text()
        self._un_error.set_visible(False)
        self._un_success.set_visible(False)

        if len(new_un) < 3:
            self._un_error.set_label("Username must be at least 3 characters.")
            self._un_error.set_visible(True)
            return
        if not cur_pw:
            self._un_error.set_label("Enter your current password to confirm.")
            self._un_error.set_visible(True)
            return

        self._set_un_busy(True)
        run(
            api.change_username(cur_pw, new_un),
            on_done=self._on_username_ok,
            on_error=self._on_username_err,
        )

    def _on_username_ok(self, result):
        self._set_un_busy(False)
        new_un = result.get("new_username", "")
        api.auth.full_name = api.auth.full_name  # full_name unchanged
        self._un_success.set_label(f"✓ Username changed to @{new_un}")
        self._un_success.set_visible(True)
        self._new_username.set_text("")
        self._un_confirm_pw.set_text("")
        if self._on_username_changed:
            self._on_username_changed(new_un)

    def _on_username_err(self, exc):
        self._set_un_busy(False)
        self._un_error.set_label(str(getattr(exc, "detail", exc)))
        self._un_error.set_visible(True)

    def _set_un_busy(self, busy):
        self._un_btn.set_sensitive(not busy)
        self._new_username.set_sensitive(not busy)
        self._un_confirm_pw.set_sensitive(not busy)
        self._un_spinner.start() if busy else self._un_spinner.stop()

    # ── Change password ───────────────────────────────────────────────────────

    def _on_change_password(self, _btn):
        cur_pw  = self._current_pw.get_text()
        new_pw  = self._new_pw.get_text()
        conf_pw = self._confirm_pw.get_text()
        self._pw_error.set_visible(False)
        self._pw_success.set_visible(False)

        if not cur_pw:
            self._pw_error.set_label("Enter your current password.")
            self._pw_error.set_visible(True)
            return
        if len(new_pw) < 8:
            self._pw_error.set_label("New password must be at least 8 characters.")
            self._pw_error.set_visible(True)
            return
        if new_pw != conf_pw:
            self._pw_error.set_label("Passwords do not match.")
            self._pw_error.set_visible(True)
            return

        self._set_pw_busy(True)
        run(
            api.change_password(cur_pw, new_pw),
            on_done=self._on_password_ok,
            on_error=self._on_password_err,
        )

    def _on_password_ok(self, _result):
        self._set_pw_busy(False)
        self._pw_success.set_label("✓ Password changed successfully.")
        self._pw_success.set_visible(True)
        self._current_pw.set_text("")
        self._new_pw.set_text("")
        self._confirm_pw.set_text("")

    def _on_password_err(self, exc):
        self._set_pw_busy(False)
        self._pw_error.set_label(str(getattr(exc, "detail", exc)))
        self._pw_error.set_visible(True)

    def _set_pw_busy(self, busy):
        self._pw_btn.set_sensitive(not busy)
        self._current_pw.set_sensitive(not busy)
        self._new_pw.set_sensitive(not busy)
        self._confirm_pw.set_sensitive(not busy)
        self._pw_spinner.start() if busy else self._pw_spinner.stop()


def _entry_row(title, password=False):
    """ActionRow + Entry — replaces Adw.EntryRow (needs libadwaita >= 1.2)."""
    row = Adw.ActionRow(title=title)
    entry = Gtk.Entry()
    entry.set_hexpand(True)
    entry.set_valign(Gtk.Align.CENTER)
    if password:
        entry.set_visibility(False)
        entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
    row.add_suffix(entry)
    row.set_activatable_widget(entry)
    return row, entry
