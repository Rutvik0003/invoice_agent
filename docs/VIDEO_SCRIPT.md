# 5-minute demo video script — Payable

What the brief asks for: show the **happy path running live**, then **at least one edge case**, and narrate **what the
process does at each step, the decisions it makes, and how you built it**. Five minutes at most, no slides.

This script does the happy path plus **three edge cases**, each tied to a problem named in PS-1. It runs **about
4:40**, which leaves 20 seconds of margin. Record in **real mode** with your own Gmail: it shows the process taking
real input from a real inbox.

## Set up (the day before or an hour before)

1. From another email address, send yourself **4 emails**, each with one invoice from `data/invoices/golden/`:

   | Attach | Subject (example) | Expected |
   |---|---|---|
   | `01_happy_clean.pdf` | Invoice VE0393 — Vertex Enterprises | Paid |
   | `03_A_split_overrun.pdf` | Final lot invoice — Kosmic Cartons | Needs verification: PO overrun |
   | `05_C_no_po.pdf` | Invoice for campaign work — Shubham Advertising | Needs verification: confirm PO |
   | `08_F_blurry_scan.pdf` | Scanned copy of bill — Ramesh Packaging | Needs verification: field not confirmed |

2. Open the live site and sign in to **Real mode**. Run all 4 bills once. This warms up the server, and it
   **caches the OCR of the blurry scan**, which otherwise takes minutes on the free server.
3. **Settings → Reset demo data.** This clears the runs and the ledger but keeps the OCR cache, so the recording
   starts like a first visit and runs fast.
4. Check the browser is at 100% zoom with the window maximised, close other tabs, and turn notifications off.
5. Do one silent practice run with a timer.

---

## The script

The **Say** column is a guide, not a script to read. Say it in your own words.

### 0:00 – 0:30 · The problem and the idea
**Screen:** start screen of the app.

> "This is **Payable**, an accounts-payable agent for Indian GST invoices. Today someone on the AP team opens every invoice
> email, finds the PO in a spreadsheet, checks the numbers and decides — slow, and the kind of work where a tired
> person makes expensive mistakes.
> The agent does that job end to end and answers one of three things: **Paid**, **Needs human verification**, or
> **Rejected** — always with the reasons.
> The design principle is: **AI reads, OCR verifies, code decides.**"

### 0:30 – 0:50 · Real input: the inbox
**Click:** Real mode → Sign in with Google (already signed in: just open **Inbox**). Make sure the bills filter is on.

> "I've connected my Gmail, read-only. The inbox shows only emails that have invoice attachments. I pick which bills to check — here's a clean one from Vertex Enterprises."

### 0:50 – 2:00 · Happy path, live (01)
**Click:** open the Vertex email → **Check this bill**. Let the stages light up; talk while they run.

> "It runs in eight stages and you can watch each one.
> **Intake** checks the file and fingerprints it, so the same file can never be paid twice.
> **Read & extract** is the only place AI is used — one Gemini call that reads the fields: vendor, GSTIN, invoice
> number, lines, taxes, total.
> Then **verify on page**, with no AI: every key value the model read has to be found on the actual page — from the
> PDF's text layer, or OCR for scans. These **green boxes** are where the total, the GSTIN and the invoice number
> really are. If the AI had misread something, it wouldn't be found, and the invoice would go to a person."

**Point at** the stage list as it finishes:

> "The rest is plain Python rules: the GST maths adds up, the vendor is approved and the bank details match our
> records, it isn't a duplicate, the PO is found, and the quantities and prices are within tolerance."

**Screen:** the decision card shows **Paid**. Hover over or click one number.

> "Everything passed, so it's paid and the PO ledger is updated. Every number links back to where it came from —
> the page or the PO line. That's the audit trail."

### 2:00 – 2:25 · Three edge cases as a batch
**Click:** back to **Inbox** → tick Kosmic Cartons, Shubham Advertising, and the scanned Ramesh copy → **Check 3 bills (batch)** → open **Running**.

> "Now three cases that are harder, each one a real problem from AP work. They run as a batch, within the free-tier
> limits of the AI, and they keep running on the server even if I leave — this Running page shows what's still
> going."

### 2:25 – 3:05 · Edge case 1: a PO split across invoices (03)
**Click:** open the Kosmic Cartons result → **Needs human verification** → point at the PO overrun reason → **Compare with PO**.

> "Vendors often split one PO across several invoices. Each invoice on its own looks fine — but the agent tracks
> what's already been billed against the PO. Earlier bills took most of it, and this one would take the PO **over its
> value**. So it doesn't pay and it doesn't reject — it asks the buyer to decide, and shows exactly how much is left."

### 3:05 – 3:50 · Edge case 2: no PO number on the invoice (05)
**Click:** open the Shubham Advertising result → then **Verification queue** → that invoice.

> "This invoice has **no PO reference** at all. Instead of giving up, the agent scores every open PO of this vendor —
> the items, the amount, the quantities — and finds one clear match.
> But it was *inferred*, not printed, so the rule is: **never auto-pay a guess**. It goes to the verification queue with
> the suggested PO pre-selected."

**Click:** type a short note → **Verify & pay**.

> "A person confirms with one click and a note, and that's logged. The agent did the searching, and a person made the final call."

### 3:50 – 4:25 · Edge case 3: a blurry scan (08)
**Click:** open the Ramesh scanned copy → show the page with boxes (green and a red dashed one).

> "Not every invoice is a clean PDF — this is a blurry scan. Here the page check uses **OCR**. Most values are
> confirmed — green — but the invoice number can't be read on the page: that's the **red dashed box**.
> The AI still returned *a* number, but nothing independent confirms it, so the agent **doesn't trust it**. It never
> guesses: a person checks that one field."

### 4:25 – 4:40 · Dashboard and close
**Click:** **Dashboard**.

> "The dashboard shows every run, its decision and why, and the most common reasons. I tested the rules on almost 300 generated invoices, and every decision
> matched. To sum up: one AI call reads the invoice, the page confirms what it read, and plain rules decide, so
> every decision can be explained. Thanks for watching."

**End at about 4:40.**

---

## If something goes wrong while recording

| Problem | What to do |
|---|---|
| "Rate limit" or "busy" notice | Click the **Try · \<other Gemini model\>** button on the card, keep talking: "each model has its own free limit." |
| A run is slow | Talk through the stages that are already lit; don't wait in silence. |
| A re-run says "already paid" | Correct behaviour; reset demo data before recording again. |
| Going over 5:00 | Cut the Dashboard part. Never cut the happy path or the edge cases. |

## Lines to keep handy (if you have spare seconds)

- "Why not let the AI decide? Because then I couldn't explain the decision, and a model can't be audited the way rules can."
- "Bank details that differ from the vendor master are flagged as possible fraud. They are checked through a known contact, never the contact on the invoice."
- "A demo mode lets reviewers try all 12 cases without signing in, each in a private sandbox."
