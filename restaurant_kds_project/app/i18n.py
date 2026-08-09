"""
i18n mínimo: diccionario ES/PT/FR + helpers. ES es el idioma por defecto y el
fallback. Cada clave trae sus tres idiomas. Se usa en templates con t('clave')
y en JS con window.I18N['clave'].
"""

LANGS = ["es", "pt", "fr"]
LANG_LABELS = {"es": "ES", "pt": "PT", "fr": "FR"}

STRINGS = {
    # ── Común ─────────────────────────────────────────────────────────────
    "common.crear":            {"es": "Crear",                 "pt": "Criar",                  "fr": "Créer"},
    "common.cancelar":         {"es": "Cancelar",              "pt": "Cancelar",               "fr": "Annuler"},
    "common.nombre_producto":  {"es": "Nombre del producto",   "pt": "Nome do produto",        "fr": "Nom du produit"},
    "common.nuevo_producto":   {"es": "+ Nuevo producto",      "pt": "+ Novo produto",         "fr": "+ Nouveau produit"},
    "common.nuevo_producto_t": {"es": "Nuevo producto",        "pt": "Novo produto",           "fr": "Nouveau produit"},
    "common.activar_alertas":  {"es": "🔔 Activar alertas",    "pt": "🔔 Ativar alertas",      "fr": "🔔 Activer alertes"},

    # ── Salón ─────────────────────────────────────────────────────────────
    "salon.title":             {"es": "SALÓN",                 "pt": "SALÃO",                  "fr": "SALLE"},
    "salon.agente":            {"es": "AGENTE:",               "pt": "AGENTE:",                "fr": "AGENT :"},
    "salon.cambiar_agente":    {"es": "CAMBIAR AGENTE",        "pt": "TROCAR AGENTE",          "fr": "CHANGER D'AGENT"},
    "salon.mesas":             {"es": "🍽️ Mesas",             "pt": "🍽️ Mesas",              "fr": "🍽️ Tables"},
    "salon.manual":            {"es": "Manual",                "pt": "Manual",                 "fr": "Manuel"},
    "salon.az":                {"es": "A–Z",                   "pt": "A–Z",                    "fr": "A–Z"},
    "salon.ordenar":           {"es": "↕ Ordenar",            "pt": "↕ Ordenar",             "fr": "↕ Trier"},
    "salon.listo_orden":       {"es": "✓ Listo",              "pt": "✓ Pronto",              "fr": "✓ Terminé"},
    "salon.quitar":            {"es": "✕ Quitar",             "pt": "✕ Remover",             "fr": "✕ Retirer"},
    "salon.uber_nombre":       {"es": "Nombre de la orden (Uber)", "pt": "Nome do pedido (Uber)", "fr": "Nom de la commande (Uber)"},
    "salon.pedido_actual":     {"es": "Pedido actual",         "pt": "Pedido atual",           "fr": "Commande en cours"},
    "salon.no_productos":      {"es": "No hay productos.",     "pt": "Sem produtos.",          "fr": "Aucun produit."},
    "salon.total":             {"es": "Total productos:",      "pt": "Total de produtos:",     "fr": "Total produits :"},
    "salon.enviar":            {"es": "Enviar",                "pt": "Enviar",                 "fr": "Envoyer"},
    "salon.borrar":            {"es": "Borrar",                "pt": "Limpar",                 "fr": "Effacer"},
    "salon.quitar_ultimo":     {"es": "Quitar último producto", "pt": "Remover último produto", "fr": "Retirer le dernier produit"},
    "salon.mesa":              {"es": "Mesa",                  "pt": "Mesa",                   "fr": "Table"},
    "salon.sin_mesa":          {"es": "Sin mesa (para llevar / Uber)", "pt": "Sem mesa (para levar / Uber)", "fr": "Sans table (à emporter / Uber)"},
    "salon.recientes":         {"es": "Órdenes recientes",     "pt": "Pedidos recentes",       "fr": "Commandes récentes"},
    "salon.sin_ordenes":       {"es": "Aún no has enviado órdenes.", "pt": "Ainda não enviou pedidos.", "fr": "Aucune commande envoyée."},
    "salon.ver_mas":           {"es": "Ver más",              "pt": "Ver mais",               "fr": "Voir plus"},
    "salon.ver_menos":         {"es": "Ver menos",            "pt": "Ver menos",              "fr": "Voir moins"},
    "salon.cancelar_ultima":   {"es": "🚫 Cancelar última orden enviada", "pt": "🚫 Cancelar último pedido enviado", "fr": "🚫 Annuler la dernière commande"},
    "salon.pedidos_salon":     {"es": "Pedidos de salón",     "pt": "Pedidos do salão",       "fr": "Commandes de salle"},
    "salon.no_pedidos_salon":  {"es": "No hay pedidos de salón.", "pt": "Sem pedidos do salão.", "fr": "Aucune commande de salle."},

    # ── Cocina ────────────────────────────────────────────────────────────
    "kitchen.title":           {"es": "COCINA",               "pt": "COZINHA",                "fr": "CUISINE"},
    "kitchen.crear_pedido":    {"es": "Crear pedido salón",   "pt": "Criar pedido do salão",  "fr": "Créer commande salle"},
    "kitchen.cerrar":          {"es": "CERRAR",               "pt": "FECHAR",                 "fr": "FERMER"},
    "kitchen.no_pedidos":      {"es": "No hay pedidos de salón.", "pt": "Sem pedidos do salão.", "fr": "Aucune commande de salle."},
    "kitchen.no_activos":      {"es": "No hay pedidos activos", "pt": "Sem pedidos ativos",     "fr": "Aucune commande active"},
    "kitchen.cargando":        {"es": "Cargando pedidos...",  "pt": "Carregando pedidos...",  "fr": "Chargement des commandes..."},
    "lbl.agente":              {"es": "Agente",               "pt": "Agente",                 "fr": "Agent"},

    # ── Estados y botones dinámicos (JS) ──────────────────────────────────
    "act.aceptar":             {"es": "ACEPTAR",              "pt": "ACEITAR",                "fr": "ACCEPTER"},
    "act.cancelar":            {"es": "CANCELAR",             "pt": "CANCELAR",               "fr": "ANNULER"},
    "act.listo":               {"es": "LISTO",               "pt": "PRONTO",                 "fr": "PRÊT"},
    "act.despachar":           {"es": "DESPACHAR",           "pt": "DESPACHAR",              "fr": "SERVIR"},
    "act.despachado":          {"es": "DESPACHADO",          "pt": "DESPACHADO",             "fr": "SERVI"},
    "act.entendido":           {"es": "Entendido",           "pt": "Entendido",              "fr": "Compris"},
    "st.nuevo":                {"es": "NUEVO",               "pt": "NOVO",                   "fr": "NOUVEAU"},
    "st.aceptado":             {"es": "ACEPTADO",            "pt": "ACEITO",                 "fr": "ACCEPTÉ"},
    "st.preparando":           {"es": "PREPARANDO",          "pt": "PREPARANDO",             "fr": "EN PRÉPARATION"},
    "st.listo":                {"es": "LISTO",               "pt": "PRONTO",                 "fr": "PRÊT"},
    "st.despachado":           {"es": "DESPACHADO",          "pt": "DESPACHADO",             "fr": "SERVI"},
    "st.cancelado":            {"es": "CANCELADO",           "pt": "CANCELADO",              "fr": "ANNULÉ"},
    "msg.pedido_enviado":      {"es": "Pedido enviado.",     "pt": "Pedido enviado.",        "fr": "Commande envoyée."},
    "msg.agrega_productos":    {"es": "Agrega productos primero.", "pt": "Adicione produtos primeiro.", "fr": "Ajoutez d'abord des produits."},
    "msg.no_enviar":           {"es": "No se pudo enviar.",  "pt": "Não foi possível enviar.", "fr": "Envoi impossible."},
    "msg.escribe_nombre":      {"es": "Escribe un nombre.",  "pt": "Digite um nome.",        "fr": "Saisissez un nom."},
    "msg.nuevo_pedido":        {"es": "🔔 NUEVO PEDIDO",     "pt": "🔔 NOVO PEDIDO",         "fr": "🔔 NOUVELLE COMMANDE"},
    "voice.nuevo_pedido":      {"es": "Nuevo pedido.",       "pt": "Novo pedido.",           "fr": "Nouvelle commande."},
    "voice.pedido_listo":      {"es": "Pedido listo.",       "pt": "Pedido pronto.",         "fr": "Commande prête."},
    "voice.pedido_cancelado":  {"es": "Pedido cancelado.",   "pt": "Pedido cancelado.",      "fr": "Commande annulée."},
    "voice.nuevo_cocina":      {"es": "Nuevo pedido de cocina.", "pt": "Novo pedido da cozinha.", "fr": "Nouvelle commande cuisine."},
}


def t(lang, key):
    entry = STRINGS.get(key)
    if not entry:
        return key
    return entry.get(lang) or entry.get("es") or key


def dict_for(lang):
    """Devuelve {clave: texto} en el idioma dado (para exponer a JS)."""
    return {k: (v.get(lang) or v.get("es")) for k, v in STRINGS.items()}
