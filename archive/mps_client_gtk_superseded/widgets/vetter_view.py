"""
widgets/vetter_view.py
Vetter panel: review queue + editable draft + submit to MP.

Workflow:
  1. Vetter selects a case from the queue
  2. Draft loads — vetter edits it directly (TextView is fully editable)
  3. Vetter clicks "Submit to MP" → final_content saved, letter frozen, case → pending_mp
  4. Vetter can also "Return to volunteer" if they need more info first
"""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gdk, GLib

from .. import api_client as api
from ..async_bridge import run


class VetterPanel(Gtk.Box):
    """
    Full-width panel for vetter role.
    Left:  queue of cases in 'drafted' status
    Right: fully editable letter + Submit to MP / Return to volunteer
    """

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self._cases  = []
        self._case   = None
        self._letter = None

        # ── Left: queue ───────────────────────────────────────────────────────
        left_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        left_box.set_size_request(320, -1)
        self.append(left_box)

        queue_hdr = Gtk.Label(label="Pending vetting")
        queue_hdr.add_css_class("title-4")
        queue_hdr.set_margin_top(12)
        queue_hdr.set_margin_start(12)
        queue_hdr.set_margin_bottom(8)
        queue_hdr.set_halign(Gtk.Align.START)
        left_box.append(queue_hdr)

        refresh_btn = Gtk.Button(label="Refresh queue")
        refresh_btn.add_css_class("flat")
        refresh_btn.set_margin_start(8)
        refresh_btn.set_margin_end(8)
        refresh_btn.set_margin_bottom(4)
        refresh_btn.connect("clicked", self._load_queue)
        left_box.append(refresh_btn)

        q_scroll = Gtk.ScrolledWindow(vexpand=True)
        q_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        left_box.append(q_scroll)

        self._queue_list = Gtk.ListBox()
        self._queue_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._queue_list.add_css_class("navigation-sidebar")
        self._queue_list.connect("row-selected", self._on_queue_row_selected)
        q_scroll.set_child(self._queue_list)

        empty_lbl = Gtk.Label(label="Queue empty — all cases vetted!")
        empty_lbl.add_css_class("dim-label")
        empty_lbl.set_margin_top(32)
        self._queue_list.set_placeholder(empty_lbl)

        self.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        # ── Right: editable letter ────────────────────────────────────────────
        right_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=8, hexpand=True
        )
        right_box.set_margin_top(8)
        right_box.set_margin_bottom(8)
        right_box.set_margin_start(8)
        right_box.set_margin_end(8)
        self.append(right_box)

        # Case header
        self._case_header = Gtk.Label(label="Select a case from the queue")
        self._case_header.set_halign(Gtk.Align.START)
        self._case_header.add_css_class("title-3")
        right_box.append(self._case_header)

        self._resident_lbl = Gtk.Label(label="")
        self._resident_lbl.set_halign(Gtk.Align.START)
        self._resident_lbl.add_css_class("caption")
        right_box.append(self._resident_lbl)

        # Volunteer notes (read-only context for vetter)
        notes_hdr = Gtk.Label(label="Volunteer notes (read-only):")
        notes_hdr.set_halign(Gtk.Align.START)
        notes_hdr.add_css_class("caption")
        right_box.append(notes_hdr)

        notes_scroll = Gtk.ScrolledWindow()
        notes_scroll.set_min_content_height(70)
        notes_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._notes_buf = Gtk.TextBuffer()
        notes_view = Gtk.TextView(buffer=self._notes_buf)
        notes_view.set_wrap_mode(Gtk.WrapMode.WORD)
        notes_view.set_editable(False)
        notes_view.set_cursor_visible(False)
        notes_view.add_css_class("dim-label")
        notes_view.set_left_margin(8)
        notes_view.set_top_margin(4)
        notes_view.set_bottom_margin(4)
        notes_scroll.set_child(notes_view)
        right_box.append(notes_scroll)

        right_box.append(Gtk.Separator())

        # Editable draft label with edit hint
        draft_hdr_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        right_box.append(draft_hdr_box)

        draft_lbl = Gtk.Label(label="Draft letter — edit directly, then submit to MP:")
        draft_lbl.set_halign(Gtk.Align.START)
        draft_lbl.set_hexpand(True)
        draft_hdr_box.append(draft_lbl)

        self._edit_badge = Gtk.Label(label="✎ editable")
        self._edit_badge.add_css_class("caption")
        self._edit_badge.add_css_class("success")
        self._edit_badge.set_visible(False)
        draft_hdr_box.append(self._edit_badge)

        # Editable letter text area
        draft_scroll = Gtk.ScrolledWindow(vexpand=True)
        draft_scroll.set_min_content_height(280)
        draft_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._draft_buf = Gtk.TextBuffer()
        self._draft_buf.connect("changed", self._on_draft_changed)
        self._draft_view = Gtk.TextView(buffer=self._draft_buf)
        self._draft_view.set_wrap_mode(Gtk.WrapMode.WORD)
        self._draft_view.set_editable(False)   # enabled once letter loads
        self._draft_view.set_left_margin(8)
        self._draft_view.set_right_margin(8)
        self._draft_view.set_top_margin(8)
        self._draft_view.set_bottom_margin(8)
        draft_scroll.set_child(self._draft_view)
        right_box.append(draft_scroll)

        # Return comment (shown when vetter wants to send back to volunteer)
        self._return_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._return_box.set_visible(False)
        right_box.append(self._return_box)

        ret_lbl = Gtk.Label(
            label="Comment for volunteer (required — explain what information is missing):"
        )
        ret_lbl.set_halign(Gtk.Align.START)
        ret_lbl.add_css_class("caption")
        self._return_box.append(ret_lbl)

        self._return_entry = Gtk.Entry()
        self._return_entry.set_placeholder_text(
            "e.g. Please ask the resident for the rejection letter reference number"
        )
        self._return_box.append(self._return_entry)

        ret_confirm_btn = Gtk.Button(label="Confirm return to volunteer")
        ret_confirm_btn.add_css_class("destructive-action")
        ret_confirm_btn.connect("clicked", self._on_return_confirm)
        self._return_box.append(ret_confirm_btn)

        # Status label
        self._status_lbl = Gtk.Label(label="")
        self._status_lbl.add_css_class("caption")
        self._status_lbl.set_halign(Gtk.Align.START)
        right_box.append(self._status_lbl)

        # Action row
        action_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        action_row.set_halign(Gtk.Align.END)
        right_box.append(action_row)

        self._copy_btn = Gtk.Button(label="Copy")
        self._copy_btn.set_sensitive(False)
        self._copy_btn.connect("clicked", self._on_copy)
        action_row.append(self._copy_btn)

        self._return_btn = Gtk.Button(label="Return to volunteer")
        self._return_btn.set_sensitive(False)
        self._return_btn.connect("clicked", self._on_return_clicked)
        action_row.append(self._return_btn)

        self._submit_btn = Gtk.Button(label="Submit to MP")
        self._submit_btn.add_css_class("suggested-action")
        self._submit_btn.add_css_class("pill")
        self._submit_btn.set_sensitive(False)
        self._submit_btn.connect("clicked", self._on_submit_to_mp)
        action_row.append(self._submit_btn)

        # Initial load
        self._load_queue()

    # ── Queue ─────────────────────────────────────────────────────────────────

    def _load_queue(self, *_):
        run(api.get_vetter_queue(), on_done=self._populate_queue)

    def _populate_queue(self, cases):
        self._cases = cases
        child = self._queue_list.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._queue_list.remove(child)
            child = nxt
        for case in cases:
            row = self._build_queue_row(case)
            row._case = case
            self._queue_list.append(row)

    def _build_queue_row(self, case):
        row = Gtk.ListBoxRow()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(12)
        box.set_margin_end(12)
        row.set_child(box)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.append(top)

        agency    = case.get("agency", "")
        case_type = case.get("case_type", "")
        urgency   = case.get("urgency", "normal")

        lbl = Gtk.Label(label=agency + " — " + case_type)
        lbl.set_halign(Gtk.Align.START)
        lbl.add_css_class("body")
        top.append(lbl)

        if urgency == "urgent":
            urg = Gtk.Label(label="URGENT")
            urg.add_css_class("error")
            urg.add_css_class("caption")
            top.append(urg)

        res = case.get("resident", {}) or {}
        res_lbl = Gtk.Label(
            label=res.get("name", "") + "  " + res.get("nric_masked", "")
        )
        res_lbl.set_halign(Gtk.Align.START)
        res_lbl.add_css_class("caption")
        res_lbl.add_css_class("dim-label")
        box.append(res_lbl)

        return row

    def _on_queue_row_selected(self, listbox, row):
        if row is None:
            return
        case = getattr(row, "_case", None)
        if case:
            self._load_case(case)

    # ── Case / Letter ─────────────────────────────────────────────────────────

    def _load_case(self, case):
        self._case   = case
        self._letter = None
        self._draft_buf.set_text("")
        self._notes_buf.set_text("")
        self._status_lbl.set_label("")
        self._return_entry.set_text("")
        self._return_box.set_visible(False)
        self._draft_view.set_editable(False)
        self._edit_badge.set_visible(False)
        self._set_actions_sensitive(False)

        agency    = case.get("agency", "")
        case_type = case.get("case_type", "")
        self._case_header.set_label(agency + " — " + case_type)

        res = case.get("resident", {}) or {}
        self._resident_lbl.set_label(
            res.get("name", "") + "  |  " + res.get("nric_masked", "")
        )

        letter_id = case.get("letter_id")
        if letter_id:
            run(
                api.get_letter(letter_id),
                on_done=self._populate_letter,
                on_error=self._on_err,
            )
        else:
            self._status_lbl.set_label("No draft letter yet — volunteer has not generated one.")

    def _populate_letter(self, letter):
        self._letter = letter
        # Show the most recent content: draft (volunteer wrote) or final (previous vetter edit)
        content = letter.get("final_content") or letter.get("draft_content") or ""
        self._draft_buf.set_text(content)

        # Show volunteer notes if stored (may not be present in all versions)
        notes = letter.get("notes", "")
        self._notes_buf.set_text(notes if notes else "(no notes recorded)")

        is_frozen = letter.get("is_frozen", False)
        if is_frozen:
            self._status_lbl.set_label(
                "This letter has already been submitted to the MP."
            )
            self._draft_view.set_editable(False)
            self._edit_badge.set_visible(False)
            self._set_actions_sensitive(False)
        else:
            self._draft_view.set_editable(True)
            self._edit_badge.set_visible(True)
            self._status_lbl.set_label(
                "Edit the draft below, then click Submit to MP."
            )
            self._set_actions_sensitive(True)

    def _on_draft_changed(self, buf):
        # Enable submit only when there is actual content
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()
        self._submit_btn.set_sensitive(bool(text) and self._letter is not None)

    def _set_actions_sensitive(self, enabled):
        self._copy_btn.set_sensitive(enabled)
        self._return_btn.set_sensitive(enabled)
        # submit_btn is also gated by _on_draft_changed

    # ── Copy ──────────────────────────────────────────────────────────────────

    def _on_copy(self, _btn):
        buf  = self._draft_buf
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set(text)
        self._copy_btn.set_label("Copied!")
        GLib.timeout_add(2000, lambda: (self._copy_btn.set_label("Copy"), False)[1])

    # ── Submit to MP ──────────────────────────────────────────────────────────

    def _on_submit_to_mp(self, _btn):
        if not self._case or not self._letter:
            return
        buf          = self._draft_buf
        final_text   = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()
        if not final_text:
            self._status_lbl.set_label("Letter is empty — cannot submit.")
            return

        self._set_actions_sensitive(False)
        self._submit_btn.set_sensitive(False)
        self._submit_btn.set_label("Submitting...")
        self._draft_view.set_editable(False)
        self._edit_badge.set_visible(False)

        run(
            api.vetter_submit(self._case["id"], final_text),
            on_done=self._on_submit_done,
            on_error=self._on_err,
        )

    def _on_submit_done(self, result):
        self._submit_btn.set_label("Submitted to MP")
        self._status_lbl.set_label(
            "Letter submitted. MP will review and approve in the MPS platform."
        )
        self._case   = None
        self._letter = None
        # Reload queue after short delay
        GLib.timeout_add(800, self._reload_after_action)

    # ── Return to volunteer ───────────────────────────────────────────────────

    def _on_return_clicked(self, _btn):
        # Toggle the return comment box
        visible = self._return_box.get_visible()
        self._return_box.set_visible(not visible)
        if not visible:
            self._return_entry.grab_focus()

    def _on_return_confirm(self, _btn):
        if not self._case:
            return
        comment = self._return_entry.get_text().strip()
        if not comment:
            self._status_lbl.set_label(
                "Enter a comment explaining what information is needed."
            )
            return
        self._set_actions_sensitive(False)
        self._submit_btn.set_sensitive(False)
        self._return_box.set_visible(False)
        self._status_lbl.set_label("Returning to volunteer...")

        run(
            api.vetter_return(self._case["id"], comment),
            on_done=self._on_return_done,
            on_error=self._on_err,
        )

    def _on_return_done(self, _result):
        self._status_lbl.set_label("Returned to volunteer.")
        self._case   = None
        self._letter = None
        self._draft_buf.set_text("")
        self._case_header.set_label("Select a case from the queue")
        self._resident_lbl.set_label("")
        self._draft_view.set_editable(False)
        self._edit_badge.set_visible(False)
        GLib.timeout_add(800, self._reload_after_action)

    def _reload_after_action(self):
        self._load_queue()
        self._submit_btn.set_label("Submit to MP")
        return False

    # ── Error ─────────────────────────────────────────────────────────────────

    def _on_err(self, exc):
        self._status_lbl.set_label("Error: " + str(getattr(exc, "detail", exc)))
        self._set_actions_sensitive(True)
        self._submit_btn.set_sensitive(True)
        self._submit_btn.set_label("Submit to MP")
        self._draft_view.set_editable(True)
        self._edit_badge.set_visible(True)
