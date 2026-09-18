"""Deterministic HDL source decoding shared by CLI, GUI and dependencies."""
from pathlib import Path


def decode_source(data):
    if data.startswith(b'\xef\xbb\xbf'):
        return data.decode('utf-8-sig'), 'UTF-8 BOM'
    try:
        return data.decode('utf-8'), 'UTF-8'
    except UnicodeDecodeError:
        try:
            # GB2312 is a strict subset of the Windows GBK code page.
            return data.decode('gbk'), 'GBK/GB2312'
        except UnicodeDecodeError as exc:
            raise UnicodeError('HDL source must use UTF-8, GBK, or GB2312 encoding') from exc


def read_source(path):
    return decode_source(Path(path).read_bytes())[0]
