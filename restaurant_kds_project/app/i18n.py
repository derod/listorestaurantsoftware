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

    # ── Página principal (hub) ────────────────────────────────────────────
    "hub.sub":            {"es": "Selecciona un módulo para continuar", "pt": "Selecione um módulo para continuar", "fr": "Sélectionnez un module pour continuer"},
    "hub.abrir":          {"es": "Abrir",                 "pt": "Abrir",                  "fr": "Ouvrir"},
    "hub.status":         {"es": "Sistema operativo — todos los módulos en línea", "pt": "Sistema operacional — todos os módulos on-line", "fr": "Système opérationnel — tous les modules en ligne"},
    "hub.salon":          {"es": "Salón",                 "pt": "Salão",                  "fr": "Salle"},
    "hub.salon_desc":     {"es": "Toma de pedidos en mesa. Envío directo a cocina sin papel.", "pt": "Pedidos na mesa. Envio direto à cozinha sem papel.", "fr": "Prise de commandes à table. Envoi direct en cuisine, sans papier."},
    "hub.kitchen":        {"es": "Kitchen Display",       "pt": "Tela de Cozinha",        "fr": "Écran Cuisine"},
    "hub.kitchen_desc":   {"es": "Pantalla de cocina en tiempo real. Alertas de pedidos vía WebSocket.", "pt": "Tela de cozinha em tempo real. Alertas de pedidos via WebSocket.", "fr": "Écran cuisine en temps réel. Alertes de commandes via WebSocket."},
    "hub.admin":          {"es": "Admin",                 "pt": "Admin",                  "fr": "Admin"},
    "hub.admin_desc":     {"es": "Configuración, productos y reportes", "pt": "Configuração, produtos e relatórios", "fr": "Configuration, produits et rapports"},
    "hub.inv":            {"es": "Inventario",            "pt": "Inventário",             "fr": "Inventaire"},
    "hub.inv_desc":       {"es": "Control de stock y existencias", "pt": "Controle de estoque e existências", "fr": "Contrôle du stock et des existences"},
    "hub.pos":            {"es": "Punto de Venta",        "pt": "Ponto de Venda",         "fr": "Point de Vente"},
    "hub.pos_desc":       {"es": "Cobros y facturación",  "pt": "Cobranças e faturamento", "fr": "Encaissements et facturation"},

    # ── Admin (hub / dashboard) ───────────────────────────────────────────
    "adm.dashboard":      {"es": "Panel de administración", "pt": "Painel de administração", "fr": "Tableau de bord admin"},
    "adm.sec_ventas":     {"es": "Ventas y dinero",       "pt": "Vendas e dinheiro",      "fr": "Ventes et argent"},
    "adm.sec_cocina":     {"es": "Cocina e inventario",   "pt": "Cozinha e inventário",   "fr": "Cuisine et inventaire"},
    "adm.sec_sistema":    {"es": "Sistema",               "pt": "Sistema",                "fr": "Système"},
    "adm.pos":            {"es": "POS",                   "pt": "POS",                    "fr": "POS"},
    "adm.ordenes":        {"es": "Órdenes",               "pt": "Pedidos",                "fr": "Commandes"},
    "adm.reportes":       {"es": "Reportes",              "pt": "Relatórios",             "fr": "Rapports"},
    "adm.rentabilidad":   {"es": "Rentabilidad",          "pt": "Rentabilidade",          "fr": "Rentabilité"},
    "adm.gastos":         {"es": "Gastos",                "pt": "Despesas",               "fr": "Dépenses"},
    "adm.factura":        {"es": "Factura Electrónica",   "pt": "Nota Fiscal Eletrônica", "fr": "Facture Électronique"},
    "adm.productos":      {"es": "Productos",             "pt": "Produtos",               "fr": "Produits"},
    "adm.insumos":        {"es": "Insumos",               "pt": "Insumos",                "fr": "Fournitures"},
    "adm.compras":        {"es": "Compras",               "pt": "Compras",                "fr": "Achats"},
    "adm.plano_mesas":    {"es": "Plano mesas",           "pt": "Mapa de mesas",          "fr": "Plan des tables"},
    "adm.logs":           {"es": "Logs",                  "pt": "Logs",                   "fr": "Journaux"},
    "adm.reloj":          {"es": "Reloj",                 "pt": "Relógio",                "fr": "Horloge"},
    "adm.audio":          {"es": "Audio",                 "pt": "Áudio",                  "fr": "Audio"},
    "adm.contactos":      {"es": "Contactos",             "pt": "Contatos",               "fr": "Contacts"},
    "adm.cuestionario":   {"es": "Cuestionario Fácil",    "pt": "Questionário Fácil",     "fr": "Questionnaire Facile"},
    "adm.agentes":        {"es": "Agentes",               "pt": "Agentes",                "fr": "Agents"},
    "adm.ordenes_hoy":    {"es": "Órdenes hoy",           "pt": "Pedidos hoje",           "fr": "Commandes aujourd'hui"},
    "adm.ordenes_ayer":   {"es": "Órdenes ayer",          "pt": "Pedidos ontem",          "fr": "Commandes hier"},
    "adm.promedio_hoy":   {"es": "Promedio hoy",          "pt": "Média hoje",             "fr": "Moyenne aujourd'hui"},
    "adm.promedio_ayer":  {"es": "Promedio ayer",         "pt": "Média ontem",            "fr": "Moyenne hier"},
    "adm.canceladas_hoy": {"es": "Canceladas hoy",        "pt": "Canceladas hoje",        "fr": "Annulées aujourd'hui"},
    "adm.activas_ahora":  {"es": "Activas ahora",         "pt": "Ativas agora",           "fr": "Actives maintenant"},
    "adm.ordenes_recientes": {"es": "Órdenes recientes",  "pt": "Pedidos recentes",       "fr": "Commandes récentes"},
    "adm.th_origen":      {"es": "Origen",                "pt": "Origem",                 "fr": "Origine"},
    "adm.th_agente":      {"es": "Agente",                "pt": "Agente",                 "fr": "Agent"},
    "adm.th_estado":      {"es": "Estado",                "pt": "Estado",                 "fr": "État"},
    "adm.th_hora":        {"es": "Hora",                  "pt": "Hora",                   "fr": "Heure"},
    "adm.th_duracion":    {"es": "Duración",              "pt": "Duração",                "fr": "Durée"},
    "adm.th_items":       {"es": "Items",                 "pt": "Itens",                  "fr": "Articles"},
    "adm.min":            {"es": "min",                   "pt": "min",                    "fr": "min"},
    "adm.dz_title":       {"es": "Zona de peligro – Reset del sistema", "pt": "Zona de perigo – Reset do sistema", "fr": "Zone dangereuse – Réinitialisation du système"},
    "adm.dz_sub":         {"es": "Esta acción no se puede deshacer. Se requiere confirmación.", "pt": "Esta ação não pode ser desfeita. É necessária confirmação.", "fr": "Cette action est irréversible. Une confirmation est requise."},
    "adm.dz_prod_desc":   {"es": "Elimina todos los productos e inventario", "pt": "Exclui todos os produtos e o inventário", "fr": "Supprime tous les produits et l'inventaire"},
    "adm.dz_ord_desc":    {"es": "Elimina todas las órdenes, items y eventos", "pt": "Exclui todos os pedidos, itens e eventos", "fr": "Supprime toutes les commandes, articles et événements"},
    "adm.dz_logs_desc":   {"es": "Elimina todos los logs de inventario", "pt": "Exclui todos os logs de inventário", "fr": "Supprime tous les journaux d'inventaire"},
    "adm.dz_inv_desc":    {"es": "Pone todas las cantidades a 0", "pt": "Zera todas as quantidades", "fr": "Remet toutes les quantités à 0"},
    "adm.dz_confirmar":   {"es": "Confirmar reset",       "pt": "Confirmar reset",        "fr": "Confirmer la réinitialisation"},
    "adm.dz_irreversible": {"es": "Esta acción no se puede deshacer.", "pt": "Esta ação não pode ser desfeita.", "fr": "Cette action est irréversible."},
    "adm.dz_escribe_pre": {"es": "Escribe",               "pt": "Digite",                 "fr": "Saisissez"},
    "adm.dz_escribe":     {"es": "para confirmar:",       "pt": "para confirmar:",        "fr": "pour confirmer :"},
    "common.confirmar":   {"es": "Confirmar",             "pt": "Confirmar",              "fr": "Confirmer"},
}


def t(lang, key):
    entry = STRINGS.get(key)
    if not entry:
        return key
    return entry.get(lang) or entry.get("es") or key


def dict_for(lang):
    """Devuelve {clave: texto} en el idioma dado (para exponer a JS)."""
    return {k: (v.get(lang) or v.get("es")) for k, v in STRINGS.items()}
