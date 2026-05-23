# Singapore Policy Auto-Update System

## NanoClaw scheduled tasks to keep your agent permanently current

Send each command block to your agent in WhatsApp or Telegram exactly as written. The agent will create the scheduled tasks and confirm each one.

---

## HOW SCHEDULED TASKS WORK IN NANOCLAW

NanoClaw runs scheduled tasks in the background. Each task can:

- Fetch and ingest URLs automatically
- Summarise what changed and message you
- Only wake the LLM if something actually changed (saves API cost)
- Run on any cron schedule (daily, weekly, monthly, on specific dates)

---

## BLOCK 1 — DAILY MONITORING (every morning at 7:00am)

Send this to your agent:

```
Set up a scheduled task: every morning at 7:00am, check the following
Singapore government newsroom pages for any new press releases or
policy announcements published in the last 24 hours. If anything new
is found, ingest it and send me a brief summary of what changed. If
nothing new, stay silent.

Pages to check:
- https://www.msf.gov.sg/media-room
- https://www.hdb.gov.sg/cs/infoweb/about-us/news-and-publications/press-releases
- https://www.mom.gov.sg/newsroom
- https://www.moh.gov.sg/news-highlights
- https://www.cpf.gov.sg/member/infohub/news
- https://www.iras.gov.sg/news-events-and-media
- https://www.ica.gov.sg/news-and-publications
- https://www.moe.gov.sg/news

Name this task: daily-policy-watch
```

---

## BLOCK 2 — WEEKLY DIGEST (every Monday at 8:00am)

Send this to your agent:

```
Set up a scheduled task: every Monday at 8:00am, check the following
sources for any new content published in the past 7 days. Ingest
anything new, then send me a structured weekly digest with:

1. New policy announcements (any agency)
2. New Parliamentary questions and replies
3. New Budget or COS statements
4. Any changes to eligibility criteria or scheme amounts
5. Upcoming deadlines or application windows I should know about

Sources to check:
- https://www.mof.gov.sg/news-resources/newsroom
- https://www.pmo.gov.sg/newsroom
- https://sprs.parl.gov.sg/search/
- https://singaporebudget.gov.sg
- https://www.reach.gov.sg/info-centre/news-and-press-releases
- https://www.sgpc.gov.sg
- https://supportgowhere.life.gov.sg

Name this task: weekly-policy-digest
```

---

## BLOCK 3 — BUDGET SEASON WATCH (February–March, daily)

Singapore Budget is announced in February. COS debates run in March. These are the most important policy update periods of the year.

Send this to your agent:

```
Set up a scheduled task: every day from 1 February to 31 March,
check the following pages for Budget and Committee of Supply updates.
Ingest all new content immediately and send me a same-day summary.
This is the most critical policy update period — do not miss anything.

Pages to check:
- https://singaporebudget.gov.sg
- https://www.mof.gov.sg/news-resources/newsroom
- https://www.pmo.gov.sg/newsroom
- https://www.msf.gov.sg/media-room
- https://www.hdb.gov.sg/cs/infoweb/about-us/news-and-publications/press-releases
- https://www.mom.gov.sg/newsroom
- https://www.moh.gov.sg/news-highlights
- https://www.cpf.gov.sg/member/infohub/news
- https://sprs.parl.gov.sg/search/

Name this task: budget-season-watch
```

---

## BLOCK 4 — PARLIAMENTARY SITTING ALERTS (every Tuesday)

Parliament typically sits on Tuesdays–Thursdays during each session. Parliamentary Questions (PQs) and replies often contain important policy clarifications relevant to MPS cases.

Send this to your agent:

