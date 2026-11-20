# stage1-resume-parser Specification

## Purpose
Stage 1 (`core/resume_parser.py`, endpoint `POST /api/resume/parse-profile`) provides pure in-memory security validation, multimodal document/image reading, deterministic PII sanitization, and structured 9-field candidate profile extraction (`CandidateProfileSchema`) using `gemini-3.8-flash` (`temperature=0.1`) as the default extraction model and `gemini-4-argon` (`temperature=0.0`) as the default LLM-as-a-Judge evaluation model in `eval/stage1_eval/`.

## Requirements

### Requirement: In-Memory File Security and Magic Bytes Validation
The `core/resume_parser.py` module SHALL validate all uploaded resume files (`raw_bytes` and `filename`) purely in memory (`io.BytesIO`) without writing raw user files to disk, and MUST enforce a five-layer security gate (`validate_and_detect_resume_format`) before invoking any parser or LLM call.

#### Scenario: Reject empty resume file
- **WHEN** a user uploads a file with `len(raw_bytes) == 0` or a text file containing only whitespace characters
- **THEN** the parser SHALL abort processing immediately and raise `ResumeValidationError` with `error_code="EMPTY_FILE"`

#### Scenario: Reject oversized resume file exceeding 10MB
- **WHEN** a user uploads a file with `len(raw_bytes) > 10 * 1024 * 1024` bytes (`MAX_RESUME_BYTES`)
- **THEN** the parser SHALL abort processing immediately and raise `ResumeValidationError` with `error_code="FILE_TOO_LARGE"`

#### Scenario: Reject unsupported file extension
- **WHEN** a user uploads a file whose extension is not in `{.pdf, .docx, .png, .jpg, .jpeg, .webp, .txt, .md}` (such as `.doc`, `.zip`, or `.exe`)
- **THEN** the parser SHALL abort processing immediately and raise `ResumeValidationError` with `error_code="UNSUPPORTED_EXTENSION"`

#### Scenario: Reject spoofed file header magic bytes
- **WHEN** a user uploads a file whose binary magic header does not match its declared extension (such as a JPEG or executable renamed to `.pdf`, an HTML script renamed to `.png`, or a non-Word archive renamed to `.docx` lacking `word/document.xml`)
- **THEN** the parser SHALL abort processing immediately and raise `ResumeValidationError` with `error_code="INVALID_MAGIC_BYTES"`

#### Scenario: Reject DOCX zip bomb or XXE entity injection
- **WHEN** a `.docx` archive has an uncompressed total size exceeding `20 * 1024 * 1024` bytes (`MAX_DOCX_UNCOMPRESSED_BYTES`) or its `word/document.xml` header contains `<!DOCTYPE` or `<!ENTITY` declarations
- **THEN** the parser SHALL abort extraction immediately and raise `ResumeValidationError` to block Zip Bomb and XXE attacks

#### Scenario: Reject prompt injection payload
- **WHEN** extracted resume text matches known prompt-hijacking patterns (such as `"ignore all previous instructions"`, `"system prompt"`, or `"忽略之前的所有指令"`)
- **THEN** the parser SHALL abort processing immediately and raise `ResumeValidationError` with `error_code="PROMPT_INJECTION_DETECTED"`

#### Scenario: Reject non-resume document content
- **WHEN** extracted text from a valid file format matches fewer than 2 resume semantic indicator categories (such as uploading a restaurant menu or arbitrary code snippet)
- **THEN** the parser SHALL abort processing immediately and raise `ResumeValidationError` with `error_code="NOT_A_RESUME"`

### Requirement: Adaptive Multimodal and DOCX Text Routing
The `core/resume_parser.py` module SHALL route visual documents and structured text documents through dedicated in-memory extraction channels to preserve layout fidelity and eliminate duplicate paragraphs.

#### Scenario: Route PDF and image resumes through native multimodal blocks
- **WHEN** the validated file format is `.pdf` (`application/pdf`) or an image (`.png`, `.jpg`, `.jpeg`, `.webp`)
- **THEN** the parser SHALL encode `raw_bytes` as Base64 multimodal content blocks (`type="document"` or `type="image"`) and pass them directly to `create_interaction_with_fallback`

#### Scenario: Deduplicate nested textboxes in Chinese Word DOCX resumes
- **WHEN** the validated file format is `.docx` and `extract_text_from_docx` parses `word/document.xml`
- **THEN** the parser SHALL skip outer `<w:p>` container nodes that wrap nested `<w:p>` elements (such as `w:txbxContent` drawing textboxes and `mc:AlternateContent` fallbacks), deduplicate leaf paragraph lines in order, and apply pre-LLM PII masking via `mask_sensitive_pii`

### Requirement: Nine-Field Structured Candidate Profile Extraction
The `extract_resume_profile_with_gemini` function SHALL invoke `gemini-3.8-flash` (`DEFAULT_STAGE1_EXTRACT_MODEL`) at `temperature=0.1` with `CandidateProfileSchema` to produce a normalized candidate profile JSON, and MUST attach the user-selected BOSS直聘 target city (`target_city` and `target_city_code`) into the Stage 1 output JSON passed downstream to Stage 2.

