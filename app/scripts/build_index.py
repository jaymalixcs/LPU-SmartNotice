"""Build and reconcile persistent ChromaDB index with safety limits and diagnostics."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import argparse
from app.services.dataset_service import DatasetService
from app.services.vector_store_service import VectorStoreService
from app.services.extraction_service import ExtractionService
from app.core.database import init_db
from app.core.config import settings

def print_diagnostics(diag: dict):
    print("\n" + "=" * 65)
    print("      LPU SmartNotice - Vector Index Completeness Report")
    print("=" * 65)
    print(f" Historical Corpus Records:     {diag['total_historical_records']}")
    print(f" Live/Synchronized Records:     {diag['total_live_records']}")
    print(f" Total Records Available:       {diag['total_corpus_records']}")
    print(f" Indexed Records in ChromaDB:   {diag['total_indexed_documents']}")
    print(f" Index Coverage:                {diag['coverage_percentage']}%")
    print(f" Missing from Vector Index:     {diag['missing_from_index_count']}")
    if diag.get("sample_missing_ids"):
        print(f" Sample Unindexed IDs:          {', '.join(diag['sample_missing_ids'][:5])}")
    print(f" Embedding Model:               {diag['embedding_model']}")
    print(f" Embedding Dimension:           {diag['embedding_dimension']}")
    print(f" Last Indexed At:               {diag['last_indexed_at']}")
    print(f" Persistent Path:               {diag['chroma_path']}")
    print("=" * 65 + "\n")

def main():
    parser = argparse.ArgumentParser(description="Build and reconcile persistent ChromaDB vector index for LPU announcements.")
    parser.add_argument("--diagnostics", "--status", dest="diagnostics", action="store_true", help="Print detailed index completeness and coverage diagnostics")
    parser.add_argument("--dry-run", action="store_true", help="Inspect and simulate indexing operations without calling API or modifying ChromaDB")
    parser.add_argument("--reconcile", action="store_true", help="Incrementally index only missing or unindexed announcements without re-embedding existing documents")
    parser.add_argument("--limit", type=int, default=settings.INITIAL_INDEX_LIMIT, help="Limit number of documents to index")
    parser.add_argument("--confirm-full", action="store_true", help="Explicitly confirm indexing full dataset")
    parser.add_argument("--force-reindex", action="store_true", help="Rebuild entire index from scratch")
    args = parser.parse_args()

    init_db()
    dataset_service = DatasetService()
    vector_store = VectorStoreService()
    extraction_service = ExtractionService()

    announcements, _ = dataset_service.load_dataset(include_live=True)
    diag = vector_store.get_detailed_index_diagnostics(announcements)

    if args.diagnostics:
        print_diagnostics(diag)
        return

    if args.dry_run:
        print("\n[DRY RUN MODE - No external API calls or database writes will be performed]")
        print_diagnostics(diag)
        if args.reconcile:
            print(f"Dry run plan: Reconcile will index {min(diag['missing_from_index_count'], args.limit)} missing record(s).")
        elif args.confirm_full:
            print(f"Dry run plan: Full indexing would process all {len(announcements)} records.")
        else:
            print(f"Dry run plan: Safe batch indexing would process top {min(len(announcements), args.limit)} records.")
        return

    if args.reconcile:
        existing_ids = set(vector_store.collection.get()["ids"]) if vector_store.collection.count() > 0 else set()
        missing_records = [a for a in announcements if a.announcement_id not in existing_ids]
        target_records = missing_records[:args.limit] if not args.confirm_full else missing_records
        print(f"\n[RECONCILING MISSING RECORDS] Target: {len(target_records)} of {len(missing_records)} unindexed records.")
    elif args.confirm_full:
        target_records = announcements
        print(f"\n[CONFIRMED FULL INDEXING] Target: All {len(announcements)} records.")
    else:
        target_records = announcements[:args.limit]
        print(f"\n[SAFE BATCH INDEXING] Target: Top {len(target_records)} of {len(announcements)} records.")
        print("Note: To index all missing historical records safely, re-run with '--reconcile'.")

    if not target_records:
        print("Vector index is already fully synchronized! 0 documents need indexing.")
        return

    # Load cached metadata if available
    extracted_map = {}
    for ann in target_records:
        meta = extraction_service.get_cached_metadata(ann.content_hash or "")
        if meta:
            extracted_map[ann.announcement_id] = meta

    print(f"\nGenerating embeddings and upserting {len(target_records)} records into ChromaDB...")
    added, skipped = vector_store.add_or_update_announcements(
        announcements=target_records,
        extracted_map=extracted_map,
        force_reindex=args.force_reindex
    )

    new_diag = vector_store.get_detailed_index_diagnostics(announcements)
    print("\n" + "=" * 65)
    print("      LPU SmartNotice - Vector Indexing Summary")
    print("=" * 65)
    print(f"[Newly Added/Updated]        {added}")
    print(f"[Skipped (Already In Index)] {skipped}")
    print(f"[Total Indexed Documents]     {new_diag['total_indexed_documents']}")
    print(f"[Coverage Percentage]        {new_diag['coverage_percentage']}%")
    print(f"[Embedding Model]             {new_diag['embedding_model']}")
    print(f"[Embedding Dimension]         {new_diag['embedding_dimension']}")
    print(f"[Persistent Path]             {new_diag['chroma_path']}")
    print("=" * 65 + "\n")

if __name__ == "__main__":
    main()
