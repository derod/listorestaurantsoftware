"""
Factura Electrónica (Hacienda CR) — utilidades de configuración.

Fase 2: cifrado de secretos (clave ATV, PIN del certificado), almacenamiento
privado del certificado .p12 (fuera de /uploads) y validación del certificado.
"""
import os
import base64
import hashlib
from pathlib import Path

from .database import DATA_DIR

# Carpeta privada para el certificado — NO se monta públicamente.
CERTS_DIR = DATA_DIR / "certs"
CERTS_DIR.mkdir(parents=True, exist_ok=True)

# client_id del IdP según ambiente (ver Guia_IdP.pdf).
CLIENT_ID = {"sandbox": "api-stag", "produccion": "api-prod"}
IDP_REALM = {"sandbox": "rut-stag", "produccion": "rut"}


def _fernet():
    from cryptography.fernet import Fernet
    secret = os.getenv("SESSION_SECRET", "dev-insecure-secret")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def encrypt(value: str | None) -> str | None:
    if not value:
        return None
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str | None) -> str | None:
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode()).decode()
    except Exception:
        return None


def validate_cert(cert_path: str | Path, pin: str | None):
    """Intenta abrir el .p12 con el PIN. Devuelve (ok: bool, detalle: str)."""
    try:
        from cryptography.hazmat.primitives.serialization import pkcs12
        data = Path(cert_path).read_bytes()
        key, cert, _extra = pkcs12.load_key_and_certificates(data, pin.encode() if pin else None)
        if cert is None:
            return False, "El archivo no contiene un certificado."
        try:
            cn = cert.subject.rfc4514_string()
        except Exception:
            cn = "certificado"
        return True, cn
    except Exception:
        return False, "Certificado o PIN inválido."
