---
name: job-apply
description: Evaluate a job posting against Kalik's CV and prepare an application (fit analysis, cover letter, interview prep). Use when Kalik sends a vacancy link or text, or asks to apply / write a cover letter.
---

# Job application helper

Inputs: a vacancy URL or pasted text. Files: `/workspace/work/jobs/cv.md` (facts), `/workspace/work/jobs/search-profile.md` (constraints, links, writing rules).

## Steps
1. Get the vacancy: `web_extract` the URL (or use the pasted text). If the page needs a login (LinkedIn, hh), ask Kalik to paste the text instead of trying to log in.
2. Read cv.md and search-profile.md.
3. Hard filters from search-profile.md (location, sponsorship, Russia/Belarus, seniority). If one fails, say which one in one line and stop unless Kalik insists.
4. Short company check with `web_search`: what they do, size, stack, remote policy; 3-5 bullets with sources.
5. Answer in Russian, in this order:
   - **Вердикт:** подаваться / подаваться с оговорками / не подаваться, one sentence why.
   - **Совпадения:** requirement → matching fact from cv.md (max 6).
   - **Пробелы:** missing requirements and how to address them honestly.
   - **Сопроводительное письмо** in the vacancy's language, following the writing rules; site link with the right UTM and `&utm_content=<company>`.
   - **К собеседованию:** 5 likely questions for this role with 1-2 line answer hints based on cv.md.
6. Never send, submit or log in anywhere. Kalik applies himself.
7. Save the result to `/workspace/work/jobs/applications/<YYYY-MM-DD>-<company>-<role>.md` so it can be found later.
