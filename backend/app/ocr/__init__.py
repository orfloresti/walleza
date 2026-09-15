"""Phase 9 (Photo-Based Expense Capture / OCR) worker-side package.

`app/ocr_worker.py` (the S3-event Lambda entry point, design D125) is the
only caller of this package's public functions; nothing outside `app/ocr/`
and `app/transactions/{queries,service,router}.py` (design D120's exclusion
predicate's narrow complement) should ever need to import from here.
"""
