import asyncio
import json
import random
import time
import traceback
import requests
from config import settings

MAX_RETRIES = 3

_PLACEHOLDER_PATTERNS = (
    "your-workspace", "your_databricks", "placeholder",
    "example.com", "<", ">",
)

_LOW_SIGNAL_PATTERNS = (
    "would you like",
    "please clarify",
    "clarify",
    "no data",
    "not available",
    "no records",
    "outside my scope",
    "out of scope",
    "cannot be calculated",
    "cannot be determined",
)


def _looks_real(value: str) -> bool:
    if not value or len(value) < 6:
        return False
    return not any(p in value.lower() for p in _PLACEHOLDER_PATTERNS)


class GenieService:
    def __init__(self, host: str = None, token: str = None, space_id: str = None):
        self.host = host or settings.databricks_host
        self.token = token or settings.databricks_token
        self.space_id = space_id or settings.genie_space_id
        real = _looks_real(self.host) and _looks_real(self.token)
        self._use_demo = settings.demo_mode or not real
        if self._use_demo:
            print("[GenieService] Demo mode — Databricks not configured. Queries will return no data.")
        else:
            print(f"[GenieService] Databricks @ {self.host} | space={self.space_id}")

    # ── Core Genie call ───────────────────────────────────────────────────────

    def _sync_ask_once(self, question: str) -> dict:
        if self._use_demo:
            return {
                "question": question,
                "text_response": (
                    "Databricks Genie is not configured. "
                    "Set DATABRICKS_HOST and DATABRICKS_TOKEN in backend/.env to query real data."
                ),
                "sql_query": None,
                "data_columns": [],
                "data_rows": [],
                "status": "DEMO",
                "error": None,
            }

        try:
            from databricks.sdk import WorkspaceClient

            # Explicit credentials — avoids shared os.environ race in threads
            w = WorkspaceClient(host=self.host, token=self.token)

            print(f"[Genie] Asking: {question[:80]}...")
            message = w.genie.start_conversation_and_wait(
                space_id=self.space_id, content=question
            )
            msg = w.genie.get_message(
                space_id=self.space_id,
                conversation_id=message.conversation_id,
                message_id=message.message_id,
            )
            print(f"[Genie] Status: {msg.status}")

            result = {
                "question": question,
                "text_response": "",
                "sql_query": None,
                "data_columns": [],
                "data_rows": [],
                "status": str(msg.status),
                "error": None,
            }

            if msg.attachments:
                for att in msg.attachments:
                    if getattr(att, "text", None) and getattr(att.text, "content", None):
                        result["text_response"] = att.text.content
                    if getattr(att, "query", None) and getattr(att.query, "query", None):
                        result["sql_query"] = att.query.query

                    is_query_attachment = bool(getattr(att, "query", None))
                    att_id = (
                        getattr(att, "attachment_id", None)
                        or getattr(att, "id", None)
                    )
                    if is_query_attachment and att_id:
                        try:
                            qr = w.genie.get_message_attachment_query_result(
                                space_id=self.space_id,
                                conversation_id=message.conversation_id,
                                message_id=message.message_id,
                                attachment_id=att_id,
                            )
                            stmt = qr.statement_response
                            if stmt and stmt.manifest and stmt.manifest.schema:
                                result["data_columns"] = [
                                    c.name for c in stmt.manifest.schema.columns
                                ]
                            if stmt and stmt.result:
                                if stmt.result.data_array:
                                    result["data_rows"] = stmt.result.data_array
                                elif stmt.result.external_links:
                                    for link in stmt.result.external_links:
                                        if getattr(link, "external_link", None):
                                            resp = requests.get(link.external_link)
                                            if resp.ok:
                                                try:
                                                    result["data_rows"] = json.loads(resp.text)
                                                except Exception:
                                                    result["data_rows"] = [[resp.text[:2000]]]
                        except Exception as qe:
                            print(f"[Genie] Could not fetch query result for attachment: {qe}")

            if not result["text_response"] and not result["data_rows"]:
                result["status"] = "FAILED"
                result["error"] = "Genie returned no text and no data rows"
                print(f"[Genie] Empty response for: {question[:60]}")

            return result

        except Exception as e:
            tb_str = traceback.format_exc()
            print(f"[Genie] ERROR for '{question[:60]}':\n{tb_str}")
            return {
                "question": question,
                "text_response": "",
                "sql_query": None,
                "data_columns": [],
                "data_rows": [],
                "status": "FAILED",
                "error": f"{type(e).__name__}: {e}",
                "traceback": tb_str,
            }

    # ── Schema discovery ──────────────────────────────────────────────────────

    async def discover_schema(self) -> str:
        """
        Ask Genie to describe available data and provide concrete table previews
        (headers + first 2 rows) so the planner can ground question selection
        in real observed values.
        """
        if self._use_demo:
            return ""

        inventory_question = (
            "Give me a complete data inventory for this analytics space. Include:\n"
            "1. All dataset and table names you have access to\n"
            "2. Every column in each table — its name, data type, and what it measures\n"
            "3. Example values for important categorical columns\n"
            "4. Scale/range of key numeric columns\n"
            "5. Time periods covered and useful grouping/filter dimensions\n\n"
            "Keep the response concise but specific."
        )
        preview_question = (
            "For each major table/dataset in this analytics space, provide:\n"
            "- dataset/table name\n"
            "- header (column names)\n"
            "- first 2 sample rows\n\n"
            "Return plain text. Do not skip major tables."
        )

        parts: list[str] = []
        for section, question in (
            ("Inventory", inventory_question),
            ("Header + First 2 Rows Preview", preview_question),
        ):
            result = await self.ask(question, max_retries=2)
            status = result.get("status", "")
            if status in ("FAILED",):
                parts.append(f"[{section}] unavailable (status={status})")
                continue
            if result.get("text_response"):
                parts.append(f"[{section}]\n{result['text_response']}")
            if result.get("data_columns") and result.get("data_rows"):
                tabular_preview = _format_table_preview(
                    result["data_columns"],
                    result["data_rows"],
                    row_limit=2,
                )
                if tabular_preview:
                    parts.append(f"[{section} - Tabular Preview]\n{tabular_preview}")

        schema_text = "\n\n".join(parts).strip()
        if len(schema_text) > 20000:
            schema_text = schema_text[:20000].rstrip() + "\n...[truncated schema preview]"
        if schema_text:
            print(f"[Genie] Schema discovered: {len(schema_text)} chars")
        else:
            print("[Genie] Schema discovery returned no content")
        return schema_text

    # ── Public async API ──────────────────────────────────────────────────────

    async def ask(self, question: str, max_retries: int = MAX_RETRIES) -> dict:
        """Async ask with exponential-backoff retry on FAILED or low-signal responses."""
        last_result: dict = {}
        base_question = question.strip()
        for attempt in range(max_retries):
            query_to_send = base_question if attempt == 0 else self._rephrase_for_data_recovery(base_question)
            result = await asyncio.to_thread(self._sync_ask_once, query_to_send)
            last_result = result
            if result.get("status") != "FAILED" and not self._is_low_signal_response(result):
                return result

            if attempt < max_retries - 1:
                delay = (2 ** attempt) + random.uniform(0, 1)
                print(
                    f"[Genie] Query low-signal/failed (attempt {attempt+1}/{max_retries}), "
                    f"retrying in {delay:.1f}s: {base_question[:60]}"
                )
                await asyncio.sleep(delay)

        last_result["error"] = (
            f"[After {max_retries} attempts] "
            + (last_result.get("error") or "Unknown error")
        )
        return last_result

    def _is_low_signal_response(self, result: dict) -> bool:
        rows = result.get("data_rows", []) or []
        text = (result.get("text_response") or "").strip().lower()
        if rows:
            return False
        if not text:
            return True
        return any(p in text for p in _LOW_SIGNAL_PATTERNS)

    def _rephrase_for_data_recovery(self, question: str) -> str:
        return (
            f"{question}\n\n"
            "Important response instructions:\n"
            "- Answer directly using currently available data.\n"
            "- If exact event-name match is unavailable, use the closest matching event/program and state the matched value.\n"
            "- If one requested metric is missing, substitute with the closest available measurable metric.\n"
            "- Do not ask clarifying questions."
        )

    async def batch_ask(
        self,
        questions: list[str],
        progress_callback=None,
    ) -> list[dict]:
        results: list[dict | None] = [None] * len(questions)

        async def _ask_one(idx: int, question: str):
            result = await self.ask(question)
            results[idx] = result
            if progress_callback:
                await progress_callback(idx, question, result)

        await asyncio.gather(*[_ask_one(i, q) for i, q in enumerate(questions)])
        return results  # type: ignore[return-value]

    @property
    def is_demo(self) -> bool:
        return self._use_demo


