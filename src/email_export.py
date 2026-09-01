"""
Builds downloadable email files (.eml / .msg) from an already-drafted
subject/body/recipient list. Sends nothing — packages the same content
the draft review screen shows into a file the user can keep as a record
or send through their own mail client.

.eml (RFC 822) uses only the standard library and is portable to any OS
this app runs on. .msg is Outlook's binary format; producing one requires
driving desktop Outlook via COM automation (pywin32), which works only on
Windows with Outlook installed locally.

Not routed through TEST_MODE: these are files under the user's own
control once downloaded, not something this app sends on its own, so
they always carry the real intended recipient.
"""

import io
import os
import re
import tempfile
import zipfile
from email.mime.text import MIMEText
from email.utils import formatdate


def safe_filename(name: str) -> str:
    # Replaces only characters illegal in a Windows/Mac/Linux filename;
    # punctuation such as & and () is left as-is.
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", name or "").strip().rstrip(".")
    return cleaned or "email"


def is_msg_supported_platform() -> bool:
    """
    Returns whether pywin32 is importable. Does not launch or attach to
    Outlook — that happens lazily inside build_msg_bytes(), when a .msg is
    actually generated. Safe to call on every Streamlit rerun to decide
    whether to show the .msg button. Outlook may still be missing even
    when this returns True; that surfaces as an exception at generation
    time, not here.
    """
    try:
        import win32com.client  # noqa: F401
        return True
    except ImportError:
        return False


def build_eml_bytes(recipients, subject: str, body: str, is_html: bool = False, from_addr: str = None) -> bytes:
    """Builds one .eml file's raw bytes (a standard RFC 822 message)."""
    recipients = [recipients] if isinstance(recipients, str) else list(recipients)
    msg = MIMEText(body, "html" if is_html else "plain")
    msg["Subject"] = subject
    msg["To"] = ", ".join(recipients)
    if from_addr:
        msg["From"] = from_addr
    msg["Date"] = formatdate(localtime=True)
    return msg.as_bytes()


def build_msg_bytes(recipients, subject: str, body: str, is_html: bool = False) -> bytes:
    """
    Builds one .msg file's raw bytes by driving desktop Outlook via COM
    automation and saving a draft item to a temp file. Each COM call is
    wrapped separately so a failure reports exactly which call failed and
    the underlying pywintypes.com_error text, rather than one generic
    "is Outlook installed?" message.

    Calls pythoncom.CoInitialize()/CoUninitialize() around the COM
    session. Required because this function runs on Streamlit's
    script-execution thread, not the process's main thread; COM does not
    auto-initialize a worker thread, and win32com raises "CoInitialize
    has not been called" without this.
    """
    try:
        import pythoncom
        import win32com.client
    except ImportError as e:
        raise RuntimeError("pywin32 is not installed — .msg export needs Windows + pywin32.") from e

    recipients = [recipients] if isinstance(recipients, str) else list(recipients)

    pythoncom.CoInitialize()
    try:
        try:
            outlook = win32com.client.Dispatch("Outlook.Application")
        except Exception as e:
            raise RuntimeError(f"Couldn't launch/attach to Outlook via COM ({e}).") from e

        try:
            mail = outlook.CreateItem(0)  # olMailItem
        except Exception as e:
            raise RuntimeError(f"Outlook.Application.CreateItem(0) failed ({e}).") from e

        try:
            mail.To = "; ".join(recipients)  # Outlook uses ';', not ','
        except Exception as e:
            raise RuntimeError(f"Couldn't set the To field ({e}). Recipients were: {recipients!r}") from e

        try:
            mail.Subject = subject
        except Exception as e:
            raise RuntimeError(f"Couldn't set the Subject field ({e}).") from e

        try:
            if is_html:
                mail.HTMLBody = body
            else:
                mail.Body = body
        except Exception as e:
            raise RuntimeError(f"Couldn't set the {'HTMLBody' if is_html else 'Body'} field ({e}).") from e

        fd, tmp_path = tempfile.mkstemp(suffix=".msg")
        os.close(fd)
        os.remove(tmp_path)  # SaveAs creates it fresh
        try:
            mail.SaveAs(tmp_path, 3)  # 3 = olMSG format
        except Exception as e:
            raise RuntimeError(f"mail.SaveAs() failed ({e}). Path tried: {tmp_path}") from e

        try:
            if not os.path.exists(tmp_path):
                raise RuntimeError("SaveAs reported success but no file was written.")
            with open(tmp_path, "rb") as f:
                data = f.read()
            if not data:
                raise RuntimeError("SaveAs wrote an empty file.")
            return data
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
    finally:
        pythoncom.CoUninitialize()


def build_zip(files: list) -> bytes:
    """files: list of (filename, bytes) tuples -> one zip's raw bytes."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        used_names = set()
        for filename, data in files:
            name = filename
            n = 2
            while name in used_names:
                base, ext = os.path.splitext(filename)
                name = f"{base}_{n}{ext}"
                n += 1
            used_names.add(name)
            zf.writestr(name, data)
    return buffer.getvalue()
