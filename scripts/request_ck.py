#!/usr/bin/env python3
"""Demande une clé consommateur OVH limitée à la zone DNS d'un domaine.
Usage : python3 request_ck.py <domaine>
À lancer soi-même (préfixe `!` dans Claude Code, pas par l'agent), puis ouvrir l'URL affichée et valider
sur le compte OVH qui possède le domaine. La clé est écrite dans ~/.cache/ovh-dns/<domaine>/ck.
"""
import configparser, json, os, sys, urllib.request

if len(sys.argv) != 2:
    sys.exit(__doc__)
domain = sys.argv[1].lower().strip().rstrip(".")
if domain.startswith("www."): domain = domain[4:]
cfg = configparser.ConfigParser(); cfg.read(os.path.expanduser("~/.ovh.conf"))
if not cfg.has_section("default"):
    sys.exit("~/.ovh.conf introuvable. Crée une clé application sur https://eu.api.ovh.com/createApp/ et renseigne [default] endpoint + [ovh-eu] application_key/application_secret.")
ep = cfg["default"]["endpoint"]; ak = cfg[ep]["application_key"]
API = {"ovh-eu": "https://eu.api.ovh.com/1.0", "ovh-ca": "https://ca.api.ovh.com/1.0", "ovh-us": "https://api.us.ovhcloud.com/1.0"}.get(ep, "https://eu.api.ovh.com/1.0")
rules = [{"method": m, "path": p} for m in ("GET", "POST", "PUT", "DELETE")
         for p in (f"/domain/zone/{domain}", f"/domain/zone/{domain}/*")]
req = urllib.request.Request(API + "/auth/credential",
    data=json.dumps({"accessRules": rules}).encode(), method="POST",
    headers={"X-Ovh-Application": ak, "Content-Type": "application/json"})
r = json.loads(urllib.request.urlopen(req, timeout=20).read())
d = os.path.expanduser(f"~/.cache/ovh-dns/{domain}"); os.makedirs(d, exist_ok=True)
p = os.path.join(d, "ck")
with open(p, "w") as f: f.write(r["consumerKey"])
os.chmod(p, 0o600)
print(f"Clé écrite dans {p} (en attente de validation).")
print("Ouvre cette URL, connecte-toi au compte OVH propriétaire du domaine et valide :")
print(r["validationUrl"])
