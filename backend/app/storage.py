"""
Firebase Storage — görsel yükleme ve public URL üretimi.

Kullanım:
    url = upload_image("local/file.jpg", "users/uid123/results/abc/konsept_1.jpg")
"""

from __future__ import annotations

import logging
import os
from datetime import timedelta

from firebase_admin import storage

log = logging.getLogger(__name__)


def _bucket():
    return storage.bucket()


def upload_image(local_path: str, remote_path: str) -> str:
    """
    Yerel dosyayı Firebase Storage'a yükler, public URL döner.

    Args:
        local_path:  Yüklenecek dosyanın yerel yolu
        remote_path: Storage'daki hedef yol (örn: "users/uid/results/id/img.jpg")

    Returns:
        Public erişim URL'i
    """
    bucket = _bucket()
    blob = bucket.blob(remote_path)

    content_type = "image/jpeg"
    if local_path.endswith(".png"):
        content_type = "image/png"
    elif local_path.endswith(".webp"):
        content_type = "image/webp"

    blob.upload_from_filename(local_path, content_type=content_type)
    blob.make_public()

    log.info("[Storage] Yüklendi: %s → %s", os.path.basename(local_path), remote_path)
    return blob.public_url


def delete_image(remote_path: str) -> None:
    """Storage'daki dosyayı siler."""
    bucket = _bucket()
    blob = bucket.blob(remote_path)
    try:
        blob.delete()
    except Exception:
        pass