# ── Result formatting ─────────────────────────────────────────────────────────

def _format_table_preview(columns: list, rows: list, row_limit: int = 2) -> str:
    if not columns:
        return ""
    cols = [str(c) for c in columns]
    lines = [" | ".join(cols), " | ".join(["---"] * len(cols))]
    for row in (rows or [])[: max(0, row_limit)]:
        values = []
        for i in range(len(cols)):
            val = row[i] if i < len(row) else None
            values.append(str(val) if val is not None else "NULL")
        lines.append(" | ".join(values))
    return "\n".join(lines)


def format_result_as_table(result: dict) -> str:
    parts = [f"### Q: {result['question']}"]
    status = result.get("status", "")
    if status == "FAILED":
        parts.append(f"**[QUERY FAILED]** {result.get('error', 'Unknown')}")
        return "\n".join(parts)
    if status == "DEMO":
        parts.append("**[DEMO MODE — no data]** Configure Databricks to see real results.")
        return "\n".join(parts)
    cols = result.get("data_columns", [])
    rows = result.get("data_rows", [])
    if cols and rows:
        parts.append("Source-of-truth: use tabular values below for all numeric conclusions.")
        parts.append(f"Data ({len(rows)} rows, {len(cols)} columns):")
        parts.append(" | ".join(str(c) for c in cols))
        parts.append(" | ".join(["---"] * len(cols)))
        for row in rows[:100]:
            parts.append(" | ".join(str(v) if v is not None else "NULL" for v in row))
        if len(rows) > 100:
            parts.append(f"... and {len(rows) - 100} more rows")
        snapshot = _numeric_snapshot(cols, rows)
        if snapshot:
            parts.append("Numeric snapshot (derived from returned rows):")
            for k, v in snapshot:
                parts.append(f"- {k}: {v}")
    elif result.get("text_response"):
        # Fall back to text-only response when no rows are available.
        parts.append(f"Response: {result['text_response']}")
    else:
        parts.append("**[NO DATA RETURNED]**")
    return "\n".join(parts)