```
Set up a scheduled task: every Tuesday, Wednesday, and Thursday at
6:00pm, check if Parliament sat today by fetching:
https://www.parliament.gov.sg/parliamentary-business/order-papers-agenda

If Parliament sat, fetch the day's questions and replies from:
https://sprs.parl.gov.sg/search/

Ingest any new questions and ministerial replies related to: housing,
CPF, social assistance, healthcare, employment, immigration, education,
or transport. Send me a summary of key policy clarifications made in
Parliament today.

Name this task: parliament-sitting-watch
```

---

## BLOCK 5 — MONTHLY DEEP REFRESH (1st of every month, 6:00am)

Send this to your agent:

```
Set up a scheduled task: on the 1st of every month at 6:00am,
do a comprehensive refresh of current policy pages. Re-ingest the
following pages to ensure the knowledge base reflects the latest
eligibility criteria, income ceilings, and scheme details:

HDB:
- https://www.hdb.gov.sg/buying-a-flat/flat-grant-and-loan-eligibility
- https://www.hdb.gov.sg/residential/buying-a-flat/understanding-your-eligibility-and-housing-loan-options/flat-and-grant-eligibility
- https://www.hdb.gov.sg/residential/renting-a-flat/renting-from-hdb/public-rental-scheme/eligibility

CPF:
- https://www.cpf.gov.sg/member/cpf-overview
- https://www.cpf.gov.sg/member/retirement-income/cpf-life
- https://www.cpf.gov.sg/member/healthcare-financing/using-medisave

MSF/ComCare:
- https://www.msf.gov.sg/what-we-do/comcare
- https://supportgowhere.life.gov.sg/schemes/CJHJsvLn/comcare
- https://www.msf.gov.sg/what-we-do/silver-support-scheme

MOH:
- https://www.chas.sg/
- https://www.moh.gov.sg/healthcare-schemes-subsidies/medifund
- https://www.moh.gov.sg/healthcare-schemes-subsidies/medishield-life

MOM:
- https://www.mom.gov.sg/passes-and-permits/employment-pass
- https://www.mom.gov.sg/passes-and-permits/long-term-visit-pass
- https://www.mom.gov.sg/employment-practices/retrenchment

GST Vouchers:
- https://www.gstvoucher.gov.sg/

After ingesting, confirm: "Monthly refresh complete. [N] pages updated."

Name this task: monthly-policy-refresh
```

---

## BLOCK 6 — CPF QUARTERLY RATE UPDATES (January, April, July, October)

CPF interest rates and BHS (Basic Healthcare Sum) are updated quarterly. This is frequently relevant to MPS cases involving CPF withdrawals.

Send this to your agent:

```
Set up a scheduled task: on the 1st of January, April, July, and
October each year at 7:00am, check the MOH and CPF pages for
quarterly interest rate and Basic Healthcare Sum updates:

- https://www.moh.gov.sg/newsroom
- https://www.cpf.gov.sg/member/infohub/news

Ingest any new quarterly announcements and send me a summary of the
updated CPF interest rates and Basic Healthcare Sum for the quarter.

Name this task: cpf-quarterly-rates
```

---

## BLOCK 7 — URGENT ALERTS (daily at 12:00pm)

Send this to your agent:

```
Set up a scheduled task: every day at 12:00pm, check the Singapore
Press Centre for any major government announcements:
https://www.sgpc.gov.sg/

If any announcement relates to: public housing, social assistance,
healthcare subsidies, CPF, employment, immigration policy, or
education — ingest it and send me an immediate alert, even if it
is not a Monday digest day.

Name this task: urgent-policy-alerts
```

---

## BLOCK 8 — PRE-MPS SESSION BRIEFING (configure for your MPS day)

Replace `WEEKDAY` with your actual MPS day (e.g. "Tuesday").

Send this to your agent:

