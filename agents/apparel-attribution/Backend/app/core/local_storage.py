"""Private local paths and exclusive worker ownership, without app imports."""
from __future__ import annotations

import errno
import os
from contextlib import contextmanager
from pathlib import Path


def _windows_private_acl(path: Path, *, directory: bool) -> None:
    # chmod on Windows does not restrict who can read a file. Install a protected
    # DACL granting only this process's user (the owner) and LocalSystem access.
    import ctypes
    from ctypes import wintypes

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    pointer = ctypes.c_void_p
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi.OpenProcessToken.restype = wintypes.BOOL
    advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, pointer, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    advapi.GetTokenInformation.restype = wintypes.BOOL
    advapi.ConvertSidToStringSidW.argtypes = [pointer, ctypes.POINTER(wintypes.LPWSTR)]
    advapi.ConvertSidToStringSidW.restype = wintypes.BOOL
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(pointer), ctypes.POINTER(wintypes.DWORD)]
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    advapi.SetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, pointer]
    advapi.SetFileSecurityW.restype = wintypes.BOOL
    kernel.GetCurrentProcess.argtypes = []
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [pointer]
    kernel.LocalFree.restype = pointer
    kernel.GetVolumePathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    kernel.GetVolumePathNameW.restype = wintypes.BOOL
    kernel.GetVolumeInformationW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR, wintypes.DWORD]
    kernel.GetVolumeInformationW.restype = wintypes.BOOL

    volume = ctypes.create_unicode_buffer(32768)
    if not kernel.GetVolumePathNameW(str(path.absolute()), volume, len(volume)):
        raise ctypes.WinError(ctypes.get_last_error())
    flags = wintypes.DWORD()
    if not kernel.GetVolumeInformationW(volume, None, 0, None, None, ctypes.byref(flags), None, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    if not flags.value & 0x00000008:  # FILE_PERSISTENT_ACLS; FAT/exFAT cannot keep secrets private.
        raise OSError("Private local storage requires a filesystem supporting persistent Windows ACLs")

    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):  # TOKEN_QUERY
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        size = wintypes.DWORD()
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))  # TokenUser
        if ctypes.get_last_error() != 122:  # ERROR_INSUFFICIENT_BUFFER
            raise ctypes.WinError(ctypes.get_last_error())
        user = ctypes.create_string_buffer(size.value)
        if not advapi.GetTokenInformation(token, 1, user, size, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        sid_text = wintypes.LPWSTR()
        sid = pointer.from_buffer(user).value  # TOKEN_USER begins with SID_AND_ATTRIBUTES.Sid
        if not advapi.ConvertSidToStringSidW(sid, ctypes.byref(sid_text)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            owner = sid_text.value
        finally:
            kernel.LocalFree(ctypes.cast(sid_text, pointer))
    finally:
        kernel.CloseHandle(token)

    inheritance = "OICI" if directory else ""
    sddl = f"O:{owner}D:P(A;{inheritance};FA;;;{owner})(A;{inheritance};FA;;;SY)"
    descriptor = pointer()
    if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        # OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION
        if not advapi.SetFileSecurityW(str(path.absolute()), 0x80000005, descriptor):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.LocalFree(descriptor)


def _reject_link(path: Path) -> None:
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        raise OSError("Private storage must not be a symbolic link or junction")


def private_directory(path: Path) -> None:
    """Create/restrict a directory; permission failures never degrade to public storage."""
    _reject_link(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "nt":
        _windows_private_acl(path, directory=True)
    else:
        path.chmod(0o700)


def private_file(path: Path) -> None:
    """Create an empty private file if absent, or restrict an existing local file."""
    _reject_link(path)
    if not path.exists():
        private_directory(path.parent)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            _reject_link(path)
        else:
            os.close(descriptor)
    if os.name == "nt":
        _windows_private_acl(path, directory=False)
    else:
        path.chmod(0o600)


@contextmanager
def worker_storage_lock(directory: Path):
    """Hold a nonblocking OS lock for the worker's lifetime; never unlink its inode."""
    private_directory(directory)
    path = directory / "worker.lock"
    private_file(path)
    with path.open("r+b") as lock:
        if os.name == "nt":
            import msvcrt

            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                raise RuntimeError("Only one worker process may use this storage directory and browser") from exc
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("Only one worker process may use this storage directory and browser") from exc
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
