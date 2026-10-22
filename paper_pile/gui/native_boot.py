"""Runs inside the native window's own process (started by NiceGUI) once the window exists.

A program cannot place its own window on Wayland, so dragging and resizing a frameless window
must be handed to the compositor: ``QWindow.startSystemMove`` / ``startSystemResize`` (also fine
on X11 and Windows). pywebview does not expose them, so this adds one method to its ``Window``
class; NiceGUI's window proxy calls methods by name, so ``window.py`` can then request it.

It also adds ``print_pdf`` (PLAN §4.17): a note's print page is loaded in an off-screen page and
saved as a PDF by Qt, the same engine that laid it out, so the PDF has the editor's page lines.

It tells the page whether the window is maximized (``body.pp-maximized``), so the
maximize / restore button shows the real state whoever changed it (button, double-click, OS).

On WSL it also fixes the size per screen: WSLg reports every monitor at 100 %, so each window
is zoomed to the scale Windows uses for the monitor it is on (see ``core/display.py``), and
re-zoomed when it moves to another monitor.
"""

import contextlib
import threading
from collections.abc import Callable
from pathlib import Path

EDGES = {"n": "TopEdge", "s": "BottomEdge", "e": "RightEdge", "w": "LeftEdge"}
_KEEP: list[object] = []  # Qt helper objects that must live as long as the window (or the job)
PDF_TIMEOUT_MS = 90_000
LAYOUT_POLL_MS = 150


def install() -> None:
    import webview
    from qtpy import QtCore, QtWidgets
    from webview.platforms.qt import BrowserView

    class Mover(QtCore.QObject):
        requested = QtCore.Signal(str, str)  # (window uid, "move" or edge letters like "se")

        def __init__(self) -> None:
            super().__init__()
            self.requested.connect(self._run)

        @QtCore.Slot(str, str)
        def _run(self, uid: str, edge: str) -> None:  # on the GUI thread
            view = BrowserView.instances.get(uid)
            handle = view.windowHandle() if view is not None else None
            if handle is None:
                return
            if edge == "move":
                handle.startSystemMove()
                return
            flags = QtCore.Qt.Edge(0)
            for letter in edge:
                flags |= getattr(QtCore.Qt.Edge, EDGES[letter])
            handle.startSystemResize(flags)

    mover = Mover()
    mover.moveToThread(QtWidgets.QApplication.instance().thread())

    def start_system_gesture(self: webview.Window, edge: str) -> None:
        mover.requested.emit(self.uid, edge)

    webview.Window.start_system_gesture = start_system_gesture  # type: ignore[attr-defined]
    _install_pdf_printer()
    _fix_permission_requests()
    _install_window_state()
    _install_screen_scale()


def _install_window_state() -> None:
    """Keep ``body.pp-maximized`` in step with the window (after every state change and load)."""
    import webview
    from qtpy import QtCore, QtWidgets
    from webview.platforms.qt import BrowserView

    class Watcher(QtCore.QObject):
        hook = QtCore.Signal()

        def __init__(self) -> None:
            super().__init__()
            self.hook.connect(self._hook_all)

        @QtCore.Slot()
        def _hook_all(self) -> None:  # on the GUI thread
            for view in list(BrowserView.instances.values()):
                handle = view.windowHandle()
                if handle is None:
                    continue
                handle.windowStateChanged.connect(lambda _s, v=view: self._tell(v))
                view.webview.page().loadFinished.connect(lambda _ok, v=view: self._tell(v))
                self._tell(view)

        @staticmethod
        def _tell(view: BrowserView) -> None:
            on = "true" if view.isMaximized() or view.isFullScreen() else "false"
            view.webview.page().runJavaScript(
                f"document.body && document.body.classList.toggle('pp-maximized', {on})"
            )

    watcher = Watcher()
    watcher.moveToThread(QtWidgets.QApplication.instance().thread())
    _KEEP.append(watcher)

    def start() -> None:
        for window in list(webview.windows):
            window.events.shown.wait(30)
        watcher.hook.emit()

    threading.Thread(target=start, daemon=True).start()


