import re
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from app.services.embedding_service import EmbeddingService
from app.services.vector_store_service import VectorStoreService
from app.services.temporal_service import resolve_target_dates, extract_notice_dates
from app.services.impact_classifier import (
    classify_impact,
    is_location_impact_query,
    extract_query_block,
    extract_query_impact_type,
    ImpactFacts,
)
from app.models.announcement import RawAnnouncement, ExtractedAnnouncementMetadata, AnnouncementDetail
from app.core.logging_config import logger

STOPWORDS = {
    "a", "about", "above", "after", "again", "all", "am", "an", "and", "any", "are",
    "as", "at", "be", "because", "been", "before", "being", "below", "between", "both",
    "but", "by", "can", "could", "did", "do", "does", "doing", "down", "during", "each",
    "few", "for", "from", "further", "had", "has", "have", "having", "he", "her", "here",
    "hers", "herself", "him", "himself", "his", "how", "i", "if", "in", "into", "is",
    "it", "its", "itself", "just", "me", "more", "most", "my", "myself", "no", "nor",
    "not", "now", "of", "off", "on", "once", "only", "or", "other", "our", "ours",
    "ourselves", "out", "over", "own", "s", "same", "she", "should", "so", "some",
    "such", "t", "than", "that", "the", "their", "theirs", "them", "themselves",
    "then", "there", "these", "they", "this", "those", "through", "to", "too", "under",
    "until", "up", "very", "was", "we", "were", "what", "when", "where", "which",
    "while", "who", "whom", "why", "will", "with", "you", "your", "yours", "yourself",
    "yourselves", "hello", "hi", "hey", "please", "thanks", "thank",
    "announcement", "announcements", "notice", "notices"
}

TYPO_CORRECTIONS = {
    "accoummodation": "accommodation",
    "accomodation": "accommodation",
    "acommodation": "accommodation",
    "residental": "residential",
    "residence": "residential",
    "hostle": "hostel",
    "timetables": "timetable",
    "annoucement": "announcement",
    "annoucements": "announcements",
    "submition": "submission",
    "verifcation": "verification",
    "karwa": "karva",
    "karwachauth": "karva chauth",
    "uni": "university",
}

CONCEPT_CLUSTERS = {
    "ACCOMMODATION": [
        "accommodation", "residential", "residence", "pg", "hostel",
        "residing", "flat", "pg/residential", "stay"
    ],
    "DEADLINE": [
        "deadline", "last date", "due date", "final date", "closing date",
        "cutoff", "cut off", "end date", "latest by", "last day"
    ],
    "ACTION_FILL": [
        "fill", "fill in", "complete", "update", "verify", "verification",
        "confirm", "confirmation", "submit", "submission", "apply", "register"
    ],
    "ROOM_EXEMPTION": [
        "room", "exempt", "exemption", "exempted", "relocation", "suspended"
    ],
    "TIMING_CHANGE": [
        "karva", "karwa", "chauth", "timing", "timings", "conducted up to",
        "close at", "closing", "closure", "rescheduled", "early closure"
    ]
}


def normalize_query_text(text: str) -> str:
    """Normalize query text by fixing common student typos and standardizing casing."""
    cleaned = text.lower()
    for typo, correction in TYPO_CORRECTIONS.items():
        cleaned = re.sub(rf"\b{re.escape(typo)}\b", correction, cleaned)
    return cleaned


