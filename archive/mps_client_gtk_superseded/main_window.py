"""
main_window.py — Main window (libadwaita 1.1.x compatible)
Left: session status + case list | Right: LetterView or VetterPanel (role-based)
"""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

from . import api_client as api
from .async_bridge import run
from .widgets.case_form import CaseFormDialog
from .widgets.letter_view import LetterView
from .widgets.vetter_view import VetterPanel
from .widgets.profile_window import ProfileWindow


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app, on_logout):
        super().__init__(application=app)
        self._on_logout  = on_logout
        self._session    = None
        self._cases      = []
        self._refresh_id = 0

        self.set_title("MPS AI Agent")
        self.set_default_size(1100, 700)

        # Root box (Adw.ToolbarView needs >= 1.4)
        root_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(root_box)

        # ── Header bar ────────────────────────────────────────────────────────
        header = Adw.HeaderBar()
        root_box.append(header)

        title_lbl = Gtk.Label(label="MPS AI Agent")
        title_lbl.add_css_class("title-4")
        header.set_title_widget(title_lbl)

        self._user_lbl = Gtk.Label(label=api.auth.full_name + " (" + api.auth.role + ")")
        self._user_lbl.add_css_class("caption")
        header.pack_end(self._user_lbl)

        logout_btn = Gtk.Button(label="Logout")
        logout_btn.add_css_class("flat")
        logout_btn.connect("clicked", self._on_logout_clicked)
        header.pack_end(logout_btn)

        profile_btn = Gtk.Button(label="⚙ Profile")
        profile_btn.add_css_class("flat")
        profile_btn.connect("clicked", self._open_profile)
        header.pack_end(profile_btn)

        qa_btn = Gtk.Button(label="Policy Q&A")
        qa_btn.add_css_class("flat")
        qa_btn.connect("clicked", self._open_qa_panel)
        header.pack_start(qa_btn)

        # ── Body pane ─────────────────────────────────────────────────────────
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_position(340)
        paned.set_vexpand(True)
        root_box.append(paned)

        # ── Left panel ────────────────────────────────────────────────────────
        left_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        paned.set_start_child(left_box)
        paned.set_shrink_start_child(False)

        # Session banner — Adw.Banner needs >= 1.3; use a styled label row
        banner_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        banner_box.add_css_class("toolbar")
        banner_box.add_css_class("osd")
        self._session_label = Gtk.Label(label="Loading session...")
        self._session_label.set_hexpand(True)
        self._session_label.set_halign(Gtk.Align.START)
        self._session_label.set_margin_start(12)
        self._session_label.set_margin_top(6)
        self._session_label.set_margin_bottom(6)
        banner_box.append(self._session_label)
        left_box.append(banner_box)

        new_case_btn = Gtk.Button(label="+ New Case")
        new_case_btn.add_css_class("suggested-action")
        new_case_btn.set_margin_top(8)
        new_case_btn.set_margin_start(8)
        new_case_btn.set_margin_end(8)
        new_case_btn.set_margin_bottom(4)
        new_case_btn.connect("clicked", self._on_new_case)
        left_box.append(new_case_btn)

        case_scroll = Gtk.ScrolledWindow(vexpand=True)
        case_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        left_box.append(case_scroll)

        self._case_list = Gtk.ListBox()
        self._case_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._case_list.add_css_class("navigation-sidebar")
        self._case_list.connect("row-selected", self._on_case_selected)
        case_scroll.set_child(self._case_list)

        empty_lbl = Gtk.Label(label="No cases yet.\nClick + New Case to begin.")
        empty_lbl.set_justify(Gtk.Justification.CENTER)
        empty_lbl.add_css_class("dim-label")
        empty_lbl.set_margin_top(32)
        self._case_list.set_placeholder(empty_lbl)

        refresh_btn = Gtk.Button(label="Refresh")
        refresh_btn.add_css_class("flat")
        refresh_btn.set_margin_start(8); refresh_btn.set_margin_end(8)
        refresh_btn.set_margin_bottom(8)
        refresh_btn.connect("clicked", self._refresh)
        left_box.append(refresh_btn)

        # ── Right panel — role-based ───────────────────────────────────────────
        right_scroll = Gtk.ScrolledWindow()
        right_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        paned.set_end_child(right_scroll)

        if api.auth.role in ("vetter", "admin"):
            self._letter_view  = None
            self._vetter_panel = VetterPanel()
            right_scroll.set_child(self._vetter_panel)
        else:
            self._vetter_panel = None
            self._letter_view  = LetterView(on_submitted=self._on_case_submitted)
            right_scroll.set_child(self._letter_view)

        # ── Policy Q&A window (hidden) ────────────────────────────────────────
        self._qa_window = self._build_qa_window()

        # ── Profile window (hidden) ───────────────────────────────────────────
        self._profile_window = ProfileWindow(
            parent=self,
            on_username_changed=self._on_username_changed,
        )

        self._refresh()
        self._refresh_id = GLib.timeout_add_seconds(60, self._auto_refresh)

    # ── Q&A window ───────────────────────────────────────────────────────────

    def _build_qa_window(self):
        """Adw.Dialog needs >= 1.5 — use a plain Gtk.Window instead."""
        win = Gtk.Window()
        win.set_title("Policy Q&A")
        win.set_modal(True)
        win.set_transient_for(self)
        win.set_default_size(520, 560)
        win.connect("close-request", lambda w: w.hide() or True)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        win.set_child(root)
        root.append(Adw.HeaderBar())

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_vexpand(True)
        box.set_margin_top(8); box.set_margin_bottom(8)
        box.set_margin_start(8); box.set_margin_end(8)
        root.append(box)

        q_lbl = Gtk.Label(label="Ask a policy question:")
        q_lbl.set_halign(Gtk.Align.START)
        box.append(q_lbl)

        qa_entry = Gtk.Entry()
        qa_entry.set_placeholder_text("e.g. What is the income ceiling for HDB BTO?")
        box.append(qa_entry)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.append(btn_row)
        qa_btn = Gtk.Button(label="Ask")
        qa_btn.add_css_class("suggested-action")
        btn_row.append(qa_btn)
        qa_spinner = Gtk.Spinner()
        btn_row.append(qa_spinner)

        ans_scroll = Gtk.ScrolledWindow(vexpand=True)
        ans_buf = Gtk.TextBuffer()
        ans_view = Gtk.TextView(buffer=ans_buf)
        ans_view.set_wrap_mode(Gtk.WrapMode.WORD)
        ans_view.set_editable(False)
        ans_view.set_left_margin(8); ans_view.set_right_margin(8)
        ans_view.set_top_margin(8); ans_view.set_bottom_margin(8)
        ans_scroll.set_child(ans_view)
        box.append(ans_scroll)

        def on_ask(_w):
            q = qa_entry.get_text().strip()
            if not q: return
            ans_buf.set_text("")
            qa_btn.set_sensitive(False)
            qa_spinner.start()
            run(api.stream_qa(
                question=q,
                on_chunk=lambda t: ans_buf.insert(ans_buf.get_end_iter(), t),
                on_done=lambda: (qa_btn.set_sensitive(True), qa_spinner.stop()),
                on_error=lambda m: (
                    ans_buf.set_text("Error: " + str(m)),
                    qa_btn.set_sensitive(True),
                    qa_spinner.stop(),
                ),
            ))
        qa_btn.connect("clicked", on_ask)
        qa_entry.connect("activate", on_ask)
        return win

    # ── Session ───────────────────────────────────────────────────────────────

    def _refresh(self, *_):
        run(api.get_current_session(),
            on_done=self._on_session_loaded,
            on_error=lambda _: self._session_label.set_label("Could not reach server"))
        run(api.get_my_cases(), on_done=self._populate_cases)

    def _auto_refresh(self):
        self._refresh()
        return True

    def _on_session_loaded(self, session):
        self._session = session
        if session is None:
            self._session_label.set_label("No active session tonight")
        else:
            date     = session.get("date", "")
            total    = session.get("total_cases", 0)
            complete = session.get("completed_cases", 0)
            self._session_label.set_label(
                date + "  —  " + str(complete) + "/" + str(total) + " cases done"
            )

    # ── Cases ─────────────────────────────────────────────────────────────────

    def _populate_cases(self, cases):
        self._cases = cases
        child = self._case_list.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._case_list.remove(child)
            child = nxt
        for case in cases:
            row = self._build_case_row(case)
            row._case = case
            self._case_list.append(row)

    def _build_case_row(self, case):
        row = Gtk.ListBoxRow()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_top(8); box.set_margin_bottom(8)
        box.set_margin_start(12); box.set_margin_end(12)
        row.set_child(box)

        agency    = case.get("agency", "")
        case_type = case.get("case_type", "")
        status    = case.get("status", "")

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.append(top)

        name_lbl = Gtk.Label(label=agency + " — " + case_type)
        name_lbl.set_halign(Gtk.Align.START)
        name_lbl.add_css_class("body")
        top.append(name_lbl)

        status_lbl = Gtk.Label(label=status)
        status_lbl.set_halign(Gtk.Align.END)
        status_lbl.set_hexpand(True)
        status_lbl.add_css_class("caption")
        if status == "returned":
            status_lbl.add_css_class("error")
        elif status == "drafted":
            status_lbl.add_css_class("warning")
        elif status in ("vetted", "pending_mp"):
            status_lbl.add_css_class("success")
        top.append(status_lbl)

        res = case.get("resident", {}) or {}
        res_lbl = Gtk.Label(
            label=res.get("name","") + "  " + res.get("nric_masked",""))
        res_lbl.set_halign(Gtk.Align.START)
        res_lbl.add_css_class("caption")
        res_lbl.add_css_class("dim-label")
        box.append(res_lbl)

        return row

    def _on_case_selected(self, listbox, row):
        if row is None: return
        case = getattr(row, "_case", None)
        if case and self._letter_view:
            self._letter_view.load_case(case)

    def _on_case_submitted(self, case_id):
        self._refresh()

    # ── New Case ──────────────────────────────────────────────────────────────

    def _on_new_case(self, _btn):
        if self._session is None:
            # Adw.AlertDialog needs >= 1.5 — use Gtk.MessageDialog
            dlg = Gtk.MessageDialog(
                transient_for=self, modal=True,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.OK,
                text="No Active Session",
                secondary_text="There is no active MPS session tonight. Ask an admin to open one.",
            )
            dlg.connect("response", lambda d, _: d.destroy())
            dlg.show()
            return
        dlg = CaseFormDialog(session_id=self._session["id"],
                             on_case_created=self._on_new_case_created)
        dlg.present(self)

    def _on_new_case_created(self, case):
        self._refresh()
        GLib.timeout_add(500, self._select_case_by_id, case["id"])

    def _select_case_by_id(self, case_id):
        child = self._case_list.get_first_child()
        while child:
            if getattr(child, "_case", {}).get("id") == case_id:
                self._case_list.select_row(child)
                break
            child = child.get_next_sibling()
        return False

    def _open_profile(self, _btn):
        self._profile_window.present()

    def _on_username_changed(self, new_username):
        """Update header label when user changes their username."""
        self._user_lbl.set_label(new_username + " (" + api.auth.role + ")")

    def _open_qa_panel(self, _btn):
        self._qa_window.present()

    def _on_logout_clicked(self, _btn):
        if self._refresh_id:
            GLib.source_remove(self._refresh_id)
            self._refresh_id = 0
        run(api.logout())
        self._on_logout()
