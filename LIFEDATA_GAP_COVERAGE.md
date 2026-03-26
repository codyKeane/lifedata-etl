 The System Today                                                                                                  
   
  LifeData V4 is a half-tested application with a production-grade ingestion engine and an untested interpretation  
  layer. The coverage data tells the story clearly:               
                                                                                                                    
  - Data in: 85-100% covered. Bulletproof.                                                                          
  - Data out: 0-25% covered. Unverified.
                                                                                                                    
  The system reliably collects, parses, deduplicates, and stores behavioral data. But the layer that gives that data
   meaning — correlations, anomaly detection, hypothesis testing, daily reports, derived metrics like               
  digital_restlessness and cognitive_load_index — has never been validated against known inputs. You are making life
   decisions based on analytics that have never been proven correct.

  What "Production-Ready" Means for This System                                                                     
   
  This is not a SaaS product. It does not need horizontal scaling, multi-tenancy, or five-nines uptime.             
  Production-ready for a personal data observatory means three things:
                                                                                                                    
  1. Correctness: Every number in the daily report is mathematically verifiable                                     
  2. Reliability: No silent failures — if data is missing or wrong, the system tells you
  3. Security: PII is protected against realistic threats (device theft, backup leak)                               
                                                                                                                    
  Against those three criteria, here's the gap map.                                                                 
                                                                                                                    
  Gap 1: The Interpretation Layer Has Zero Verification                                                             
                                                                  
  This is the primary gap. Four files that produce the system's analytical output have 0% test coverage:            
                                                                  
  ┌─────────────────────────────┬───────┬────────────────────────────┬──────────────────────────────────────────┐   
  │            File             │ Stmts │        What it does        │                   Risk                   │ 
  ├─────────────────────────────┼───────┼────────────────────────────┼──────────────────────────────────────────┤ 
  │ analysis/correlator.py      │ 83    │ Pearson/Spearman           │ Every correlation number in reports is   │ 
  │                             │       │ correlation engine         │ unverified                               │ 
  ├─────────────────────────────┼───────┼────────────────────────────┼──────────────────────────────────────────┤   
  │ analysis/hypothesis.py      │ 33    │ 10 pre-defined hypothesis  │ "Supported/Not Supported" conclusions    │
  │                             │       │ tests                      │ are untested                             │   
  ├─────────────────────────────┼───────┼────────────────────────────┼──────────────────────────────────────────┤
  │ analysis/reports.py         │ 183   │ Daily markdown report      │ The document you read every morning has  │   
  │                             │       │ generator                  │ never been validated                     │   
  ├─────────────────────────────┼───────┼────────────────────────────┼──────────────────────────────────────────┤
  │ modules/media/transcribe.py │ 75    │ Whisper transcription      │ Audio processing pipeline untested       │   
  │                             │       │ orchestration              │                                          │   
  └─────────────────────────────┴───────┴────────────────────────────┴──────────────────────────────────────────┘
                                                                                                                    
  Eight module.py files with post_ingest() logic sit between 10-25%. These compute the derived metrics that feed    
  into everything above. The chain of unverified computation is:
                                                                                                                    
  Raw events → post_ingest() [10-25% covered] → derived metrics → correlator [0%] → hypothesis [0%] → report [0%]
                                                                                                                    
  What needs to happen:
                                                                                                                    
  Write tests with known-input/known-output pairs. Not mock-heavy unit tests — actual statistical validation:       
   
  - Feed the correlator two perfectly correlated series. Assert r=1.0, p<0.001.                                     
  - Feed it two uncorrelated series. Assert r≈0, p>0.05.          
  - Feed the hypothesis engine a case where direction="negative", r=-0.8, p=0.01. Assert supported=True.            
  - Feed the hypothesis engine a case where direction="negative", r=0.8, p=0.01. Assert supported=False.            
  - Feed reports.py a populated database fixture. Assert the output contains expected sections, values, and         
  formatting.                                                                                                       
  - Feed behavior's post_ingest() a day with zero screen events. Assert no division-by-zero crash.                  
  - Feed cognition's post_ingest() a day with one data point. Assert graceful degradation, not a statistics error.  
                                                                                                                    
  Target: bring analysis/ from 21% to 70%+. Bring the worst module.py files from 10-25% to 50%+. This is            
  approximately 20-30 hours of focused test writing.                                                                
                                                                                                                    
  Gap 2: The Analysis Layer is Structurally Coupled                                                                 
   
  The analysis layer hardcodes ~20 source_module strings and 9 sets of magic-number thresholds. This means:         
                                                                  
  - Renaming body.derived to body.sleep_metrics silently breaks anomaly detection                                   
  - Adding a 12th module produces no analysis output until someone edits reports.py
  - The 14:00 caffeine threshold, the 6-hour sleep threshold, the 20% battery threshold — none of these are         
  configurable or justified by the data                                                                             
                                                                                                                    
  What needs to happen:                                                                                             
                                                                  
  This is the largest single refactor. Two options:                                                                 
                                                                  
  Option A (Recommended): Metrics Registry pattern. Each module declares its analytical endpoints in a structured   
  format (e.g., a dict returned by a new get_metrics_manifest() method). The analysis layer reads the registry
  instead of hardcoding module names. Reports and anomaly patterns become data-driven.                              
                                                                  
  Option B: Fully leverage get_daily_summary(). The interface already exists but the analysis layer ignores it.     
  Refactor reports.py and anomaly.py to consume summaries rather than raw SQL.
                                                                                                                    
  Either option eliminates the hardcoded coupling. Thresholds move to config.yaml. Estimated effort: 10-15 hours.   
   
  Gap 3: The Security Surface Has One Real Hole                                                                     
                                                                  
  The HMAC key hostname fallback in social/parsers.py:32-35 is the only exploitable security vulnerability.         
  Everything else — file permissions, path traversal protection, SQL injection prevention, config validation — is
  solid.                                                                                                            
                                                                  
  What needs to happen:

  1. Remove the hostname fallback from _PII_HMAC_KEY (15 minutes)                                                   
  2. Add PII_HMAC_KEY to .env.example with generation instructions (5 minutes)
  3. Raise RuntimeError if the key is missing at module load (5 minutes)                                            
                                                                                                                    
  That's it. The PII-at-rest encryption question (Gemini's Fernet recommendation) is a valid long-term concern, but 
  the HMAC fix closes the immediate hole. Total: 25 minutes.                                                        
                                                                                                                    
  Gap 4: No Automated Quality Gate                                

  605 tests exist. mypy strict mode exists. ruff linting exists. None of it runs automatically. Every quality check 
  is a make command that a human must remember to run.
                                                                                                                    
  What needs to happen:                                           

  A GitHub Actions workflow with three jobs:                                                                        
   
  test:      pytest tests/ -v --timeout=30                                                                          
  typecheck: mypy --strict core/                                                                                    
  lint:      ruff check core/ modules/ analysis/ scripts/
                                                                                                                    
  Triggers on push to main. Blocks merge if any job fails. 2 hours to set up.                                       
                                                                                                                    
  Gap 5: Scripts Are a Black Box                                                                                    
                                                                  
  All 8 scripts (833 statements) have 0% coverage. These are the system's interface with the outside world — API    
  calls, web scraping, sensor processing. They handle network failures, rate limiting, data format changes, and
  malformed responses. None of this is tested.                                                                      
                                                                  
  What needs to happen:

  Mock-based tests for each script's core logic:                                                                    
  - _http.py: Test retry_get with mock responses (200, 429, 500, timeout)
  - fetch_news.py: Test sentiment extraction with known headlines                                                   
  - fetch_markets.py: Test price parsing with known API response shapes
  - process_sensors.py: Test windowed aggregation with synthetic accelerometer data                                 
                                                                                                                    
  This doesn't require API access. Use unittest.mock.patch on requests.get. 6-8 hours.                              
                                                                                                                    
  The Execution Plan                                                                                                
                                                                                                                    
  Sequenced by dependency order, not just priority:                                                                 
   
  Week 1 (3 hours):                                                                                                 
  ├── Fix HMAC key fallback                    [Gap 3, 25 min]    
  ├── Fix hypothesis parentheses               [5 min]                                                              
  ├── Fix Schumann regex                       [5 min]                                                              
  ├── Add cognition parser assertion           [1 min]                                                              
  ├── Clarify hypothesis naming                [5 min]                                                              
  ├── Standardize derived metric timestamps    [Gap 1 prerequisite, 2 hours]
  │   └── Required before writing post_ingest tests                                                                 
  │       because non-deterministic timestamps make                                                                 
  │       test assertions unreliable                                                                                
  │                                                                                                                 
  Week 2-3 (20-30 hours):                                                                                           
  ├── Write analysis layer tests               [Gap 1]                                                              
  │   ├── correlator.py known-input tests      [4 hours]
  │   ├── hypothesis.py direction tests        [2 hours]                                                            
  │   ├── reports.py fixture-based tests       [4 hours]                                                            
  │   └── anomaly.py pattern tests             [3 hours]                                                            
  ├── Write post_ingest() tests                [Gap 1]                                                              
  │   ├── behavior edge cases                  [4 hours]          
  │   ├── cognition normalization              [3 hours]                                                            
  │   ├── body/social/oracle/world basics      [4 hours]                                                            
  │   └── meta submodule tests                 [3 hours]                                                            
  ├── Document CSV parser assumption           [Gap 1, 30 min]                                                      
  │                                                                                                                 
  Week 4 (12-17 hours):                                           
  ├── Refactor analysis layer                  [Gap 2, 10-15 hours]                                                 
  │   ├── Implement metrics registry OR                                                                             
  │   │   refactor to use get_daily_summary()
  │   ├── Move thresholds to config.yaml                                                                            
  │   └── Add WARNING logs for missing metrics                    
  ├── Set up GitHub Actions CI                 [Gap 4, 2 hours]                                                     
  │                                                               
  Week 5-6 (8 hours, can overlap):                                                                                  
  ├── Write script tests                       [Gap 5, 6-8 hours]                                                   
  ├── Create .env.example                      [15 min]                                                             
  └── Remaining Tier 3-4 cleanup               [3-4 hours]                                                          
      ├── Centralize timezone offset                                                                                
      ├── Extract correlator helper                                                                                 
      ├── Move app classification to config                                                                         
      └── Standardize cursor handling                                                                               
                                                                                                                    
  Total: approximately 45-55 hours of focused work across 5-6 weeks.                                                
                                                                                                                    
  After This Work Is Done                                                                                           
                                                                  
  The system will have:
  - ~75% overall coverage (up from 50%), with the interpretation path at 60-80%
  - Zero hardcoded module references in the analysis layer                                                          
  - Configurable thresholds for all anomaly patterns      
  - Automated CI that catches regressions before they hit main                                                      
  - Sealed PII protection with mandatory HMAC key                                                                   
  - Deterministic derived metrics that produce identical results across re-runs                                     
  - Tested API integration with mock-based validation of retry logic                                                
                                                                                                                    
  At that point, the system meets production requirements for a personal data observatory. The remaining Phase 4    
  items (PII encryption at rest, real-time ingestion, vaderSentiment replacement) are genuine strategic decisions   
  that depend on how the system's use case evolves — not gaps that need filling.