def _numeric_snapshot(cols: list, rows: list) -> list[tuple[str, str]]:
    snapshots: list[tuple[str, str]] = []
    for col_idx, col_name in enumerate(cols):
        numeric_vals: list[float] = []
        for row in rows:
            if col_idx >= len(row):
                continue
            val = row[col_idx]
            if val is None:
                continue
            s = str(val).replace(",", "").strip()
            try:
                numeric_vals.append(float(s))
            except Exception:
                continue
        if not numeric_vals:
            continue
        total = sum(numeric_vals)
        max_v = max(numeric_vals)
        min_v = min(numeric_vals)
        snapshots.append((str(col_name), f"sum={total:,.2f}, max={max_v:,.2f}, min={min_v:,.2f}"))
    return snapshots[:6]


def build_data_packet(results: list[dict]) -> tuple[str, dict]:
    sections, failed = [], []
    for i, r in enumerate(results):
        sections.append(format_result_as_table(r))
        status = r.get("status", "") if r else "MISSING"
        if status in ("FAILED", "DEMO", "MISSING"):
            failed.append(i + 1)
    data_packet = "\n\n".join(sections)
    stats = {
        "total_queries": len(results),
        "succeeded": len(results) - len(failed),
        "failed": len(failed),
        "failed_indices": failed,
        "data_packet_chars": len(data_packet),
        "data_packet_tokens_est": len(data_packet) // 4,
    }
    return data_packet, stats
