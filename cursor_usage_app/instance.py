"""Single-instance ownership and command IPC.

Windows uses a per-user named mutex and named pipe.  Other platforms use a
loopback TCP socket so development and tests need neither Win32 nor disk
polling.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import socket
import struct
import sys
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

COMMANDS = frozenset(
    {
        "show-main",
        "refresh",
        "hide-ball",
        "hide-dock",
        "apply-settings",
        "reset-widget-positions",
        "reembed-dock",
        "quit",
    }
)
DEFAULT_APP_ID = "cursor-usage-app"
DEFAULT_MAX_MESSAGE_SIZE = 64 * 1024

CommandCallback = Callable[[str, dict[str, Any]], None]


class IPCError(RuntimeError):
    """The IPC peer sent invalid data or could not complete a request."""


def _user_key(app_id: str) -> str:
    try:
        uid = str(os.getuid())
    except AttributeError:
        uid = os.environ.get("USERPROFILE", "")
    identity = f"{app_id}\0{getpass.getuser()}\0{uid}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def _encode_frame(value: Mapping[str, Any], limit: int) -> bytes:
    try:
        body = json.dumps(
            value, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("IPC payload must be JSON serializable") from exc
    if not body or len(body) > limit:
        raise ValueError(f"IPC message exceeds the {limit}-byte limit")
    return struct.pack("!I", len(body)) + body


def _decode_body(body: bytes) -> dict[str, Any]:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IPCError("invalid IPC JSON") from exc
    if not isinstance(value, dict):
        raise IPCError("IPC JSON must be an object")
    return value


def _validate_command(command: str, payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if command not in COMMANDS:
        raise ValueError(f"unsupported IPC command: {command!r}")
    if payload is None:
        return {}
    if not isinstance(payload, Mapping):
        raise TypeError("IPC payload must be a mapping")
    return dict(payload)


class SingleInstance:
    """Own one application instance and exchange framed JSON commands.

    Typical main-process integration::

        instance = SingleInstance()
        if not instance.acquire():
            instance.send("show-main")
            return
        instance.register_callback(on_command)
        instance.start()
        ...
        instance.close()
    """

    def __init__(
        self,
        app_id: str = DEFAULT_APP_ID,
        *,
        max_message_size: int = DEFAULT_MAX_MESSAGE_SIZE,
        io_timeout: float = 2.0,
    ) -> None:
        if not app_id or "\x00" in app_id:
            raise ValueError("app_id must be a non-empty string without NUL")
        if max_message_size < 128:
            raise ValueError("max_message_size must be at least 128 bytes")
        if io_timeout <= 0:
            raise ValueError("io_timeout must be positive")

        self.app_id = app_id
        self.max_message_size = int(max_message_size)
        self.io_timeout = float(io_timeout)
        self._key = _user_key(app_id)
        self.mutex_name = rf"Local\CursorUsage-{self._key}"
        self.pipe_name = rf"\\.\pipe\CursorUsage-{self._key}"
        self._port = 49152 + (int(self._key[:8], 16) % (65535 - 49152))

        self._primary: bool | None = None
        self._started = False
        self._closed = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._callback: CommandCallback | None = None
        self._callback_lock = threading.Lock()

        self._mutex_handle: int | None = None
        self._server_socket: socket.socket | None = None
        self._pipe_handle: int | None = None
        self._pipe_lock = threading.Lock()

    @property
    def is_primary(self) -> bool:
        """Whether this object owns the single-instance primitive."""
        return self._primary is True and not self._closed

    @property
    def is_listening(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def acquire(self) -> bool:
        """Try to become the primary instance; safe to call repeatedly."""
        if self._closed:
            raise RuntimeError("SingleInstance is closed")
        if self._primary is not None:
            return self._primary
        if sys.platform == "win32":
            self._primary = self._acquire_windows()
        else:
            self._primary = self._acquire_fallback()
        return self._primary

    def register_callback(self, callback: CommandCallback | None) -> None:
        """Set the callback invoked as ``callback(command, payload)``."""
        if callback is not None and not callable(callback):
            raise TypeError("callback must be callable or None")
        with self._callback_lock:
            self._callback = callback

    def start(self, callback: CommandCallback | None = None) -> bool:
        """Acquire ownership and start listening if this is the primary."""
        if callback is not None:
            self.register_callback(callback)
        if not self.acquire():
            return False
        if self._started:
            return True
        self._started = True
        target = self._listen_windows if sys.platform == "win32" else self._listen_fallback
        self._thread = threading.Thread(
            target=target,
            daemon=True,
            name=f"{self.app_id}-ipc",
        )
        self._thread.start()
        return True

    def send(
        self,
        command: str,
        payload: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
        retries: int = 3,
    ) -> bool:
        """Send a command and wait for acknowledgement.

        Transient disconnects are retried until ``timeout`` expires.  Invalid
        commands and oversized/non-JSON payloads raise immediately.
        """
        data = _validate_command(command, payload)
        frame = _encode_frame({"command": command, "payload": data}, self.max_message_size)
        timeout = self.io_timeout if timeout is None else float(timeout)
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if retries < 1:
            raise ValueError("retries must be at least 1")

        deadline = time.monotonic() + timeout
        for attempt in range(retries):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                if sys.platform == "win32":
                    response = self._send_windows(frame, remaining)
                else:
                    response = self._send_fallback(frame, remaining)
                return response.get("ok") is True
            except (OSError, IPCError):
                if attempt + 1 < retries:
                    time.sleep(min(0.05 * (attempt + 1), max(0.0, deadline - time.monotonic())))
        return False

    def close(self, *, join_timeout: float = 2.0) -> None:
        """Stop listening and release all ownership resources."""
        if self._closed:
            return
        self._closed = True
        self._stop.set()

        if sys.platform == "win32" and self._pipe_handle is not None:
            try:
                wake = _win_open_pipe(self.pipe_name, min(0.2, join_timeout))
            except OSError:
                pass
            else:
                _win_close(wake)

        server = self._server_socket
        self._server_socket = None
        if server is not None:
            try:
                server.close()
            except OSError:
                pass

        # The listener thread owns its pipe handle and closes it itself; here we
        # only cancel the blocking ConnectNamedPipe/ReadFile. Closing it from
        # both sides could close a recycled handle value (e.g. a semaphore).
        with self._pipe_lock:
            pipe = self._pipe_handle
        if pipe is not None and sys.platform == "win32":
            _win_cancel(pipe)

        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(max(0.0, join_timeout))
            if thread.is_alive() and sys.platform == "win32":
                with self._pipe_lock:
                    pipe, self._pipe_handle = self._pipe_handle, None
                if pipe is not None:
                    _win_close(pipe)

        if self._mutex_handle is not None and sys.platform == "win32":
            _win_release_mutex(self._mutex_handle)
            self._mutex_handle = None
        self._primary = False

    def __enter__(self) -> "SingleInstance":
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
        command = request.get("command")
        payload = request.get("payload", {})
        try:
            data = _validate_command(command, payload)
        except (TypeError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}
        with self._callback_lock:
            callback = self._callback
        try:
            if callback is not None:
                callback(command, data)
        except Exception as exc:
            return {"ok": False, "error": f"callback failed: {exc}"}
        return {"ok": True}

    # Loopback fallback (Linux/macOS development, no files or polling).

    def _acquire_fallback(self) -> bool:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server.bind(("127.0.0.1", self._port))
            server.listen(8)
            server.settimeout(0.2)
        except OSError:
            server.close()
            return False
        self._server_socket = server
        return True

    def _listen_fallback(self) -> None:
        while not self._stop.is_set():
            server = self._server_socket
            if server is None:
                break
            try:
                conn, _address = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with conn:
                conn.settimeout(self.io_timeout)
                try:
                    request = self._recv_socket_frame(conn)
                    conn.sendall(_encode_frame(self._dispatch(request), self.max_message_size))
                except (OSError, IPCError, ValueError):
                    continue

    def _send_fallback(self, frame: bytes, timeout: float) -> dict[str, Any]:
        with socket.create_connection(("127.0.0.1", self._port), timeout=timeout) as conn:
            conn.settimeout(timeout)
            conn.sendall(frame)
            return self._recv_socket_frame(conn)

    def _recv_socket_frame(self, conn: socket.socket) -> dict[str, Any]:
        header = self._recv_socket_exact(conn, 4)
        length = struct.unpack("!I", header)[0]
        if length < 1 or length > self.max_message_size:
            raise IPCError("invalid IPC message length")
        return _decode_body(self._recv_socket_exact(conn, length))

    @staticmethod
    def _recv_socket_exact(conn: socket.socket, size: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < size:
            chunk = conn.recv(size - len(chunks))
            if not chunk:
                raise IPCError("IPC peer disconnected mid-frame")
            chunks.extend(chunk)
        return bytes(chunks)

    # Windows named mutex / named pipe.

    def _acquire_windows(self) -> bool:
        handle, already_exists = _win_create_mutex(self.mutex_name)
        if already_exists:
            _win_close(handle)
            return False
        self._mutex_handle = handle
        return True

    def _listen_windows(self) -> None:
        while not self._stop.is_set():
            pipe = _win_create_pipe(self.pipe_name, self.max_message_size + 4)
            with self._pipe_lock:
                if self._stop.is_set():
                    _win_close(pipe)
                    break
                self._pipe_handle = pipe
            try:
                if not _win_connect_pipe(pipe):
                    continue
                if self._stop.is_set():
                    break
                timer = threading.Timer(self.io_timeout, _win_cancel, args=(pipe,))
                timer.daemon = True
                timer.start()
                try:
                    request = self._recv_pipe_frame(pipe)
                    response = _encode_frame(self._dispatch(request), self.max_message_size)
                    _win_write_all(pipe, response)
                    _win_flush(pipe)
                finally:
                    timer.cancel()
            except (OSError, IPCError, ValueError):
                pass
            finally:
                with self._pipe_lock:
                    owned = self._pipe_handle == pipe
                    if owned:
                        self._pipe_handle = None
                if owned:
                    _win_disconnect(pipe)
                    _win_close(pipe)

    def _send_windows(self, frame: bytes, timeout: float) -> dict[str, Any]:
        pipe = _win_open_pipe(self.pipe_name, timeout)
        timer = threading.Timer(timeout, _win_cancel, args=(pipe,))
        timer.daemon = True
        timer.start()
        try:
            _win_write_all(pipe, frame)
            return self._recv_pipe_frame(pipe)
        finally:
            timer.cancel()
            _win_close(pipe)

    def _recv_pipe_frame(self, pipe: int) -> dict[str, Any]:
        header = _win_read_exact(pipe, 4)
        length = struct.unpack("!I", header)[0]
        if length < 1 or length > self.max_message_size:
            raise IPCError("invalid IPC message length")
        return _decode_body(_win_read_exact(pipe, length))


def send_command(
    command: str,
    payload: Mapping[str, Any] | None = None,
    *,
    app_id: str = DEFAULT_APP_ID,
    timeout: float = 2.0,
    retries: int = 3,
    max_message_size: int = DEFAULT_MAX_MESSAGE_SIZE,
) -> bool:
    """Send one command without acquiring instance ownership."""
    client = SingleInstance(
        app_id,
        max_message_size=max_message_size,
        io_timeout=timeout,
    )
    return client.send(command, payload, timeout=timeout, retries=retries)


def start_or_notify(
    callback: CommandCallback | None = None,
    *,
    app_id: str = DEFAULT_APP_ID,
    timeout: float = 2.0,
) -> SingleInstance | None:
    """Start a primary listener, or notify the existing primary and return None."""
    instance = SingleInstance(app_id, io_timeout=timeout)
    if instance.start(callback):
        return instance
    instance.send("show-main", timeout=timeout)
    instance.close()
    return None


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    _ERROR_ALREADY_EXISTS = 183
    _ERROR_PIPE_BUSY = 231
    _ERROR_PIPE_CONNECTED = 535
    _PIPE_ACCESS_DUPLEX = 0x00000003
    _PIPE_TYPE_BYTE = 0x00000000
    _PIPE_READMODE_BYTE = 0x00000000
    _PIPE_WAIT = 0x00000000
    _PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
    _OPEN_EXISTING = 3
    _GENERIC_READ = 0x80000000
    _GENERIC_WRITE = 0x40000000

    _kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    _kernel32.CreateMutexW.restype = wintypes.HANDLE
    _kernel32.ReleaseMutex.argtypes = (wintypes.HANDLE,)
    _kernel32.ReleaseMutex.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.CreateNamedPipeW.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
        wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
    )
    _kernel32.CreateNamedPipeW.restype = wintypes.HANDLE
    _kernel32.ConnectNamedPipe.argtypes = (wintypes.HANDLE, ctypes.c_void_p)
    _kernel32.ConnectNamedPipe.restype = wintypes.BOOL
    _kernel32.DisconnectNamedPipe.argtypes = (wintypes.HANDLE,)
    _kernel32.DisconnectNamedPipe.restype = wintypes.BOOL
    _kernel32.WaitNamedPipeW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD)
    _kernel32.WaitNamedPipeW.restype = wintypes.BOOL
    _kernel32.CreateFileW.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    )
    _kernel32.CreateFileW.restype = wintypes.HANDLE
    _kernel32.ReadFile.argtypes = (
        wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
    )
    _kernel32.ReadFile.restype = wintypes.BOOL
    _kernel32.WriteFile.argtypes = (
        wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
    )
    _kernel32.WriteFile.restype = wintypes.BOOL
    _kernel32.FlushFileBuffers.argtypes = (wintypes.HANDLE,)
    _kernel32.FlushFileBuffers.restype = wintypes.BOOL
    _kernel32.CancelIoEx.argtypes = (wintypes.HANDLE, ctypes.c_void_p)
    _kernel32.CancelIoEx.restype = wintypes.BOOL


def _win_error(message: str) -> OSError:
    import ctypes

    return ctypes.WinError(ctypes.get_last_error(), message)


def _win_create_mutex(name: str) -> tuple[int, bool]:
    import ctypes

    ctypes.set_last_error(0)
    handle = _kernel32.CreateMutexW(None, False, name)
    if not handle:
        raise _win_error("CreateMutexW failed")
    return int(handle), ctypes.get_last_error() == _ERROR_ALREADY_EXISTS


def _win_release_mutex(handle: int) -> None:
    _win_close(handle)


def _win_close(handle: int) -> None:
    _kernel32.CloseHandle(handle)


def _win_create_pipe(name: str, buffer_size: int) -> int:
    handle = _kernel32.CreateNamedPipeW(
        name,
        _PIPE_ACCESS_DUPLEX,
        _PIPE_TYPE_BYTE | _PIPE_READMODE_BYTE | _PIPE_WAIT | _PIPE_REJECT_REMOTE_CLIENTS,
        1,
        buffer_size,
        buffer_size,
        0,
        None,
    )
    if handle == _INVALID_HANDLE_VALUE:
        raise _win_error("CreateNamedPipeW failed")
    return int(handle)


def _win_connect_pipe(pipe: int) -> bool:
    import ctypes

    if _kernel32.ConnectNamedPipe(pipe, None):
        return True
    error = ctypes.get_last_error()
    if error == _ERROR_PIPE_CONNECTED:
        return True
    if error in (109, 232, 995):
        return False
    raise _win_error("ConnectNamedPipe failed")


def _win_open_pipe(name: str, timeout: float) -> int:
    import ctypes

    deadline = time.monotonic() + timeout
    while True:
        remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
        if remaining_ms <= 1 and time.monotonic() >= deadline:
            raise TimeoutError("timed out waiting for IPC pipe")
        if not _kernel32.WaitNamedPipeW(name, remaining_ms):
            error = ctypes.get_last_error()
            if error not in (_ERROR_PIPE_BUSY, 2, 121):
                raise _win_error("WaitNamedPipeW failed")
            if time.monotonic() >= deadline:
                raise TimeoutError("timed out waiting for IPC pipe")
            continue
        handle = _kernel32.CreateFileW(
            name,
            _GENERIC_READ | _GENERIC_WRITE,
            0,
            None,
            _OPEN_EXISTING,
            0,
            None,
        )
        if handle != _INVALID_HANDLE_VALUE:
            return int(handle)
        if ctypes.get_last_error() != _ERROR_PIPE_BUSY:
            raise _win_error("CreateFileW for IPC pipe failed")


def _win_read_exact(handle: int, size: int) -> bytes:
    import ctypes

    result = bytearray()
    while len(result) < size:
        wanted = size - len(result)
        buffer = ctypes.create_string_buffer(wanted)
        read = wintypes.DWORD()
        if not _kernel32.ReadFile(handle, buffer, wanted, ctypes.byref(read), None):
            raise _win_error("ReadFile from IPC pipe failed")
        if read.value == 0:
            raise IPCError("IPC peer disconnected mid-frame")
        result.extend(buffer.raw[: read.value])
    return bytes(result)


def _win_write_all(handle: int, data: bytes) -> None:
    import ctypes

    offset = 0
    while offset < len(data):
        chunk = data[offset:]
        buffer = ctypes.create_string_buffer(chunk)
        written = wintypes.DWORD()
        if not _kernel32.WriteFile(
            handle, buffer, len(chunk), ctypes.byref(written), None
        ):
            raise _win_error("WriteFile to IPC pipe failed")
        if written.value == 0:
            raise IPCError("IPC peer disconnected during write")
        offset += written.value


def _win_flush(handle: int) -> None:
    _kernel32.FlushFileBuffers(handle)


def _win_disconnect(handle: int) -> None:
    _kernel32.DisconnectNamedPipe(handle)


def _win_cancel(handle: int) -> None:
    try:
        _kernel32.CancelIoEx(handle, None)
    except (AttributeError, OSError):
        pass
