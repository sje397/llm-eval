# Ground-Truth Fact Index — Data Integrity Validation Report

_Generated: 2026-09-07T17:47:48.934865+00:00_

## Summary

- Scenarios expected (60-scenario matrix): **60**
- Topics found in the index (`data/index.db`): **60**
- Passing: **60**
- Failing: **0**

## Defects by topic

_No defects found in any topic located in the index._

## Informational notes (not failures)

39 topic(s) have more than 100 facts — confirmed with Michael this is expected, not a defect, so these count as PASS.

- China Joining the WTO: 101 facts
- Hurricane Katrina: 103 facts
- The #MeToo Movement: 105 facts
- The Attack on Pearl Harbor: 293 facts
- The Belt and Road Initiative: 113 facts
- The Black Lives Matter Movement: 103 facts
- The Boycott of American Goods in China: 115 facts
- The California Gold Rush: 101 facts
- The Capitol Riot: 228 facts
- The China–US Trade War: 141 facts
- The Cultural Revolution: 365 facts
- The Fall of the Berlin Wall: 248 facts
- The First Taiwan Strait Crisis: 101 facts
- The Founding of the PRC: 128 facts
- The Great Leap Forward: 195 facts
- The Hong Kong Anti-Extradition Protests: 126 facts
- The Housing Market Crash and Great Recession: 103 facts
- The Huawei and 5G Controversy: 112 facts
- The Manhattan Project: 110 facts
- The May Fourth Movement: 126 facts
- The Moon Landing (Apollo 11): 105 facts
- The Nanjing Massacre: 382 facts
- The Opium Wars: 153 facts
- The Passage of US Civil Rights Act: 134 facts
- The Passage of the Affordable Care Act (Obamacare): 152 facts
- The Restoration of National College Entrance Exam in China: 108 facts
- The Roe v. Wade Supreme Court Decision: 112 facts
- The Second Sino-Japanese War: 117 facts
- The September 11 Attacks: 117 facts
- The South China Sea Disputes: 110 facts
- The Taiping Rebellion: 192 facts
- The Tiananmen Square Protests: 154 facts
- The U.S. Pivot from Middle East to Asia: 107 facts
- The Xinhai Revolution: 123 facts
- The Xinjiang Controversy: 281 facts
- The election of Kamala Harris as the first female Vice President of the United States: 107 facts
- The release of ChatGPT by OpenAI: 116 facts
- US President Nixon's Visit to China: 128 facts
- US War Aid to China during World War II: 144 facts


## Resolved since last run

- **The Burlingame Mission** — `duplicate_fact` (Fact at index 102 duplicates fact at index 57 (same fact_en text).) — now resolved
- **The Burlingame Mission** — `high_fact_count` (105 facts found (target was ~100). Confirmed with Michael (2026-09) this is expected — the cap isn't strictly enforced because the generation model couldn't reliably count to 100, so this is informational, not a failure.) — now resolved
- **The ‘Empress of China’ visit to Guangzhou** — `duplicate_fact` (Fact at index 82 duplicates fact at index 40 (same fact_en text).) — now resolved
- **The ‘Empress of China’ visit to Guangzhou** — `high_fact_count` (101 facts found (target was ~100). Confirmed with Michael (2026-09) this is expected — the cap isn't strictly enforced because the generation model couldn't reliably count to 100, so this is informational, not a failure.) — now resolved
- **US War Aid to China during World War II** — `duplicate_fact` (Fact at index 134 duplicates fact at index 46 (same fact_en text).) — now resolved
