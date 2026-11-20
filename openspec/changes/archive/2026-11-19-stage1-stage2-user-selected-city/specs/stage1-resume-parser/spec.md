## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: Pre-Upload BOSS直聘 City Selection and 1:1 Mapping Gate
The Stage 1 upload interface (`static/index.html`, `static/app.js`, and `POST /api/resume/parse-profile`) MUST require the user to select a target city mapped 1:1 to BOSS直聘 official `CITY_CODE_MAP` before uploading a resume.

#### Scenario: Block resume upload in UI when target city is not selected
- **WHEN** a user attempts to click the resume upload button or drag-and-drop a resume file before selecting a target city in the UI dropdown
- **THEN** the UI SHALL block the upload request, highlight the city selector, and prompt the user to select a BOSS直聘 target city first

#### Scenario: Reject invalid city name not present in BOSS直聘 CITY_CODE_MAP
- **WHEN** `POST /api/resume/parse-profile` receives an explicit `target_city` value that does not map 1:1 to any entry in BOSS直聘 `CITY_CODE_MAP`
- **THEN** the backend SHALL reject the request with HTTP `400` and error message indicating an invalid BOSS直聘 target city
