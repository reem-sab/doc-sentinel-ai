import textstat
import re

def analyze_document_for_ai(text):
    # 1. READABILITY SCORE (0-100%)
    # We use Flesch Reading Ease. 60-70 is the "Sweet Spot" for AI.
    raw_readability = textstat.flesch_reading_ease(text)
    # Clamp the score between 0 and 100 for the UI
    readability_score = max(0, min(100, raw_readability))

    # 2. DISCOVERABILITY SCORE (0-100%)
    # We check for structural elements that help AI "scrapers" and "crawlers"
    disc_points = 0
    
    # Does it have Markdown/HTML Headers? (Crucial for AI Chunking)
    if re.search(r'(#+ |<h[1-6]>)', text):
        disc_points += 40
        
    # Does it have a Summary or Intro section?
    if "summary" in text.lower()[:500] or "introduction" in text.lower()[:500]:
        disc_points += 30
        
    # Is the text length optimal? (Too short is "thin content", too long is "noisy")
    word_count = len(text.split())
    if 300 <= word_count <= 1500:
        disc_points += 30
    elif word_count > 1500:
        disc_points += 15 # Partial points for being too long
        
    # 3. GENERATE IMPROVEMENTS
    tips = []
    if readability_score < 60:
        tips.append("Sentence structure is complex. Shorten sentences for better AI 'zero-shot' understanding.")
    if not re.search(r'(#+ |<h[1-6]>)', text):
        tips.append("Add Markdown headers (e.g., # Header) to help AI models 'chunk' your data.")
        
    return {
        "readability": readability_score,
        "discoverability": disc_points,
        "tips": tips
    }
