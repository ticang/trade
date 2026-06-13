"""Probe Chinese-FinBERT sentiment scoring on Chinese financial text."""
from functools import lru_cache


@lru_cache(maxsize=1)
def _pipeline():
    from transformers import AutoTokenizer, AutoModelForSequenceClassification

    name = "yiyanghkust/finbert-tone-chinese"  # Chinese financial sentiment; M-1a candidate
    tok = AutoTokenizer.from_pretrained(name)
    model = AutoModelForSequenceClassification.from_pretrained(name)
    return tok, model


def _label_weight(label: str) -> float:
    low = label.lower()
    if "pos" in low:
        return 1.0
    if "neg" in low:
        return -1.0
    return 0.0


def score_sentiment(text: str) -> float:
    """Return sentiment in [-1, 1]; positive = bullish.

    Computed as the softmax-weighted sum of per-label weights
    (Positive=+1, Negative=-1, Neutral=0), yielding a signed probability mass.
    """
    import torch

    tok, model = _pipeline()
    inputs = tok(text, return_tensors="pt", truncation=True, max_length=512)
    with torch.no_grad():
        logits = model(**inputs).logits[0]
        probs = torch.softmax(logits, dim=0)
    id2label = model.config.id2label
    s = sum(_label_weight(lab) * float(probs[i]) for i, lab in id2label.items())
    return float(s)
