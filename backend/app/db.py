"""
Firestore veritabanı işlemleri.

Şema:
    users/{uid}
        email, tier, created_at, limits{analyses_per_month, images_per_month}

    users/{uid}/results/{result_id}
        url, product_title, output_dir, created_at, data{...}

    users/{uid}/usage/{YYYY-MM}
        analyses, images, chat_messages
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from firebase_admin import firestore
from google.cloud.firestore_v1 import FieldFilter

log = logging.getLogger(__name__)

# Tier → limit tanımları
TIER_LIMITS: dict[str, dict] = {
    "free":  {"analyses_per_month": 5,   "images_per_month": 25},
    "pro":   {"analyses_per_month": 30,  "images_per_month": 150},
    "admin": {"analyses_per_month": 9999, "images_per_month": 9999},
}


def _db():
    return firestore.client()


def _month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


# ── Kullanıcı ────────────────────────────────────────────────────────────────

def get_or_create_user(uid: str, email: str) -> dict:
    """Kullanıcıyı Firestore'dan çeker, yoksa oluşturur."""
    db   = _db()
    ref  = db.collection("users").document(uid)
    snap = ref.get()

    if snap.exists:
        data = snap.to_dict()
        # limits her zaman koddan türetilir — stale Firestore alanına bakılmaz
        data["limits"] = TIER_LIMITS.get(data.get("tier", "free"), TIER_LIMITS["free"])
        return data

    # Yeni kullanıcı — varsayılan tier: free
    data = {
        "uid":        uid,
        "email":      email,
        "tier":       "free",
        "created_at": firestore.SERVER_TIMESTAMP,
    }
    ref.set(data)
    log.info("[DB] Yeni kullanıcı oluşturuldu: %s (%s)", uid, email)
    data["limits"] = TIER_LIMITS["free"]
    return data


def set_user_tier(uid: str, tier: str) -> None:
    """Admin: kullanıcı tierını günceller."""
    if tier not in TIER_LIMITS:
        raise ValueError(f"Geçersiz tier: {tier}")
    db  = _db()
    ref = db.collection("users").document(uid)
    ref.update({"tier": tier})   # limits Firestore'da saklanmıyor, koddan türetiliyor
    log.info("[DB] Tier güncellendi: %s → %s", uid, tier)


# ── Pazaryeri API Anahtarları ─────────────────────────────────────────────────

SUPPORTED_PLATFORMS = {"trendyol", "hepsiburada", "n11", "amazon", "ebay", "gittigidiyor"}

def save_api_key(uid: str, platform: str, api_key: str) -> None:
    """Pazaryeri API anahtarını Firestore'a kaydeder."""
    db = _db()
    ref = db.collection("users").document(uid).collection("api_keys").document(platform)
    ref.set({
        "platform": platform,
        "api_key": api_key,
        "updated_at": firestore.SERVER_TIMESTAMP,
    }, merge=True)
    log.info("[DB] API key kaydedildi: uid=%s, platform=%s", uid, platform)


def list_api_keys(uid: str) -> list[dict]:
    """Kullanıcının kayıtlı API anahtarlarını döner (key maskeli)."""
    db = _db()
    docs = db.collection("users").document(uid).collection("api_keys").stream()
    result = []
    for doc in docs:
        d = doc.to_dict()
        # Mask the key: show first 4 + last 4 chars
        key = d.get("api_key", "")
        if len(key) > 8:
            d["api_key_masked"] = key[:4] + "•" * (len(key) - 8) + key[-4:]
        else:
            d["api_key_masked"] = "•" * len(key)
        d.pop("api_key", None)  # Never return the real key
        if hasattr(d.get("updated_at"), "isoformat"):
            d["updated_at"] = d["updated_at"].isoformat()
        result.append(d)
    return result


def delete_api_key(uid: str, platform: str) -> None:
    """Pazaryeri API anahtarını siler."""
    db = _db()
    db.collection("users").document(uid).collection("api_keys").document(platform).delete()
    log.info("[DB] API key silindi: uid=%s, platform=%s", uid, platform)


# ── Kota Kontrolü ────────────────────────────────────────────────────────────