```
Set up a scheduled task: every WEEKDAY at 5:30pm, prepare a
pre-MPS briefing for tonight's session. The briefing should include:

1. Any new policy changes in the past 7 days relevant to MPS cases
   (housing, healthcare, social assistance, employment, CPF)
2. Any new application windows opening or closing this week
   (e.g. BTO launches, GST voucher claims, CHAS renewal)
3. Any parliamentary replies this week that clarify policy
4. A reminder of the current key figures I need to know:
   - HDB income ceilings
   - ComCare assessment thresholds
   - CPF contribution rates
   - CHAS card eligibility thresholds
   - Current MediShield Life premium ranges

Send the briefing to me as a formatted message.

Name this task: pre-mps-briefing
```

---

## BLOCK 9 — ANNUAL POLICY CALENDAR REMINDERS

Key annual dates where policies change or applications open. Send this to your agent:

```
Set up annual reminders for Singapore government policy dates:

January 1: Remind me — new CPF rates and BHS take effect today.
  Check: https://www.cpf.gov.sg/member/infohub/news

February (Budget month): Remind me — Singapore Budget announced this
  month. Set daily monitoring of singaporebudget.gov.sg until end of
  March for all COS announcements.

March (COS month): Remind me — Committee of Supply debates this month.
  Check Parliament Hansard daily.

April 1: Remind me — check if any new housing grants or income
  ceilings took effect. Re-ingest HDB grant pages.

July: Remind me — mid-year check on any policy changes since Budget.
  Run a full refresh of all agency newsroom pages.

October: Remind me — CPF quarterly rates updated. Check MOH and CPF.

November: Remind me — check for any end-of-year policy circulars
  from HDB, MOH, MOM, and MSF before the year closes.

Name these tasks collectively: annual-policy-calendar
```

---

## BLOCK 10 — CHECK TASK STATUS

At any time, send your agent:

```
/tasks
```

This lists all active scheduled tasks with their next run time.

To pause a task:

```
/tasks pause daily-policy-watch
```

To resume:

```
/tasks resume daily-policy-watch
```

To delete a task:

```
/tasks stop budget-season-watch
```

---

## RSS FEEDS — Direct ingestion links

Some agencies publish RSS feeds. Ingest these directly for structured updates.

### MFA (Ministry of Foreign Affairs)

- https://www.mfa.gov.sg/RSS-Feeds

### NEA (National Environment Agency)

- https://www.nea.gov.sg/rss/rss-feeds

### For agencies without RSS

The scheduled tasks in Blocks 1–7 above poll newsroom pages directly. NanoClaw compares content between visits and only ingests what is new.

---

## WHAT THE AGENT WILL DO AUTOMATICALLY

Once all scheduled tasks are set up:

| When | What it checks | What it sends you |
|---|---|---|
| Every morning 7am | All agency newsrooms | Only if something new published |
| Every Monday 8am | Full policy landscape | Weekly digest of changes |
| Feb 1 – Mar 31 daily | Budget + COS pages | Same-day Budget/COS updates |
| Tue/Wed/Thu 6pm | Parliament sitting | PQ replies on MPS-relevant topics |
| 1st of every month | All current policy pages | Confirmation of refresh |
| Jan/Apr/Jul/Oct 1 | CPF quarterly rates | New interest rates + BHS |
| Every day 12pm | Singapore Press Centre | Urgent policy alerts only |
| Every MPS evening | Full briefing | Pre-session policy brief |

---

## TESTING YOUR AUTO-UPDATE SYSTEM

After setting up all tasks, verify they registered:

```
/tasks
```

You should see 9–10 active tasks listed.

Test a manual run:

```
run task daily-policy-watch now
```

The agent should fetch the newsroom pages, report what it found, and confirm the task will next run at 7:00am tomorrow.

---

## WHEN A MAJOR POLICY CHANGES

If you hear about a major policy change (e.g. in the news) and want to immediately update the knowledge base:

```
ingest this immediately and update the knowledge graph:
https://www.hdb.gov.sg/[new-policy-page]
```

Or for a general sweep:

```
run task monthly-policy-refresh now
```

The agent will re-ingest all current policy pages and flag anything that has changed since the last ingestion.