#### Scenario: Extract candidate title prioritizing explicit job intention
- **WHEN** the resume explicitly states a target job role or job intention
- **THEN** `candidate_title` SHALL extract that explicit target role
- **AND** when the resume does not state an explicit target job role, `candidate_title` SHALL synthesize a precise professional title from the candidate's most recent 1 to 2 work experiences

#### Scenario: Extract complete higher education trajectory across bachelor master and doctoral degrees
- **WHEN** the resume contains multiple higher education degrees (such as both Bachelor and Master degrees, or up to a Doctoral degree)
- **THEN** `education_summary` SHALL capture all higher education degree levels, majors, and university names rather than keeping only the highest degree

#### Scenario: Attach user-selected BOSS直聘 target city into Stage 1 output JSON
- **WHEN** a user selects a valid BOSS直聘 city (such as `"杭州"`, mapped 1:1 to `"101210100"`) in the UI before uploading a resume and submits it to `POST /api/resume/parse-profile`
- **THEN** after resume content parsing completes, Stage 1 SHALL inject `"target_city": "杭州"`, `"target_city_code": "101210100"`, and `"target_cities": ["杭州"]` into the Stage 1 output JSON (`profile` and top-level response) for downstream handoff to Stage 2

#### Scenario: Fallback target cities to highest degree university location when no explicit UI city is provided
- **WHEN** `extract_resume_profile_with_gemini` is invoked offline or in benchmark evaluation without an explicit `target_city` parameter and the resume does not mention any target or work city
- **THEN** `target_cities` SHALL populate the city where the candidate's highest-degree university is located

#### Scenario: Normalize explicit or inferred monthly salary floor
- **WHEN** extracting `inferred_salary_floor`
- **THEN** the parser SHALL preserve the exact monthly figure if explicitly stated in the resume, or conservatively infer a monthly floor from experience and city if unstated, and normalize the string into `"X.Xw"` format (bounded within `[0.3w, 8.0w]`)

### Requirement: Pre-Upload BOSS直聘 City Selection and 1:1 Mapping Gate
The Stage 1 upload interface (`static/index.html`, `static/app.js`, and `POST /api/resume/parse-profile`) MUST require the user to select a target city mapped 1:1 to BOSS直聘 official `CITY_CODE_MAP` before uploading a resume.

#### Scenario: Block resume upload in UI when target city is not selected
- **WHEN** a user attempts to click the resume upload button or drag-and-drop a resume file before selecting a target city in the UI dropdown
- **THEN** the UI SHALL block the upload request, highlight the city selector, and prompt the user to select a BOSS直聘 target city first

#### Scenario: Reject invalid city name not present in BOSS直聘 CITY_CODE_MAP
- **WHEN** `POST /api/resume/parse-profile` receives an explicit `target_city` value that does not map 1:1 to any entry in BOSS直聘 `CITY_CODE_MAP`
- **THEN** the backend SHALL reject the request with HTTP `400` and error message indicating an invalid BOSS直聘 target city

### Requirement: Dual-End Deterministic PII Sanitization
The `mask_sensitive_pii` and `sanitize_and_normalize_profile` functions MUST strip all personal identifiable information before returning the profile or passing it to Stage 2.

#### Scenario: Mask phone numbers ID numbers emails and granular street or dormitory addresses
- **WHEN** `sanitize_and_normalize_profile` processes any model-extracted or fallback `CandidateProfileSchema`
- **THEN** it SHALL mask all 11-digit mainland mobile numbers (`138****0000`), 18-digit ID numbers (`420106********1234`), email addresses, candidate names, and granular street/building/dormitory addresses (`[地址已脱敏]`) across all 9 fields

### Requirement: Stage 1 Automated Benchmark and LLM-as-a-Judge Gate
The Stage 1 evaluation suite (`eval/stage1_eval/evaluate_stage1_parser.py` and `eval/stage1_eval/llm_judge_stage1.py`) SHALL verify extraction quality against `eval/dataset/stage1/` using `gemini-4-argon` (`DEFAULT_LLM_JUDGE_MODEL`) at `temperature=0.0` and archive reports under `eval/runs/`.

#### Scenario: Enforce zero tolerance on explicit numbers and 40 percent tolerance on inferred salary floor
- **WHEN** `llm_judge_stage1.py` evaluates an extracted profile against `ground_truth` on `QUAL-01` through `QUAL-09`
- **THEN** `gemini-4-argon` SHALL enforce strict zero tolerance on explicitly stated salary figures, years of experience, university names, and quantitative business metrics
- **AND** when `inferred_salary_floor` is inferred from experience without an explicit salary in the resume, `llm_judge_stage1.py` SHALL allow a `±40%` tolerance interval without penalty

#### Scenario: Enforce 100 percent interception rate on disqualified attack samples
- **WHEN** `evaluate_stage1_parser.py` runs against `DISQ-01` through `DISQ-09` in `eval/dataset/stage1/disqualified_manifest.json`
- **THEN** all 9 abnormal samples SHALL be blocked (`disqualified_interception_rate == 1.0`) with `actual_error_code == expected_error_code`
