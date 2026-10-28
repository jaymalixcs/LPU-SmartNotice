from fastapi import APIRouter
from app.core.config import settings
from app.core.security import validate_api_key_configured
from app.core.database import get_db_connection
from app.services.dataset_service import DatasetService
from app.services.vector_store_service import VectorStoreService

router = APIRouter(tags=["Health & Status"])

@router.get("/health")
def get_health_status():
    """Return detailed application health, database, vector index, and subsystem status."""
    dataset_service = DatasetService()
    vector_store = VectorStoreService()

    try:
        _, dataset_report = dataset_service.load_dataset()
        dataset_healthy = True
    except Exception as e:
        dataset_report = {"status": "error", "error": str(e)}
        dataset_healthy = False

    try:
        index_status = vector_store.get_index_status()
        chroma_healthy = True
    except Exception as e:
        index_status = {"status": "error", "error": str(e)}
        chroma_healthy = False

    # Check SQLite DB
    sqlite_stats = {}
    db_healthy = False
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM live_announcements")
        live_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM extracted_metadata")
        extracted_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM student_profiles")
        profile_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM ums_sync_history")
        sync_count = c.fetchone()[0]
        # Processing status breakdown for live records
        c.execute("SELECT processing_status, COUNT(*) as cnt FROM live_announcements GROUP BY processing_status")
        status_breakdown = {row["processing_status"]: row["cnt"] for row in c.fetchall()}
        conn.close()
        sqlite_stats = {
            "live_announcements": live_count,
            "extracted_metadata": extracted_count,
            "student_profiles": profile_count,
            "sync_history_runs": sync_count,
            "live_processing_status": status_breakdown,
        }
        db_healthy = True
    except Exception as e:
        sqlite_stats = {"error": str(e)}

    api_key_configured = validate_api_key_configured()

    return {
        "status": "healthy" if (dataset_healthy and db_healthy) else "degraded",
        "app_name": "LPU SmartNotice",
        "version": "1.0.0",
        "subsystems": {
            "fastapi": "healthy",
            "sqlite": "healthy" if db_healthy else "error",
            "chromadb": "healthy" if chroma_healthy else "error",
            "gemini_api": "configured" if api_key_configured else "offline_fallback"
        },
        "api_key_configured": api_key_configured,
        "generation_model": settings.GEMINI_GENERATION_MODEL,
        "embedding_model": settings.GEMINI_EMBEDDING_MODEL,
        "sqlite_stats": sqlite_stats,
        "dataset_summary": dataset_report,
        "vector_index_summary": index_status
    }

@router.post("/health/cache-refresh")
def refresh_cache():
    """Force reloads the in-memory announcements cache from disk and SQLite."""
    dataset_service = DatasetService()
    announcements, report = dataset_service.load_dataset(force_reload=True)
    return {
        "status": "success",
        "message": f"Successfully reloaded cache with {len(announcements)} announcements.",
        "dataset_summary": report
    }

@router.get("/index/status")
def get_index_status():
    """Return detailed vector store index status."""
    vector_store = VectorStoreService()
    return vector_store.get_detailed_index_diagnostics()


@router.get("/diagnostics/pipeline")
def get_pipeline_diagnostics():
    """Return comprehensive pipeline diagnostics comparing all storage layers."""
    from app.services.ums_sync_service import UMSSyncService
    return UMSSyncService().get_pipeline_diagnostics()