class RetrievalService:
    """Hybrid Retrieval Service combining Semantic Embeddings + Lexical Scoring + RRF Candidate Merging."""

    def __init__(self):
        self.embedding_service = EmbeddingService()
        self.vector_store = VectorStoreService()

    def lexical_score(
        self,
        query: str,
        document_text: str,
        title: str = "",
        reference_number: Optional[str] = None
    ) -> float:
        """Compute term-frequency based lexical relevance score for exact matches, references, concepts, and deadline phrases."""
        norm_query = normalize_query_text(query)
        doc_lower = document_text.lower()
        title_lower = title.lower() if title else ""
        ref_lower = (reference_number or "").lower()

        raw_terms = re.findall(r"[\w/.-]+", norm_query)
        query_terms = [t for t in set(raw_terms) if len(t) >= 2 and t not in STOPWORDS]
        if not query_terms:
            return 0.0

        score = 0.0

        # 1. Term-frequency scoring
        for term in query_terms:
            count = doc_lower.count(term)
            if count > 0:
                score += (1.0 + 0.5 * min(count, 5))

        # 2. Distinctive reference number matching (e.g. LPU/10.2/ANN... or 0086)
        if ref_lower:
            for term in query_terms:
                if len(term) >= 4 and term in ref_lower:
                    score += 15.0

        # Specific Block number booster (e.g. "Block 34", "Block 14", "Block 38", "Block 33")
        block_match = re.search(r'\bblock\s*(\d{1,2})\b', norm_query)
        if block_match:
            b_num = block_match.group(1)
            # Matches "Block 34", room number starting with 34 (e.g. 34301), or isolated 34
            if (
                re.search(rf'\bblock\s*{b_num}\b', doc_lower) or
                re.search(rf'\b{b_num}\d{{3}}[a-z]?\b', doc_lower) or
                re.search(rf'^{b_num}\b|\n{b_num}\n|\b{b_num}\b', doc_lower) or
                (title_lower and (b_num in title_lower))
            ):
                score += 25.0

        # Distinctive rare event terms (e.g. karva, chauth)
        for rare_term in ["karva", "karwa", "chauth"]:
            if rare_term in norm_query and rare_term in doc_lower:
                score += 12.0

        # 3. Distinctive title matching bonus
        if title_lower:
            matched_title_terms = sum(1 for t in query_terms if t in title_lower)
            if matched_title_terms >= 2:
                score += 4.0 * matched_title_terms

        # 4. Concept matching & Cross-concept synergy
        matched_concepts_in_query = set()
        matched_concepts_in_doc = set()

        for concept_name, terms in CONCEPT_CLUSTERS.items():
            if any(term in norm_query for term in terms):
                matched_concepts_in_query.add(concept_name)
            if any(term in doc_lower for term in terms):
                matched_concepts_in_doc.add(concept_name)

        overlap_concepts = matched_concepts_in_query.intersection(matched_concepts_in_doc)
        if overlap_concepts:
            score += 4.0 * len(overlap_concepts)

            # High synergy: query seeks accommodation deadline/action and doc covers accommodation + deadline/action
            if "ACCOMMODATION" in overlap_concepts and ("DEADLINE" in overlap_concepts or "ACTION_FILL" in overlap_concepts):
                score += 16.0

        # 5. Explicit deadline phrase detection
        has_deadline_query = "DEADLINE" in matched_concepts_in_query or any(w in norm_query for w in ["last date", "deadline", "due date", "final date"])
        if has_deadline_query:
            deadline_phrase_pattern = r"(?:last date|deadline|due date|complete by|verify by|submit by|latest by)\s*(?:is|to|for|of|:|—|-)?\s*([^\n.]+)"
            if re.search(deadline_phrase_pattern, doc_lower):
                score += 8.0

        # 6. Bonus for exact query phrase match
        clean_q = " ".join(query_terms)
        if len(clean_q) > 3 and clean_q in doc_lower:
            score += 5.0

        return score

    def reciprocal_rank_fusion(
        self,
        semantic_results: List[Tuple[str, float]],
        lexical_results: List[Tuple[str, float]],
        k: int = 60
    ) -> List[Tuple[str, float]]:
        """Combine two ranked lists using Reciprocal Rank Fusion (RRF) with calibrated score weighting."""
        scores: Dict[str, float] = {}

        # Semantic ranks
        for rank, (doc_id, sim_score) in enumerate(semantic_results):
            scores[doc_id] = scores.get(doc_id, 0.0) + (1.0 / (k + rank + 1)) + (0.005 * sim_score)

        # Lexical ranks: incorporate normalized lexical strength so distinctive exact matches outrank weak vector matches
        for rank, (doc_id, l_score) in enumerate(lexical_results):
            lex_boost = min(l_score / 200.0, 0.05)
            scores[doc_id] = scores.get(doc_id, 0.0) + (1.0 / (k + rank + 1)) + lex_boost

        sorted_docs = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return sorted_docs

    def search(
        self,
        query: str,
        top_k: int = 5,
        category_filter: Optional[str] = None,
        raw_announcements: Optional[List[RawAnnouncement]] = None
    ) -> List[Dict[str, Any]]:
        """Hybrid search returning ranked announcement evidence records with similarity scores."""
        if not query or not query.strip():
            return []

        norm_query = normalize_query_text(query)

        # If raw announcements not provided, lazily load full corpus (historical + live)
        if raw_announcements is None:
            try:
                from app.services.dataset_service import DatasetService
                raw_announcements, _ = DatasetService().load_dataset(include_live=True)
            except Exception as e:
                logger.debug("Could not load raw announcements for search fallback: %s", e)
                raw_announcements = []

        # 1. Semantic Vector Search via ChromaDB
        semantic_tuples: List[Tuple[str, float]] = []
        doc_map: Dict[str, Dict[str, Any]] = {}

        try:
            collection_count = self.vector_store.collection.count()
            if collection_count > 0:
                query_vector = self.embedding_service.embed_text(norm_query)
                chroma_filter = {"category": category_filter} if category_filter else None

                chroma_res = self.vector_store.collection.query(
                    query_embeddings=[query_vector],
                    n_results=min(max(top_k * 4, 20), collection_count),
                    where=chroma_filter,
                    include=["documents", "metadatas", "distances"]
                )

                if chroma_res and chroma_res["ids"] and chroma_res["ids"][0]:
                    ids = chroma_res["ids"][0]
                    docs = chroma_res["documents"][0] if chroma_res["documents"] else []
                    metas = chroma_res["metadatas"][0] if chroma_res["metadatas"] else []
                    distances = chroma_res["distances"][0] if chroma_res["distances"] else []

                    for i, doc_id in enumerate(ids):
                        dist = distances[i] if i < len(distances) else 1.0
                        sim_score = max(0.0, 1.0 - dist)
                        semantic_tuples.append((doc_id, sim_score))

                        doc_map[doc_id] = {
                            "announcement_id": doc_id,
                            "document": docs[i] if i < len(docs) else "",
                            "metadata": metas[i] if i < len(metas) else {},
                            "semantic_score": sim_score
                        }
        except Exception as vec_err:
            logger.warning("Vector retrieval query failed (%s); continuing with full lexical search.", vec_err)

        # 2. Comprehensive Lexical Scoring across raw announcements
        norm_q = normalize_query_text(query)
        is_room_query = any(w in norm_q for w in ["room", "exempt", "class", "block", "relocation", "lab"])
        target_dates = resolve_target_dates(query)

        raw_scored_candidates: List[Tuple[RawAnnouncement, str, float]] = []

        if raw_announcements:
            for ann in raw_announcements:
                doc_text = f"Title: {ann.title}\nRef: {ann.reference_number}\nContent: {ann.full_content}"
                l_score = self.lexical_score(
                    query=query,
                    document_text=doc_text,
                    title=ann.title,
                    reference_number=ann.reference_number
                )

                notice_dates = extract_notice_dates(ann.publication_date, ann.full_content, ann.title)
                date_matched = any(td in notice_dates for td in target_dates) if target_dates else True

                # Specialized booster for room exemption queries
                if is_room_query:
                    c_lower = ann.full_content.lower()
                    has_room_pattern = bool(re.search(r'\b\d{4,5}[A-Z]?\b', ann.full_content) or 'central library' in c_lower or 'lab' in c_lower)
                    has_timing = any(t in c_lower for t in ['until', 'entire day', 'am', 'pm', 'exempt'])
                    if has_room_pattern and has_timing:
                        if target_dates:
                            if date_matched:
                                l_score = max(l_score, 18.0)
                            else:
                                l_score = min(l_score, 0.1)
                        else:
                            l_score = max(l_score, 8.0)

                if l_score > 0.0:
                    raw_scored_candidates.append((ann, doc_text, l_score))

            # Sort raw lexical candidates by score and retain top pool
            raw_scored_candidates.sort(key=lambda x: x[2], reverse=True)
            top_lexical_candidates = raw_scored_candidates[:max(top_k * 5, 30)]

            for ann, doc_text, l_score in top_lexical_candidates:
                ann_id = ann.announcement_id
                if ann_id not in doc_map:
                    doc_map[ann_id] = {
                        "announcement_id": ann_id,
                        "document": doc_text,
                        "metadata": {
                            "announcement_id": ann.announcement_id,
                            "title": ann.title,
                            "publication_date": ann.publication_date,
                            "reference_number": ann.reference_number or "",
                            "attachment_present": ann.attachment_present,
                            "attachment_names": ", ".join(ann.attachment_names),
                            "category": "GENERAL",
                            "decision_completeness": "ATTACHMENT_MISSING" if ann.attachment_present else "COMPLETE",
                            "source": getattr(ann, "source", "historical"),
                            "source_url": getattr(ann, "source_url", None)
                        },
                        "semantic_score": 0.0
                    }

        # Compute lexical scores for all documents currently in doc_map
        lexical_tuples: List[Tuple[str, float]] = []
        for doc_id, data in doc_map.items():
            l_score = self.lexical_score(
                query=query,
                document_text=data["document"],
                title=data["metadata"].get("title", ""),
                reference_number=data["metadata"].get("reference_number")
            )
            doc_pub = data["metadata"].get("publication_date", "")
            notice_dates = extract_notice_dates(doc_pub, data["document"], data["metadata"].get("title", ""))
            date_matched = any(td in notice_dates for td in target_dates) if target_dates else True

            if is_room_query:
                c_lower = data["document"].lower()
                has_room_pattern = bool(re.search(r'\b\d{4,5}[A-Z]?\b', data["document"]) or 'central library' in c_lower or 'lab' in c_lower)
                has_timing = any(t in c_lower for t in ['until', 'entire day', 'am', 'pm', 'exempt'])
                if has_room_pattern and has_timing:
                    if target_dates:
                        if date_matched:
                            l_score = max(l_score, 18.0)
                        else:
                            l_score = min(l_score, 0.1)
                    else:
                        l_score = max(l_score, 8.0)

            if l_score > 0:
                lexical_tuples.append((doc_id, l_score))

        lexical_tuples.sort(key=lambda x: x[1], reverse=True)

        # 3. Candidate Merging via Reciprocal Rank Fusion (RRF)
        rrf_ranked = self.reciprocal_rank_fusion(semantic_tuples, lexical_tuples)

        # If query specifies explicit target dates (e.g. today/tomorrow), boost date-matched notices
        if target_dates:
            matched_docs = []
            unmatched_docs = []
            for doc_id, score in rrf_ranked:
                doc_item = doc_map.get(doc_id, {})
                doc_meta = doc_item.get("metadata", {})
                doc_pub = doc_meta.get("publication_date", "")
                doc_text = doc_item.get("document", "")
                notice_dates = extract_notice_dates(doc_pub, doc_text, doc_meta.get("title", ""))
                if any(td in notice_dates for td in target_dates):
                    matched_docs.append((doc_id, score + 2.0))
                else:
                    unmatched_docs.append((doc_id, score))
            rrf_ranked = matched_docs + unmatched_docs

        # 4. Format top_k output — include impact classification for each result
        final_results = []
        for doc_id, rrf_score in rrf_ranked[:top_k]:
            item = doc_map[doc_id]
            meta = item["metadata"]
            raw_att = meta.get("attachment_names", [])
            if isinstance(raw_att, list):
                att_names = [str(x) for x in raw_att if str(x).strip()]
            else:
                att_names = [x.strip() for x in str(raw_att).split(",") if x.strip()]

            notice_dates = extract_notice_dates(meta.get("publication_date", ""), item["document"], meta.get("title", ""))
            date_matched = any(td in notice_dates for td in target_dates) if target_dates else None

            # Classify impact for this result using the deterministic classifier
            result_title = meta.get("title", "")
            # Extract content portion from the document (after "Content: ")
            doc_content = item["document"]
            content_start = doc_content.find("Content: ")
            result_content = doc_content[content_start + 9:] if content_start >= 0 else doc_content
            impact_facts = classify_impact(result_title, result_content)

            final_results.append({
                "announcement_id": doc_id,
                "title": result_title,
                "publication_date": meta.get("publication_date", ""),
                "reference_number": meta.get("reference_number") or None,
                "document": item["document"],
                "attachment_present": bool(meta.get("attachment_present", False)),
                "attachment_names": att_names,
                "attachment_content_available": False,
                "decision_completeness": meta.get("decision_completeness", "COMPLETE"),
                "category": meta.get("category", "GENERAL"),
                "urgency": meta.get("urgency", "LOW"),
                "source": meta.get("source", "historical"),
                "source_url": meta.get("source_url") or None,
                "rrf_score": round(rrf_score, 4),
                "semantic_score": round(item["semantic_score"], 4),
                "notice_dates": notice_dates,
                "matches_target_date": date_matched,
                "impact_type": impact_facts.impact_type,
                "impact_facts": impact_facts.to_dict(),
            })

        return final_results

    def search_location_impact(
        self,
        query: str,
        top_k: int = 15,
        raw_announcements: Optional[List[RawAnnouncement]] = None
    ) -> Dict[str, Any]:
        """Intent-aware search for location-impact queries (e.g. "What affects Block 34?").

        Returns results categorized by impact type so the chatbot can present
        exemptions, restrictions, events, and mentions separately.

        Returns a dict with:
            - "categories": ordered dict of impact_type -> list of results
            - "results": flat ranked list (same as search())
            - "query_block": block number extracted from query
            - "query_impact_type": specific impact type requested (or None)
        """
        # Get base results using the standard search
        results = self.search(query=query, top_k=top_k, raw_announcements=raw_announcements)

        query_block = extract_query_block(query)
        query_impact_type = extract_query_impact_type(query)
        target_dates = resolve_target_dates(query)

        # Category priority order (most actionable first)
        category_order = [
            "ROOM_EXEMPTION",
            "ROOM_UNAVAILABLE",
            "BLOCK_RESTRICTION",
            "CLASS_CANCELLATION",
            "VENUE_CHANGE",
            "EVENT_LOCATION",
            "ROOM_MENTION_ONLY",
            "UNKNOWN_IMPACT",
        ]

        # Group results by impact type
        categories: Dict[str, List[Dict[str, Any]]] = {cat: [] for cat in category_order}
        for result in results:
            impact_type = result.get("impact_type", "UNKNOWN_IMPACT")
            if impact_type not in categories:
                categories[impact_type] = []
            categories[impact_type].append(result)

        # Re-rank within each category: prioritize exact block match, then date match,
        # then RRF score. If query specifies a specific impact type, filter to that.
        for cat, items in categories.items():
            if query_block:
                # Boost results whose block matches the query block
                for item in items:
                    impact = item.get("impact_facts", {})
                    item_block = impact.get("block")
                    if item_block == query_block:
                        item["_block_match"] = True
                    else:
                        item["_block_match"] = False
                # Sort: block match first, then date match, then RRF score
                items.sort(
                    key=lambda x: (
                        0 if x.get("_block_match") else 1,
                        0 if x.get("matches_target_date") else 1,
                        -x.get("rrf_score", 0),
                    )
                )
            else:
                items.sort(key=lambda x: -x.get("rrf_score", 0))

        # If query specifies a specific impact type, filter the flat results
        if query_impact_type:
            results = [r for r in results if r.get("impact_type") == query_impact_type]

        # Remove empty categories
        categories = {k: v for k, v in categories.items() if v}

        return {
            "categories": categories,
            "results": results,
            "query_block": query_block,
            "query_impact_type": query_impact_type,
            "target_dates": target_dates,
        }

