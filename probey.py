#!/usr/bin/env python3
import argparse
import asyncio
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Set, Dict, Any, Optional

import httpx


def read_hosts_file(path: str) -> Set[str]:
    p = Path(path).expanduser()
    hosts: Set[str] = set()
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # If user pastes full URLs, normalize to hostname
        line = line.replace("http://", "").replace("https://", "").split("/")[0]
        if line:
            hosts.add(line)
    return hosts


def run_subfinder(domain: str) -> Set[str]:
    if shutil.which("subfinder") is None:
        return set()
    p = subprocess.run(
        ["subfinder", "-d", domain, "-silent"],
        capture_output=True,
        text=True,
        check=False,
    )
    return {ln.strip() for ln in (p.stdout or "").splitlines() if ln.strip()}


async def probe_url(client: httpx.AsyncClient, url: str) -> Dict[str, Any]:
    try:
        r = await client.get(url, follow_redirects=True)
        return {
            "url": url,
            "final_url": str(r.url),
            "status_code": r.status_code,
            "server": r.headers.get("server"),
            "content_type": r.headers.get("content-type"),
        }
    except (httpx.RequestError, httpx.TimeoutException) as e:
        return {"url": url, "error": f"{type(e).__name__}: {e}"}


async def probe_host(host: str, sem: asyncio.Semaphore) -> Dict[str, Any]:
    async with sem:
        timeout = httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0)
        async with httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": "mini-probe/1.1"},
        ) as client:
            results = await asyncio.gather(
                probe_url(client, f"https://{host}"),
                
            )
    return {"host": host, "probes": results}


async def run(domain: Optional[str], hosts_file: Optional[str], concurrency: int) -> Dict[str, Any]:
    hosts: Set[str] = set()

    if hosts_file:
        hosts = read_hosts_file(hosts_file)
    elif domain:
        hosts |= run_subfinder(domain)
        hosts.add(domain)

    sem = asyncio.Semaphore(concurrency)

    tasks = [probe_host(h, sem) for h in sorted(hosts)]
    host_results: List[Dict[str, Any]] = []

    batch_size = 200
    for i in range(0, len(tasks), batch_size):
        host_results.extend(await asyncio.gather(*tasks[i : i + batch_size]))

    return {
        "root_domain": domain,
        "hosts_file": hosts_file,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "host_count": len(hosts),
        "hosts": host_results,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Minimal host probe (http/https) to JSON")
    ap.add_argument("--domain", help="Root domain, e.g. example.com (used if no --hosts-file)")
    ap.add_argument("--hosts-file", help="File with hosts/URLs, one per line (overrides --domain)")
    ap.add_argument("--out", default="results.json", help="Output JSON file")
    ap.add_argument("--concurrency", type=int, default=40, help="Concurrent host probes")
    args = ap.parse_args()

    if not args.hosts_file and not args.domain:
        raise SystemExit("Provide --hosts-file or --domain")

    data = asyncio.run(run(args.domain.strip() if args.domain else None, args.hosts_file, args.concurrency))

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"Wrote {args.out} ({data['host_count']} hosts)")


if __name__ == "__main__":
    main()
