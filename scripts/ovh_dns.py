#!/usr/bin/env python3
"""Zone DNS OVH par API (stdlib Python 3.9).

Usage :
  ovh_dns.py list    <domaine>
  ovh_dns.py backup  <domaine>
  ovh_dns.py welcome <domaine> [--delete]
  ovh_dns.py vercel  <domaine> [--cname <cible>] [--apply]
  ovh_dns.py set     <domaine> <sous-domaine|@> <type> <cible> [--ttl N]
  ovh_dns.py delete  <domaine> <id>
  ovh_dns.py check   <domaine>
  ovh_dns.py mail    <domaine>

Clé consommateur : ~/.cache/ovh-dns/<domaine>/ck, sinon $OVH_CONSUMER_KEY, sinon ~/.ovh.conf.
Toute écriture fait d'abord une sauvegarde JSON de la zone.
"""
import argparse, configparser, datetime, hashlib, json, os, subprocess, sys, time
import urllib.error, urllib.request

ENDPOINTS = {"ovh-eu": "https://eu.api.ovh.com/1.0", "ovh-ca": "https://ca.api.ovh.com/1.0", "ovh-us": "https://api.us.ovhcloud.com/1.0"}
BASE = ENDPOINTS["ovh-eu"]
VERCEL_A = "216.198.79.1"
VERCEL_CNAME_DEFAULT = "cname.vercel-dns.com."
OVH_WELCOME_IPS = {"51.91.236.255", "2001:41d0:301::28", "2001:41d0:0301:0000:0000:0000:0000:0028"}
MAIL_SUBS = {"autoconfig", "autodiscover", "imap", "mail", "pop3", "smtp", "_dmarc", "_domainkey"}
MAIL_TYPES = {"MX", "SRV", "SPF", "DKIM", "DMARC"}


def die(msg, code=1):
    print(msg, file=sys.stderr)
    sys.exit(code)


def ck_path(domain):
    return os.path.expanduser(f"~/.cache/ovh-dns/{domain}/ck")


def load_ck(domain):
    """Clé consommateur : ~/.cache/ovh-dns/<domaine>/ck, sinon OVH_CONSUMER_KEY, sinon consumer_key de ~/.ovh.conf."""
    p = ck_path(domain)
    if os.path.isfile(p):
        ck = open(p).read().strip()
        if ck:
            return ck, p
    if os.environ.get("OVH_CONSUMER_KEY"):
        return os.environ["OVH_CONSUMER_KEY"], "$OVH_CONSUMER_KEY"
    cfg = configparser.ConfigParser(); cfg.read(os.path.expanduser("~/.ovh.conf"))
    if cfg.has_section("default"):
        ep = cfg["default"]["endpoint"]
        ck = cfg[ep].get("consumer_key") if cfg.has_section(ep) else None
        if ck:
            return ck, "~/.ovh.conf"
    die(f"Aucune clé consommateur pour {domain}.\n"
        f"À lancer soi-même (avec le préfixe !) :  ! python3 {os.path.dirname(os.path.abspath(__file__))}/request_ck.py {domain}\n"
        f"puis ouvrir l'URL affichée et valider.")

