"""本机凭据保护：用 Windows 用户凭据加密后再落库。

只做加解密，不决定保存位置或使用方式。连接凭据和工具凭据共用这一处。
"""
import ctypes
from ctypes import wintypes
import os


class Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.c_void_p)]


def protect(data, decrypt=False):
    if os.name != "nt":
        raise ValueError("此版本使用 Windows 用户凭据保护，需要在 Windows 服务中保存。")
    source = ctypes.create_string_buffer(data)
    incoming = Blob(len(data), ctypes.addressof(source))
    outgoing = Blob()
    dll = ctypes.WinDLL("crypt32", use_last_error=True)
    call = dll.CryptUnprotectData if decrypt else dll.CryptProtectData
    if not call(ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        # LocalFree 的参数必须声明为指针类型，否则 64 位地址会被截断。
        local_free = ctypes.windll.kernel32.LocalFree
        local_free.argtypes = [ctypes.c_void_p]
        local_free.restype = ctypes.c_void_p
        local_free(outgoing.data)
