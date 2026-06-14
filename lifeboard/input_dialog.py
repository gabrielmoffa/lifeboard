#!/usr/bin/env python3
"""
Standalone floating input dialog for Lifeboard.
Runs as a separate process so it can take focus over any app.
Prints the user's input to stdout and exits.
"""

import sys
from AppKit import (
    NSApplication, NSPanel, NSTextField, NSButton, NSFont, NSColor,
    NSMakeRect, NSFloatingWindowLevel, NSTitledWindowMask,
    NSClosableWindowMask, NSObject,
)
from PyObjCTools import AppHelper
import objc


class DialogDelegate(NSObject):
    def init(self):
        self = objc.super(DialogDelegate, self).init()
        self.result = None
        return self

    @objc.python_method
    def setup(self, panel, text_field):
        self.panel = panel
        self.text_field = text_field

    @objc.python_method
    def _current_text(self):
        editor = self.text_field.currentEditor()
        if editor is not None:
            return editor.string().strip()
        return self.text_field.stringValue().strip()

    @objc.python_method
    def _submit_text(self, text):
        if text:
            self.result = text
            print(text, flush=True)
            NSApplication.sharedApplication().terminate_(None)

    def submit_(self, sender):
        self._submit_text(self._current_text())

    def control_textView_doCommandBySelector_(self, control, text_view, command_selector):
        if command_selector in (
            b"insertNewline:",
            b"insertNewlineIgnoringFieldEditor:",
            "insertNewline:",
            "insertNewlineIgnoringFieldEditor:",
        ):
            self._submit_text(text_view.string().strip())
            return True
        return False

    def windowWillClose_(self, notification):
        NSApplication.sharedApplication().terminate_(None)


def main():
    title = sys.argv[1] if len(sys.argv) > 1 else "Lifeboard"
    message = sys.argv[2] if len(sys.argv) > 2 else "What do you want to change?"

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(0)  # Regular — allows taking focus

    frame = NSMakeRect(0, 0, 520, 100)
    style = NSTitledWindowMask | NSClosableWindowMask
    panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        frame, style, 2, False
    )
    panel.setTitle_(title)
    panel.setLevel_(NSFloatingWindowLevel + 1)
    panel.setFloatingPanel_(True)
    panel.setHidesOnDeactivate_(False)
    panel.center()

    content = panel.contentView()

    # Text field
    text_field = NSTextField.alloc().initWithFrame_(NSMakeRect(16, 36, 390, 44))
    text_field.setFont_(NSFont.systemFontOfSize_(15))
    text_field.setPlaceholderString_(message)
    content.addSubview_(text_field)

    # Submit button
    btn = NSButton.alloc().initWithFrame_(NSMakeRect(414, 42, 90, 32))
    btn.setTitle_("Go")
    btn.setBezelStyle_(1)
    content.addSubview_(btn)

    # Delegate
    delegate = DialogDelegate.alloc().init()
    delegate.setup(panel, text_field)
    btn.setTarget_(delegate)
    btn.setAction_(objc.selector(delegate.submit_, signature=b"v@:@"))
    btn.setKeyEquivalent_("\r")
    text_field.setTarget_(delegate)
    text_field.setAction_(objc.selector(delegate.submit_, signature=b"v@:@"))
    text_field.setDelegate_(delegate)
    panel.setDelegate_(delegate)
    panel.setDefaultButtonCell_(btn.cell())

    panel.makeKeyAndOrderFront_(None)
    text_field.becomeFirstResponder()
    app.activateIgnoringOtherApps_(True)

    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()
