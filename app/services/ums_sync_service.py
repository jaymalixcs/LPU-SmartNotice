"""Incremental Synchronization Service for UMS Announcements.

Coordinates fetching, deduplicating, revising, extracting metadata with Gemini,
and upserting into SQLite and ChromaDB vector index without modifying historical datasets.
"""

import json
import threading
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.core.database import get_db_connection
from app.core.logging_config import logger
from app.models.announcement import RawAnnouncement
from app.services.embedding_service import EmbeddingService
from app.services.extraction_service import ExtractionService
from app.services.ums_source import UMSSourceAdapter
from app.services.vector_store_service import VectorStoreService


class UMSSyncService:
    """Manages incremental synchronization of UMS announcements into SmartNotice."""

    _sync_lock = threading.Lock()

    def __init__(
        self,
        source_adapter: Optional[UMSSourceAdapter] = None,
        extraction_service: Optional[ExtractionService] = None,
        vector_store: Optional[VectorStoreService] = None,
        embedding_service: Optional[EmbeddingService] = None,
    ):
        self.source = source_adapter or UMSSourceAdapter()
        self.extraction_service = extraction_service or ExtractionService()
        self.vector_store = vector_store or VectorStoreService()
        self.embedding_service = embedding_service or EmbeddingService()

    def is_sync_running(self) -> bool:
        """Check if a sync is currently in progress.

        If the in-memory threading lock is not held, any historical 'RUNNING' record in
        the SQLite database is from an interrupted run (e.g. server reload or crash)
        and will be marked as 'INTERRUPTED' to prevent permanent 409 lockouts.
        """
        if self._sync_lock.locked():
            return True
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT sync_id FROM ums_sync_history WHERE status = 'RUNNING'")
        stale_rows = cursor.fetchall()
        if stale_rows:
            cursor.execute(
                """
                UPDATE ums_sync_history
                SET status = 'INTERRUPTED',
                    completed_at = CURRENT_TIMESTAMP,
                    message = 'Sync interrupted by server restart or reload.',
                    error_message = 'Sync was interrupted and cleared automatically.'
                WHERE status = 'RUNNING'
                """
            )
            conn.commit()
            conn.close()
            logger.info("Auto-cleared %d stale 'RUNNING' sync record(s).", len(stale_rows))
            return False
        conn.close()
        return False

    def get_sync_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Retrieve recent sync execution records."""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT sync_id, started_at, completed_at, status,
                   fetched_count, candidate_count, inserted_count, updated_count,
                   skipped_count, failed_count, indexed_count, message,
                   error_message, triggered_by
            FROM ums_sync_history
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_latest_sync_status(self) -> Optional[Dict[str, Any]]:
        """Get summary of the most recent sync run."""
        history = self.get_sync_history(limit=1)
        return history[0] if history else None

    def get_synced_announcements(self) -> List[RawAnnouncement]:
        """Load all live/synced announcements from the SQLite database."""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT announcement_id, title, publication_date, reference_number,
                   full_content, attachment_present, attachment_names,
                   content_hash, source, source_url
            FROM live_announcements
            ORDER BY publication_date DESC, created_at DESC
            """
        )
        rows = cursor.fetchall()
        conn.close()

        results: List[RawAnnouncement] = []
        for r in rows:
            attach_names = json.loads(r["attachment_names"]) if r["attachment_names"] else []
            results.append(
                RawAnnouncement(
                    announcement_id=r["announcement_id"],
                    title=r["title"],
                    publication_date=r["publication_date"],
                    reference_number=r["reference_number"],
                    full_content=r["full_content"],
                    attachment_present=bool(r["attachment_present"]),
                    attachment_names=attach_names,
                    content_hash=r["content_hash"],
                    source=r["source"] or "ums",
                    source_url=r["source_url"],
                )
            )
        return results

    def get_pipeline_diagnostics(self) -> Dict[str, Any]:
        """Read-only diagnostic comparing records across storage layers.

        Compares:
          - Raw records in SQLite live_announcements
          - Extracted metadata in SQLite extracted_metadata
          - ChromaDB indexed IDs
          - Records visible to the feed/search (via DatasetService)

        Does NOT expose secrets, PII, or admin controls.
        """
        from app.services.vector_store_service import VectorStoreService

        conn = get_db_connection()
        cursor = conn.cursor()

        # 1. Raw live records
        cursor.execute("SELECT COUNT(*) as cnt FROM live_announcements")
        live_count = cursor.fetchone()["cnt"]

        # Processing status breakdown
        cursor.execute(
            "SELECT processing_status, COUNT(*) as cnt FROM live_announcements GROUP BY processing_status"
        )
        status_breakdown = {row["processing_status"]: row["cnt"] for row in cursor.fetchall()}

        # Sample live IDs
        cursor.execute("SELECT announcement_id FROM live_announcements ORDER BY created_at DESC LIMIT 10")
        recent_live_ids = [row["announcement_id"] for row in cursor.fetchall()]

        # 2. Extracted metadata
        cursor.execute("SELECT COUNT(*) as cnt FROM extracted_metadata")
        extracted_count = cursor.fetchone()["cnt"]

        # How many live announcements have extracted metadata?
        cursor.execute(
            """
            SELECT COUNT(DISTINCT la.announcement_id) as cnt
            FROM live_announcements la
            INNER JOIN extracted_metadata em ON la.content_hash = em.content_hash
            """
        )
        live_with_metadata = cursor.fetchone()["cnt"]

        conn.close()

        # 3. ChromaDB indexed IDs
        try:
            vs = VectorStoreService()
            chroma_count = vs.collection.count()
            chroma_ids = set()
            if chroma_count > 0:
                chroma_ids = set(vs.collection.get()["ids"])
        except Exception as exc:
            chroma_count = 0
            chroma_ids = set()
            logger.warning("Diagnostics: could not read ChromaDB: %s", exc)

        # 4. DatasetService total (historical + live)
        try:
            from app.services.dataset_service import DatasetService
            ds = DatasetService()
            all_announcements, report = ds.load_dataset(include_live=True)
            corpus_count = len(all_announcements)
            hist_count = corpus_count - live_count if corpus_count >= live_count else 0
        except Exception as exc:
            corpus_count = 0
            hist_count = 0
            logger.warning("Diagnostics: could not load dataset: %s", exc)

        # 5. Compute coverage gaps
        live_ids_set = set(recent_live_ids)
        indexed_recent = [aid for aid in recent_live_ids if aid in chroma_ids]
        not_indexed_recent = [aid for aid in recent_live_ids if aid not in chroma_ids]

        return {
            "raw_live_records": live_count,
            "historical_records": hist_count,
            "total_corpus_records": corpus_count,
            "extracted_metadata_records": extracted_count,
            "live_with_extracted_metadata": live_with_metadata,
            "chromadb_indexed_count": chroma_count,
            "processing_status_breakdown": status_breakdown,
            "recent_live_ids": recent_live_ids,
            "recent_live_indexed": indexed_recent,
            "recent_live_not_indexed": not_indexed_recent,
            "coverage_gap": max(0, corpus_count - chroma_count),
        }

    def run_sync(self, triggered_by: str = "manual", limit: int = 25) -> Dict[str, Any]:
        """Execute incremental sync by fetching from configured source adapter."""
        raw_list = self.source.fetch_latest_announcements(limit=limit)
        return self.ingest_announcements(raw_list, triggered_by=triggered_by)

    def ingest_announcements(
        self,
        raw_list: List[Dict[str, Any]],
        triggered_by: str = "manual",
        skip_gemini_extraction: bool = True,
    ) -> Dict[str, Any]:
        """Ingest, deduplicate, persist, extract metadata, and embed raw announcement records.

        Args:
            raw_list: Normalized announcement dicts from the source adapter.
            triggered_by: Tag identifying the sync initiator (e.g. ``"browser"``, ``"manual"``).
            skip_gemini_extraction: When ``True`` (default) the per-notice Gemini extraction
                API call is bypassed and the fast heuristic fallback is used instead.
                Set to ``False`` only for single-notice imports where rich metadata is
                required immediately.  Bulk browser-syncs should always keep this ``True``
                so that 100+ notices are ingested in seconds rather than minutes.
        """
        if not self._sync_lock.acquire(blocking=False):
            raise RuntimeError("Another synchronization operation is already in progress.")

        sync_id = f"SYNC-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
        started_at = datetime.now().isoformat()

        # Record start in DB
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO ums_sync_history (
                sync_id, started_at, status, triggered_by
            ) VALUES (?, ?, 'RUNNING', ?)
            """,
            (sync_id, started_at, triggered_by),
        )
        conn.commit()
        conn.close()

        metrics = {
            "sync_id": sync_id,
            "started_at": started_at,
            "completed_at": None,
            "status": "RUNNING",
            "message": "Synchronization in progress...",
            "fetched_count": len(raw_list),
            "candidate_count": 0,
            "inserted_count": 0,
            "updated_count": 0,
            "skipped_count": 0,
            "failed_count": 0,
            "indexed_count": 0,
            "error_message": None,
        }

        try:
            # Process each announcement incrementally
            new_or_updated: List[Tuple[RawAnnouncement, str]] = []  # (ann, 'INSERT'|'UPDATE')

            for raw_item in raw_list:
                try:
                    ann = self.source.normalize_announcement(raw_item)
                    metrics["candidate_count"] += 1
                    action = self._persist_announcement(ann)
                    if action == "INSERTED":
                        metrics["inserted_count"] += 1
                        new_or_updated.append((ann, "INSERT"))
                    elif action == "UPDATED":
                        metrics["updated_count"] += 1
                        new_or_updated.append((ann, "UPDATE"))
                    else:
                        metrics["skipped_count"] += 1
                except Exception as exc:
                    logger.error("Error processing announcement item: %s", exc)
                    metrics["failed_count"] += 1

            # Connect to AI Pipeline (Extraction & Vector Indexing)
            # Process in batch for speed: prepare all doc texts, then embed all at once.
            if new_or_updated and settings.AUTO_EMBED_NEW_NOTICES:
                doc_texts: List[str] = []
                chroma_metas: List[dict] = []
                processed_ann_ids: List[str] = []

                for ann, _action_type in new_or_updated:
                    cached = self.extraction_service.get_cached_metadata(ann.content_hash or "")
                    if cached:
                        meta_obj = cached
                    elif skip_gemini_extraction:
                        # Fast path: heuristic only — no Gemini API call, no network round-trip.
                        # The heuristic now includes deterministic impact classification.
                        meta_obj = self.extraction_service.fallback_heuristic_extraction(ann)
                        # Persist heuristic metadata so it doesn't need re-computation later
                        try:
                            self.extraction_service.save_cached_metadata(
                                ann.announcement_id,
                                ann.content_hash or "",
                                meta_obj,
                                processing_time_ms=0,
                                status="SUCCESS",
                            )
                        except Exception as save_err:
                            logger.debug("Could not persist heuristic metadata for %s: %s", ann.announcement_id, save_err)
                    else:
                        try:
                            meta_obj = self.extraction_service.extract_metadata(ann)
                        except Exception as exc:
                            logger.warning(
                                "Gemini extraction failed for %s (%s); using heuristic.",
                                ann.announcement_id, exc,
                            )
                            meta_obj = self.extraction_service.fallback_heuristic_extraction(ann)

                    doc_text = self.vector_store.prepare_document_text(ann, meta_obj)
                    doc_texts.append(doc_text)
                    chroma_metas.append({
                        "announcement_id": ann.announcement_id,
                        "title": ann.title,
                        "publication_date": ann.publication_date,
                        "reference_number": ann.reference_number or "N/A",
                        "category": meta_obj.category if meta_obj else "GENERAL",
                        "urgency": meta_obj.urgency.value if meta_obj else "LOW",
                        "attachment_present": ann.attachment_present,
                        "source": ann.source or "ums",
                        "impact_type": meta_obj.impact_type if meta_obj and meta_obj.impact_type else "UNKNOWN_IMPACT",
                    })
                    processed_ann_ids.append(ann.announcement_id)

                # Mark records as ANALYZED
                self._update_processing_status(processed_ann_ids, "ANALYZED")

                # Batch-embed all doc texts — each batch = one API call instead of N calls
                EMBED_BATCH_SIZE = 20
                all_vectors: List[List[float]] = []
                embed_failed = False
                for batch_start in range(0, len(doc_texts), EMBED_BATCH_SIZE):
                    batch = doc_texts[batch_start: batch_start + EMBED_BATCH_SIZE]
                    try:
                        batch_vectors = self.embedding_service.embed_batch(batch)
                        all_vectors.extend(batch_vectors)
                    except Exception as exc:
                        logger.warning(
                            "Batch embedding failed (batch starting at %d): %s — falling back per-notice.",
                            batch_start, exc,
                        )
                        embed_failed = True
                        for t in batch:
                            try:
                                all_vectors.append(self.embedding_service.embed_text(t))
                            except Exception as per_exc:
                                logger.warning("Per-notice embedding also failed: %s", per_exc)
                                all_vectors.append([0.0] * self.embedding_service.dimension)

                # Upsert all into ChromaDB in one bulk call
                ids = [m["announcement_id"] for m in chroma_metas]
                indexed_ids: List[str] = []
                try:
                    self.vector_store.collection.upsert(
                        ids=ids,
                        embeddings=all_vectors,
                        documents=doc_texts,
                        metadatas=chroma_metas,
                    )
                    metrics["indexed_count"] = len(ids)
                    indexed_ids = ids
                    logger.info("Batch-upserted %d announcements into ChromaDB.", len(ids))
                except Exception as exc:
                    logger.warning("Bulk ChromaDB upsert failed: %s — trying one-by-one.", exc)
                    for i, ann_id in enumerate(ids):
                        try:
                            self.vector_store.collection.upsert(
                                ids=[ann_id],
                                embeddings=[all_vectors[i]],
                                documents=[doc_texts[i]],
                                metadatas=[chroma_metas[i]],
                            )
                            indexed_ids.append(ann_id)
                            metrics["indexed_count"] += 1
                        except Exception as item_exc:
                            logger.error("Failed to upsert %s into ChromaDB: %s", ann_id, item_exc)

                # Update processing status: INDEXED for successful, FAILED for failed
                if indexed_ids:
                    self._update_processing_status(indexed_ids, "INDEXED")
                failed_ids = [aid for aid in processed_ann_ids if aid not in indexed_ids]
                if failed_ids:
                    self._update_processing_status(failed_ids, "STORED", error_msg="Embedding or indexing failed; record stored but not in vector index.")

            elif new_or_updated and not settings.AUTO_EMBED_NEW_NOTICES:
                # Records stored but embedding disabled — mark as STORED (searchable via lexical only)
                stored_ids = [ann.announcement_id for ann, _ in new_or_updated]
                self._update_processing_status(stored_ids, "STORED")

            # Determine truthful, nuanced status and user message (Phase 8)
            if metrics["inserted_count"] > 0 or metrics["updated_count"] > 0:
                # Clear the in-memory dataset cache so the next feed/search/RAG request
                # sees the newly stored records without requiring a server restart.
                try:
                    from app.services.dataset_service import DatasetService
                    DatasetService.clear_cache()
                    logger.info("Dataset cache cleared after successful sync (inserted=%d, updated=%d).",
                                metrics["inserted_count"], metrics["updated_count"])
                except Exception as cache_err:
                    logger.warning("Error clearing dataset cache (records still in SQLite, cache may be stale until restart): %s", cache_err)
            if metrics["failed_count"] > 0 and metrics["inserted_count"] == 0 and metrics["updated_count"] == 0 and metrics["skipped_count"] == 0:
                metrics["status"] = "FAILED"
                metrics["message"] = f"Failed to ingest announcements ({metrics['failed_count']} error(s) occurred)."
            elif metrics["fetched_count"] == 0:
                metrics["status"] = "EMPTY_SOURCE"
                metrics["message"] = "Source returned 0 announcements. Please verify portal connectivity or session credentials."
            elif metrics["inserted_count"] == 0 and metrics["updated_count"] == 0 and metrics["skipped_count"] > 0:
                metrics["status"] = "UP_TO_DATE"
                metrics["message"] = f"All {metrics['skipped_count']} announcements are already up to date in SmartNotice."
            elif metrics["inserted_count"] > 0 or metrics["updated_count"] > 0:
                metrics["status"] = "SUCCESS"
                summary_parts = []
                if metrics["inserted_count"] > 0:
                    summary_parts.append(f"{metrics['inserted_count']} new")
                if metrics["updated_count"] > 0:
                    summary_parts.append(f"{metrics['updated_count']} revised")
                if metrics["skipped_count"] > 0:
                    summary_parts.append(f"{metrics['skipped_count']} unchanged")
                metrics["message"] = f"Successfully synced: {', '.join(summary_parts)}."
            else:
                metrics["status"] = "SUCCESS"
                metrics["message"] = "Synchronization completed successfully."

        except Exception as exc:
            logger.exception("UMS ingestion failed: %s", exc)
            metrics["status"] = "FAILED"
            metrics["error_message"] = str(exc)
            metrics["message"] = f"Synchronization error: {str(exc)}"

        finally:
            completed_at = datetime.now().isoformat()
            metrics["completed_at"] = completed_at

            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE ums_sync_history
                SET completed_at = ?, status = ?, fetched_count = ?,
                    candidate_count = ?, inserted_count = ?, updated_count = ?,
                    skipped_count = ?, failed_count = ?, indexed_count = ?,
                    message = ?, error_message = ?
                WHERE sync_id = ?
                """,
                (
                    completed_at,
                    metrics["status"],
                    metrics["fetched_count"],
                    metrics["candidate_count"],
                    metrics["inserted_count"],
                    metrics["updated_count"],
                    metrics["skipped_count"],
                    metrics["failed_count"],
                    metrics["indexed_count"],
                    metrics["message"],
                    metrics["error_message"],
                    sync_id,
                ),
            )
            conn.commit()
            conn.close()
            self._sync_lock.release()

        return metrics

    def _persist_announcement(self, ann: RawAnnouncement) -> str:
        """Persist announcement in SQLite with deduplication and revision detection."""
        conn = get_db_connection()
        cursor = conn.cursor()

        # Check by announcement_id or (reference_number when available)
        existing = None
        if ann.announcement_id:
            cursor.execute(
                "SELECT announcement_id, content_hash, revision_count FROM live_announcements WHERE announcement_id = ?",
                (ann.announcement_id,),
            )
            existing = cursor.fetchone()

        if not existing and ann.reference_number:
            cursor.execute(
                "SELECT announcement_id, content_hash, revision_count FROM live_announcements WHERE reference_number = ?",
                (ann.reference_number,),
            )
            existing = cursor.fetchone()

        # Exact match check by content_hash to avoid duplicate inserts
        if not existing:
            cursor.execute(
                "SELECT announcement_id, content_hash FROM live_announcements WHERE content_hash = ?",
                (ann.content_hash,),
            )
            hash_match = cursor.fetchone()
            if hash_match:
                conn.close()
                return "SKIPPED"

        if existing:
            # If hash is identical, skip unchanged notice
            if existing["content_hash"] == ann.content_hash:
                conn.close()
                return "SKIPPED"

            # Content revised! Update existing record and increment revision count
            rev = (existing["revision_count"] or 1) + 1
            cursor.execute(
                """
                UPDATE live_announcements
                SET title = ?, publication_date = ?, full_content = ?,
                    attachment_present = ?, attachment_names = ?,
                    content_hash = ?, source_url = ?, revision_count = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE announcement_id = ?
                """,
                (
                    ann.title,
                    ann.publication_date,
                    ann.full_content,
                    1 if ann.attachment_present else 0,
                    json.dumps(ann.attachment_names),
                    ann.content_hash,
                    ann.source_url,
                    rev,
                    existing["announcement_id"],
                ),
            )
            conn.commit()
            conn.close()
            logger.info("Updated announcement %s to revision %d", ann.announcement_id, rev)
            return "UPDATED"

        # Brand new announcement
        cursor.execute(
            """
            INSERT INTO live_announcements (
                announcement_id, source_id, title, publication_date,
                reference_number, full_content, attachment_present,
                attachment_names, content_hash, source, source_url, revision_count,
                processing_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'STORED')
            """,
            (
                ann.announcement_id,
                ann.announcement_id.replace("ANN-UMS-", ""),
                ann.title,
                ann.publication_date,
                ann.reference_number,
                ann.full_content,
                1 if ann.attachment_present else 0,
                json.dumps(ann.attachment_names),
                ann.content_hash,
                ann.source or "ums",
                ann.source_url,
            ),
        )
        conn.commit()
        conn.close()
        logger.info("Inserted new live announcement: %s (%s)", ann.announcement_id, ann.title[:40])
        return "INSERTED"

    def _update_processing_status(
        self, announcement_ids: List[str], status: str, error_msg: Optional[str] = None
    ) -> None:
        """Update the processing_status column for a batch of live announcements.

        Statuses: STORED, ANALYZED, INDEXED, READY, FAILED
        """
        if not announcement_ids:
            return
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            placeholders = ",".join("?" * len(announcement_ids))
            if error_msg:
                cursor.execute(
                    f"UPDATE live_announcements SET processing_status = ?, index_error = ?, updated_at = CURRENT_TIMESTAMP WHERE announcement_id IN ({placeholders})",
                    [status, error_msg] + announcement_ids,
                )
            else:
                cursor.execute(
                    f"UPDATE live_announcements SET processing_status = ?, index_error = NULL, updated_at = CURRENT_TIMESTAMP WHERE announcement_id IN ({placeholders})",
                    [status] + announcement_ids,
                )
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.warning("Failed to update processing status to %s: %s", status, exc)

    def _process_ai_pipeline(self, ann: RawAnnouncement, skip_gemini_extraction: bool = True) -> None:
        """Run extraction and vector embedding for a new or updated announcement.

        Args:
            ann: The announcement to process.
            skip_gemini_extraction: When ``True`` (default) bypass the Gemini extraction
                API call and use the heuristic fallback directly.  This makes bulk sync
                complete in seconds instead of minutes.  The richer Gemini-extracted
                metadata can be back-filled later via the ``/api/ums/reextract`` endpoint
                or the ``build_index.py --reconcile`` script.
        """
        metadata = None
        # 1. Extraction: check SQLite cache first; if a fresh Gemini call is wanted
        #    (skip_gemini_extraction=False) and no cache hit exists, call the API.
        cached = self.extraction_service.get_cached_metadata(ann.content_hash or "")
        if cached:
            metadata = cached
        elif skip_gemini_extraction:
            # Fast path: heuristic only — no Gemini API call, no network round-trip.
            logger.debug(
                "Skipping Gemini extraction for %s (bulk sync mode); using heuristic fallback.",
                ann.announcement_id,
            )
            metadata = self.extraction_service.fallback_heuristic_extraction(ann)
        else:
            try:
                metadata = self.extraction_service.extract_metadata(ann)
            except Exception as exc:
                logger.warning(
                    "Gemini API extraction failed for %s (%s). Using heuristic fallback.",
                    ann.announcement_id,
                    exc,
                )
                metadata = self.extraction_service.fallback_heuristic_extraction(ann)

        # 2. Vector indexing: embed and upsert into ChromaDB
        if settings.AUTO_EMBED_NEW_NOTICES:
            try:
                doc_text = self.vector_store.prepare_document_text(ann, metadata)
                vector = self.embedding_service.embed_text(doc_text)
                chroma_meta = {
                    "announcement_id": ann.announcement_id,
                    "title": ann.title,
                    "publication_date": ann.publication_date,
                    "reference_number": ann.reference_number or "N/A",
                    "category": metadata.category if metadata else "GENERAL",
                    "urgency": metadata.urgency.value if metadata else "LOW",
                    "attachment_present": ann.attachment_present,
                    "source": ann.source or "ums",
                }
                # Upsert into ChromaDB
                self.vector_store.collection.upsert(
                    ids=[ann.announcement_id],
                    embeddings=[vector],
                    documents=[doc_text],
                    metadatas=[chroma_meta],
                )
                logger.info("Upserted %s into ChromaDB vector index.", ann.announcement_id)
                return True
            except Exception as exc:
                logger.warning("Failed to embed announcement %s into ChromaDB: %s", ann.announcement_id, exc)
                return False
        return False
