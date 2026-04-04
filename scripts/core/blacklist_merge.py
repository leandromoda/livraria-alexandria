# ============================================================
# BLACKLIST MERGE — utilitário compartilhado
# Livraria Alexandria
#
# Lê blacklist.json existente (ou cria vazio), acrescenta
# novas entradas deduplicando por slug, grava de volta.
# ============================================================

import json
import os

from core.logger import log


def merge_blacklist(new_entries, blacklist_path):
    """Acrescenta entradas ao blacklist.json, deduplicando por slug.

    Retorna a quantidade de entradas efetivamente adicionadas.
    """

    if not new_entries:
        return 0

    # Ler existente ou criar vazio
    if os.path.exists(blacklist_path):
        with open(blacklist_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {"entries": []}

    existing_slugs = {e.get("slug") for e in data.get("entries", []) if e.get("slug")}

    added = 0

    for entry in new_entries:
        slug = entry.get("slug", "")
        if not slug:
            continue
        if slug in existing_slugs:
            continue

        data["entries"].append({
            "slug":     slug,
            "reason":   entry.get("reason", "cowork-agent"),
            "severity": entry.get("severity", "medium"),
            "details":  entry.get("details", ""),
        })
        existing_slugs.add(slug)
        added += 1

    if added > 0:
        with open(blacklist_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        log(f"[BLACKLIST_MERGE] {added} entrada(s) adicionada(s) → {blacklist_path}")

    return added