def print_to_pdf(url: str, path: str, paper: str, done: Callable[[bool], None]) -> None:
    """Load the print page ``url`` off-screen, wait until it has laid itself out on sheets
    (``window.ppPrint``), then save it to ``path``. Call on the Qt GUI thread; ``done(ok)`` is
    called there when the file is written (or it failed / timed out)."""
    from qtpy import QtCore
    from qtpy.QtCore import QMarginsF, QUrl
    from qtpy.QtGui import QPageLayout, QPageSize
    from qtpy.QtWebEngineCore import QWebEnginePage

    page = QWebEnginePage()
    _KEEP.append(page)
    poll = QtCore.QTimer(page)
    poll.setInterval(LAYOUT_POLL_MS)
    state = {"printing": False, "finished": False}

    def finish(ok: bool) -> None:
        if state["finished"]:
            return
        state["finished"] = True
        poll.stop()
        if page in _KEEP:
            _KEEP.remove(page)
        page.deleteLater()
        done(ok)

    def laid_out(ready: object) -> None:
        if not ready or state["printing"] or state["finished"]:
            return
        state["printing"] = True
        poll.stop()
        size_id = QPageSize.PageSizeId.Letter if paper == "Letter" else QPageSize.PageSizeId.A4
        layout = QPageLayout(
            QPageSize(size_id), QPageLayout.Orientation.Portrait, QMarginsF(0, 0, 0, 0)
        )
        page.printToPdf(path, layout)

    page.pdfPrintingFinished.connect(lambda _path, ok: finish(bool(ok)))
    poll.timeout.connect(
        lambda: page.runJavaScript("!!(window.ppPrint && window.ppPrint.done)", 0, laid_out)
    )
    page.loadFinished.connect(lambda ok: poll.start() if ok else finish(False))
    QtCore.QTimer.singleShot(PDF_TIMEOUT_MS, lambda: finish(False))
    page.load(QUrl(url))


def _install_pdf_printer() -> None:
    """``window.print_pdf(url, path, paper)``, called by name from the server process (NiceGUI's
    method queue runs it on a worker thread; the answer goes back on its response queue)."""
    import webview
    from qtpy import QtCore, QtWidgets

    class Printer(QtCore.QObject):
        requested = QtCore.Signal(str, str, str, object)

        def __init__(self) -> None:
            super().__init__()
            self.requested.connect(self._run)

        @QtCore.Slot(str, str, str, object)
        def _run(self, url: str, path: str, paper: str, done: object) -> None:  # GUI thread
            print_to_pdf(url, path, paper, done)  # type: ignore[arg-type]

    printer = Printer()
    printer.moveToThread(QtWidgets.QApplication.instance().thread())
    _KEEP.append(printer)  # a queued call is lost if its receiver is collected first

    def print_pdf(self: webview.Window, url: str, path: str, paper: str) -> str:
        finished = threading.Event()
        result = {"ok": False}

        def done(ok: bool) -> None:
            result["ok"] = ok
            finished.set()

        printer.requested.emit(url, path, paper, done)
        finished.wait(PDF_TIMEOUT_MS / 1000 + 5)
        return "ok" if result["ok"] else "failed"

    webview.Window.print_pdf = print_pdf  # type: ignore[attr-defined]


def _fix_permission_requests() -> None:
    """pywebview 6.2.1 answers a page's permission request (clipboard read, notifications, …)
    with a plain int, which PyQt6 rejects with a TypeError that takes the whole window down.
    Re-wire the signal to an answer of the right type: every request is denied (the app needs
    none of them)."""
    import webview
    from qtpy import QtCore, QtWidgets
    from qtpy.QtWebEngineCore import QWebEnginePage
    from webview.platforms.qt import BrowserView

    deny = QWebEnginePage.PermissionPolicy.PermissionDeniedByUser

    class OnGui(QtCore.QObject):
        run = QtCore.Signal(object)

        def __init__(self) -> None:
            super().__init__()
            self.run.connect(self._run)

        @QtCore.Slot(object)
        def _run(self, fn: object) -> None:
            fn()  # type: ignore[operator]

    on_gui = OnGui()
    on_gui.moveToThread(QtWidgets.QApplication.instance().thread())
    _KEEP.append(on_gui)  # a queued call is lost if its receiver is collected first

    def rewire() -> None:  # on the GUI thread
        for view in list(BrowserView.instances.values()):
            page = view.webview.page()
            with contextlib.suppress(TypeError, RuntimeError):
                page.featurePermissionRequested.disconnect()
            page.featurePermissionRequested.connect(
                lambda url, feature, p=page: p.setFeaturePermission(url, feature, deny)
            )

    def start() -> None:
        for window in list(webview.windows):
            window.events.shown.wait(30)
        on_gui.run.emit(rewire)

    threading.Thread(target=start, daemon=True).start()


