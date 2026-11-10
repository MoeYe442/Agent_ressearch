"""Read only after validating the opened file, not a prior path lookup."""
import os
from pathlib import Path, PurePosixPath
import re
import stat


def physical_lines(text):
    """Python source coordinates count CR/LF/CRLF, not form-feed or U+2028."""
    return re.findall(r"[^\r\n]*(?:\r\n|\r|\n|$)", text)[:-1]


def _windows_open(path):
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    handle = create(str(path), 0x80000000, 7, None, 3, 0x00200000, None)  # READ, SHARE R/W/DELETE, OPEN_EXISTING, OPEN_REPARSE_POINT
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    return handle


def _windows_read(root, path, limit):
    import ctypes
    import msvcrt
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    kernel.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = _windows_open(path)
    owned = True
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        size = kernel.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
        if not size or size >= len(buffer):
            raise ValueError("unverifiable_file_handle")
        final = buffer.value
        if final.startswith("\\\\?\\UNC\\"):
            final = "\\\\" + final[8:]
        elif final.startswith("\\\\?\\"):
            final = final[4:]
        # root is the registered canonical path, deliberately not resolved again after opening.
        if not Path(final).is_relative_to(root):
            raise ValueError("file_handle_outside_root")
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        owned = False
        with os.fdopen(fd, "rb") as file:
            info = os.fstat(file.fileno())
            if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError("not_regular_file")
            return file.read(limit + 1)
    finally:
        if owned:
            kernel.CloseHandle(handle)


def secure_read(root: Path, relative: str, limit: int):
    root = Path(os.path.abspath(root))
    parts = PurePosixPath(relative).parts
    if not parts or PurePosixPath(relative).is_absolute() or any(p in {"..", "."} for p in parts) or "\\" in relative or ":" in relative:
        raise ValueError("invalid_path")
    if os.name == "nt":
        raw = _windows_read(root, root.joinpath(*parts), limit)
    else:
        # Anchor every directory by descriptor, refusing links at every component.
        fd = os.open(root.anchor, os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in (*root.parts[1:], *parts[:-1]):
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = next_fd
            file_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            with os.fdopen(file_fd, "rb") as file:
                if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
                    raise ValueError("not_regular_file")
                raw = file.read(limit + 1)
        finally:
            os.close(fd)
    return raw
