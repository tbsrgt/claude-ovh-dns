---
name: dns
description: >
  Zone DNS OVH par API : lister, sauvegarder, repérer et supprimer les enregistrements de
  bienvenue, pointer vers Vercel, vérifier la propagation, auditer SPF/DKIM/DMARC. À utiliser
  pour « pointe le domaine vers Vercel », « montre la zone », « c'est propagé ? », « DMARC ».
user-invocable: true
argument-hint: "<list|backup|welcome|vercel|set|delete|check|mail> <domaine> [options]"
---

# DNS OVH

Script : `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/ovh_dns.py <commande> <domaine> [options]`
(Python 3.9 stdlib, clé OVH dans `~/.ovh.conf`, clé consommateur par domaine dans
`~/.cache/ovh-dns/<domaine>/ck`, sinon `$OVH_CONSUMER_KEY`, sinon `consumer_key` de `~/.ovh.conf`).

## Règles
1. **Sauvegarde avant écriture** : le script la fait seul (`~/.cache/ovh-dns/<domaine>/zone-backup-AAAA-MM-JJ.json`). Montre le chemin dans ta réponse.
2. **Plan avant action** : lance `vercel` et `welcome` **sans** `--apply` / `--delete`, montre le plan à l'utilisateur, n'applique qu'avec son accord explicite dans la conversation.
3. **Jamais toucher au mail** : MX, SRV, SPF, DKIM, DMARC, autoconfig/autodiscover/imap/mail/pop3/smtp. `set` et `delete` les refusent sans `--force-mail` ; `vercel` et `welcome` ne les proposent jamais.
4. Clé manquante ou expirée (« This credential is not valid », 401/403) : **ne lance pas** `request_ck.py` toi-même (bloqué en mode auto). Demande à l'utilisateur de taper
   `! python3 ${CLAUDE_PLUGIN_ROOT}/scripts/request_ck.py <domaine>` puis d'ouvrir l'URL affichée sur le bon compte OVH.

## Commandes
| Commande | Effet |
|---|---|
| `list <d>` | Tableau id / sous-domaine / type / ttl / cible, enregistrements mail marqués `[mail]`. |
| `backup <d>` | Sauvegarde JSON (records + export BIND). |
| `welcome <d> [--delete]` | Repère A/AAAA 51.91.236.255, TXT `1|www…` et `3|welcome` (page d'attente OVH, bloquent le CNAME www). Supprime seulement avec `--delete`. |
| `vercel <d> [--cname <cible>] [--apply]` | Plan : apex `A 216.198.79.1`, `www CNAME` vers la cible donnée par Vercel (sinon `cname.vercel-dns.com.`), suppression de ce qui bloque (www A/AAAA, apex AAAA, bienvenue). `--apply` écrit puis rafraîchit la zone. |
| `set <d> <sous-dom|@> <type> <cible> [--ttl N]` | Crée ou met à jour un enregistrement (TXT : toujours ajout). |
| `delete <d> <id>` | Supprime un enregistrement par id. |
| `check <d>` | dig apex A et www CNAME via 1.1.1.1, 8.8.8.8 et les NS OVH, comparaison avec la zone, codes HTTP apex et www. |
| `mail <d>` | État MX / SPF / DMARC / DKIM et recommandations. |

## Première utilisation
Si `~/.ovh.conf` manque : expliquer la création d'une clé application sur https://eu.api.ovh.com/createApp/ et le format du fichier (voir README). Puis clé consommateur par domaine via `request_ck.py` (étape 4 des règles).

## Notes par domaine
Les particularités de chaque zone (hôte principal www ou apex, enregistrements mail à
préserver, TXT de vérification Search Console) sont notées dans `~/.cache/ovh-dns/<domaine>/NOTES.md`
quand ce fichier existe : lis-le avant toute écriture. Sans notes, `list` puis demande
confirmation avant de toucher autre chose que les enregistrements A/CNAME de l'apex et de www.

## Procédure : pointer un nouveau domaine vers Vercel
1. Côté Vercel, ajouter le domaine au projet (`npx vercel domains add <d>` ou connecteur Vercel `add_project_domain`) et noter la cible CNAME recommandée pour www (`xxxx.vercel-dns-017.com.`). Décider si www ou apex est principal (recommandé : www principal, apex redirige).
2. `backup <d>` puis `list <d>` : vérifier qu'il y a bien des enregistrements mail à préserver, le dire.
3. `welcome <d>` → montrer → `welcome <d> --delete`.
4. `vercel <d> --cname <cible>` → montrer le plan → `vercel <d> --cname <cible> --apply`.
5. `check <d>` toutes les 5 à 10 minutes jusqu'à « Propagé partout » ; côté Vercel le certificat se génère ensuite seul.
6. `mail <d>` : appliquer les recommandations SPF/DMARC uniquement avec accord (commandes `set … --force-mail`).
7. Réponse : chemin de la sauvegarde, enregistrements modifiés, état de propagation, reste à faire.