class OVH:
    def __init__(self, domain):
        global BASE
        cfg = configparser.ConfigParser(); cfg.read(os.path.expanduser("~/.ovh.conf"))
        if not cfg.has_section("default"):
            die("~/.ovh.conf introuvable ou incomplet. Crée une clé application sur "
                "https://eu.api.ovh.com/createApp/ puis écris :\n[default]\nendpoint=ovh-eu\n\n[ovh-eu]\napplication_key=...\napplication_secret=...")
        ep = cfg["default"]["endpoint"]
        BASE = ENDPOINTS.get(ep, BASE)
        self.ak = cfg[ep]["application_key"]; self.as_ = cfg[ep]["application_secret"]
        self.ck, self.ck_from = load_ck(domain)
        self.domain = domain
        with urllib.request.urlopen(BASE + "/auth/time", timeout=15) as r:
            self.delta = int(r.read()) - int(time.time())

    def call(self, method, path, body=None):
        url = BASE + path
        data = json.dumps(body) if body is not None else ""
        ts = str(int(time.time()) + self.delta)
        sig = "$1$" + hashlib.sha1("+".join([self.as_, self.ck, method, url, data, ts]).encode()).hexdigest()
        req = urllib.request.Request(url, data=data.encode() if data else None, method=method, headers={
            "X-Ovh-Application": self.ak, "X-Ovh-Consumer": self.ck, "X-Ovh-Timestamp": ts,
            "X-Ovh-Signature": sig, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            txt = e.read().decode(errors="replace")
            if e.code in (401, 403):
                die(f"OVH {e.code} sur {method} {path} : {txt}\n"
                    f"La clé ({self.ck_from}) est invalide, expirée ou sans droit sur cette zone.\n"
                    f"À lancer soi-même (avec le préfixe !) :  ! python3 {os.path.dirname(os.path.abspath(__file__))}/request_ck.py {self.domain}")
            die(f"OVH {e.code} sur {method} {path} : {txt}")

    # --- zone helpers -------------------------------------------------------
    def records(self):
        ids = self.call("GET", f"/domain/zone/{self.domain}/record") or []
        out = []
        for i in ids:
            out.append(self.call("GET", f"/domain/zone/{self.domain}/record/{i}"))
        return sorted(out, key=lambda r: (r.get("subDomain") or "", r.get("fieldType"), r.get("target")))

    def backup(self):
        recs = self.records()
        export = self.call("GET", f"/domain/zone/{self.domain}/export")
        d = os.path.expanduser(f"~/.cache/ovh-dns/{self.domain}")
        os.makedirs(d, exist_ok=True)
        stamp = datetime.date.today().isoformat()
        path = os.path.join(d, f"zone-backup-{stamp}.json")
        n = 1
        while os.path.exists(path):
            n += 1; path = os.path.join(d, f"zone-backup-{stamp}-{n}.json")
        json.dump({"records": recs, "export": export}, open(path, "w"), indent=2, ensure_ascii=False)
        os.chmod(path, 0o600)
        return path, recs

    def refresh(self):
        self.call("POST", f"/domain/zone/{self.domain}/refresh")

    def create(self, sub, ftype, target, ttl=0):
        body = {"fieldType": ftype, "subDomain": sub, "target": target}
        if ttl: body["ttl"] = ttl
        return self.call("POST", f"/domain/zone/{self.domain}/record", body)

    def update(self, rid, target, ttl=None):
        body = {"target": target}
        if ttl is not None: body["ttl"] = ttl
        return self.call("PUT", f"/domain/zone/{self.domain}/record/{rid}", body)

    def delete(self, rid):
        return self.call("DELETE", f"/domain/zone/{self.domain}/record/{rid}")


def is_mail(rec):
    sub = (rec.get("subDomain") or "").lower()
    t = rec.get("fieldType"); target = (rec.get("target") or "").lower()
    if t in MAIL_TYPES: return True
    if sub in MAIL_SUBS or sub.endswith("._domainkey") or sub.startswith("_dmarc"): return True
    if t == "TXT" and ("v=spf1" in target or "v=dmarc1" in target or "v=dkim1" in target): return True
    return False


def fmt_table(recs):
    rows = [(str(r["id"]), r.get("subDomain") or "@", r["fieldType"], str(r.get("ttl", 0)), r.get("target") or "") for r in recs]
    w = [max(len(x[i]) for x in rows + [("id", "sous-dom", "type", "ttl", "cible")]) for i in range(4)]
    print(f"{'id':<{w[0]}}  {'sous-dom':<{w[1]}}  {'type':<{w[2]}}  {'ttl':<{w[3]}}  cible")
    for r in rows:
        flag = "  [mail]" if is_mail(dict(id=r[0], subDomain=None if r[1] == "@" else r[1], fieldType=r[2], target=r[4])) else ""
        print(f"{r[0]:<{w[0]}}  {r[1]:<{w[1]}}  {r[2]:<{w[2]}}  {r[3]:<{w[3]}}  {r[4]}{flag}")


def dig(name, rtype, server=None):
    cmd = ["dig", "+short", "+time=4", "+tries=1", name, rtype]
    if server: cmd.append("@" + server)
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=12).stdout
    except Exception as e:
        return [f"erreur: {e}"]
    return [l.strip() for l in out.splitlines() if l.strip() and not l.startswith(";")]


# --- commands ---------------------------------------------------------------
def cmd_list(o, a):
    recs = o.records()
    print(f"Zone {o.domain} : {len(recs)} enregistrements (clé : {o.ck_from})")
    fmt_table(recs)


def cmd_backup(o, a):
    path, recs = o.backup()
    print(f"Sauvegarde de {len(recs)} enregistrements : {path}")


def find_welcome(recs, domain):
    hits = []
    for r in recs:
        t, target, sub = r["fieldType"], (r.get("target") or "").strip('"'), r.get("subDomain") or ""
        if t in ("A", "AAAA") and target in OVH_WELCOME_IPS: hits.append(r)
        elif t == "TXT" and (target.startswith("3|welcome") or target.startswith("1|www")): hits.append(r)
    return hits


def cmd_welcome(o, a):
    recs = o.records()
    hits = find_welcome(recs, o.domain)
    if not hits:
        print("Aucun enregistrement de bienvenue OVH dans la zone."); return
    print("Enregistrements de bienvenue OVH :"); fmt_table(hits)
    if not a.delete:
        print("\nRien supprimé (relance avec --delete)."); return
    path, _ = o.backup(); print(f"Sauvegarde : {path}")
    for r in hits:
        o.delete(r["id"]); print(f"supprimé {r['id']} ({r.get('subDomain') or '@'} {r['fieldType']} {r['target']})")
    o.refresh(); print("Zone rafraîchie.")


def cmd_vercel(o, a):
    cname = a.cname or VERCEL_CNAME_DEFAULT
    if not cname.endswith("."): cname += "."
    recs = o.records()
    apex_a = [r for r in recs if r["fieldType"] == "A" and not r.get("subDomain")]
    apex_aaaa = [r for r in recs if r["fieldType"] == "AAAA" and not r.get("subDomain")]
    www = [r for r in recs if (r.get("subDomain") or "").lower() == "www" and r["fieldType"] in ("A", "AAAA", "CNAME", "TXT")]
    welcome = find_welcome(recs, o.domain)
    plan = []  # (action, desc, fn)
    # apex A
    ok_a = [r for r in apex_a if r["target"] == VERCEL_A]
    for r in apex_a:
        if r["target"] != VERCEL_A:
            plan.append(("modifier", f"@ A {r['target']} -> {VERCEL_A} (id {r['id']})", lambda r=r: o.update(r["id"], VERCEL_A)))
    if not apex_a:
        plan.append(("créer", f"@ A {VERCEL_A}", lambda: o.create("", "A", VERCEL_A)))
    for r in apex_aaaa:
        plan.append(("supprimer", f"@ AAAA {r['target']} (id {r['id']}) : Vercel n'en fournit pas", lambda r=r: o.delete(r["id"])))
    # www
    www_cname = [r for r in www if r["fieldType"] == "CNAME"]
    for r in www:
        if r["fieldType"] != "CNAME":
            plan.append(("supprimer", f"www {r['fieldType']} {r['target']} (id {r['id']}) : bloque le CNAME", lambda r=r: o.delete(r["id"])))
    for r in www_cname:
        if r["target"] != cname:
            plan.append(("modifier", f"www CNAME {r['target']} -> {cname} (id {r['id']})", lambda r=r: o.update(r["id"], cname)))
    if not www_cname:
        plan.append(("créer", f"www CNAME {cname}", lambda: o.create("www", "CNAME", cname)))
    for r in welcome:
        if r not in apex_a and r not in apex_aaaa and r not in www:
            plan.append(("supprimer", f"{r.get('subDomain') or '@'} {r['fieldType']} {r['target']} (id {r['id']}) : bienvenue OVH", lambda r=r: o.delete(r["id"])))
    print(f"Plan Vercel pour {o.domain} (apex A {VERCEL_A}, www CNAME {cname}) :")
    if not plan:
        print("  rien à faire, la zone est déjà conforme."); return
    for act, desc, _ in plan: print(f"  - {act} : {desc}")
    kept = [r for r in recs if is_mail(r)]
    print(f"  ({len(kept)} enregistrements mail conservés tels quels)")
    if not a.apply:
        print("\nAucune écriture (relance avec --apply)."); return
    path, _ = o.backup(); print(f"\nSauvegarde : {path}")
    for act, desc, fn in plan:
        fn(); print(f"fait : {act} {desc}")
    o.refresh(); print("Zone rafraîchie. Pense à ajouter le domaine dans le projet Vercel, puis `check`.")


def cmd_set(o, a):
    sub = "" if a.sub in ("@", "") else a.sub
    if is_mail({"subDomain": sub, "fieldType": a.type.upper(), "target": a.target}) and not a.force_mail:
        die("Enregistrement lié au mail : refusé par défaut (ajoute --force-mail si tu sais ce que tu fais).")
    recs = o.records()
    same = [r for r in recs if (r.get("subDomain") or "") == sub and r["fieldType"] == a.type.upper()]
    path, _ = o.backup(); print(f"Sauvegarde : {path}")
    if same and a.type.upper() != "TXT":
        r = same[0]; o.update(r["id"], a.target, a.ttl); print(f"modifié id {r['id']} : {sub or '@'} {a.type.upper()} -> {a.target}")
        for extra in same[1:]:
            o.delete(extra["id"]); print(f"supprimé doublon id {extra['id']}")
    else:
        r = o.create(sub, a.type.upper(), a.target, a.ttl or 0); print(f"créé id {r['id']} : {sub or '@'} {a.type.upper()} {a.target}")
    o.refresh(); print("Zone rafraîchie.")


def cmd_delete(o, a):
    rec = o.call("GET", f"/domain/zone/{o.domain}/record/{a.id}")
    if is_mail(rec) and not a.force_mail:
        die(f"id {a.id} = {rec.get('subDomain') or '@'} {rec['fieldType']} {rec['target']} : enregistrement mail, refusé (--force-mail pour forcer).")
    path, _ = o.backup(); print(f"Sauvegarde : {path}")
    o.delete(a.id); o.refresh()
    print(f"supprimé id {a.id} : {rec.get('subDomain') or '@'} {rec['fieldType']} {rec['target']}")


def cmd_check(o, a):
    recs = o.records()
    zone_apex = sorted(r["target"] for r in recs if r["fieldType"] == "A" and not r.get("subDomain"))
    zone_www = sorted(r["target"].rstrip(".") for r in recs if (r.get("subDomain") or "").lower() == "www" and r["fieldType"] == "CNAME")
    ns = [x.rstrip(".") for x in dig(o.domain, "NS", "1.1.1.1")]
    servers = [("1.1.1.1", "Cloudflare"), ("8.8.8.8", "Google")] + [(n, "NS OVH") for n in ns[:2]]
    print(f"Zone OVH : apex A {zone_apex or '-'} ; www CNAME {zone_www or '-'}")
    all_ok = True
    for srv, label in servers:
        apex = sorted(dig(o.domain, "A", srv))
        www_c = sorted(x.rstrip(".") for x in dig(f"www.{o.domain}", "CNAME", srv))
        ok_apex = apex == zone_apex
        ok_www = (www_c == zone_www) if zone_www else True
        all_ok &= ok_apex and ok_www
        print(f"  {label:<10} {srv:<24} apex A {apex or '-'} {'OK' if ok_apex else 'DIFF'} ; www {www_c or '-'} {'OK' if ok_www else 'DIFF'}")
    # HTTP
    for host in (o.domain, f"www.{o.domain}"):
        try:
            out = subprocess.run(["curl", "-sI", "-o", "/dev/null", "-w", "%{http_code} %{redirect_url}", "--max-time", "10", f"https://{host}/"],
                                 capture_output=True, text=True, timeout=15).stdout.strip()
        except Exception as e:
            out = f"erreur {e}"
        print(f"  https://{host}/ -> {out}")
    print("\nPropagé partout." if all_ok else "\nPas encore propagé partout (TTL OVH 0 à 3600 s, réessaie plus tard).")


def cmd_mail(o, a):
    d = o.domain
    mx = dig(d, "MX", "1.1.1.1")
    txt = [t.strip('"').replace('" "', '') for t in dig(d, "TXT", "1.1.1.1")]
    spf = [t for t in txt if t.lower().startswith("v=spf1")]
    dmarc = [t.strip('"').replace('" "', '') for t in dig(f"_dmarc.{d}", "TXT", "1.1.1.1")]
    recs = o.records()
    dkim = [r for r in recs if "_domainkey" in (r.get("subDomain") or "")]
    print(f"Audit mail {d}")
    print(f"  MX    : {mx or 'AUCUN'}")
    print(f"  SPF   : {spf or 'AUCUN'}")
    print(f"  DMARC : {dmarc or 'AUCUN'}")
    print(f"  DKIM  : {[(r.get('subDomain'), r['fieldType']) for r in dkim] or 'aucun sélecteur dans la zone'}")
    print("\nRecommandations :")
    if not mx: print("  - Aucun MX : le domaine ne reçoit pas de mail.")
    if not spf: print(f"  - Ajouter SPF, ex. OVH : set {d} @ TXT \"v=spf1 include:mx.ovh.com ~all\" --force-mail")
    elif len(spf) > 1: print("  - Plusieurs SPF : n'en garder qu'un seul (sinon SPF invalide).")
    elif "+all" in spf[0]: print("  - SPF en +all : trop permissif, passer en ~all ou -all.")
    if not dmarc:
        print(f"  - Ajouter DMARC : set {d} _dmarc TXT \"v=DMARC1; p=quarantine; rua=mailto:bonjour@{d}\" --force-mail  (avec une adresse qui existe vraiment)")
    elif "p=none" in dmarc[0].replace(" ", ""):
        print("  - DMARC en p=none : passer en p=quarantine une fois SPF et DKIM vérifiés (rua=mailto:bonjour@…).")
    if not dkim: print("  - DKIM : activer la signature chez OVH (Web Cloud > E-mails > domaine > DKIM) puis vérifier les CNAME ovhmo*._domainkey.")
    print("  - Les enregistrements mail ne sont jamais modifiés par `vercel` ni `welcome`.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    for name in ("list", "backup", "check", "mail"):
        p = sp.add_parser(name); p.add_argument("domain")
    p = sp.add_parser("welcome"); p.add_argument("domain"); p.add_argument("--delete", action="store_true")
    p = sp.add_parser("vercel"); p.add_argument("domain"); p.add_argument("--cname"); p.add_argument("--apply", action="store_true")
    p = sp.add_parser("set"); p.add_argument("domain"); p.add_argument("sub"); p.add_argument("type"); p.add_argument("target")
    p.add_argument("--ttl", type=int, default=None); p.add_argument("--force-mail", action="store_true")
    p = sp.add_parser("delete"); p.add_argument("domain"); p.add_argument("id", type=int); p.add_argument("--force-mail", action="store_true")
    a = ap.parse_args()
    a.domain = a.domain.lower().strip().rstrip(".")
    if a.domain.startswith("www."): a.domain = a.domain[4:]
    o = OVH(a.domain)
    {"list": cmd_list, "backup": cmd_backup, "welcome": cmd_welcome, "vercel": cmd_vercel, "set": cmd_set,
     "delete": cmd_delete, "check": cmd_check, "mail": cmd_mail}[a.cmd](o, a)


if __name__ == "__main__":
    main()
