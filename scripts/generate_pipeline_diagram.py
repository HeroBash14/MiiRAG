from pathlib import Path

import pymupdf


def generate_pipeline_svg() -> str:
    return """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1360 1020" width="1360" height="1020">
  <defs>
    <marker id="arr-green" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 1 L 10 5 L 0 9 z" fill="#059669" />
    </marker>
    <marker id="arr-blue" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 1 L 10 5 L 0 9 z" fill="#0284c7" />
    </marker>
    <marker id="arr-purple" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 1 L 10 5 L 0 9 z" fill="#7c3aed" />
    </marker>
    <marker id="arr-orange" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 1 L 10 5 L 0 9 z" fill="#ea580c" />
    </marker>
  </defs>

  <!-- Background: Clean Bright Surface -->
  <rect width="1360" height="1020" fill="#f8fafc" />

  <!-- Subtle Blueprint Grid Pattern -->
  <g opacity="0.35" stroke="#cbd5e1" stroke-width="1">
    <line x1="0" y1="100" x2="1360" y2="100" />
    <line x1="0" y1="280" x2="1360" y2="280" />
    <line x1="0" y1="590" x2="1360" y2="590" />
    <line x1="0" y1="840" x2="1360" y2="840" />
    <line x1="450" y1="0" x2="450" y2="1020" />
    <line x1="910" y1="0" x2="910" y2="1020" />
  </g>

  <!-- Header -->
  <g transform="translate(60, 40)">
    <rect x="-8" y="-6" width="46" height="46" rx="10" fill="#ecfdf5" stroke="#059669" stroke-width="2" />
    <text x="6" y="27" font-family="system-ui, -apple-system, sans-serif" font-size="22" font-weight="900" fill="#059669">&#9881;</text>
    <text x="50" y="20" font-family="system-ui, -apple-system, sans-serif" font-size="26" font-weight="800" fill="#0f172a">MiiRAG Ingestion &amp; Embedding Pipeline Flow</text>
    <text x="50" y="40" font-family="system-ui, -apple-system, sans-serif" font-size="14" font-weight="500" fill="#475569">Step-by-step lifecycle from raw multi-format upload to hybrid Markdown decoding, chunking &amp; dual-store sync</text>
  </g>

  <!-- ROW 1: STEPS 1, 2, 3 (Top 3 Cards) -->
  <!-- STEP 1: UPLOAD & VALIDATION -->
  <g transform="translate(60, 110)">
    <rect width="380" height="155" rx="12" fill="#ffffff" stroke="#10b981" stroke-width="2" />
    <rect x="18" y="14" width="60" height="20" rx="4" fill="#ecfdf5" />
    <text x="24" y="28" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="800" fill="#059669">STEP 1</text>
    <text x="88" y="29" font-family="system-ui, -apple-system, sans-serif" font-size="14" font-weight="700" fill="#0f172a">Upload &amp; Magic Validation</text>
    
    <text x="18" y="56" font-family="system-ui, -apple-system, sans-serif" font-size="12" fill="#334155">&#8226; Accepts: <tspan font-weight="700" fill="#0284c7">.pdf</tspan>, <tspan font-weight="700" fill="#0284c7">.docx</tspan>, <tspan font-weight="700" fill="#0284c7">.pptx</tspan> (Max 50MB)</text>
    <text x="18" y="78" font-family="system-ui, -apple-system, sans-serif" font-size="12" fill="#334155">&#8226; Magic header check: <tspan font-family="monospace" font-weight="700" fill="#0f172a">%PDF-</tspan> or <tspan font-family="monospace" font-weight="700" fill="#0f172a">PK\x03\x04</tspan></text>
    <text x="18" y="100" font-family="system-ui, -apple-system, sans-serif" font-size="12" fill="#334155">&#8226; Computes <tspan font-weight="700" fill="#0f172a">SHA-256</tspan> content hash for caching</text>
    <text x="18" y="122" font-family="system-ui, -apple-system, sans-serif" font-size="12" fill="#334155">&#8226; Saves original raw file to <tspan font-family="monospace" font-size="11" fill="#475569">storage/uploads/{kid}/</tspan></text>
    
    <rect x="18" y="132" width="85" height="18" rx="4" fill="#ecfdf5" />
    <text x="24" y="145" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="700" fill="#059669">&#10003; Validated</text>
  </g>

  <!-- Arrow Step 1 -> Step 2 -->
  <path d="M 440 187 L 500 187" stroke="#059669" stroke-width="2.5" fill="none" marker-end="url(#arr-green)" />

  <!-- STEP 2: VERSIONING & DIFFING -->
  <g transform="translate(500, 110)">
    <rect width="380" height="155" rx="12" fill="#ffffff" stroke="#cbd5e1" stroke-width="1.5" />
    <rect x="18" y="14" width="60" height="20" rx="4" fill="#f1f5f9" />
    <text x="24" y="28" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="800" fill="#475569">STEP 2</text>
    <text x="88" y="29" font-family="system-ui, -apple-system, sans-serif" font-size="14" font-weight="700" fill="#0f172a">Version Diff &amp; Deduplication</text>
    
    <text x="18" y="56" font-family="system-ui, -apple-system, sans-serif" font-size="12" fill="#334155">&#8226; Auto-increments version: <tspan font-weight="700" fill="#059669">v1 &rarr; v2 &rarr; v3</tspan></text>
    <text x="18" y="78" font-family="system-ui, -apple-system, sans-serif" font-size="12" fill="#334155">&#8226; Compares with <tspan font-family="monospace" font-size="11" fill="#0f172a">keep_document_ids</tspan></text>
    <text x="18" y="100" font-family="system-ui, -apple-system, sans-serif" font-size="12" fill="#334155">&#8226; <tspan font-weight="700" fill="#d97706">Reused Docs:</tspan> Skip re-extraction &amp; re-embedding!</text>
    <text x="18" y="122" font-family="system-ui, -apple-system, sans-serif" font-size="12" fill="#334155">&#8226; <tspan font-weight="700" fill="#059669">New Docs:</tspan> Enqueued for async processing</text>
    
    <rect x="18" y="132" width="135" height="18" rx="4" fill="#fef3c7" />
    <text x="24" y="145" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="700" fill="#92400e">&#9889; Zero Re-Embed Waste</text>
  </g>

  <!-- Arrow Step 2 -> Step 3 -->
  <path d="M 880 187 L 940 187" stroke="#059669" stroke-width="2.5" fill="none" marker-end="url(#arr-green)" />

  <!-- STEP 3: ASYNC WORKER ENQUEUE -->
  <g transform="translate(940, 110)">
    <rect width="360" height="155" rx="12" fill="#ffffff" stroke="#cbd5e1" stroke-width="1.5" />
    <rect x="18" y="14" width="60" height="20" rx="4" fill="#eff6ff" />
    <text x="24" y="28" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="800" fill="#1d4ed8">STEP 3</text>
    <text x="88" y="29" font-family="system-ui, -apple-system, sans-serif" font-size="14" font-weight="700" fill="#0f172a">Worker Dispatch</text>
    
    <text x="18" y="56" font-family="system-ui, -apple-system, sans-serif" font-size="12" fill="#334155">&#8226; Instant HTTP response: <tspan font-family="monospace" font-weight="700" fill="#059669">201 Created</tspan></text>
    <text x="18" y="78" font-family="system-ui, -apple-system, sans-serif" font-size="12" fill="#334155">&#8226; Document status set to <tspan font-weight="700" fill="#0284c7">processing</tspan></text>
    <text x="18" y="100" font-family="system-ui, -apple-system, sans-serif" font-size="12" fill="#334155">&#8226; Per-knowledge <tspan font-family="monospace" font-size="11" fill="#0f172a">asyncio.Lock</tspan> concurrency safety</text>
    <text x="18" y="122" font-family="system-ui, -apple-system, sans-serif" font-size="12" fill="#334155">&#8226; Background async execution loop</text>
    
    <rect x="18" y="132" width="105" height="18" rx="4" fill="#eff6ff" />
    <text x="24" y="145" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="700" fill="#1e40af">&#8987; Non-Blocking</text>
  </g>

  <!-- Connect Step 3 down to Step 4 -->
  <path d="M 1120 265 L 1120 315 L 680 315 L 680 345" stroke="#059669" stroke-width="2.5" fill="none" marker-end="url(#arr-green)" />

  <!-- STEP 4: HYBRID TWO-TIER DECODER (Broad Center Section) -->
  <g transform="translate(60, 350)">
    <rect width="1240" height="235" rx="14" fill="#ffffff" stroke="#0284c7" stroke-width="2" />
    
    <!-- Header Pill -->
    <rect x="25" y="16" width="60" height="22" rx="4" fill="#e0f2fe" />
    <text x="31" y="31" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="800" fill="#0284c7">STEP 4</text>
    <text x="95" y="32" font-family="system-ui, -apple-system, sans-serif" font-size="15" font-weight="700" fill="#0f172a">Page-Preserving Hybrid Markdown Decoder Architecture</text>
    <text x="25" y="55" font-family="system-ui, -apple-system, sans-serif" font-size="12" fill="#475569">Converts PDF, DOCX, and PPTX to structured Markdown with 1:1 page/slide alignment and visual snapshots</text>

    <!-- TIER 1: HIGH FIDELITY -->
    <g transform="translate(25, 70)">
      <rect width="580" height="145" rx="10" fill="#f0f9ff" stroke="#38bdf8" stroke-width="1.5" />
      <rect x="15" y="12" width="205" height="22" rx="4" fill="#0284c7" />
      <text x="23" y="27" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="800" fill="#ffffff">TIER 1 (Preferred / Headless Engine)</text>
      
      <text x="15" y="54" font-family="system-ui, -apple-system, sans-serif" font-size="12" fill="#0f172a">&#8226; <tspan font-weight="700">LibreOffice Headless (soffice):</tspan> Converts DOCX/PPTX &rarr; PDF</text>
      <text x="15" y="74" font-family="system-ui, -apple-system, sans-serif" font-size="12" fill="#0f172a">&#8226; <tspan font-weight="700">PyMuPDF find_tables():</tspan> Detects borders &amp; builds clean Markdown tables</text>
      <text x="15" y="94" font-family="system-ui, -apple-system, sans-serif" font-size="12" fill="#0f172a">&#8226; <tspan font-weight="700">PyMuPDF get_pixmap(dpi=150):</tspan> Renders PNG snapshot per page/slide</text>
      <text x="15" y="114" font-family="system-ui, -apple-system, sans-serif" font-size="12" fill="#0f172a">&#8226; <tspan font-weight="700">python-pptx Notes Enrichment:</tspan> Extracts Speaker Notes &rarr; <tspan font-family="monospace">&gt; **Catatan Presenter:**</tspan></text>
      
      <rect x="15" y="122" width="130" height="16" rx="4" fill="#bae6fd" />
      <text x="21" y="134" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="700" fill="#0369a1">&#10003; 100% Visual Fidelity</text>
    </g>

    <!-- TIER 2: PURE PYTHON AST FALLBACK -->
    <g transform="translate(635, 70)">
      <rect width="580" height="145" rx="10" fill="#fffbeb" stroke="#f59e0b" stroke-width="1.5" />
      <rect x="15" y="12" width="205" height="22" rx="4" fill="#d97706" />
      <text x="23" y="27" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="800" fill="#ffffff">TIER 2 (Pure Python AST Fallback)</text>
      
      <text x="15" y="54" font-family="system-ui, -apple-system, sans-serif" font-size="12" fill="#0f172a">&#8226; <tspan font-weight="700">Triggered if:</tspan> LibreOffice is missing or headless conversion fails</text>
      <text x="15" y="74" font-family="system-ui, -apple-system, sans-serif" font-size="12" fill="#0f172a">&#8226; <tspan font-weight="700">python-docx AST:</tspan> Traverses body elements (Headings 1-4, Bullets, Tables)</text>
      <text x="15" y="94" font-family="system-ui, -apple-system, sans-serif" font-size="12" fill="#0f172a">&#8226; <tspan font-weight="700">python-pptx AST:</tspan> Sorts shapes by (top, left) for natural reading order</text>
      <text x="15" y="114" font-family="system-ui, -apple-system, sans-serif" font-size="12" fill="#0f172a">&#8226; <tspan font-weight="700">Styles Extracted:</tspan> Bold (**), Italic (*), Monospace (`code`), Tables (|---|)</text>
      
      <rect x="15" y="122" width="130" height="16" rx="4" fill="#fde68a" />
      <text x="21" y="134" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="700" fill="#92400e">&#10003; Zero Dependencies</text>
    </g>
  </g>

  <!-- Arrow Step 4 down to Step 5 -->
  <path d="M 680 585 L 680 625" stroke="#059669" stroke-width="2.5" fill="none" marker-end="url(#arr-green)" />

  <!-- ROW 3: STEPS 5, 6, 7 (Bottom 3 Columns) -->
  <!-- STEP 5: TABLE-AWARE CHUNKING -->
  <g transform="translate(60, 630)">
    <rect width="380" height="210" rx="12" fill="#ffffff" stroke="#10b981" stroke-width="2" />
    <rect x="18" y="14" width="60" height="20" rx="4" fill="#ecfdf5" />
    <text x="24" y="28" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="800" fill="#059669">STEP 5</text>
    <text x="88" y="29" font-family="system-ui, -apple-system, sans-serif" font-size="14" font-weight="700" fill="#0f172a">Table-Aware Semantic Chunking</text>
    
    <text x="18" y="56" font-family="system-ui, -apple-system, sans-serif" font-size="12" fill="#334155">&#8226; Configuration: <tspan font-family="monospace" font-weight="700" fill="#0f172a">CHUNK_SIZE=1000, OVERLAP=150</tspan></text>
    <text x="18" y="78" font-family="system-ui, -apple-system, sans-serif" font-size="12" fill="#334155">&#8226; <tspan font-weight="700" fill="#059669">Table Header Preservation:</tspan></text>
    <text x="30" y="96" font-family="system-ui, -apple-system, sans-serif" font-size="11" fill="#475569">When a table splits across chunks, column header</text>
    <text x="30" y="112" font-family="system-ui, -apple-system, sans-serif" font-size="11" fill="#475569">row + <tspan font-family="monospace">|---|---|</tspan> is repeated on every chunk!</text>
    <text x="18" y="134" font-family="system-ui, -apple-system, sans-serif" font-size="12" fill="#334155">&#8226; <tspan font-weight="700" fill="#0284c7">1:1 Physical Page Number Alignment:</tspan></text>
    <text x="30" y="152" font-family="system-ui, -apple-system, sans-serif" font-size="11" fill="#475569">Chunks never cross page boundaries</text>
    <text x="18" y="174" font-family="system-ui, -apple-system, sans-serif" font-size="12" fill="#334155">&#8226; Separators: <tspan font-family="monospace">\n\n &rarr; \n &rarr; . &rarr; space</tspan></text>
    
    <rect x="18" y="185" width="130" height="18" rx="4" fill="#ecfdf5" />
    <text x="24" y="198" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="700" fill="#059669">&#10003; Context Integrity Kept</text>
  </g>

  <!-- Arrow Step 5 -> Step 6 -->
  <path d="M 440 735 L 500 735" stroke="#7c3aed" stroke-width="2.5" fill="none" marker-end="url(#arr-purple)" />

  <!-- STEP 6: DENSE VECTOR EMBEDDING -->
  <g transform="translate(500, 630)">
    <rect width="380" height="210" rx="12" fill="#ffffff" stroke="#7c3aed" stroke-width="2" />
    <rect x="18" y="14" width="60" height="20" rx="4" fill="#f3e8ff" />
    <text x="24" y="28" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="800" fill="#7e22ce">STEP 6</text>
    <text x="88" y="29" font-family="system-ui, -apple-system, sans-serif" font-size="14" font-weight="700" fill="#0f172a">Dense Vector Embedding</text>
    
    <text x="18" y="56" font-family="system-ui, -apple-system, sans-serif" font-size="12" fill="#334155">&#8226; SOTA Model: <tspan font-weight="700" fill="#7e22ce">BAAI/bge-m3</tspan></text>
    <text x="18" y="78" font-family="system-ui, -apple-system, sans-serif" font-size="12" fill="#334155">&#8226; Execution: Local PyTorch CUDA / Multi-CPU</text>
    <text x="18" y="100" font-family="system-ui, -apple-system, sans-serif" font-size="12" fill="#334155">&#8226; Embedding Dimension: <tspan font-weight="700" fill="#7e22ce">1024 float32 dimensions</tspan></text>
    <text x="18" y="122" font-family="system-ui, -apple-system, sans-serif" font-size="12" fill="#334155">&#8226; Batch Processing: <tspan font-family="monospace">EMBEDDING_BATCH_SIZE=16</tspan></text>
    <text x="18" y="144" font-family="system-ui, -apple-system, sans-serif" font-size="12" fill="#334155">&#8226; L2 Normalization: Unit vectors for Cosine distance</text>
    <text x="18" y="166" font-family="system-ui, -apple-system, sans-serif" font-size="12" fill="#334155">&#8226; Cloud Fallback: Google Vertex AI Gemini Embed</text>
    
    <rect x="18" y="185" width="125" height="18" rx="4" fill="#f3e8ff" />
    <text x="24" y="198" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="700" fill="#7e22ce">&#10003; 1024-dim Dense Vector</text>
  </g>

  <!-- Arrow Step 6 -> Step 7 -->
  <path d="M 880 735 L 940 735" stroke="#ea580c" stroke-width="2.5" fill="none" marker-end="url(#arr-orange)" />

  <!-- STEP 7: DUAL-STORE SYNC -->
  <g transform="translate(940, 630)">
    <rect width="360" height="210" rx="12" fill="#ffffff" stroke="#ea580c" stroke-width="2" />
    <rect x="18" y="14" width="60" height="20" rx="4" fill="#fff7ed" />
    <text x="24" y="28" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="800" fill="#c2410c">STEP 7</text>
    <text x="88" y="29" font-family="system-ui, -apple-system, sans-serif" font-size="14" font-weight="700" fill="#0f172a">Dual-Store Persistence</text>
    
    <text x="18" y="56" font-family="system-ui, -apple-system, sans-serif" font-size="12" font-weight="700" fill="#c2410c">&#9729; MinIO S3 Object Storage:</text>
    <text x="30" y="74" font-family="system-ui, -apple-system, sans-serif" font-size="11" fill="#475569">Uploads 150 DPI PNG page snapshots</text>
    <text x="30" y="90" font-family="system-ui, -apple-system, sans-serif" font-size="11" fill="#475569">Bucket: <tspan font-family="monospace">evorag / documents/{kid}/{doc_id}/</tspan></text>
    
    <text x="18" y="112" font-family="system-ui, -apple-system, sans-serif" font-size="12" font-weight="700" fill="#7e22ce">&#128450; PostgreSQL pgvector:</text>
    <text x="30" y="130" font-family="system-ui, -apple-system, sans-serif" font-size="11" fill="#475569">Inserts <tspan font-family="monospace">document_chunks</tspan> with HNSW vector index</text>
    
    <text x="18" y="152" font-family="system-ui, -apple-system, sans-serif" font-size="12" font-weight="700" fill="#059669">&#10003; Final Status Update:</text>
    <text x="30" y="170" font-family="system-ui, -apple-system, sans-serif" font-size="11" fill="#475569">Document &rarr; <tspan font-weight="700" fill="#059669">embedded</tspan> | Knowledge &rarr; <tspan font-weight="700" fill="#059669">done</tspan></text>
    
    <rect x="18" y="185" width="115" height="18" rx="4" fill="#ecfdf5" />
    <text x="24" y="198" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="700" fill="#065f46">&#10003; Fully Synchronized</text>
  </g>

  <!-- SUMMARY FOOTER BAR -->
  <g transform="translate(60, 860)">
    <rect width="1240" height="100" rx="12" fill="#ffffff" stroke="#cbd5e1" stroke-width="1.5" />
    <rect x="25" y="14" width="220" height="22" rx="4" fill="#eff6ff" />
    <text x="35" y="29" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="800" fill="#1e40af">KEY PIPELINE GUARANTEES</text>
    
    <text x="25" y="58" font-family="system-ui, -apple-system, sans-serif" font-size="12" fill="#0f172a">&#9989; <tspan font-weight="700">Superior Retrieval Accuracy:</tspan> Markdown tables &amp; speaker notes give LLMs exact column and presenter context</text>
    <text x="25" y="78" font-family="system-ui, -apple-system, sans-serif" font-size="12" fill="#0f172a">&#9989; <tspan font-weight="700">Visual Multimodal Grounding:</tspan> Every single chunk is tied 1:1 to an authentic MinIO page snapshot image</text>
    
    <text x="680" y="58" font-family="system-ui, -apple-system, sans-serif" font-size="12" fill="#0f172a">&#9989; <tspan font-weight="700">Zero Re-Embedding Waste:</tspan> Existing version documents are reused without re-embedding</text>
    <text x="680" y="78" font-family="system-ui, -apple-system, sans-serif" font-size="12" fill="#0f172a">&#9989; <tspan font-weight="700">Isolated Test Environment:</tspan> Tests strictly execute on <tspan font-family="monospace">miirag_test</tspan>, protecting production/dev data</text>
  </g>
</svg>"""

def render_pipeline_diagram():
    svg_str = generate_pipeline_svg()
    out_dir = Path("docs/images")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    svg_path = out_dir / "embedding_pipeline_flow.svg"
    png_path = out_dir / "embedding_pipeline_flow.png"
    
    svg_path.write_text(svg_str, encoding="utf-8")
    
    doc = pymupdf.open(stream=svg_str.encode("utf-8"), filetype="svg")
    pix = doc[0].get_pixmap(dpi=180)
    pix.save(str(png_path))
    print(f"Generated: {svg_path} and {png_path} ({pix.width}x{pix.height})")

if __name__ == "__main__":
    render_pipeline_diagram()
