"""login_window.py — Login + Sign-up screen (libadwaita 1.1.x compatible)"""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

from . import api_client as api
from .async_bridge import run


class LoginWindow(Adw.ApplicationWindow):
    def __init__(self, app, on_success):
        super().__init__(application=app)
        self._on_success = on_success
        self.set_title("MPS AI Agent")
        self.set_default_size(420, 480)
        self.set_resizable(False)

        # Root
        root_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(root_box)

        self._header = Adw.HeaderBar()
        self._header.set_show_end_title_buttons(False)
        root_box.append(self._header)

        # Stack: "login" page and "signup" page
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self._stack.set_vexpand(True)
        root_box.append(self._stack)

        # Back button lives in the header permanently — shown only on signup page
        self._back_btn = Gtk.Button(label="← Back")
        self._back_btn.add_css_class("flat")
        self._back_btn.connect("clicked", lambda _: self._show_page("login"))
        self._back_btn.set_visible(False)
        self._header.pack_start(self._back_btn)

        self._stack.add_named(self._build_login_page(), "login")
        self._stack.add_named(self._build_signup_page(), "signup")
        self._stack.set_visible_child_name("login")

    # ── Page builders ─────────────────────────────────────────────────────────

    def _build_login_page(self):
        clamp = Adw.Clamp(maximum_size=360)
        clamp.set_vexpand(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_margin_top(32); box.set_margin_bottom(32)
        box.set_margin_start(16); box.set_margin_end(16)
        clamp.set_child(box)

        icon = Gtk.Image.new_from_icon_name("emblem-system-symbolic")
        icon.set_pixel_size(48)
        box.append(icon)

        title = Gtk.Label(label="<b>MPS AI Agent</b>")
        title.set_use_markup(True)
        title.set_justify(Gtk.Justification.CENTER)
        box.append(title)

        subtitle = Gtk.Label(label="Volunteer Portal")
        subtitle.add_css_class("dim-label")
        subtitle.set_justify(Gtk.Justification.CENTER)
        box.append(subtitle)

        # Credential card
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        card.add_css_class("card")
        box.append(card)

        self._username = Gtk.Entry()
        self._username.set_placeholder_text("Username")
        self._username.set_margin_top(8); self._username.set_margin_bottom(4)
        self._username.set_margin_start(8); self._username.set_margin_end(8)
        self._username.connect("activate", self._on_enter)
        card.append(self._username)

        card.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        self._password = Gtk.Entry()
        self._password.set_placeholder_text("Password")
        self._password.set_visibility(False)
        self._password.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        self._password.set_margin_top(4); self._password.set_margin_bottom(8)
        self._password.set_margin_start(8); self._password.set_margin_end(8)
        self._password.connect("activate", self._on_enter)
        card.append(self._password)

        self._login_error = Gtk.Label(label="")
        self._login_error.add_css_class("error")
        self._login_error.set_visible(False)
        self._login_error.set_wrap(True)
        box.append(self._login_error)

        self._login_btn = Gtk.Button(label="Log In")
        self._login_btn.add_css_class("suggested-action")
        self._login_btn.add_css_class("pill")
        self._login_btn.connect("clicked", self._on_login_clicked)
        box.append(self._login_btn)

        self._login_spinner = Gtk.Spinner()
        box.append(self._login_spinner)

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.set_margin_top(8)
        box.append(sep)

        signup_hint = Gtk.Label(label="New volunteer?")
        signup_hint.add_css_class("dim-label")
        signup_hint.add_css_class("caption")
        box.append(signup_hint)

        goto_signup = Gtk.Button(label="Create an account")
        goto_signup.add_css_class("flat")
        goto_signup.connect("clicked", lambda _: self._show_page("signup"))
        box.append(goto_signup)

        return clamp

    def _build_signup_page(self):
        clamp = Adw.Clamp(maximum_size=360)
        clamp.set_vexpand(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_margin_top(24); box.set_margin_bottom(24)
        box.set_margin_start(16); box.set_margin_end(16)
        clamp.set_child(box)

        title = Gtk.Label(label="<b>Create Account</b>")
        title.set_use_markup(True)
        box.append(title)

        subtitle = Gtk.Label(label="Your account will have Volunteer access. An admin can promote you to Vetter later.")
        subtitle.add_css_class("dim-label")
        subtitle.add_css_class("caption")
        subtitle.set_wrap(True)
        subtitle.set_justify(Gtk.Justification.CENTER)
        box.append(subtitle)

        # Fields card
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        card.add_css_class("card")
        box.append(card)

        self._su_fullname = Gtk.Entry()
        self._su_fullname.set_placeholder_text("Full name")
        self._su_fullname.set_margin_top(8); self._su_fullname.set_margin_bottom(4)
        self._su_fullname.set_margin_start(8); self._su_fullname.set_margin_end(8)
        self._su_fullname.connect("activate", self._on_signup_clicked)
        card.append(self._su_fullname)

        card.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        self._su_username = Gtk.Entry()
        self._su_username.set_placeholder_text("Choose a username (min 3 chars)")
        self._su_username.set_margin_top(4); self._su_username.set_margin_bottom(4)
        self._su_username.set_margin_start(8); self._su_username.set_margin_end(8)
        self._su_username.connect("activate", self._on_signup_clicked)
        card.append(self._su_username)

        card.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        self._su_password = Gtk.Entry()
        self._su_password.set_placeholder_text("Password (min 8 chars)")
        self._su_password.set_visibility(False)
        self._su_password.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        self._su_password.set_margin_top(4); self._su_password.set_margin_bottom(4)
        self._su_password.set_margin_start(8); self._su_password.set_margin_end(8)
        self._su_password.connect("activate", self._on_signup_clicked)
        card.append(self._su_password)

        card.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        self._su_confirm = Gtk.Entry()
        self._su_confirm.set_placeholder_text("Confirm password")
        self._su_confirm.set_visibility(False)
        self._su_confirm.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        self._su_confirm.set_margin_top(4); self._su_confirm.set_margin_bottom(8)
        self._su_confirm.set_margin_start(8); self._su_confirm.set_margin_end(8)
        self._su_confirm.connect("activate", self._on_signup_clicked)
        card.append(self._su_confirm)

        self._signup_error = Gtk.Label(label="")
        self._signup_error.add_css_class("error")
        self._signup_error.set_visible(False)
        self._signup_error.set_wrap(True)
        box.append(self._signup_error)

        self._signup_success = Gtk.Label(label="")
        self._signup_success.add_css_class("success")
        self._signup_success.set_visible(False)
        self._signup_success.set_wrap(True)
        box.append(self._signup_success)

        self._signup_btn = Gtk.Button(label="Create Account")
        self._signup_btn.add_css_class("suggested-action")
        self._signup_btn.add_css_class("pill")
        self._signup_btn.connect("clicked", self._on_signup_clicked)
        box.append(self._signup_btn)

        self._signup_spinner = Gtk.Spinner()
        box.append(self._signup_spinner)

        return clamp

    # ── Navigation ────────────────────────────────────────────────────────────

    def _show_page(self, name):
        self._stack.set_visible_child_name(name)
        self._sync_header(name)
        # Clear errors when switching
        self._login_error.set_visible(False)
        self._signup_error.set_visible(False)
        self._signup_success.set_visible(False)

    def _sync_header(self, page):
        if page == "login":
            self.set_title("MPS AI Agent — Login")
            self._back_btn.set_visible(False)
        else:
            self.set_title("Create Account")
            self._back_btn.set_visible(True)

    # ── Login ─────────────────────────────────────────────────────────────────

    def _on_enter(self, _widget):
        self._on_login_clicked(None)

    def _on_login_clicked(self, _btn):
        username = self._username.get_text().strip()
        password = self._password.get_text()
        if not username or not password:
            self._show_login_error("Enter username and password.")
            return
        self._set_login_busy(True)
        run(api.login(username, password),
            on_done=self._login_ok,
            on_error=self._login_fail)

    def _login_ok(self, _result):
        self._set_login_busy(False)
        self._on_success()

    def _login_fail(self, exc):
        self._set_login_busy(False)
        detail = getattr(exc, "detail", str(exc))
        if "locked" in str(detail).lower():
            msg = "Account locked — too many failed attempts."
        elif "incorrect" in str(detail).lower() or "401" in str(exc):
            msg = "Incorrect username or password."
        else:
            msg = f"Login failed: {detail}"
        self._show_login_error(msg)

    def _show_login_error(self, msg):
        self._login_error.set_label(msg)
        self._login_error.set_visible(True)

    def _set_login_busy(self, busy):
        self._login_btn.set_sensitive(not busy)
        self._username.set_sensitive(not busy)
        self._password.set_sensitive(not busy)
        self._login_spinner.start() if busy else self._login_spinner.stop()

    # ── Sign up ───────────────────────────────────────────────────────────────

    def _on_signup_clicked(self, _widget):
        full_name = self._su_fullname.get_text().strip()
        username  = self._su_username.get_text().strip()
        password  = self._su_password.get_text()
        confirm   = self._su_confirm.get_text()

        if not full_name:
            self._show_signup_error("Full name is required.")
            return
        if len(username) < 3:
            self._show_signup_error("Username must be at least 3 characters.")
            return
        if len(password) < 8:
            self._show_signup_error("Password must be at least 8 characters.")
            return
        if password != confirm:
            self._show_signup_error("Passwords do not match.")
            return

        self._set_signup_busy(True)
        run(api.signup(username, password, full_name),
            on_done=self._signup_ok,
            on_error=self._signup_fail)

    def _signup_ok(self, result):
        self._set_signup_busy(False)
        self._signup_error.set_visible(False)
        self._signup_success.set_label(
            "✓ Account created! You can now log in."
        )
        self._signup_success.set_visible(True)
        # Pre-fill login and switch after 1.5 s
        self._username.set_text(self._su_username.get_text().strip())
        self._password.set_text("")
        GLib.timeout_add(1500, lambda: (self._show_page("login"), False)[1])

    def _signup_fail(self, exc):
        self._set_signup_busy(False)
        self._show_signup_error(str(getattr(exc, "detail", exc)))

    def _show_signup_error(self, msg):
        self._signup_error.set_label(msg)
        self._signup_error.set_visible(True)

    def _set_signup_busy(self, busy):
        self._signup_btn.set_sensitive(not busy)
        self._su_fullname.set_sensitive(not busy)
        self._su_username.set_sensitive(not busy)
        self._su_password.set_sensitive(not busy)
        self._su_confirm.set_sensitive(not busy)
        self._signup_spinner.start() if busy else self._signup_spinner.stop()
