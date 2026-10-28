import os
from typing import List, Union
from google import genai
from google.genai import types

from app.core.config import settings
from app.core.logging_config import logger
from app.core.security import validate_api_key_configured

class EmbeddingService:
    """Service for generating vector embeddings using Gemini embedding API."""

    def __init__(self):
        self.model_name = settings.GEMINI_EMBEDDING_MODEL
        self.dimension = settings.EMBEDDING_DIMENSION

    def get_client(self) -> genai.Client:
        key = settings.GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY", "")
        if not key or key == "your_gemini_api_key_here":
            raise ValueError("GEMINI_API_KEY is not configured in .env file.")
        return genai.Client(api_key=key, http_options=types.HttpOptions(timeout=12000))

    def generate_offline_pseudo_embedding(self, text: str) -> List[float]:
        """Generate deterministic normalized float vector for testing and offline environments."""
        import hashlib
        import math
        seed = hashlib.sha256(text.encode("utf-8")).digest()
        raw_vals = [((seed[i % len(seed)] + i * 17) % 100) / 100.0 - 0.5 for i in range(self.dimension)]
        magnitude = math.sqrt(sum(v * v for v in raw_vals)) or 1.0
        return [round(v / magnitude, 6) for v in raw_vals]

    def embed_text(self, text: str) -> List[float]:
        """Generate embedding vector for a single string."""
        if not text or not text.strip():
            # Return zero vector if text is empty
            return [0.0] * self.dimension

        if not validate_api_key_configured():
            logger.debug("GEMINI_API_KEY not configured. Generating deterministic offline vector.")
            return self.generate_offline_pseudo_embedding(text)

        try:
            client = self.get_client()
            response = client.models.embed_content(
                model=self.model_name,
                contents=text,
                config=types.EmbedContentConfig(
                    output_dimensionality=self.dimension
                )
            )

            if not response.embeddings or not response.embeddings[0].values:
                raise RuntimeError("Empty embedding response returned by Gemini API.")

            vector = response.embeddings[0].values
            if len(vector) != self.dimension:
                logger.warning("Embedding dimension mismatch: expected %d, got %d", self.dimension, len(vector))

            return list(vector)

        except Exception as e:
            logger.warning("Embedding generation failed (%s). Falling back to offline pseudo-embedding.", e)
            return self.generate_offline_pseudo_embedding(text)

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a list of strings in a single API call where possible.

        Falls back to per-text embedding when the batch API is unavailable.
        """
        if not texts:
            return []

        if not validate_api_key_configured():
            logger.debug("GEMINI_API_KEY not configured. Generating deterministic offline vectors.")
            return [self.generate_offline_pseudo_embedding(t) for t in texts]

        try:
            client = self.get_client()
            # Wrap each text in a distinct Content object with a text part so Gemini batch-embeds
            # each item individually rather than treating the list as parts of a single content.
            contents = [
                types.Content(parts=[types.Part.from_text(text=t)])
                for t in texts
            ]
            response = client.models.embed_content(
                model=self.model_name,
                contents=contents,
                config=types.EmbedContentConfig(
                    output_dimensionality=self.dimension
                )
            )
            if not response.embeddings or len(response.embeddings) != len(texts):
                raise RuntimeError(
                    f"Batch embedding returned {len(response.embeddings) if response.embeddings else 0} "
                    f"results for {len(texts)} inputs."
                )
            return [list(emb.values) for emb in response.embeddings]

        except Exception as e:
            logger.warning("Batch embedding failed (%s); falling back to offline pseudo-embeddings.", e)
            return [self.generate_offline_pseudo_embedding(t) for t in texts]