def _install_screen_scale() -> None:
    from paper_pile.core import display

    if not display.is_wsl():
        return
    import platformdirs
    import webview
    from qtpy import QtCore, QtWidgets
    from webview.platforms.qt import BrowserView

    cache = Path(platformdirs.user_cache_dir("paper-pile")) / "monitors.json"

    class Scaler(QtCore.QObject):
        monitors_ready = QtCore.Signal(object)  # list[display.Monitor], from any thread

        def __init__(self) -> None:
            super().__init__()
            self._monitors: list[display.Monitor] = []
            self._hooked: set[str] = set()
            self.monitors_ready.connect(self._set)

        @QtCore.Slot(object)
        def _set(self, monitors: list[display.Monitor]) -> None:  # on the GUI thread
            self._monitors = monitors
            for view in list(BrowserView.instances.values()):
                self._hook(view)
                self._apply(view)

        def _hook(self, view: BrowserView) -> None:
            handle = view.windowHandle()
            if view.uid in self._hooked or handle is None:
                return
            self._hooked.add(view.uid)
            handle.screenChanged.connect(lambda _screen, v=view: self._apply(v))
            # Maximize / restore / any new height: only the taskbar strip is measured again, the
            # window is never resized then (resizing a window the compositor still has maximized
            # is a Wayland protocol error that kills the app). On Wayland "maximized" arrives
            # BEFORE the new size, so the height change is what gives the right strip.
            handle.windowStateChanged.connect(lambda _state, v=view: self._apply(v, fit=False))
            handle.heightChanged.connect(lambda _h, v=view: self._apply(v, fit=False))
            view.webview.page().loadFinished.connect(lambda _ok, v=view: self._apply(v))

        def _apply(self, view: BrowserView, *, fit: bool = True) -> None:
            handle = view.windowHandle()
            screen = handle.screen() if handle is not None else None
            if screen is None:
                return
            screens = []
            for s in QtWidgets.QApplication.screens():
                g, dpr = s.geometry(), s.devicePixelRatio()
                rect = (round(g.x() * dpr), round(g.y() * dpr))
                size = (round(g.width() * dpr), round(g.height() * dpr))
                screens.append(display.Screen(s.name(), *rect, *size))
            monitor = display.match_monitors(screens, self._monitors).get(screen.name())
            dpr = screen.devicePixelRatio()
            # Qt may already scale this screen (dpr); zoom only by what is still missing
            zoom = monitor.scale / dpr if monitor else 1.0
            old = view.webview.zoomFactor()
            width, height = view.width(), view.height()
            if abs(old - zoom) > 0.001:
                view.webview.setZoomFactor(zoom)
                # keep the page's own size (like Windows does on a DPI change)
                width, height = round(width * zoom / old), round(height * zoom / old)
            self._insets(view, monitor, dpr, zoom)
            if not fit or view.isMaximized() or view.isFullScreen():
                return
            # never taller or wider than the monitor without the Windows taskbar: WSLg's own idea
            # of the free area is the whole screen, so the bottom would hide behind the taskbar
            room = screen.availableGeometry()
            room_w, room_h = room.width(), room.height()
            if monitor is not None:
                work_w, work_h = display.work_area(monitor)
                room_w, room_h = min(room_w, round(work_w / dpr)), min(room_h, round(work_h / dpr))
            fitted = (min(width, room_w), min(height, room_h))
            if fitted != (view.width(), view.height()):
                view.resize(*fitted)

        def _insets(
            self, view: BrowserView, monitor: display.Monitor | None, dpr: float, zoom: float
        ) -> None:
            """Maximized over the taskbar (WSLg on some screens): keep the page out of it."""
            top = bottom = 0
            if monitor is not None and view.isMaximized():
                top, bottom = display.taskbar_insets(monitor, round(view.height() * dpr))
            root = "document.documentElement.style"
            view.webview.page().runJavaScript(
                f"{root}.setProperty('--pp-inset-top', '{top / dpr / zoom:.1f}px');"
                f"{root}.setProperty('--pp-inset-bottom', '{bottom / dpr / zoom:.1f}px');"
            )

    scaler = Scaler()
    scaler.moveToThread(QtWidgets.QApplication.instance().thread())

    def ask_windows() -> None:
        fresh = display.query_windows_monitors()
        if fresh:
            display.save_cached(cache, fresh)
            scaler.monitors_ready.emit(fresh)

    def start() -> None:  # off the GUI thread: wait for the windows, then cached, then fresh
        for window in list(webview.windows):
            window.events.shown.wait(30)
        cached = display.load_cached(cache)
        if cached:
            scaler.monitors_ready.emit(cached)
        ask_windows()

    app = QtWidgets.QApplication.instance()
    app.screenAdded.connect(lambda _s: threading.Thread(target=ask_windows, daemon=True).start())
    app.screenRemoved.connect(lambda _s: threading.Thread(target=ask_windows, daemon=True).start())
    threading.Thread(target=start, daemon=True).start()
