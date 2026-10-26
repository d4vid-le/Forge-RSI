"""
SkillForge — data pipeline engine.

Stage 1 of the SkillForge training pipeline: take downloaded data in whatever
shape it arrives, normalise it into one training format, flag every defect,
drive line-by-line human review, and export one clean file.

    from pipeline import ingest_records, clean_records, Store, export_session

    records, quarantine, reports = ingest_records(["data/*.json"])
    records, stats = clean_records(records)
    with Store("data/skillforge.db") as st:
        sid = st.create_session(sources, config, stats)
        st.add_records(sid, records)

Command line: `python -m pipeline --help`
"""

# submodules first — `pipeline.ingest` is the module, `ingest_records` the helper
from . import schema, ingest, clean, store, export

from .schema import Record, render_chatml, parse_chatml, looks_like_chatml
from .ingest import IngestOptions, expand_paths, summarize
from .ingest import ingest as ingest_records
from .clean import clean_records, clean_record, CleanOptions, flag_summary
from .store import Store
from .export import export_session, auto_name, validate_export, dedupe_records

__all__ = [
    "schema", "ingest", "clean", "store", "export",
    "Record", "render_chatml", "parse_chatml", "looks_like_chatml",
    "ingest_records", "IngestOptions", "expand_paths", "summarize",
    "clean_records", "clean_record", "CleanOptions", "flag_summary",
    "Store",
    "export_session", "auto_name", "validate_export", "dedupe_records",
]

__version__ = "0.1.0"
