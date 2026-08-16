# Despliegue — datos persistentes en un volumen (`/data`)

LISTO guarda **todo lo persistente** bajo una sola carpeta raíz: la variable de
entorno **`DATA_DIR`**. Ahí viven:

- La base de datos: `DATA_DIR/restaurant_kds.db`
- Los archivos subidos: `DATA_DIR/uploads/**` (servidos en `/uploads/...`)
  - `uploads/menu/` — portadas y fotos del Menú Online
  - `uploads/products/` — fotos de productos
  - `uploads/audio/` — sonidos
  - `uploads/documentation/` — documentos oficiales (guías sanitarias)

Por defecto `DATA_DIR = .` (el directorio de la app), por eso en desarrollo la BD
y los uploads quedan dentro del repo. **Para producción, apúntalo a un volumen
persistente** (p. ej. `/data`) para que los datos y las imágenes sobrevivan a los
redeploys sin necesidad de commitearlos.

## Pasos

1. **Adjunta un volumen persistente** montado en `/data` (Railway/Render/Fly/…
   "web volume").
2. **Configura las variables de entorno:**

   | Variable | Valor | Notas |
   |---|---|---|
   | `DATA_DIR` | `/data` | Raíz de BD + uploads en el volumen. |
   | `ADMIN_PASSCODE` | *(tu clave)* | Requerido. |
   | `SESSION_SECRET` | *(cadena larga aleatoria)* | Sesiones. |
   | `SECURE_COOKIES` | `1` | Si sirves por HTTPS. |
   | `SEED_DB_FROM_BUNDLE` | `1` | **Solo el primer deploy**, para migrar tu BD actual del repo al volumen (copia `restaurant_kds.db` solo si el volumen no tiene una). Quítalo después. |

3. **Arranca.** En el primer arranque con el volumen vacío, la app:
   - copia al volumen los assets que vienen en el repo (`uploads/**`: documentos
     oficiales, imágenes demo) **si faltan** — nunca sobrescribe;
   - crea la BD (o la copia del repo si pusiste `SEED_DB_FROM_BUNDLE=1`);
   - siembra los datos demo que falten (idempotente).

A partir de ahí, las fotos que suban desde Admin → Menú Online se guardan en el
volumen (`/data/uploads/menu/`) y se sirven al instante — **sin recommittear nada**.

## Migrar tus datos actuales (una vez)

Si ya venías versionando la BD en git y quieres conservarla:

- **Opción A (automática):** primer deploy con `SEED_DB_FROM_BUNDLE=1`; copia
  `restaurant_kds.db` del repo al volumen. Luego quita la variable.
- **Opción B (manual):** copia tu `restaurant_kds.db` y tu carpeta `uploads/` al
  volumen `/data` con las herramientas del proveedor (SSH/consola), una sola vez.

## Backups

Como todo está en `/data`, respaldar = copiar ese volumen (o solo
`/data/restaurant_kds.db` y `/data/uploads/`). Programa snapshots del volumen en tu
proveedor.
