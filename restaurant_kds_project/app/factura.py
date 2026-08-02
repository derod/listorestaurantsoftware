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


def idp_token_url(ambiente: str) -> str:
    realm = IDP_REALM.get(ambiente, IDP_REALM["sandbox"])
    return f"https://idp.comprobanteselectronicos.go.cr/auth/realms/{realm}/protocol/openid-connect/token"


def get_idp_token(cfg):
    """Autentica contra el IdP de Hacienda (grant password). Devuelve
    (payload|None, error|None). El payload trae access_token, refresh_token, etc."""
    import json
    import urllib.request
    import urllib.parse
    import urllib.error
    if not (cfg and cfg.atv_usuario and cfg.atv_clave_enc):
        return None, "Faltan credenciales del ATV (usuario/clave)."
    clave = decrypt(cfg.atv_clave_enc)
    if not clave:
        return None, "No se pudo descifrar la clave del ATV (¿cambió SESSION_SECRET?)."
    body = urllib.parse.urlencode({
        "grant_type": "password",
        "client_id": CLIENT_ID.get(cfg.ambiente, "api-stag"),
        "username": cfg.atv_usuario,
        "password": clave,
    }).encode()
    req = urllib.request.Request(
        idp_token_url(cfg.ambiente),
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:300]
        return None, f"HTTP {e.code} — {detail}"
    except Exception as e:  # noqa: BLE001
        return None, f"No se pudo conectar: {e}"


def build_consecutivo(sucursal: str, terminal: str, tipo: str, numero: int) -> str:
    """20 dígitos: sucursal(3) + terminal(5) + tipo(2) + consecutivo(10)."""
    return f"{int(sucursal or 1):03d}{int(terminal or 1):05d}{tipo:>02}{numero:010d}"


def build_clave(cedula_emisor: str, consecutivo20: str, fecha, situacion: str = "1",
                seguridad: str | None = None, pais: str = "506") -> str:
    """50 dígitos: pais(3) + ddmmaa(6) + cedula(12) + consecutivo(20) + situacion(1) + seguridad(8)."""
    import random
    ced = "".join(ch for ch in (cedula_emisor or "") if ch.isdigit()).zfill(12)[-12:]
    fecha_str = fecha.strftime("%d%m%y")
    seg = (seguridad or f"{random.randint(0, 99999999):08d}")[:8].zfill(8)
    clave = f"{pais}{fecha_str}{ced}{consecutivo20}{situacion}{seg}"
    return clave


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
