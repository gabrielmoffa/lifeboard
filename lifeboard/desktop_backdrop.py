"""Desktop-level Lifeboard backing window."""

import os

from AppKit import (
    NSBackingStoreBuffered,
    NSColor,
    NSImage,
    NSImageScaleAxesIndependently,
    NSImageView,
    NSScreen,
    NSWindow,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorIgnoresCycle,
    NSWindowCollectionBehaviorStationary,
    NSWindowStyleMaskBorderless,
)


DESKTOP_WINDOW_LEVEL = -2147483623


class DesktopBackdrop:
    """Show Lifeboard's PNG above WallpaperAgent but below desktop icons/apps."""

    def __init__(self, image_path: str):
        self.image_path = image_path
        self._windows = []
        self._last_signature = None

    def refresh(self):
        if not os.path.exists(self.image_path):
            self.hide()
            return

        signature = self._signature()
        if signature != self._last_signature:
            self.hide()
            self._windows = [self._make_window(screen) for screen in NSScreen.screens()]
            self._last_signature = signature

        image = NSImage.alloc().initWithContentsOfFile_(self.image_path)
        if image is None:
            self.hide()
            return

        for window in self._windows:
            image_view = window.contentView()
            image_view.setImage_(image)
            window.orderBack_(None)

    def hide(self):
        for window in self._windows:
            window.orderOut_(None)
        self._windows = []
        self._last_signature = None

    def _signature(self):
        signature = []
        for screen in NSScreen.screens():
            frame = screen.frame()
            signature.append(
                (
                    screen.localizedName(),
                    int(frame.origin.x),
                    int(frame.origin.y),
                    int(frame.size.width),
                    int(frame.size.height),
                )
            )
        return tuple(sorted(signature))

    def _make_window(self, screen):
        frame = screen.frame()
        image_view = NSImageView.alloc().initWithFrame_(frame)
        image_view.setImageScaling_(NSImageScaleAxesIndependently)

        window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_screen_(
            frame,
            NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False,
            screen,
        )
        window.setContentView_(image_view)
        window.setBackgroundColor_(NSColor.clearColor())
        window.setOpaque_(False)
        window.setIgnoresMouseEvents_(True)
        window.setLevel_(DESKTOP_WINDOW_LEVEL)
        window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary
            | NSWindowCollectionBehaviorIgnoresCycle
        )
        return window
