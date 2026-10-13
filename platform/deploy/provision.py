#!/usr/bin/env python3
"""Create (or update) the licensing platform on Railway and point player.oncue.cy at it.

    RAILWAY_API_TOKEN=...  CLOUDFLARE_API_TOKEN=...  PLATFORM_ADMIN_PASSWORD=...  python platform/deploy/provision.py
    python platform/deploy/provision.py --dry-run      # show the plan without changing anything

What it does, step by step (each step is idempotent, so it can be re-run):
  1. finds the Railway project (default: the barpi project) and its production environment
  2. creates a service named "player" from github.com/giannakkas/barpi, branch main, if missing
  3. sets its root directory to platform/ and its config file to platform/railway.json
  4. sets the variables: DATABASE_URL (the project's Postgres, schema "licensing"),
     PLATFORM_ADMIN_PASSWORD, PLATFORM_SESSION_SECRET, LICENSE_SIGNING_SECRET, PUBLIC_URL
  5. adds the custom domain player.oncue.cy and reads back the DNS records Railway wants
  6. creates those records in the Cloudflare zone oncue.cy (CNAME with the proxy OFF, plus
     the _railway-verify TXT: see the README's "Cloudflare DNS" section for why both matter)
  7. triggers a deployment

Environment:
  RAILWAY_API_TOKEN        account or team token (Railway → Account settings → Tokens)
  CLOUDFLARE_API_TOKEN     token with Zone.DNS edit on oncue.cy
  PLATFORM_ADMIN_PASSWORD  the password for the platform's admin screens
  PLATFORM_SESSION_SECRET  optional; generated and kept on Railway if absent
  LICENSE_SIGNING_SECRET   optional; generated and kept on Railway if absent
  RAILWAY_PROJECT_ID       optional (default: barpi's project id)
  RAILWAY_ENVIRONMENT      optional (default: production)
  DOMAIN                   optional (default: player.oncue.cy)

The Railway part uses Railway's public GraphQL API; field names follow its published schema
but were written without a token to try them against, so if a mutation is refused the error
is printed verbatim and the remaining steps still run where they can.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from urllib import error, request

RAILWAY_API = "https://backboard.railway.com/graphql/v2"
CF_API = "https://api.cloudflare.com/client/v4"
DEFAULT_PROJECT = "c7e3e820-6bd0-49be-9a75-7bf07e971192"
REPO = "giannakkas/barpi"
BRANCH = "main"
SERVICE = "player"


def call(url: str, token: str, payload: dict | None = None, method: str = "POST") -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise SystemExit(f"HTTP {exc.code} from {url}: {body[:800]}") from exc


def gql(token: str, query: str, variables: dict) -> dict:
    out = call(RAILWAY_API, token, {"query": query, "variables": variables})
    if out.get("errors"):
        raise RuntimeError(json.dumps(out["errors"], indent=2))
    return out["data"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    env = os.environ
    project_id = env.get("RAILWAY_PROJECT_ID", DEFAULT_PROJECT)
    env_name = env.get("RAILWAY_ENVIRONMENT", "production")
    domain = env.get("DOMAIN", "player.oncue.cy")
    rtoken, cftoken = env.get("RAILWAY_API_TOKEN"), env.get("CLOUDFLARE_API_TOKEN")
    admin_pw = env.get("PLATFORM_ADMIN_PASSWORD")
    missing = [n for n, v in (("RAILWAY_API_TOKEN", rtoken), ("CLOUDFLARE_API_TOKEN", cftoken),
                              ("PLATFORM_ADMIN_PASSWORD", admin_pw)) if not v]
    if missing and not args.dry_run:
        print("missing:", ", ".join(missing)); return 2
    variables = {
        "DATABASE_URL": "${{Postgres.DATABASE_URL}}?schema=licensing",
        "PLATFORM_ADMIN_PASSWORD": admin_pw or "<set>",
        "PLATFORM_SESSION_SECRET": env.get("PLATFORM_SESSION_SECRET") or secrets.token_urlsafe(32),
        "LICENSE_SIGNING_SECRET": env.get("LICENSE_SIGNING_SECRET") or secrets.token_urlsafe(32),
        "PUBLIC_URL": f"https://{domain}",
    }
    print(f"project {project_id}, environment {env_name}, service {SERVICE}, repo {REPO}@{BRANCH}, domain {domain}")
    if args.dry_run:
        print("variables:", json.dumps({k: ('<secret>' if 'SECRET' in k or 'PASSWORD' in k else v) for k, v in variables.items()}, indent=2))
        print("dry run: nothing changed"); return 0

    # 1. project, environment, existing services
    data = gql(rtoken, """query($id: String!) { project(id: $id) { name
        environments { edges { node { id name } } } services { edges { node { id name } } } } }""", {"id": project_id})
    project = data["project"]
    envs = {e["node"]["name"]: e["node"]["id"] for e in project["environments"]["edges"]}
    services = {s["node"]["name"]: s["node"]["id"] for s in project["services"]["edges"]}
    if env_name not in envs:
        raise SystemExit(f"environment {env_name!r} not found; have {list(envs)}")
    env_id = envs[env_name]
    print(f"1. project {project['name']!r}: services {list(services)}")
    if "Postgres" not in services:
        print("   warning: no service named 'Postgres'; DATABASE_URL reference will not resolve")

    # 2. the service
    if SERVICE in services:
        service_id = services[SERVICE]; print(f"2. service {SERVICE!r} exists ({service_id})")
    else:
        data = gql(rtoken, """mutation($input: ServiceCreateInput!) { serviceCreate(input: $input) { id name } }""",
                   {"input": {"projectId": project_id, "name": SERVICE, "source": {"repo": REPO}, "branch": BRANCH}})
        service_id = data["serviceCreate"]["id"]; print(f"2. created service {SERVICE!r} ({service_id})")

    # 3. root directory + config file
    gql(rtoken, """mutation($serviceId: String!, $environmentId: String!, $input: ServiceInstanceUpdateInput!) {
        serviceInstanceUpdate(serviceId: $serviceId, environmentId: $environmentId, input: $input) }""",
        {"serviceId": service_id, "environmentId": env_id,
         "input": {"rootDirectory": "platform", "railwayConfigFile": "platform/railway.json", "branch": BRANCH}})
    print("3. root directory platform/, config platform/railway.json")

    # 4. variables
    gql(rtoken, """mutation($input: VariableCollectionUpsertInput!) { variableCollectionUpsert(input: $input) }""",
        {"input": {"projectId": project_id, "environmentId": env_id, "serviceId": service_id, "variables": variables}})
    print("4. variables set:", ", ".join(variables))

    # 5. custom domain
    data = gql(rtoken, """query($projectId: String!, $environmentId: String!, $serviceId: String!) {
        domains(projectId: $projectId, environmentId: $environmentId, serviceId: $serviceId) {
          customDomains { id domain status { dnsRecords { hostlabel fqdn recordType requiredValue currentValue status } } } } }""",
        {"projectId": project_id, "environmentId": env_id, "serviceId": service_id})
    existing = [d for d in data["domains"]["customDomains"] if d["domain"] == domain]
    if existing:
        cd = existing[0]; print(f"5. domain {domain} already attached")
    else:
        data = gql(rtoken, """mutation($input: CustomDomainCreateInput!) { customDomainCreate(input: $input) {
            id domain status { dnsRecords { hostlabel fqdn recordType requiredValue currentValue status } } } }""",
            {"input": {"projectId": project_id, "environmentId": env_id, "serviceId": service_id, "domain": domain, "targetPort": 8080}})
        cd = data["customDomainCreate"]; print(f"5. domain {domain} attached")
    records = cd["status"]["dnsRecords"]
    for r in records:
        print(f"   needs {r['recordType']} {r['fqdn']} -> {r['requiredValue']} ({r['status']})")

    # 6. Cloudflare
    zone_name = ".".join(domain.split(".")[-2:])
    zones = call(f"{CF_API}/zones?name={zone_name}", cftoken, method="GET")["result"]
    if not zones:
        raise SystemExit(f"Cloudflare zone {zone_name} not found with this token")
    zone_id = zones[0]["id"]
    for r in records:
        name = r["fqdn"]; rtype = r["recordType"]; content = r["requiredValue"]
        found = call(f"{CF_API}/zones/{zone_id}/dns_records?type={rtype}&name={name}", cftoken, method="GET")["result"]
        body = {"type": rtype, "name": name, "content": content, "ttl": 1, "proxied": False}
        if found:
            call(f"{CF_API}/zones/{zone_id}/dns_records/{found[0]['id']}", cftoken, body, method="PUT")
            print(f"6. updated {rtype} {name} -> {content}")
        else:
            call(f"{CF_API}/zones/{zone_id}/dns_records", cftoken, body)
            print(f"6. created {rtype} {name} -> {content}")

    # 7. deploy
    gql(rtoken, """mutation($serviceId: String!, $environmentId: String!) {
        serviceInstanceDeploy(serviceId: $serviceId, environmentId: $environmentId) }""",
        {"serviceId": service_id, "environmentId": env_id})
    print(f"7. deployment triggered. Certificate issuance takes a few minutes once the TXT is live: https://{domain}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
