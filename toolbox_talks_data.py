"""Structured content for the 19 NYC DOB Ch 33 toolbox talks (EN + ES).

This module is the SINGLE SOURCE OF TRUTH for talk content. The
generator (generate_toolbox_talks.py) reads from here and emits the
matching toolbox_talks_source/<slug>_<lang>.html files, which are
then rendered to PDF by apply_toolbox_talks_seed.py.

Each talk has:
  topic_number    int, unique
  slug            kebab-case filename stem
  category        Site / Fall / Scaffold / Demo / General
  ch33_ref        DOB Ch 33 section citation
  est_minutes     usually 15
  title_en / title_es
  why_en / why_es           2-3 sentences
  rules_en[] / rules_es[]   3-5 bullets (rules with section refs)
  do_en[] / do_es[]         3-5 action bullets
  dont_en[] / dont_es[]     3-5 don't bullets
  questions_en[] / questions_es[]  2-3 discussion questions

Spanish vocabulary: real NYC / Latin-American jobsite Spanish, NOT
classroom Spanish or Spanglish. Industry terms preserved (andamio,
arnés, casco, línea de vida, etc.).
"""

# Talks get added here as we author them. Authoring discipline:
# add ONE talk, regenerate HTMLs, render PDFs, verify single page,
# commit + push. Do NOT batch 19 in memory before any commit
# (context stall would lose work — per handoff).
TALKS = []
