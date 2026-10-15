"""Day37 B10: immutable tenant-bound result receipts, reports and private exports.

Internal isolated service only. Not a hosted customer dashboard; all report
publishing is trusted-only. No user can grant itself research status or results.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import io
import json
import re
import secrets
import zipfile

from aidy.strategy_lab_tenant_vault import AccessDenied, TenantVault, _canonical, _open_db

HEX32 = re.compile(r"^[0-9a-f]{32}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
MAX_FILE_BYTES = 2_000_000
KINDS = {"json": "application/json", "csv": "text/csv", "pdf": "application/pdf"}
STAGES = ("RESEARCH_QUEUED", "RESEARCH_RUNNING", "RESEARCH_BLOCKED",
          "SYNTHETIC_ACCEPTANCE_ONLY", "RESEARCH_FAILED")
TRANSITIONS = {
    "RESEARCH_QUEUED": {"RESEARCH_RUNNING", "RESEARCH_BLOCKED", "RESEARCH_FAILED"},
    "RESEARCH_RUNNING": {"RESEARCH_BLOCKED", "RESEARCH_FAILED", "SYNTHETIC_ACCEPTANCE_ONLY"},
    "RESEARCH_BLOCKED": set(),
    "RESEARCH_FAILED": set(),
    "SYNTHETIC_ACCEPTANCE_ONLY": set(),
}


class ResultRejected(ValueError):
    """Untrusted or inconsistent result/status packet."""


class CustomerResults:
    def __init__(self, vault: TenantVault, *, publisher_key: bytes):
        if not isinstance(publisher_key, bytes) or len(publisher_key) < 32:
            raise ValueError("Separate 32-byte trusted publisher secret required")
        if publisher_key in (vault._provision, vault._pepper):
            raise ValueError("Independent publisher secret required")
        self._vault = vault
        self._key = publisher_key
        with _open_db(vault._path) as con:
            con.executescript("""
            CREATE TABLE IF NOT EXISTS customer_jobs(
                id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id),
                draft_id TEXT NOT NULL REFERENCES drafts(id),
                source_sha256 TEXT NOT NULL, stage TEXT NOT NULL,
                version INTEGER NOT NULL, created INTEGER NOT NULL,
                UNIQUE(tenant_id,draft_id,version));
            CREATE INDEX IF NOT EXISTS customer_jobs_tenant ON customer_jobs(tenant_id,id);
            CREATE TABLE IF NOT EXISTS customer_events(
                job_id TEXT NOT NULL REFERENCES customer_jobs(id),
                seq INTEGER NOT NULL, stage TEXT NOT NULL,
                event_digest TEXT NOT NULL, created INTEGER NOT NULL,
                PRIMARY KEY(job_id,seq), UNIQUE(job_id,event_digest));
            CREATE TABLE IF NOT EXISTS customer_artifacts(
                id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES customer_jobs(id),
                tenant_id TEXT NOT NULL REFERENCES tenants(id),
                kind TEXT NOT NULL, name TEXT NOT NULL,
                payload_hash TEXT NOT NULL, ciphertext BLOB NOT NULL,
                created INTEGER NOT NULL, UNIQUE(job_id,name));
            CREATE INDEX IF NOT EXISTS customer_artifacts_tenant
                ON customer_artifacts(tenant_id,id);
            """)

    def _publisher(self, key: bytes) -> None:
        if not isinstance(key, bytes) or not hmac.compare_digest(key, self._key):
            raise AccessDenied("Access denied")

    def create_job(self, *, publisher_key: bytes, tenant_id: str,
                   draft_id: str, source_sha256: str) -> str:
        """Internal scheduler only; no client method to claim a result."""
        self._publisher(publisher_key)
        if (not isinstance(tenant_id, str) or not HEX32.fullmatch(tenant_id)
                or not isinstance(draft_id, str) or not HEX32.fullmatch(draft_id)
                or not isinstance(source_sha256, str)
                or not HEX64.fullmatch(source_sha256)):
            raise ResultRejected("Invalid job origin")
        with _open_db(self._vault._path) as con:
            con.execute("BEGIN IMMEDIATE")
            source = con.execute(
                "SELECT source_sha256 FROM drafts WHERE id=? AND tenant_id=? AND expires>?",
                (draft_id, tenant_id, int(self._vault._clock())),
            ).fetchone()
            if not source or source["source_sha256"] != source_sha256:
                raise ResultRejected("Source not authenticated to tenant")
            row = con.execute(
                "SELECT COALESCE(MAX(version),0)+1 AS version FROM customer_jobs "
                "WHERE tenant_id=? AND draft_id=?", (tenant_id, draft_id),
            ).fetchone()
            version = row["version"]
            job_id = secrets.token_hex(16)
            now = int(self._vault._clock())
            con.execute(
                "INSERT INTO customer_jobs VALUES(?,?,?,?,?,?,?)",
                (job_id, tenant_id, draft_id, source_sha256,
                 "RESEARCH_QUEUED", version, now),
            )
            event = hashlib.sha256(_canonical(
                {"job": job_id, "stage": "RESEARCH_QUEUED", "seq": 1}
            )).hexdigest()
            con.execute("INSERT INTO customer_events VALUES(?,?,?,?,?)",
                        (job_id, 1, "RESEARCH_QUEUED", event, now))
            con.commit()
        return job_id

    def transition(self, *, publisher_key: bytes, job_id: str, new_stage: str,
                   evidence_sha256: str) -> None:
        self._publisher(publisher_key)
        if (not isinstance(job_id, str) or not HEX32.fullmatch(job_id)
                or new_stage not in STAGES
                or not isinstance(evidence_sha256, str)
                or not HEX64.fullmatch(evidence_sha256)):
            raise ResultRejected("Invalid status transition")
        with _open_db(self._vault._path) as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute(
                "SELECT stage FROM customer_jobs WHERE id=?", (job_id,)
            ).fetchone()
            if not row:
                raise ResultRejected("Unknown internal job")
            if new_stage not in TRANSITIONS[row["stage"]]:
                raise ResultRejected("Invalid or backwards status transition")
            seq = con.execute(
                "SELECT MAX(seq)+1 FROM customer_events WHERE job_id=?", (job_id,)
            ).fetchone()[0]
            event = hashlib.sha256(_canonical({
                "job": job_id, "stage": new_stage,
                "seq": seq, "evidence_sha256": evidence_sha256,
            })).hexdigest()
            con.execute("UPDATE customer_jobs SET stage=? WHERE id=?",
                        (new_stage, job_id))
            con.execute("INSERT INTO customer_events VALUES(?,?,?,?,?)",
                        (job_id, seq, new_stage, event, int(self._vault._clock())))
            con.commit()

    def publish_artifact(self, *, publisher_key: bytes, job_id: str,
                         filename: str, kind: str, payload: bytes) -> str:
        """Publish only synthetic/blocked test evidence until independent qualification."""
        self._publisher(publisher_key)
        if (not isinstance(job_id, str) or not HEX32.fullmatch(job_id)
                or kind not in KINDS or not isinstance(payload, bytes)
                or not 1 <= len(payload) <= MAX_FILE_BYTES
                or not isinstance(filename, str)
                or not re.fullmatch(r"[A-Za-z0-9_.-]{3,120}", filename)
                or filename.startswith(".") or ".." in filename
                or not filename.endswith("." + kind)):
            raise ResultRejected("Invalid file")
        if kind == "pdf" and not payload.startswith(b"%PDF-"):
            raise ResultRejected("Invalid PDF content")
        if kind == "json":
            try:
                json.loads(payload)
            except (UnicodeDecodeError, ValueError) as exc:
                raise ResultRejected("Invalid JSON content") from exc
        if kind == "csv":
            try:
                payload.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ResultRejected("Invalid CSV encoding") from exc
        with _open_db(self._vault._path) as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute(
                "SELECT tenant_id,stage FROM customer_jobs WHERE id=?",
                (job_id,),
            ).fetchone()
            if not row or row["stage"] not in {
                    "RESEARCH_BLOCKED", "RESEARCH_FAILED", "SYNTHETIC_ACCEPTANCE_ONLY"}:
                raise ResultRejected("Real result qualification not established")
            tenant = row["tenant_id"]
            ident = secrets.token_hex(16)
            aad = f"aidy.day37|{tenant}|{ident}|{kind}".encode()
            nonce = secrets.token_bytes(12)
            ciphertext = nonce + self._vault._aes.encrypt(nonce, payload, aad)
            con.execute(
                "INSERT INTO customer_artifacts VALUES(?,?,?,?,?,?,?,?)",
                (ident, job_id, tenant, kind, filename,
                 hashlib.sha256(payload).hexdigest(), ciphertext,
                 int(self._vault._clock())),
            )
            con.commit()
        return ident

    def list_jobs(self, token: str) -> list[dict]:
        with _open_db(self._vault._path) as con:
            _, tenant = self._vault._principal(con, token)
            jobs = con.execute(
                "SELECT id,draft_id,stage,version,created,source_sha256 "
                "FROM customer_jobs WHERE tenant_id=? ORDER BY created,draft_id,version,id",
                (tenant,),
            ).fetchall()
            return [dict(j) for j in jobs]

    def job_history(self, token: str, job_id: str) -> list[dict]:
        if not isinstance(job_id, str) or not HEX32.fullmatch(job_id):
            raise AccessDenied("Access denied")
        with _open_db(self._vault._path) as con:
            _, tenant = self._vault._principal(con, token)
            row = con.execute("SELECT 1 FROM customer_jobs WHERE id=? AND tenant_id=?",
                              (job_id, tenant)).fetchone()
            if not row:
                raise AccessDenied("Access denied")
            return [dict(x) for x in con.execute(
                "SELECT seq,stage,event_digest,created FROM customer_events "
                "WHERE job_id=? ORDER BY seq", (job_id,),
            ).fetchall()]

    def list_artifacts(self, token: str, job_id: str) -> list[dict]:
        if not isinstance(job_id, str) or not HEX32.fullmatch(job_id):
            raise AccessDenied("Access denied")
        with _open_db(self._vault._path) as con:
            _, tenant = self._vault._principal(con, token)
            row = con.execute("SELECT 1 FROM customer_jobs WHERE id=? AND tenant_id=?",
                              (job_id, tenant)).fetchone()
            if not row:
                raise AccessDenied("Access denied")
            return [dict(x) for x in con.execute(
                "SELECT id,kind,name,payload_hash,created FROM customer_artifacts "
                "WHERE job_id=? AND tenant_id=? ORDER BY name",
                (job_id, tenant),
            ).fetchall()]

    def download(self, token: str, artifact_id: str) -> tuple[str, bytes]:
        if not isinstance(artifact_id, str) or not HEX32.fullmatch(artifact_id):
            raise AccessDenied("Access denied")
        with _open_db(self._vault._path) as con:
            _, tenant = self._vault._principal(con, token)
            row = con.execute(
                "SELECT kind,name,payload_hash,ciphertext FROM customer_artifacts "
                "WHERE id=? AND tenant_id=?", (artifact_id, tenant),
            ).fetchone()
        if not row:
            raise AccessDenied("Access denied")
        aad = f"aidy.day37|{tenant}|{artifact_id}|{row['kind']}".encode()
        from cryptography.exceptions import InvalidTag

        try:
            raw = self._vault._aes.decrypt(
                row["ciphertext"][:12], row["ciphertext"][12:], aad
            )
        except (ValueError, InvalidTag) as exc:
            raise AccessDenied("Access denied") from exc
        if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), row["payload_hash"]):
            raise AccessDenied("Access denied")
        return row["name"], raw

    def offline_dashboard(self, token: str) -> str:
        """Static own-tenant snapshot: no server-side customer file link exposure."""
        jobs = self.list_jobs(token)
        rows = []
        for job in jobs:
            rows.append("<tr><td>" + html.escape(job["id"]) + "</td><td>"
                        + html.escape(job["stage"]) + "</td><td>"
                        + str(job["version"]) + "</td><td>"
                        + str(len(self.list_artifacts(token, job["id"])))
                        + " authorised downloads</td></tr>")
        body = "".join(rows) if rows else "<tr><td colspan='4'>No reports yet</td></tr>"
        return (
            "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<title>GoldThinker — private strategy results preview</title>"
            "<style>body{font:16px system-ui;background:#101216;color:#e5e6e8;"
            "max-width:960px;margin:4rem auto;padding:1rem}"
            "h1{color:#e3b94b}table{border-collapse:collapse;width:100%}"
            "td,th{border-bottom:1px solid #353638;padding:1rem;text-align:left}"
            "</style></head><body><h1>GoldThinker — My research</h1>"
            "<p>Private offline preview. All downloads require a current "
            "server-authenticated tenant session. No trading has been enabled.</p>"
            "<table><thead><tr><th>Job</th><th>Stage</th><th>Version</th>"
            "<th>Files</th></tr></thead><tbody>" + body
            + "</tbody></table></body></html>"
        )

    def export_job_zip(self, token: str, job_id: str) -> bytes:
        history = self.job_history(token, job_id)
        files = self.list_artifacts(token, job_id)
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            items: list[tuple[str, bytes]] = [
                ("job_history.json", _canonical(history)),
            ]
            for item in files:
                name, contents = self.download(token, item["id"])
                items.append((name, contents))
            for name, payload in sorted(items):
                info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o600 << 16
                archive.writestr(info, payload)
        return output.getvalue()