def check_quota(uid: str, action: str) -> None:
    """
    Kullanıcının kotasını kontrol eder.
    action: 'analysis' | 'image'

    Raises:
        PermissionError: Kota doluysa
    """
    db    = _db()
    user  = db.collection("users").document(uid).get().to_dict() or {}
    tier  = user.get("tier", "free")
    limits = TIER_LIMITS.get(tier, TIER_LIMITS["free"])

    month = _month_key()
    usage_snap = db.collection("users").document(uid)\
                   .collection("usage").document(month).get()
    usage = usage_snap.to_dict() or {}

    if action == "analysis":
        current = usage.get("analyses", 0)
        limit   = limits["analyses_per_month"]
        if current >= limit:
            raise PermissionError(
                f"Aylık analiz limitine ulaştınız ({limit} analiz). "
                f"Tier: {tier}."
            )
    elif action == "image":
        current = usage.get("images", 0)
        limit   = limits["images_per_month"]
        if current >= limit:
            raise PermissionError(
                f"Aylık görsel limitine ulaştınız ({limit} görsel). "
                f"Tier: {tier}."
            )


def increment_usage(uid: str, action: str, amount: int = 1) -> None:
    """Kullanım sayacını artırır. Atomik."""
    db    = _db()
    month = _month_key()
    ref   = db.collection("users").document(uid)\
               .collection("usage").document(month)

    field_map = {
        "analysis":     "analyses",
        "image":        "images",
        "chat_message": "chat_messages",
    }
    field = field_map.get(action)
    if not field:
        return

    ref.set({field: firestore.Increment(amount)}, merge=True)


# ── Sonuç Kayıt ──────────────────────────────────────────────────────────────

def save_result(uid: str, url: str, product_title: str, output_dir: str, data: dict) -> str:
    """
    Analiz sonucunu Firestore'a kaydeder.

    Returns:
        result_id: Kaydedilen dökümanın ID'si
    """
    db  = _db()
    ref = db.collection("users").document(uid).collection("results").document()

    doc = {
        "url":           url,
        "product_title": product_title,
        "output_dir":    output_dir,
        "created_at":    firestore.SERVER_TIMESTAMP,
        "data":          data,
    }
    ref.set(doc)
    log.info("[DB] Sonuç kaydedildi: uid=%s, id=%s, title=%s", uid, ref.id, product_title)
    return ref.id


def list_results(uid: str, limit: int = 20) -> list[dict]:
    """Kullanıcının analizlerini tarihe göre sıralı döner."""
    db   = _db()
    docs = (
        db.collection("users").document(uid)
          .collection("results")
          .order_by("created_at", direction=firestore.Query.DESCENDING)
          .limit(limit)
          .stream()
    )
    results = []
    for doc in docs:
        d = doc.to_dict()
        d["id"] = doc.id
        # Timestamp → ISO string
        if hasattr(d.get("created_at"), "isoformat"):
            d["created_at"] = d["created_at"].isoformat()
        # data büyük olabilir — listede sadece özet dön
        d.pop("data", None)
        results.append(d)
    return results


def get_result(uid: str, result_id: str) -> dict | None:
    """Tek analiz sonucunu döner (data dahil)."""
    db   = _db()
    snap = (
        db.collection("users").document(uid)
          .collection("results").document(result_id)
          .get()
    )
    if not snap.exists:
        return None
    d = snap.to_dict()
    d["id"] = snap.id
    if hasattr(d.get("created_at"), "isoformat"):
        d["created_at"] = d["created_at"].isoformat()
    return d


def get_usage(uid: str) -> dict:
    """Mevcut ay kullanım istatistiklerini döner."""
    db    = _db()
    month = _month_key()
    snap  = db.collection("users").document(uid)\
               .collection("usage").document(month).get()
    usage = snap.to_dict() or {}
    usage["month"] = month

    user  = db.collection("users").document(uid).get().to_dict() or {}
    tier  = user.get("tier", "free")
    usage["tier"]   = tier
    usage["limits"] = TIER_LIMITS.get(tier, TIER_LIMITS["free"])
    return usage
