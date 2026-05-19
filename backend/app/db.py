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


def get_stats(uid: str) -> dict:
    """Dashboard metriklerini döner. Ürün silmek geçmiş sayaçları düşürmez."""
    db = _db()
    usage = get_usage(uid)

    products = list(
        db.collection("users").document(uid)
          .collection("products")
          .stream()
    )
    total_products = len(products)
    total_improved = 0
    total_analyses = 0
    scores = []
    for doc in products:
        d = doc.to_dict() or {}
        status = d.get("status", "draft")
        if status in ("analyzed", "improved"):
            total_analyses += 1
        if status == "improved":
            total_improved += 1
        # Skor: doğrudan products alanından veya data.content_analysis.score
        score = d.get("score")
        if score is None:
            score = (d.get("data") or {}).get("content_analysis", {}).get("score")
        if isinstance(score, (int, float)):
            scores.append(score)

    return {
        "total_analyses": total_analyses,
        "this_month": usage.get("analyses", 0),
        "images_this_month": usage.get("images", 0),
        "avg_score": round(sum(scores) / len(scores)) if scores else None,
        "total_products": total_products,
        "total_improved": total_improved,
        "tier": usage.get("tier", "free"),
        "limits": usage.get("limits", TIER_LIMITS["free"]),
    }


# ── Ürün Yönetimi ───────────────────────────────────────────────────────────

def create_product(uid: str, url: str, product_title: str, platform: str, status: str = "draft") -> str:
    db = _db()
    ref = db.collection("users").document(uid).collection("products").document()
    ref.set({
        "url": url,
        "product_title": product_title,
        "platform": platform,
        "status": status,
        "score": None,
        "image_paths": [],
        "created_at": firestore.SERVER_TIMESTAMP,
        "updated_at": firestore.SERVER_TIMESTAMP,
    })
    return ref.id


def update_product_scraped(uid: str, product_id: str, scraped_data: dict, status: str = "inspected") -> None:
    _db().collection("users").document(uid).collection("products").document(product_id).update({
        "scraped_data": scraped_data,
        "product_title": scraped_data.get("title", ""),
        "status": status,
        "updated_at": firestore.SERVER_TIMESTAMP,
    })


def update_product_analyzed(uid: str, product_id: str, analysis_data: dict, score: int) -> None:
    _db().collection("users").document(uid).collection("products").document(product_id).update({
        "data": analysis_data,
        "score": score,
        "status": "analyzed",
        "updated_at": firestore.SERVER_TIMESTAMP,
    })


def update_product_content(uid: str, product_id: str, content_update: dict, gift_suggestions, new_score=None) -> None:
    """İyileştirme aşamasında üretilen içeriği (yeni başlık/açıklama/keywords) data alanına ekler."""
    ref = _db().collection("users").document(uid).collection("products").document(product_id)
    updates = {f"data.content_analysis.{k}": v for k, v in content_update.items()}
    updates["data.gift_suggestions"] = gift_suggestions
    if new_score is not None:
        updates["new_score"] = new_score
    updates["updated_at"] = firestore.SERVER_TIMESTAMP
    ref.update(updates)


def update_product_improved(uid: str, product_id: str, image_paths: list[str]) -> None:
    _db().collection("users").document(uid).collection("products").document(product_id).update({
        "image_paths": image_paths,
        "status": "improved",
        "updated_at": firestore.SERVER_TIMESTAMP,
    })


def get_product(uid: str, product_id: str) -> dict | None:
    snap = _db().collection("users").document(uid).collection("products").document(product_id).get()
    if not snap.exists:
        return None
    d = snap.to_dict() or {}
    d["id"] = snap.id
    for key in ("created_at", "updated_at"):
        if hasattr(d.get(key), "isoformat"):
            d[key] = d[key].isoformat()
    return d


def list_products(uid: str, limit: int = 50) -> list[dict]:
    docs = (
        _db().collection("users").document(uid)
        .collection("products")
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .limit(limit)
        .stream()
    )
    items = []
    for doc in docs:
        d = doc.to_dict() or {}
        d["id"] = doc.id
        for key in ("created_at", "updated_at"):
            if hasattr(d.get(key), "isoformat"):
                d[key] = d[key].isoformat()
        sd = d.get("scraped_data") or {}
        imgs = sd.get("image_urls") or []
        d["thumbnail"] = imgs[0] if imgs else None
        d.pop("data", None)
        items.append(d)
    return items


def delete_product(uid: str, product_id: str) -> None:
    _db().collection("users").document(uid).collection("products").document(product_id).delete()


# ── Bağlı Mağazalar ───────────────────────────────────────────────────────────

def save_store(uid: str, name: str, platform: str, api_url: str) -> str:
    """Yeni mağaza bağlantısını kaydeder. Aynı platform varsa üzerine yazar."""
    db   = _db()
    docs = (
        db.collection("users").document(uid)
          .collection("connected_stores")
          .where(filter=FieldFilter("platform", "==", platform))
          .limit(1)
          .stream()
    )
    existing = next(docs, None)
    if existing:
        ref = existing.reference
    else:
        ref = db.collection("users").document(uid).collection("connected_stores").document()

    ref.set({
        "name":       name,
        "platform":   platform,
        "api_url":    api_url,
        "created_at": firestore.SERVER_TIMESTAMP,
    })
    log.info("[DB] Mağaza kaydedildi: uid=%s, platform=%s, url=%s", uid, platform, api_url)
    return ref.id


def list_stores(uid: str) -> list[dict]:
    db   = _db()
    docs = (
        db.collection("users").document(uid)
          .collection("connected_stores")
          .order_by("created_at", direction=firestore.Query.DESCENDING)
          .stream()
    )
    result = []
    for doc in docs:
        d = doc.to_dict() or {}
        d["id"] = doc.id
        if hasattr(d.get("created_at"), "isoformat"):
            d["created_at"] = d["created_at"].isoformat()
        result.append(d)
    return result


def delete_store(uid: str, store_id: str) -> None:
    _db().collection("users").document(uid).collection("connected_stores").document(store_id).delete()
    log.info("[DB] Mağaza silindi: uid=%s, store_id=%s", uid, store_id)


def get_store(uid: str, store_id: str) -> dict | None:
    snap = _db().collection("users").document(uid).collection("connected_stores").document(store_id).get()
    if not snap.exists:
        return None
    d = snap.to_dict() or {}
    d["id"] = snap.id
    if hasattr(d.get("created_at"), "isoformat"):
        d["created_at"] = d["created_at"].isoformat()
    return d


def update_product_source(uid: str, product_id: str, store_id: str, store_product_id: str) -> None:
    """Ürünün kaynak mağaza bilgisini günceller (import sonrası)."""
    _db().collection("users").document(uid).collection("products").document(product_id).update({
        "source_store_id":     store_id,
        "source_product_id":   store_product_id,
    })
