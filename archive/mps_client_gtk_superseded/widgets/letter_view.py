"""
widgets/letter_view.py
Streaming draft letter panel + copy-to-clipboard button.
Core daily tool for MPS volunteers.
"""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gdk, GLib

from .. import api_client as api
from ..async_bridge import run


class LetterView(Gtk.Box):
    """
    Panel shown when a case row is selected.
    Layout:
      Notes textview    <- volunteer fills case details
      Generate button   <- triggers WebSocket streaming
      Status bar        <- queue position / spinner
      Draft textview    <- editable after generation
      Copy button       <- copies text to clipboard
      Submit button     <- submits for vetter review
    """

    def __init__(self, on_submitted=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.set_margin_top(8); self.set_margin_bottom(8)
        self.set_margin_start(8); self.set_margin_end(8)

        self._on_submitted = on_submitted
        self._case         = None
        self._letter_id    = None
        self._generating   = False

        # Header
        self._header = Gtk.Label(label="Select a case to begin")
        self._header.set_halign(Gtk.Align.START)
        self._header.add_css_class("title-3")
        self.append(self._header)

        self._resident_lbl = Gtk.Label(label="")
        self._resident_lbl.set_halign(Gtk.Align.START)
        self._resident_lbl.add_css_class("caption")
        self.append(self._resident_lbl)

        self.append(Gtk.Separator())

        # Notes
        notes_lbl = Gtk.Label(label="Case notes (what the resident told you):")
        notes_lbl.set_halign(Gtk.Align.START)
        self.append(notes_lbl)

        notes_scroll = Gtk.ScrolledWindow()
        notes_scroll.set_min_content_height(120)
        notes_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._notes_view = Gtk.TextView()
        self._notes_view.set_wrap_mode(Gtk.WrapMode.WORD)
        self._notes_view.set_left_margin(8); self._notes_view.set_right_margin(8)
        self._notes_view.set_top_margin(8); self._notes_view.set_bottom_margin(8)
        notes_scroll.set_child(self._notes_view)
        self.append(notes_scroll)

        # Re-appeal extras
        self._reappeal_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._reappeal_box.set_visible(False)
        self.append(self._reappeal_box)
        rej_lbl = Gtk.Label(label="Rejection reason (if known):")
        rej_lbl.set_halign(Gtk.Align.START)
        self._reappeal_box.append(rej_lbl)
        self._rejection_entry = Gtk.Entry()
        self._rejection_entry.set_placeholder_text("e.g. Income ceiling exceeded")
        self._reappeal_box.append(self._rejection_entry)

        # Generate row
        gen_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.append(gen_row)
        self._gen_btn = Gtk.Button(label="Generate Draft")
        self._gen_btn.add_css_class("suggested-action")
        self._gen_btn.set_sensitive(False)
        self._gen_btn.connect("clicked", self._on_generate)
        gen_row.append(self._gen_btn)
        self._spinner = Gtk.Spinner()
        gen_row.append(self._spinner)
        self._status_lbl = Gtk.Label(label="")
        self._status_lbl.add_css_class("caption")
        gen_row.append(self._status_lbl)

        self.append(Gtk.Separator())

        # Draft
        draft_lbl = Gtk.Label(label="Draft letter (edit before copying):")
        draft_lbl.set_halign(Gtk.Align.START)
        self.append(draft_lbl)

        draft_scroll = Gtk.ScrolledWindow(vexpand=True)
        draft_scroll.set_min_content_height(200)
        draft_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._draft_buf = Gtk.TextBuffer()
        self._draft_view = Gtk.TextView(buffer=self._draft_buf)
        self._draft_view.set_wrap_mode(Gtk.WrapMode.WORD)
        self._draft_view.set_left_margin(8); self._draft_view.set_right_margin(8)
        self._draft_view.set_top_margin(8); self._draft_view.set_bottom_margin(8)
        self._draft_view.set_editable(False)
        draft_scroll.set_child(self._draft_view)
        self.append(draft_scroll)

        # Vetter comment (shown when case returned)
        self._vetter_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._vetter_box.set_visible(False)
        self.append(self._vetter_box)
        vn_lbl = Gtk.Label(label="Vetter comment:")
        vn_lbl.set_halign(Gtk.Align.START)
        vn_lbl.add_css_class("error")
        self._vetter_box.append(vn_lbl)
        self._vetter_note = Gtk.Label(label="")
        self._vetter_note.set_halign(Gtk.Align.START)
        self._vetter_note.set_wrap(True)
        self._vetter_box.append(self._vetter_note)

        # Action row
        action_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        action_row.set_halign(Gtk.Align.END)
        self.append(action_row)

        self._save_btn = Gtk.Button(label="Save edits")
        self._save_btn.set_sensitive(False)
        self._save_btn.connect("clicked", self._on_save)
        action_row.append(self._save_btn)

        self._copy_btn = Gtk.Button(label="Copy to Clipboard")
        self._copy_btn.add_css_class("pill")
        self._copy_btn.add_css_class("suggested-action")
        self._copy_btn.set_sensitive(False)
        self._copy_btn.connect("clicked", self._on_copy)
        action_row.append(self._copy_btn)

        self._submit_btn = Gtk.Button(label="Submit for vetting")
        self._submit_btn.add_css_class("destructive-action")
        self._submit_btn.set_sensitive(False)
        self._submit_btn.connect("clicked", self._on_submit)
        action_row.append(self._submit_btn)

    # ── Public ────────────────────────────────────────────────────────────────

    def load_case(self, case: dict):
        self._case      = case
        self._letter_id = case.get("letter_id")
        status          = case.get("status", "")

        agency    = case.get("agency", "")
        case_type = case.get("case_type", "")
        self._header.set_label(agency + " — " + case_type)

        res = case.get("resident", {}) or {}
        if res:
            self._resident_lbl.set_label(
                res.get("name", "") + "  |  " + res.get("nric_masked", "")
            )

        is_reappeal = not case.get("is_new_issue", True)
        self._reappeal_box.set_visible(is_reappeal)

        comment = case.get("vetter_comment", "")
        if comment:
            self._vetter_box.set_visible(True)
            self._vetter_note.set_label(comment)
        else:
            self._vetter_box.set_visible(False)

        if self._letter_id:
            run(api.get_letter(self._letter_id),
                on_done=self._populate_letter, on_error=self._on_err)
        else:
            self._draft_buf.set_text("")
            self._draft_view.set_editable(False)

        is_frozen = status in ("vetted", "approved", "sent")
        self._gen_btn.set_sensitive(not is_frozen)
        self._draft_view.set_editable(not is_frozen and bool(self._letter_id))
        self._copy_btn.set_sensitive(bool(self._letter_id))
        self._save_btn.set_sensitive(bool(self._letter_id) and not is_frozen)
        self._submit_btn.set_sensitive(
            bool(self._letter_id)
            and status not in ("drafted", "vetted", "approved", "sent")
        )

    def _populate_letter(self, letter: dict):
        content = letter.get("draft_content") or letter.get("final_content") or ""
        self._draft_buf.set_text(content)
        self._copy_btn.set_sensitive(True)
        self._save_btn.set_sensitive(True)
        self._submit_btn.set_sensitive(True)
        self._draft_view.set_editable(True)

    # ── Generate ──────────────────────────────────────────────────────────────

    def _on_generate(self, _btn):
        if not self._case:
            return
        buf   = self._notes_view.get_buffer()
        notes = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()
        if not notes:
            self._status_lbl.set_label("Enter case notes before generating.")
            return

        is_reappeal = not self._case.get("is_new_issue", True)
        rejection   = self._rejection_entry.get_text().strip() if is_reappeal else ""

        self._draft_buf.set_text("")
        self._draft_view.set_editable(False)
        self._copy_btn.set_sensitive(False)
        self._submit_btn.set_sensitive(False)
        self._save_btn.set_sensitive(False)
        self._gen_btn.set_sensitive(False)
        self._spinner.start()
        self._status_lbl.set_label("Queued...")
        self._generating = True

        run(api.stream_draft(
            case_id=self._case["id"],
            notes=notes,
            is_reappeal=is_reappeal,
            rejection_reason=rejection,
            previous_letter_id=self._letter_id,
            on_chunk=self._on_chunk,
            on_queue=self._on_queue,
            on_done=self._on_done,
            on_error=self._on_stream_err,
        ))

    def _on_queue(self, position):
        if position > 0:
            self._status_lbl.set_label("Queue position: " + str(position))
        else:
            self._status_lbl.set_label("Generating...")

    def _on_chunk(self, text):
        end = self._draft_buf.get_end_iter()
        self._draft_buf.insert(end, text)
        end2 = self._draft_buf.get_end_iter()
        self._draft_view.scroll_to_iter(end2, 0, False, 0, 0)

    def _on_done(self, letter_id):
        self._letter_id = letter_id
        self._generating = False
        self._spinner.stop()
        self._status_lbl.set_label("Done — review and edit before copying.")
        self._draft_view.set_editable(True)
        self._copy_btn.set_sensitive(True)
        self._save_btn.set_sensitive(True)
        self._submit_btn.set_sensitive(True)
        self._gen_btn.set_sensitive(True)

    def _on_stream_err(self, msg):
        self._generating = False
        self._spinner.stop()
        self._status_lbl.set_label("Error: " + str(msg))
        self._gen_btn.set_sensitive(True)

    # ── Copy ──────────────────────────────────────────────────────────────────

    def _on_copy(self, _btn):
        buf  = self._draft_buf
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set(text)
        self._copy_btn.set_label("Copied!")
        GLib.timeout_add(2000, self._reset_copy_label)

    def _reset_copy_label(self):
        self._copy_btn.set_label("Copy to Clipboard")
        return False

    # ── Save ──────────────────────────────────────────────────────────────────

    def _on_save(self, _btn):
        if not self._letter_id:
            return
        buf  = self._draft_buf
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        self._save_btn.set_sensitive(False)
        self._save_btn.set_label("Saving...")
        run(api.update_letter(self._letter_id, text),
            on_done=self._on_save_done, on_error=self._on_err)

    def _on_save_done(self, _letter):
        self._save_btn.set_sensitive(True)
        self._save_btn.set_label("Saved!")
        GLib.timeout_add(2000, lambda: (self._save_btn.set_label("Save edits"), False)[1])

    # ── Submit ────────────────────────────────────────────────────────────────

    def _on_submit(self, _btn):
        if not self._case:
            return
        self._submit_btn.set_sensitive(False)
        self._submit_btn.set_label("Submitting...")
        run(api.submit_case(self._case["id"]),
            on_done=self._on_submit_done, on_error=self._on_err)

    def _on_submit_done(self, _case):
        self._submit_btn.set_label("Submitted for vetting")
        if self._on_submitted:
            self._on_submitted(self._case["id"])

    # ── Error ─────────────────────────────────────────────────────────────────

    def _on_err(self, exc):
        self._status_lbl.set_label("Error: " + str(getattr(exc, "detail", exc)))
        self._spinner.stop()
        self._gen_btn.set_sensitive(True)
