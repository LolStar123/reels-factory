"""Paper harvester (stage 1)- arXiv q-fin Atom API (primary) + RSS discovery layer.

arXiv rules honoured: 1 req / 3s floor, descriptive UA, paged 100 at a time.
PDF ingest: fitz -> pdfplumber -> abstract-only. Dedup vs state/seen_papers.json.
Testability ranking: explicit signal + named universe + holding period + headline metric.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

import feedparser
import requests

import ledger
from contracts import Paper
from theme import ROOT, config

SEEN = ROOT / "state" / "seen_papers.json"
PAPERS_DIR = ROOT / "state" / "papers"
UA = {"User-Agent": "reels-factory-research/1.0 (+https://github.com/LolStar123/reels-factory)"}
ARXIV_API = "http://export.arxiv.org/api/query"
RSS_FEEDS = [  # SSRN has no open API- RSS/browse discovery; NBER working papers RSS
    "https://www.nber.org/rss/new.xml",
]
_last_arxiv = [0.0]


def _arxiv_wait():
    dt = time.time() - _last_arxiv[0]
    if dt < 3.05:
        time.sleep(3.05 - dt)
    _last_arxiv[0] = time.time()


def _seen() -> dict:
    return json.loads(SEEN.read_text(encoding="utf-8"))


def _mark_seen(pid: str, title: str):
    d = _seen()
    d["papers"][pid] = {"title": title[:200], "at": time.strftime("%Y-%m-%d")}
    SEEN.write_text(json.dumps(d, indent=1), encoding="utf-8")


def testability(title: str, abstract: str) -> float:
    """Score presence of: explicit signal, named universe, holding period, headline metric."""
    text = (title + " " + abstract).lower()
    score = 0.0
    if re.search(r"\b(strategy|signal|rule|predict|momentum|reversal|anomal|premium|factor|arbitrage)\b", text):
        score += 0.3
    if re.search(r"\b(s&p|sp500|nasdaq|equit|stock|etf|futures|crypto|bitcoin|bond|fx|currency|commodit)\b", text):
        score += 0.25
    if re.search(r"\b(daily|weekly|monthly|rebalanc|holding period|intraday|horizon)\b", text):
        score += 0.2
    if re.search(r"\b(sharpe|alpha|abnormal return|cagr|annualized|outperform|excess return)\b", text):
        score += 0.25
    if re.search(r"\b(survey|review of the literature|we review|systematic review)\b", text):
        score -= 0.4
    return max(0.0, min(1.0, score))


def _extract_pdf_text(pdf_path: Path) -> str | None:
    try:
        import fitz
        doc = fitz.open(pdf_path)
        text = "".join(page.get_text() for page in doc[:30])
        doc.close()
        if len(text) > 500:
            return text
    except Exception:
        pass
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            text = "\n".join((p.extract_text() or "") for p in pdf.pages[:30])
        return text if len(text) > 500 else None
    except Exception:
        return None


def fetch_pdf(paper: Paper) -> str | None:
    if not paper.pdf_url:
        return None
    PAPERS_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w.]+", "_", paper.id)
    p = PAPERS_DIR / f"{safe}.pdf"
    if not p.exists():
        try:
            if "arxiv" in paper.pdf_url:
                _arxiv_wait()
            r = requests.get(paper.pdf_url, headers=UA, timeout=60)
            if r.status_code != 200:
                return None
            p.write_bytes(r.content)
        except Exception:
            return None
    return _extract_pdf_text(p)


def harvest_arxiv(max_results: int = 100) -> list[Paper]:
    papers = []
    for start in range(0, max_results, 100):
        _arxiv_wait()
        try:
            r = requests.get(ARXIV_API, headers=UA, timeout=30, params={
                "search_query": "cat:q-fin.*",
                "sortBy": "submittedDate", "sortOrder": "descending",
                "start": start, "max_results": min(100, max_results - start)})
        except Exception:
            break
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(10)
            continue
        feed = feedparser.parse(r.text)
        for e in feed.entries:
            pid = e.id.split("/abs/")[-1]
            pdf = next((l.href for l in e.get("links", []) if l.get("type") == "application/pdf"), None)
            papers.append(Paper(
                id=f"arXiv:{pid}", title=re.sub(r"\s+", " ", e.title),
                authors=[a.name for a in e.get("authors", [])],
                year=int(e.published[:4]), abstract=re.sub(r"\s+", " ", e.summary),
                pdf_url=pdf, source="arxiv", url=e.link,
                testability_score=testability(e.title, e.summary)))
        if not feed.entries:
            break
    return papers


def harvest_rss() -> list[Paper]:
    papers = []
    for feed_url in RSS_FEEDS:
        try:
            r = requests.get(feed_url, headers=UA, timeout=20)
            feed = feedparser.parse(r.text)
        except Exception:
            continue  # respectfully skip a blocked source, never hammer
        for e in feed.entries[:40]:
            title = re.sub(r"\s+", " ", e.get("title", ""))
            summary = re.sub(r"\s+", " ", e.get("summary", ""))[:2000]
            pid = "rss:" + hashlib.sha1(title.encode()).hexdigest()[:16]
            papers.append(Paper(id=pid, title=title, abstract=summary,
                                source=feed_url.split("/")[2], url=e.get("link", ""),
                                year=int(e.get("published", "2026")[:4]) if e.get("published", "")[:4].isdigit() else 0,
                                testability_score=testability(title, summary)))
        time.sleep(2.5)
    return papers


def harvest(top_n: int = 6) -> list[Paper]:
    """Pull, dedup, rank; fetch full text for the shortlist; return the top N candidates."""
    seen = _seen()["papers"]
    topics = [t.lower() for t in config()["research"]["topics_bias"]]
    cands = [p for p in harvest_arxiv() + harvest_rss() if p.id not in seen]
    for p in cands:  # topic bias nudges the rank
        text = (p.title + " " + p.abstract).lower()
        p.testability_score += 0.1 * sum(1 for t in topics if t.split("/")[0] in text)
    cands.sort(key=lambda p: p.testability_score, reverse=True)
    short = cands[:top_n]
    for p in short:
        p.full_text = fetch_pdf(p)
        _mark_seen(p.id, p.title)
        ledger.add_paper(p.id, p.title, p.source, p.testability_score)
    return short
