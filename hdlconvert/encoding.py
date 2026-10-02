"""Deterministic HDL source decoding shared by CLI, GUI and dependencies."""
from pathlib import Path
import os
import tempfile

OUTPUT_ENCODINGS = {'gb2312': 'gb2312', 'gbk': 'gbk', 'utf-8': 'utf-8'}


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


def output_codec(value='gb2312'):
    key = str(value).strip().lower().replace('_', '-')
    if key == 'utf8':
        key = 'utf-8'
    if key not in OUTPUT_ENCODINGS:
        raise ValueError('output encoding must be GB2312, GBK, or UTF-8')
    return OUTPUT_ENCODINGS[key]


def atomic_write_text(path, text, encoding='gb2312'):
    """Encode before touching disk, then replace the destination in one operation."""
    data = text.encode(output_codec(encoding))
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('wb', dir=destination.parent,
                                         suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        os.replace(temporary, destination)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
